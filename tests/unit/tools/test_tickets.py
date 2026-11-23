"""Ticket tools: ``get_ticket`` T1-T6 and ``list_my_tickets`` L1-L3 (M03 §7).

Run against the real seed (data/seed), through a real ``create_agent`` loop.

``opsdesk.tools.tickets`` is imported inside the ``tickets`` fixture: its decorator
lines call ``harness_tool`` at import time, so while that is still a stub a top-level
import would abort the whole pytest session instead of failing these tests.
"""

import json
from dataclasses import dataclass, field, replace
from types import ModuleType
from typing import Any

import pytest
from langchain_core.utils.function_calling import convert_to_openai_tool

from opsdesk.domain.ids import TenantId, TicketId
from opsdesk.domain.models import Ticket
from opsdesk.domain.ports import Repositories, TicketRepository
from opsdesk.observability.events import EventKind
from support import CallTool, MakeCaller

VIEW_FIELDS = {
    "id",
    "title",
    "status",
    "priority",
    "category",
    "assignee_id",
    "created_at",
    "updated_at",
}


@pytest.fixture
def tickets() -> ModuleType:
    from opsdesk.tools import tickets

    return tickets


def _ids(result: dict[str, Any]) -> list[str]:
    return [t["id"] for t in result["data"]]


# ---------------------------------------------------------------------- get_ticket


async def test_t1_own_ticket_is_returned_as_a_ticket_view(
    tickets: ModuleType, make_caller: MakeCaller, call_tool: CallTool
) -> None:
    an = await make_caller("E-001")
    result = await call_tool(tickets.get_ticket, {"ticket_id": "T-0002"}, an.tool_context)

    assert result["status"] == "ok"
    assert set(result["data"]) == VIEW_FIELDS  # nothing more: no description, no tenant
    assert result["data"]["id"] == "T-0002"
    assert result["data"]["status"] == "in_progress"
    assert result["data"]["assignee_id"] == "E-005"


async def test_t2_colleagues_ticket_is_denied_not_owner(
    tickets: ModuleType, make_caller: MakeCaller, call_tool: CallTool
) -> None:
    an = await make_caller("E-001")
    result = await call_tool(tickets.get_ticket, {"ticket_id": "T-0003"}, an.tool_context)

    assert (result["status"], result["error_code"]) == ("denied", "not_owner")
    assert result["data"] is None
    assert "Figma" not in json.dumps(result)  # not even the title leaks


async def test_t3_it_staff_sees_any_ticket_of_their_tenant(
    tickets: ModuleType, make_caller: MakeCaller, call_tool: CallTool
) -> None:
    hoa = await make_caller("E-005")
    result = await call_tool(tickets.get_ticket, {"ticket_id": "T-0003"}, hoa.tool_context)

    assert result["status"] == "ok"
    assert result["data"]["id"] == "T-0003"


async def test_t4_other_tenants_ticket_is_not_found(
    tickets: ModuleType, make_caller: MakeCaller, call_tool: CallTool
) -> None:
    minh = await make_caller("G-001", "globex")
    result = await call_tool(tickets.get_ticket, {"ticket_id": "T-0002"}, minh.tool_context)

    assert result["status"] == "not_found"
    assert result["error_code"] != "cross_tenant"
    assert "acme" not in json.dumps(result).lower()


async def test_t4_cross_tenant_is_indistinguishable_from_missing(
    tickets: ModuleType, make_caller: MakeCaller, call_tool: CallTool
) -> None:
    # The real point of T4: Globex cannot tell "exists at Acme" from "does not exist".
    minh = await make_caller("G-001", "globex")
    acme_ticket = await call_tool(tickets.get_ticket, {"ticket_id": "T-0002"}, minh.tool_context)
    no_ticket = await call_tool(tickets.get_ticket, {"ticket_id": "T-9999"}, minh.tool_context)

    assert acme_ticket == no_ticket


async def test_t5_unknown_ticket_is_not_found(
    tickets: ModuleType, make_caller: MakeCaller, call_tool: CallTool
) -> None:
    an = await make_caller("E-001")
    result = await call_tool(tickets.get_ticket, {"ticket_id": "T-9999"}, an.tool_context)

    assert result["status"] == "not_found"
    assert result["safe_message"]
    assert result["error_code"]


