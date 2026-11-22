"""SQLite implementations of the repository ports (aiosqlite, plain SQL, no ORM).

Usage (always as a context manager, so the connection is closed; on Windows an open
connection keeps the file locked and breaks temp-dir cleanup):

    async with open_sqlite_repositories(Path("var/opsdesk.db")) as repos:
        await repos.tickets.save(ticket)

Each adapter converts entity <-> row explicitly. Rows read back go through the domain
models again (``model_validate``), so corrupt rows fail loudly instead of leaking into
the application as invalid entities.
"""

import json
from collections.abc import AsyncGenerator, Iterable, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

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

SCHEMA_VERSION = 1
_SCHEMA_FILE = Path(__file__).with_name("schema.sql")

# Fixed-width UTC format: lexical order equals chronological order (see schema.sql).
_TS_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


class SchemaVersionError(RuntimeError):
    """The database was created by a different schema version."""


# --------------------------------------------------------------------- conversions


def _ts(value: datetime) -> str:
    return value.astimezone(UTC).strftime(_TS_FORMAT)


def _ts_or_none(value: datetime | None) -> str | None:
    return None if value is None else _ts(value)


def _json_set(values: Iterable[str]) -> str:
    # Sorted so the same set always produces the same text (stable diffs, equality).
    return json.dumps(sorted(values))


# --------------------------------------------------------------------------- base


