"""Repository contract: ONE suite, run against EVERY adapter (M01 §6).

The ``repos`` fixture is parametrized, so each test below runs twice: once with the
in-memory adapter and once with SQLite. Any future adapter (Postgres, an HTTP API)
is added to ``ADAPTERS`` and must pass the same tests unchanged.

What the contract promises (see ``opsdesk.domain.ports``):
  * round trip: save then get returns an equal entity (Money, tz-aware datetimes, sets)
  * tenant isolation: the right id with the wrong tenant returns None
  * upsert: saving an existing id replaces it, never duplicates it
  * stable order: lists are sorted (created_at, id) / (name, id)
"""

from collections.abc import AsyncGenerator, Callable
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from opsdesk.core.money import Money
from opsdesk.domain.models import AccessRequest, Employee, SoftwareItem, Tenant, Ticket
from opsdesk.domain.ports import Repositories
from opsdesk.persistence.memory import in_memory_repositories
from opsdesk.persistence.sqlite.repositories import open_sqlite_repositories

T0 = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
ADAPTERS = ["memory", "sqlite"]


@pytest.fixture(params=ADAPTERS)
async def repos(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncGenerator[Repositories]:
    if request.param == "memory":
        yield in_memory_repositories()
    else:
        # `async with` closes the connection before tmp_path is cleaned up; on Windows
        # an open connection would lock the file and fail the cleanup.
        async with open_sqlite_repositories(tmp_path / "contract.db") as sqlite_repos:
            yield sqlite_repos


# ----------------------------------------------------------------------- round trip


async def test_tenant_round_trip(repos: Repositories) -> None:
    tenant = Tenant.model_validate({"id": "acme", "name": "Acme Corporation"})
    await repos.tenants.save(tenant)
    assert await repos.tenants.get(tenant.id) == tenant


async def test_employee_round_trip_keeps_sets(
    repos: Repositories, make_employee: Callable[..., Employee]
) -> None:
    emp = make_employee(
        full_name="Nguyễn Thị Ánh",  # non-ASCII must survive (UTF-8 on Windows too)
        roles=["employee", "it_staff", "it_manager"],
        owned_software=["SW-SLACK", "SW-DOCKER"],
    )
    await repos.employees.save(emp)
    assert await repos.employees.get(emp.tenant_id, emp.id) == emp


async def test_ticket_round_trip_keeps_timezone_aware_datetimes(
    repos: Repositories, make_ticket: Callable[..., Ticket]
) -> None:
    ict = timezone(timedelta(hours=7))
    ticket = make_ticket(
        created_at=datetime(2026, 3, 1, 16, 0, 0, 123456, tzinfo=ict),  # microseconds too
        updated_at=datetime(2026, 3, 2, 9, 30, tzinfo=UTC),
        assignee_id="E-005",
        asset_tag="LAP-1042",
    )
    await repos.tickets.save(ticket)
    loaded = await repos.tickets.get(ticket.tenant_id, ticket.id)
    assert loaded == ticket
    assert loaded is not None
    assert loaded.created_at.tzinfo is not None
    assert loaded.created_at.utcoffset() == timedelta(0)


async def test_ticket_round_trip_with_nulls(
    repos: Repositories, make_ticket: Callable[..., Ticket]
) -> None:
    ticket = make_ticket(assignee_id=None, asset_tag=None, description="")
    await repos.tickets.save(ticket)
    assert await repos.tickets.get(ticket.tenant_id, ticket.id) == ticket


async def test_software_round_trip_keeps_money(
    repos: Repositories, make_software: Callable[..., SoftwareItem]
) -> None:
    item = make_software(
        id="SW-ADOBE-CC",
        name="Adobe Creative Cloud",
        annual_cost=15_000_000,
        restricted_to=["design", "sales"],
        requires_admin=True,
    )
    await repos.software.save(item)
    loaded = await repos.software.get(item.id)
    assert loaded == item
    assert loaded is not None
    assert loaded.annual_cost == Money(15_000_000)


@pytest.mark.parametrize(
    "overrides",
    [
        {},  # pending, licence
        {"kind": "admin_rights", "software_id": None},
        {"status": "approved", "decided_by": "E-006", "decided_at": T0 + timedelta(hours=1)},
        {"status": "rejected", "decided_by": "E-007", "decided_at": T0 + timedelta(days=1)},
        {"status": "cancelled"},
    ],
)
async def test_access_request_round_trip(
    repos: Repositories,
    make_access_request: Callable[..., AccessRequest],
    overrides: dict[str, object],
) -> None:
    req = make_access_request(**overrides)
    await repos.access_requests.save(req)
    assert await repos.access_requests.get(req.tenant_id, req.id) == req


async def test_get_missing_returns_none(repos: Repositories) -> None:
    assert await repos.tenants.get("nope") is None  # type: ignore[arg-type]
    assert await repos.employees.get("acme", "E-404") is None  # type: ignore[arg-type]
    assert await repos.tickets.get("acme", "T-404") is None  # type: ignore[arg-type]
    assert await repos.software.get("SW-404") is None  # type: ignore[arg-type]
    assert await repos.access_requests.get("acme", "AR-404") is None  # type: ignore[arg-type]


# ----------------------------------------------------------------- tenant isolation


async def test_ticket_with_wrong_tenant_returns_none(
    repos: Repositories, make_ticket: Callable[..., Ticket]
) -> None:
    ticket = make_ticket(id="T-0010", tenant_id="globex")
    await repos.tickets.save(ticket)
    assert await repos.tickets.get("acme", "T-0010") is None  # type: ignore[arg-type]
    assert await repos.tickets.get("globex", "T-0010") == ticket  # type: ignore[arg-type]


async def test_employee_with_wrong_tenant_returns_none(
    repos: Repositories, make_employee: Callable[..., Employee]
) -> None:
    await repos.employees.save(make_employee(id="G-001", tenant_id="globex"))
    assert await repos.employees.get("acme", "G-001") is None  # type: ignore[arg-type]


async def test_access_request_with_wrong_tenant_returns_none(
    repos: Repositories, make_access_request: Callable[..., AccessRequest]
) -> None:
    await repos.access_requests.save(make_access_request(id="AR-G1", tenant_id="globex"))
    assert await repos.access_requests.get("acme", "AR-G1") is None  # type: ignore[arg-type]


async def test_same_id_in_two_tenants_are_separate_entities(
    repos: Repositories, make_ticket: Callable[..., Ticket]
) -> None:
    acme = make_ticket(id="T-0001", tenant_id="acme", title="Acme laptop")
    globex = make_ticket(id="T-0001", tenant_id="globex", title="Globex laptop")
    await repos.tickets.save(acme)
    await repos.tickets.save(globex)
    assert await repos.tickets.get("acme", "T-0001") == acme  # type: ignore[arg-type]
    assert await repos.tickets.get("globex", "T-0001") == globex  # type: ignore[arg-type]


# ---------------------------------------------------------------------------- lists


async def test_list_by_reporter_only_that_reporter_in_that_tenant(
    repos: Repositories, make_ticket: Callable[..., Ticket]
) -> None:
    mine_1 = make_ticket(id="T-1", reporter_id="E-001", created_at=T0, updated_at=T0)
    mine_2 = make_ticket(
        id="T-2", reporter_id="E-001", created_at=T0 + timedelta(1), updated_at=T0 + timedelta(1)
    )
    someone_else = make_ticket(id="T-3", reporter_id="E-002")
    other_tenant_same_reporter_id = make_ticket(id="T-4", tenant_id="globex", reporter_id="E-001")
    for t in (mine_2, someone_else, other_tenant_same_reporter_id, mine_1):
        await repos.tickets.save(t)

    result = await repos.tickets.list_by_reporter("acme", "E-001")  # type: ignore[arg-type]
    assert result == [mine_1, mine_2]


async def test_lists_are_ordered_by_created_at_then_id(
    repos: Repositories, make_ticket: Callable[..., Ticket]
) -> None:
    later = T0 + timedelta(hours=1)
    # Saved in scrambled order; T-B and T-A share a timestamp, so id breaks the tie.
    tickets = [
        make_ticket(id="T-C", created_at=later, updated_at=later),
        make_ticket(id="T-B", created_at=T0, updated_at=T0),
        make_ticket(id="T-A", created_at=T0, updated_at=T0),
    ]
    for t in tickets:
        await repos.tickets.save(t)
    result = await repos.tickets.list_by_tenant("acme")  # type: ignore[arg-type]
    assert [t.id for t in result] == ["T-A", "T-B", "T-C"]


async def test_list_by_tenant_excludes_other_tenants(
    repos: Repositories, make_ticket: Callable[..., Ticket]
) -> None:
    await repos.tickets.save(make_ticket(id="T-1", tenant_id="acme"))
    await repos.tickets.save(make_ticket(id="T-2", tenant_id="globex"))
    result = await repos.tickets.list_by_tenant("acme")  # type: ignore[arg-type]
    assert [t.id for t in result] == ["T-1"]


async def test_empty_lists(repos: Repositories) -> None:
    assert await repos.tickets.list_by_tenant("acme") == []  # type: ignore[arg-type]
    assert await repos.access_requests.list_pending("acme") == []  # type: ignore[arg-type]
    assert await repos.software.list_all() == []


async def test_list_pending_only_pending_in_tenant_oldest_first(
    repos: Repositories, make_access_request: Callable[..., AccessRequest]
) -> None:
    newer = make_access_request(id="AR-2", created_at=T0 + timedelta(hours=2))
    older = make_access_request(id="AR-1", created_at=T0)
    approved = make_access_request(
        id="AR-3", status="approved", decided_by="E-006", decided_at=T0 + timedelta(hours=3)
    )
    other_tenant = make_access_request(id="AR-4", tenant_id="globex")
    for r in (newer, approved, other_tenant, older):
        await repos.access_requests.save(r)
    assert await repos.access_requests.list_pending("acme") == [older, newer]  # type: ignore[arg-type]


async def test_list_by_requester(
    repos: Repositories, make_access_request: Callable[..., AccessRequest]
) -> None:
    mine = make_access_request(id="AR-1", requester_id="E-001")
    theirs = make_access_request(id="AR-2", requester_id="E-002")
    await repos.access_requests.save(mine)
    await repos.access_requests.save(theirs)
    result = await repos.access_requests.list_by_requester("acme", "E-001")  # type: ignore[arg-type]
    assert result == [mine]


async def test_software_list_all_sorted_by_name(
    repos: Repositories, make_software: Callable[..., SoftwareItem]
) -> None:
    for sw_id, name in [("SW-3", "Zoom Pro"), ("SW-1", "Figma"), ("SW-2", "Slack")]:
        await repos.software.save(make_software(id=sw_id, name=name))
    assert [s.name for s in await repos.software.list_all()] == ["Figma", "Slack", "Zoom Pro"]


# --------------------------------------------------------------------------- upsert


async def test_saving_existing_ticket_updates_it(
    repos: Repositories, make_ticket: Callable[..., Ticket]
) -> None:
    original = make_ticket(status="open")
    await repos.tickets.save(original)
    moved = original.evolve(status="in_progress", updated_at=T0 + timedelta(hours=1))
    await repos.tickets.save(moved)

    assert await repos.tickets.get(original.tenant_id, original.id) == moved
    assert len(await repos.tickets.list_by_tenant(original.tenant_id)) == 1  # no duplicate


async def test_saving_existing_access_request_updates_it(
    repos: Repositories, make_access_request: Callable[..., AccessRequest]
) -> None:
    pending = make_access_request()
    await repos.access_requests.save(pending)
    approved = pending.evolve(status="approved", decided_by="E-006", decided_at=T0)
    await repos.access_requests.save(approved)

    assert await repos.access_requests.get(pending.tenant_id, pending.id) == approved
    assert await repos.access_requests.list_pending(pending.tenant_id) == []


async def test_saving_existing_employee_and_software_updates_them(
    repos: Repositories,
    make_employee: Callable[..., Employee],
    make_software: Callable[..., SoftwareItem],
) -> None:
    emp = make_employee(owned_software=[])
    await repos.employees.save(emp)
    await repos.employees.save(emp.evolve(owned_software=["SW-FIGMA"]))
    loaded = await repos.employees.get(emp.tenant_id, emp.id)
    assert loaded is not None
    assert loaded.owned_software == frozenset({"SW-FIGMA"})

    sw = make_software(annual_cost=1_000_000)
    await repos.software.save(sw)
    await repos.software.save(sw.evolve(annual_cost=Money(2_000_000)))
    loaded_sw = await repos.software.get(sw.id)
    assert loaded_sw is not None
    assert loaded_sw.annual_cost == Money(2_000_000)
    assert len(await repos.software.list_all()) == 1