@dataclass
class SpyTickets:
    """A ticket repository that records ``get`` calls and delegates to the real one."""

    inner: TicketRepository
    gets: list[TicketId] = field(default_factory=list[TicketId])

    async def get(self, tenant_id: TenantId, ticket_id: TicketId) -> Ticket | None:
        self.gets.append(ticket_id)
        return await self.inner.get(tenant_id, ticket_id)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


async def test_t6_malformed_id_is_invalid_and_never_reaches_the_repository(
    tickets: ModuleType, make_caller: MakeCaller, call_tool: CallTool, seed_repos: Repositories
) -> None:
    spy = SpyTickets(seed_repos.tickets)
    an = await make_caller("E-001", repos=replace(seed_repos, tickets=spy))  # pyright: ignore[reportArgumentType]
    result = await call_tool(tickets.get_ticket, {"ticket_id": "abc"}, an.tool_context)

    assert (result["status"], result["error_code"]) == ("invalid", "invalid_id")
    assert spy.gets == []
    # Inside the harness boundary: the wrapper ran and logged it.
    [finished] = an.events(EventKind.TOOL_FINISHED)
    assert finished.payload["status"] == "invalid"


async def test_lower_case_id_is_accepted(
    tickets: ModuleType, make_caller: MakeCaller, call_tool: CallTool
) -> None:
    an = await make_caller("E-001")
    result = await call_tool(tickets.get_ticket, {"ticket_id": "t-0002"}, an.tool_context)

    assert result["status"] == "ok"
    assert result["data"]["id"] == "T-0002"


async def test_get_ticket_events_name_the_tool(
    tickets: ModuleType, make_caller: MakeCaller, call_tool: CallTool
) -> None:
    an = await make_caller("E-001")
    await call_tool(tickets.get_ticket, {"ticket_id": "T-0002"}, an.tool_context)

    assert an.sink.kinds() == [EventKind.TOOL_STARTED, EventKind.TOOL_FINISHED]
    started, finished = an.sink.events
    assert started.payload == {"tool": "get_ticket", "args": {"ticket_id": "T-0002"}}
    assert (finished.payload["tool"], finished.payload["status"]) == ("get_ticket", "ok")


# ----------------------------------------------------------------- list_my_tickets


async def test_l1_own_tickets_oldest_first(
    tickets: ModuleType, make_caller: MakeCaller, call_tool: CallTool
) -> None:
    an = await make_caller("E-001")
    result = await call_tool(tickets.list_my_tickets, {}, an.tool_context)

    assert result["status"] == "ok"
    # Oldest first by created_at: T-0009 (resolved) was opened on 2026-02-26, before
    # the others (2026-03-02). The milestone table lists these in id order.
    assert _ids(result) == ["T-0009", "T-0001", "T-0002", "T-0006"]
    assert all(set(t) == VIEW_FIELDS for t in result["data"])


async def test_l2_status_filter(
    tickets: ModuleType, make_caller: MakeCaller, call_tool: CallTool
) -> None:
    an = await make_caller("E-001")
    result = await call_tool(tickets.list_my_tickets, {"status": "resolved"}, an.tool_context)

    assert result["status"] == "ok"
    assert _ids(result) == ["T-0009"]


async def test_l3_no_tickets_is_empty_with_a_friendly_message(
    tickets: ModuleType, make_caller: MakeCaller, call_tool: CallTool
) -> None:
    lan = await make_caller("E-007")
    result = await call_tool(tickets.list_my_tickets, {}, lan.tool_context)

    assert result["status"] == "empty"
    assert result["safe_message"]
    assert result["error_code"] is None


async def test_filter_with_no_match_is_empty(
    tickets: ModuleType, make_caller: MakeCaller, call_tool: CallTool
) -> None:
    an = await make_caller("E-001")
    result = await call_tool(tickets.list_my_tickets, {"status": "closed"}, an.tool_context)

    assert result["status"] == "empty"


