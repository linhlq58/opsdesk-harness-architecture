"""In-memory adapters for every repository port.

Fast, dependency-free storage for unit tests, evaluations and demos. It must behave
exactly like the SQLite adapter; ``tests/contract/test_repositories.py`` runs the same
suite against both to prove it.

Entities are immutable (frozen Pydantic models), so storing and returning the same
instance is safe: nobody can change a stored ticket behind the repository's back.
"""

from collections.abc import Iterable
from datetime import datetime

from opsdesk.domain.ids import AccessRequestId, EmployeeId, SoftwareId, TenantId, TicketId
from opsdesk.domain.models import (
    AccessRequest,
    AccessRequestStatus,
    Employee,
    SoftwareItem,
    Tenant,
    Ticket,
)
from opsdesk.domain.ports import Repositories


def _oldest_first[T: (Ticket, AccessRequest)](items: Iterable[T]) -> list[T]:
    """Sort by ``created_at`` then ``id``: the order every list port promises."""

    def key(item: T) -> tuple[datetime, str]:
        return (item.created_at, item.id)

    return sorted(items, key=key)


class InMemoryTenantRepository:
    def __init__(self) -> None:
        self._items: dict[TenantId, Tenant] = {}

    async def get(self, tenant_id: TenantId) -> Tenant | None:
        return self._items.get(tenant_id)

    async def save(self, tenant: Tenant) -> None:
        self._items[tenant.id] = tenant


class InMemoryEmployeeRepository:
    def __init__(self) -> None:
        # Keyed by (tenant, id): the tenant is part of the identity, never optional.
        self._items: dict[tuple[TenantId, EmployeeId], Employee] = {}

    async def get(self, tenant_id: TenantId, employee_id: EmployeeId) -> Employee | None:
        return self._items.get((tenant_id, employee_id))

    async def save(self, employee: Employee) -> None:
        self._items[(employee.tenant_id, employee.id)] = employee


class InMemoryTicketRepository:
    def __init__(self) -> None:
        self._items: dict[tuple[TenantId, TicketId], Ticket] = {}

    async def get(self, tenant_id: TenantId, ticket_id: TicketId) -> Ticket | None:
        return self._items.get((tenant_id, ticket_id))

    async def list_by_reporter(self, tenant_id: TenantId, reporter_id: EmployeeId) -> list[Ticket]:
        return _oldest_first(
            t
            for (tid, _), t in self._items.items()
            if tid == tenant_id and t.reporter_id == reporter_id
        )

    async def list_by_tenant(self, tenant_id: TenantId) -> list[Ticket]:
        return _oldest_first(t for (tid, _), t in self._items.items() if tid == tenant_id)

    async def save(self, ticket: Ticket) -> None:
        self._items[(ticket.tenant_id, ticket.id)] = ticket


class InMemorySoftwareRepository:
    def __init__(self) -> None:
        self._items: dict[SoftwareId, SoftwareItem] = {}

    async def get(self, software_id: SoftwareId) -> SoftwareItem | None:
        return self._items.get(software_id)

    async def list_all(self) -> list[SoftwareItem]:
        return sorted(self._items.values(), key=lambda s: (s.name, s.id))

    async def save(self, item: SoftwareItem) -> None:
        self._items[item.id] = item


class InMemoryAccessRequestRepository:
    def __init__(self) -> None:
        self._items: dict[tuple[TenantId, AccessRequestId], AccessRequest] = {}

    async def get(self, tenant_id: TenantId, request_id: AccessRequestId) -> AccessRequest | None:
        return self._items.get((tenant_id, request_id))

    async def list_by_requester(
        self, tenant_id: TenantId, requester_id: EmployeeId
    ) -> list[AccessRequest]:
        return _oldest_first(
            r
            for (tid, _), r in self._items.items()
            if tid == tenant_id and r.requester_id == requester_id
        )

    async def list_pending(self, tenant_id: TenantId) -> list[AccessRequest]:
        return _oldest_first(
            r
            for (tid, _), r in self._items.items()
            if tid == tenant_id and r.status is AccessRequestStatus.PENDING_APPROVAL
        )

    async def save(self, request: AccessRequest) -> None:
        self._items[(request.tenant_id, request.id)] = request


def in_memory_repositories() -> Repositories:
    """A fresh, empty set of in-memory repositories.

    Building ``Repositories`` here also makes pyright check that every class above
    really satisfies its port (a missing method or wrong signature is a type error).
    """
    return Repositories(
        tenants=InMemoryTenantRepository(),
        employees=InMemoryEmployeeRepository(),
        tickets=InMemoryTicketRepository(),
        software=InMemorySoftwareRepository(),
        access_requests=InMemoryAccessRequestRepository(),
    )
