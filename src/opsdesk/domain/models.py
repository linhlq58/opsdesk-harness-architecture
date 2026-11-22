"""Domain entities and enums.

Every entity is an immutable Pydantic model. "Changing" an entity means building a new
one with ``evolve(...)``, which re-runs validation, so an invalid state can never exist
in memory, whether it came from seed data, the database or a policy.

Invariants checked here hold for *any* instance. Rules that depend on who is acting or
on configuration (visibility, transitions, approval) live in ``domain.policies``.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Self

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    PlainValidator,
    model_validator,
)

from opsdesk.core.money import Money
from opsdesk.domain.ids import (
    AccessRequestId,
    EmployeeId,
    SoftwareId,
    TenantId,
    TicketId,
)

# ------------------------------------------------------------------------ field types


def _to_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


# AwareDatetime rejects naive datetimes; AfterValidator normalises every offset to UTC.
type UtcDatetime = Annotated[AwareDatetime, AfterValidator(_to_utc)]


def _parse_money(value: Any) -> Money:
    """Accept a ``Money``, a bare amount (VND), or ``{"amount": ..., "currency": ...}``.

    Pydantic only turns ``ValueError`` into a ``ValidationError``. ``Money`` raises
    ``TypeError`` for floats, so it is re-raised as ``ValueError`` here; otherwise a bad
    seed file would crash with a raw traceback instead of a validation report.
    """
    if isinstance(value, Money):
        return value
    try:
        if isinstance(value, dict):
            data: dict[str, Any] = value  # pyright: ignore[reportUnknownVariableType]
            return Money(data["amount"], data.get("currency", "VND"))
        return Money(value)
    except (TypeError, KeyError) as exc:
        raise ValueError(str(exc)) from exc


def _dump_money(value: Money) -> dict[str, str]:
    # Amount as a string: exact in JSON (no float) and readable in SQLite / YAML.
    return {"amount": str(value.amount), "currency": value.currency}


type MoneyField = Annotated[Money, PlainValidator(_parse_money), PlainSerializer(_dump_money)]

type NonEmptyStr = Annotated[str, Field(min_length=1)]

# ----------------------------------------------------------------------------- enums


class Department(StrEnum):
    ENGINEERING = "engineering"
    DESIGN = "design"
    HR = "hr"
    FINANCE = "finance"
    IT = "it"
    SALES = "sales"


class Role(StrEnum):
    """Business roles. These are not security scopes (those arrive in M02)."""

    EMPLOYEE = "employee"
    IT_STAFF = "it_staff"
    IT_MANAGER = "it_manager"
    HR = "hr"
    FINANCE = "finance"


class TicketCategory(StrEnum):
    HARDWARE = "hardware"
    SOFTWARE = "software"
    ACCESS = "access"
    NETWORK = "network"
    SECURITY = "security"
    OTHER = "other"


class TicketPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TicketStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    WAITING_ON_USER = "waiting_on_user"
    RESOLVED = "resolved"
    CLOSED = "closed"


class AccessKind(StrEnum):
    SOFTWARE_LICENCE = "software_licence"
    ADMIN_RIGHTS = "admin_rights"


class AccessRequestStatus(StrEnum):
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


DECIDED_STATUSES: frozenset[AccessRequestStatus] = frozenset(
    {AccessRequestStatus.APPROVED, AccessRequestStatus.REJECTED}
)

# -------------------------------------------------------------------------- entities


class DomainModel(BaseModel):
    """Base for all entities: immutable, no unknown fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    def evolve(self, **changes: Any) -> Self:
        """Return a copy with ``changes`` applied, **validated**.

        Pydantic's ``model_copy(update=...)`` skips validation, so it could build e.g.
        an approved request with no ``decided_by``. ``evolve`` rebuilds the model
        through the validators instead.
        """
        return self.model_validate(self.model_dump() | changes)


class Tenant(DomainModel):
    id: TenantId
    name: NonEmptyStr


class Employee(DomainModel):
    id: EmployeeId
    tenant_id: TenantId
    full_name: NonEmptyStr
    email: NonEmptyStr
    department: Department
    roles: frozenset[Role]
    owned_software: frozenset[SoftwareId] = frozenset()

    @model_validator(mode="after")
    def _roles_include_employee(self) -> Self:
        if Role.EMPLOYEE not in self.roles:
            raise ValueError("roles must include 'employee'")
        return self

    def has_any_role(self, *roles: Role) -> bool:
        return not self.roles.isdisjoint(roles)

    @property
    def is_it(self) -> bool:
        return self.has_any_role(Role.IT_STAFF, Role.IT_MANAGER)


class Ticket(DomainModel):
    id: TicketId
    tenant_id: TenantId
    reporter_id: EmployeeId
    assignee_id: EmployeeId | None = None
    title: NonEmptyStr
    description: str
    category: TicketCategory
    priority: TicketPriority
    status: TicketStatus = TicketStatus.OPEN
    asset_tag: str | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime

    @model_validator(mode="after")
    def _updated_not_before_created(self) -> Self:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not be earlier than created_at")
        return self


class SoftwareItem(DomainModel):
    id: SoftwareId
    name: NonEmptyStr
    annual_cost: MoneyField
    restricted_to: frozenset[Department] = frozenset()  # empty = everyone
    requires_admin: bool = False

    def is_available_to(self, department: Department) -> bool:
        return not self.restricted_to or department in self.restricted_to


class AccessRequest(DomainModel):
    id: AccessRequestId
    tenant_id: TenantId
    requester_id: EmployeeId
    kind: AccessKind
    software_id: SoftwareId | None = None
    justification: str
    status: AccessRequestStatus = AccessRequestStatus.PENDING_APPROVAL
    decided_by: EmployeeId | None = None
    decided_at: UtcDatetime | None = None
    created_at: UtcDatetime

    @model_validator(mode="after")
    def _kind_matches_software(self) -> Self:
        is_licence = self.kind is AccessKind.SOFTWARE_LICENCE
        if is_licence != (self.software_id is not None):
            raise ValueError("software_id is required for licences and forbidden otherwise")
        return self

    @model_validator(mode="after")
    def _decision_fields_match_status(self) -> Self:
        decided = self.status in DECIDED_STATUSES
        has_decider = self.decided_by is not None
        has_time = self.decided_at is not None
        if not (decided == has_decider == has_time):
            raise ValueError(
                "decided_by and decided_at must be set if and only if status is "
                "approved or rejected"
            )
        if self.decided_at is not None and self.decided_at < self.created_at:
            raise ValueError("decided_at must not be earlier than created_at")
        return self