async def test_list_is_scoped_to_the_callers_tenant(
    tickets: ModuleType, make_caller: MakeCaller, call_tool: CallTool
) -> None:
    minh = await make_caller("G-001", "globex")
    result = await call_tool(tickets.list_my_tickets, {}, minh.tool_context)

    assert _ids(result) == ["T-0010"]


# ------------------------------------------------------------- D6-B: bounded output


@dataclass
class ManyTickets:
    """A ticket repository where the caller reported many tickets (oldest first)."""

    inner: TicketRepository
    tickets: list[Ticket]

    async def list_by_reporter(self, tenant_id: TenantId, reporter_id: str) -> list[Ticket]:
        return [
            t for t in self.tickets if t.tenant_id == tenant_id and t.reporter_id == reporter_id
        ]

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


@pytest.fixture
def an_with_25_tickets(make_caller: MakeCaller, seed_repos: Repositories, make_ticket: Any) -> Any:
    many = [make_ticket(id=f"T-{100 + i:04d}", reporter_id="E-001") for i in range(25)]
    repos = replace(seed_repos, tickets=ManyTickets(seed_repos.tickets, many))  # pyright: ignore[reportArgumentType]
    return make_caller("E-001", repos=repos)


async def test_limit_cuts_the_oldest_first_list(
    tickets: ModuleType, make_caller: MakeCaller, call_tool: CallTool
) -> None:
    an = await make_caller("E-001")
    result = await call_tool(tickets.list_my_tickets, {"limit": 2}, an.tool_context)

    assert _ids(result) == ["T-0009", "T-0001"]


async def test_default_limit_is_10(
    tickets: ModuleType, an_with_25_tickets: Any, call_tool: CallTool
) -> None:
    an = await an_with_25_tickets
    result = await call_tool(tickets.list_my_tickets, {}, an.tool_context)

    assert len(result["data"]) == 10
    assert _ids(result)[0] == "T-0100"  # oldest first


async def test_limit_above_max_is_clamped_to_20_inside_the_harness(
    tickets: ModuleType, an_with_25_tickets: Any, call_tool: CallTool
) -> None:
    an = await an_with_25_tickets
    result = await call_tool(tickets.list_my_tickets, {"limit": 50}, an.tool_context)

    assert result["status"] == "ok"
    assert len(result["data"]) == 20
    # Not rejected by the schema: the wrapper ran and logged the call (D6-B, like D4-B).
    [finished] = an.events(EventKind.TOOL_FINISHED)
    assert finished.payload["status"] == "ok"


async def test_limit_below_one_is_raised_to_one(
    tickets: ModuleType, make_caller: MakeCaller, call_tool: CallTool
) -> None:
    an = await make_caller("E-001")
    result = await call_tool(tickets.list_my_tickets, {"limit": 0}, an.tool_context)

    assert _ids(result) == ["T-0009"]


# ----------------------------------------------------------- model-visible schemas


def _properties(tool: Any) -> set[str]:
    return set(convert_to_openai_tool(tool)["function"]["parameters"]["properties"])


def test_schemas_expose_only_business_arguments(tickets: ModuleType) -> None:
    assert _properties(tickets.get_ticket) == {"ticket_id"}
    # No reporter_id: "my" tickets are always the caller's (M03 self-check Q4).
    # limit is a business argument (D6-B).
    assert _properties(tickets.list_my_tickets) == {"status", "limit"}


def test_descriptions_are_written(tickets: ModuleType) -> None:
    for tool in (tickets.get_ticket, tickets.list_my_tickets):
        assert tool.description
        assert "TODO" not in tool.description


# ------------------------------------------------------------------- TicketView 📖


# TicketView lives in the same module, so these also wait for harness_tool.


def test_ticket_view_fields_match_the_milestone(tickets: ModuleType) -> None:
    assert set(tickets.TicketView.model_fields) == VIEW_FIELDS


def test_ticket_view_from_ticket_copies_the_visible_fields(
    tickets: ModuleType, make_ticket: Any
) -> None:
    ticket = make_ticket(id="T-0042", assignee_id="E-005", description="secret notes")
    view = tickets.TicketView.from_ticket(ticket)

    assert view.model_dump() == ticket.model_dump(include=VIEW_FIELDS)
    assert "secret notes" not in view.model_dump_json()
