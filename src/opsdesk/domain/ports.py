"""Repository ports: what the domain needs from storage, not how it is done.

These are ``Protocol``s (structural types). Any class with matching async methods *is*
a repository, without inheriting from anything. ``opsdesk.persistence`` provides the
adapters (in-memory, SQLite); the dependency points inward, so persistence imports
this module and never the reverse (enforced by the ``layers`` contract).

Design rules every adapter must honour (checked by tests/contract):

* **Tenant-scoped by shape.** Every lookup of tenant data takes a ``tenant_id``. There
  is no ``get(ticket_id)``: an id from another tenant simply returns ``None``, exactly
  as if it did not exist (no "exists but forbidden" leak).
* **Save is an upsert** keyed by the entity id (and tenant). The entity's own
  ``tenant_id`` decides where it is stored.
* **Entities in, entities out.** Adapters return fully validated domain models, never
  rows or dicts. A round trip (save then get) returns an equal entity.
* **Stable order.** Lists are sorted (see each method), so results are reproducible
  in tests, evaluations and model prompts.

The software catalogue is the one exception to tenant scoping: it is shared reference
data (product names and prices) and holds nothing that belongs to a tenant.
"""

from dataclasses import dataclass
from typing import Protocol

from opsdesk.domain.ids import AccessRequestId, EmployeeId, SoftwareId, TenantId, TicketId
from opsdesk.domain.models import AccessRequest, Employee, SoftwareItem, Tenant, Ticket


class TenantRepository(Protocol):
    async def get(self, tenant_id: TenantId) -> Tenant | None: ...

    async def save(self, tenant: Tenant) -> None: ...


class EmployeeRepository(Protocol):
    async def get(self, tenant_id: TenantId, employee_id: EmployeeId) -> Employee | None: ...

    async def save(self, employee: Employee) -> None: ...


class TicketRepository(Protocol):
    async def get(self, tenant_id: TenantId, ticket_id: TicketId) -> Ticket | None: ...

    async def list_by_reporter(self, tenant_id: TenantId, reporter_id: EmployeeId) -> list[Ticket]:
        """Tickets reported by one employee, oldest first (``created_at``, then ``id``)."""
        ...

    async def list_by_tenant(self, tenant_id: TenantId) -> list[Ticket]:
        """Every ticket of a tenant (the IT queue), oldest first.

        Returns raw tenant data: callers that show it to a person or a model must
        filter with ``can_view_ticket`` first.
        """
        ...

    async def save(self, ticket: Ticket) -> None: ...


class SoftwareRepository(Protocol):
    async def get(self, software_id: SoftwareId) -> SoftwareItem | None: ...

    async def list_all(self) -> list[SoftwareItem]:
        """The whole catalogue, sorted by ``name``."""
        ...

    async def save(self, item: SoftwareItem) -> None: ...


class AccessRequestRepository(Protocol):
    async def get(
        self, tenant_id: TenantId, request_id: AccessRequestId
    ) -> AccessRequest | None: ...

    async def list_by_requester(
        self, tenant_id: TenantId, requester_id: EmployeeId
    ) -> list[AccessRequest]:
        """One employee's requests, oldest first (``created_at``, then ``id``)."""
        ...

    async def list_pending(self, tenant_id: TenantId) -> list[AccessRequest]:
        """Requests waiting for approval (the approval queue, M14), oldest first."""
        ...

    async def save(self, request: AccessRequest) -> None: ...


@dataclass(frozen=True, slots=True)
class Repositories:
    """All repositories of one storage backend, passed around as a single object.

    Built by the persistence layer (``in_memory_repositories()``, SQLite in step 3);
    consumed by the seed loader now and by tools / services from M03.
    """

    tenants: TenantRepository
    employees: EmployeeRepository
    tickets: TicketRepository
    software: SoftwareRepository
    access_requests: AccessRequestRepository