class _SqliteRepository:
    """Shared plumbing: run queries and upsert rows on one open connection."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def _fetch_one(self, sql: str, params: tuple[Any, ...]) -> aiosqlite.Row | None:
        async with self._conn.execute(sql, params) as cursor:
            return await cursor.fetchone()

    async def _fetch_all(self, sql: str, params: tuple[Any, ...] = ()) -> list[aiosqlite.Row]:
        async with self._conn.execute(sql, params) as cursor:
            return list(await cursor.fetchall())

    async def _upsert(self, table: str, key: tuple[str, ...], row: Mapping[str, Any]) -> None:
        # Table and column names come from this module, never from user input, so
        # building them into the SQL is safe. Values always go through placeholders.
        columns = ", ".join(row)
        placeholders = ", ".join(f":{name}" for name in row)
        updates = ", ".join(f"{name} = excluded.{name}" for name in row if name not in key)
        sql = (
            f"INSERT INTO {table} ({columns}) VALUES ({placeholders}) "
            f"ON CONFLICT ({', '.join(key)}) DO UPDATE SET {updates}"
        )
        await self._conn.execute(sql, dict(row))
        await self._conn.commit()


# ------------------------------------------------------------------------ tenants


class SqliteTenantRepository(_SqliteRepository):
    async def get(self, tenant_id: TenantId) -> Tenant | None:
        row = await self._fetch_one("SELECT id, name FROM tenants WHERE id = ?", (tenant_id,))
        return None if row is None else Tenant.model_validate(dict(row))

    async def save(self, tenant: Tenant) -> None:
        await self._upsert("tenants", ("id",), {"id": tenant.id, "name": tenant.name})


# ---------------------------------------------------------------------- employees


def _employee_from_row(row: aiosqlite.Row) -> Employee:
    data = dict(row)
    data["roles"] = json.loads(data["roles"])
    data["owned_software"] = json.loads(data["owned_software"])
    return Employee.model_validate(data)


class SqliteEmployeeRepository(_SqliteRepository):
    async def get(self, tenant_id: TenantId, employee_id: EmployeeId) -> Employee | None:
        row = await self._fetch_one(
            "SELECT * FROM employees WHERE tenant_id = ? AND id = ?", (tenant_id, employee_id)
        )
        return None if row is None else _employee_from_row(row)

    async def save(self, employee: Employee) -> None:
        await self._upsert(
            "employees",
            ("tenant_id", "id"),
            {
                "tenant_id": employee.tenant_id,
                "id": employee.id,
                "full_name": employee.full_name,
                "email": employee.email,
                "department": employee.department.value,
                "roles": _json_set(employee.roles),
                "owned_software": _json_set(employee.owned_software),
            },
        )


# ------------------------------------------------------------------------ tickets


class SqliteTicketRepository(_SqliteRepository):
    async def get(self, tenant_id: TenantId, ticket_id: TicketId) -> Ticket | None:
        row = await self._fetch_one(
            "SELECT * FROM tickets WHERE tenant_id = ? AND id = ?", (tenant_id, ticket_id)
        )
        return None if row is None else Ticket.model_validate(dict(row))

    async def list_by_reporter(self, tenant_id: TenantId, reporter_id: EmployeeId) -> list[Ticket]:
        rows = await self._fetch_all(
            "SELECT * FROM tickets WHERE tenant_id = ? AND reporter_id = ? ORDER BY created_at, id",
            (tenant_id, reporter_id),
        )
        return [Ticket.model_validate(dict(r)) for r in rows]

    async def list_by_tenant(self, tenant_id: TenantId) -> list[Ticket]:
        rows = await self._fetch_all(
            "SELECT * FROM tickets WHERE tenant_id = ? ORDER BY created_at, id", (tenant_id,)
        )
        return [Ticket.model_validate(dict(r)) for r in rows]

    async def save(self, ticket: Ticket) -> None:
        await self._upsert(
            "tickets",
            ("tenant_id", "id"),
            {
                "tenant_id": ticket.tenant_id,
                "id": ticket.id,
                "reporter_id": ticket.reporter_id,
                "assignee_id": ticket.assignee_id,
                "title": ticket.title,
                "description": ticket.description,
                "category": ticket.category.value,
                "priority": ticket.priority.value,
                "status": ticket.status.value,
                "asset_tag": ticket.asset_tag,
                "created_at": _ts(ticket.created_at),
                "updated_at": _ts(ticket.updated_at),
            },
        )


# ----------------------------------------------------------------------- software


def _software_from_row(row: aiosqlite.Row) -> SoftwareItem:
    return SoftwareItem.model_validate(
        {
            "id": row["id"],
            "name": row["name"],
            "annual_cost": {
                "amount": row["annual_cost_amount"],
                "currency": row["annual_cost_currency"],
            },
            "restricted_to": json.loads(row["restricted_to"]),
            "requires_admin": bool(row["requires_admin"]),
        }
    )


class SqliteSoftwareRepository(_SqliteRepository):
    async def get(self, software_id: SoftwareId) -> SoftwareItem | None:
        row = await self._fetch_one("SELECT * FROM software WHERE id = ?", (software_id,))
        return None if row is None else _software_from_row(row)

    async def list_all(self) -> list[SoftwareItem]:
        # SQLite's default BINARY collation compares UTF-8 bytes, which orders like
        # Python's str comparison, so this matches the in-memory adapter.
        rows = await self._fetch_all("SELECT * FROM software ORDER BY name, id")
        return [_software_from_row(r) for r in rows]

    async def save(self, item: SoftwareItem) -> None:
        await self._upsert(
            "software",
            ("id",),
            {
                "id": item.id,
                "name": item.name,
                "annual_cost_amount": str(item.annual_cost.amount),
                "annual_cost_currency": item.annual_cost.currency,
                "restricted_to": _json_set(item.restricted_to),
                "requires_admin": int(item.requires_admin),
            },
        )


# ---------------------------------------------------------------- access requests


class SqliteAccessRequestRepository(_SqliteRepository):
    async def get(self, tenant_id: TenantId, request_id: AccessRequestId) -> AccessRequest | None:
        row = await self._fetch_one(
            "SELECT * FROM access_requests WHERE tenant_id = ? AND id = ?",
            (tenant_id, request_id),
        )
        return None if row is None else AccessRequest.model_validate(dict(row))

    async def list_by_requester(
        self, tenant_id: TenantId, requester_id: EmployeeId
    ) -> list[AccessRequest]:
        rows = await self._fetch_all(
            "SELECT * FROM access_requests WHERE tenant_id = ? AND requester_id = ? "
            "ORDER BY created_at, id",
            (tenant_id, requester_id),
        )
        return [AccessRequest.model_validate(dict(r)) for r in rows]

    async def list_pending(self, tenant_id: TenantId) -> list[AccessRequest]:
        rows = await self._fetch_all(
            "SELECT * FROM access_requests WHERE tenant_id = ? AND status = ? "
            "ORDER BY created_at, id",
            (tenant_id, AccessRequestStatus.PENDING_APPROVAL.value),
        )
        return [AccessRequest.model_validate(dict(r)) for r in rows]

    async def save(self, request: AccessRequest) -> None:
        await self._upsert(
            "access_requests",
            ("tenant_id", "id"),
            {
                "tenant_id": request.tenant_id,
                "id": request.id,
                "requester_id": request.requester_id,
                "kind": request.kind.value,
                "software_id": request.software_id,
                "justification": request.justification,
                "status": request.status.value,
                "decided_by": request.decided_by,
                "decided_at": _ts_or_none(request.decided_at),
                "created_at": _ts(request.created_at),
            },
        )


# ------------------------------------------------------------------ schema & open


async def apply_schema(conn: aiosqlite.Connection) -> None:
    """Create tables if missing and check the schema version. Safe to run repeatedly."""
    await conn.executescript(_SCHEMA_FILE.read_text(encoding="utf-8"))
    async with conn.execute("SELECT version FROM schema_version") as cursor:
        rows = list(await cursor.fetchall())
    if not rows:
        await conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
        await conn.commit()
    elif len(rows) != 1 or rows[0][0] != SCHEMA_VERSION:
        found = [r[0] for r in rows]
        raise SchemaVersionError(f"expected schema version {SCHEMA_VERSION}, found {found}")


@asynccontextmanager
async def open_sqlite_repositories(path: Path) -> AsyncGenerator[Repositories]:
    """Open (creating if needed) the database at ``path`` and yield its repositories.

    One connection is shared by all repositories and closed on exit.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(path) as conn:
        conn.row_factory = aiosqlite.Row
        await apply_schema(conn)
        yield Repositories(
            tenants=SqliteTenantRepository(conn),
            employees=SqliteEmployeeRepository(conn),
            tickets=SqliteTicketRepository(conn),
            software=SqliteSoftwareRepository(conn),
            access_requests=SqliteAccessRequestRepository(conn),
        )
