from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from opsdesk.core.money import Money
from opsdesk.domain.models import (
    AccessKind,
    AccessRequest,
    AccessRequestStatus,
    Department,
    Employee,
    Role,
    SoftwareItem,
    Tenant,
    Ticket,
    TicketStatus,
)

T0 = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)


def employee(**overrides: Any) -> Employee:
    data: dict[str, Any] = {
        "id": "E-001",
        "tenant_id": "acme",
        "full_name": "An Nguyen",
        "email": "an@acme.test",
        "department": "engineering",
        "roles": ["employee"],
    }
    return Employee.model_validate(data | overrides)


def ticket(**overrides: Any) -> Ticket:
    data: dict[str, Any] = {
        "id": "T-0001",
        "tenant_id": "acme",
        "reporter_id": "E-001",
        "title": "Laptop will not boot",
        "description": "Black screen after update",
        "category": "hardware",
        "priority": "high",
        "created_at": T0,
        "updated_at": T0,
    }
    return Ticket.model_validate(data | overrides)


def access_request(**overrides: Any) -> AccessRequest:
    data: dict[str, Any] = {
        "id": "AR-001",
        "tenant_id": "acme",
        "requester_id": "E-001",
        "kind": "software_licence",
        "software_id": "SW-FIGMA",
        "justification": "Design reviews",
        "created_at": T0,
    }
    return AccessRequest.model_validate(data | overrides)


# ---------------------------------------------------------------------- immutability


def test_entities_are_frozen() -> None:
    t = ticket()
    with pytest.raises(ValidationError, match="frozen"):
        t.status = TicketStatus.CLOSED  # type: ignore[misc]


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError, match="extra"):
        Tenant.model_validate({"id": "acme", "name": "Acme", "plan": "gold"})


def test_evolve_returns_new_instance_and_keeps_original() -> None:
    t = ticket()
    later = T0 + timedelta(hours=1)
    moved = t.evolve(status=TicketStatus.IN_PROGRESS, updated_at=later)
    assert moved.status is TicketStatus.IN_PROGRESS
    assert moved.updated_at == later
    assert t.status is TicketStatus.OPEN


def test_evolve_revalidates_unlike_model_copy() -> None:
    req = access_request()
    # model_copy skips validation and happily builds an invalid entity...
    broken = req.model_copy(update={"status": AccessRequestStatus.APPROVED})
    assert broken.decided_by is None
    # ...evolve does not.
    with pytest.raises(ValidationError, match="decided_by"):
        req.evolve(status=AccessRequestStatus.APPROVED)


# ------------------------------------------------------------------------- datetimes


def test_naive_datetime_is_rejected() -> None:
    naive = datetime(2026, 3, 1, 9, 0)  # noqa: DTZ001 - deliberately naive
    with pytest.raises(ValidationError, match="timezone"):
        ticket(created_at=naive, updated_at=naive)


def test_datetimes_are_normalised_to_utc() -> None:
    ict = timezone(timedelta(hours=7))
    t = ticket(created_at=datetime(2026, 3, 1, 16, 0, tzinfo=ict), updated_at=T0)
    assert t.created_at == T0
    assert t.created_at.tzinfo is UTC


def test_iso_strings_from_yaml_are_parsed() -> None:
    t = ticket(created_at="2026-03-01T09:00:00Z", updated_at="2026-03-01T10:00:00+00:00")
    assert t.created_at == T0


def test_ticket_updated_before_created_is_rejected() -> None:
    with pytest.raises(ValidationError, match="updated_at"):
        ticket(updated_at=T0 - timedelta(seconds=1))


# -------------------------------------------------------------------------- employee


def test_yaml_lists_become_frozensets_of_enums() -> None:
    e = employee(roles=["employee", "it_staff"], owned_software=["SW-SLACK"])
    assert e.roles == frozenset({Role.EMPLOYEE, Role.IT_STAFF})
    assert e.department is Department.ENGINEERING
    assert e.owned_software == frozenset({"SW-SLACK"})


@pytest.mark.parametrize("roles", [[], ["it_staff"], ["hr", "finance"]])
def test_roles_must_include_employee(roles: list[str]) -> None:
    with pytest.raises(ValidationError, match="employee"):
        employee(roles=roles)


def test_unknown_role_is_rejected() -> None:
    with pytest.raises(ValidationError):
        employee(roles=["employee", "admin"])


def test_is_it() -> None:
    assert employee(roles=["employee", "it_staff"]).is_it
    assert employee(roles=["employee", "it_manager"]).is_it
    assert not employee(roles=["employee", "hr"]).is_it


# -------------------------------------------------------------------------- software


@pytest.mark.parametrize("cost", [5_000_000, "5000000", {"amount": "5000000", "currency": "VND"}])
def test_software_cost_accepts_yaml_shapes(cost: Any) -> None:
    sw = SoftwareItem.model_validate({"id": "SW-FIGMA", "name": "Figma", "annual_cost": cost})
    assert sw.annual_cost == Money(5_000_000)


def test_software_cost_rejects_float() -> None:
    with pytest.raises(ValidationError, match="float"):
        SoftwareItem.model_validate({"id": "SW-X", "name": "X", "annual_cost": 1.5})


def test_money_round_trips_through_json() -> None:
    sw = SoftwareItem(id="SW-FIGMA", name="Figma", annual_cost=Money(5_000_000))  # type: ignore[arg-type]
    dumped = sw.model_dump_json()
    assert '"amount":"5000000"' in dumped
    assert SoftwareItem.model_validate_json(dumped) == sw
    assert sw.annual_cost.amount == Decimal(5_000_000)


def test_software_availability() -> None:
    open_to_all = SoftwareItem.model_validate({"id": "SW-1", "name": "Slack", "annual_cost": 0})
    design_only = SoftwareItem.model_validate(
        {"id": "SW-2", "name": "Adobe CC", "annual_cost": 0, "restricted_to": ["design"]}
    )
    assert open_to_all.is_available_to(Department.FINANCE)
    assert design_only.is_available_to(Department.DESIGN)
    assert not design_only.is_available_to(Department.ENGINEERING)


# -------------------------------------------------------------------- access request


def test_licence_requires_software_id() -> None:
    with pytest.raises(ValidationError, match="software_id"):
        access_request(software_id=None)


def test_admin_rights_forbid_software_id() -> None:
    with pytest.raises(ValidationError, match="software_id"):
        access_request(kind="admin_rights")
    assert access_request(kind="admin_rights", software_id=None).kind is AccessKind.ADMIN_RIGHTS


@pytest.mark.parametrize("status", ["approved", "rejected"])
def test_decided_request_needs_decider_and_time(status: str) -> None:
    with pytest.raises(ValidationError, match="decided_by"):
        access_request(status=status)
    with pytest.raises(ValidationError, match="decided_by"):
        access_request(status=status, decided_by="E-006")
    ok = access_request(status=status, decided_by="E-006", decided_at=T0)
    assert ok.decided_by == "E-006"


@pytest.mark.parametrize("status", ["pending_approval", "cancelled"])
def test_undecided_request_must_not_have_decider(status: str) -> None:
    with pytest.raises(ValidationError, match="decided_by"):
        access_request(status=status, decided_by="E-006", decided_at=T0)


def test_decision_cannot_predate_request() -> None:
    with pytest.raises(ValidationError, match="decided_at"):
        access_request(status="approved", decided_by="E-006", decided_at=T0 - timedelta(minutes=1))
