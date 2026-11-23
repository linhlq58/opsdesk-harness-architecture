"""Read-only ticket tools (M03 §8).

Decisions: D3-A (cross-tenant is not_found), D4-B (id format checked inside the tool),
D5-A (minimal ``TicketView``), D6-B (``limit`` default 10, clamped to 1..20).

Tests: ``tests/unit/tools/test_tickets.py`` (cases T1-T6, L1-L3).
"""

from pydantic import BaseModel, ConfigDict, Field

from opsdesk.core.clock import UtcDatetime
from opsdesk.core.result import ToolResult
from opsdesk.domain.ids import EmployeeId, TicketId, parse_ticket_id
from opsdesk.domain.models import Ticket, TicketCategory, TicketPriority, TicketStatus
from opsdesk.domain.policies.visibility import can_view_ticket
from opsdesk.security.scopes import Scope
from opsdesk.tools.context import ToolContext
from opsdesk.tools.taxonomy import result_from_decision
from opsdesk.tools.wrapper import harness_tool

# ----------------------------------------------------------------- what the model sees


class TicketView(BaseModel):
    """The part of a ``Ticket`` the model may see (M03 §7.1).

    Left out on purpose: ``description`` (free text written by people, possibly other
    employees, and a place for prompt injection), ``tenant_id`` (an internal detail
    the model never needs), ``reporter_id`` (for ``list_my_tickets`` it is always the
    caller), ``asset_tag`` (asset lookups come in M08).

    ``extra="forbid"``: adding a field is a deliberate change here, never a side effect
    of ``Ticket`` growing.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: TicketId
    title: str
    status: TicketStatus
    priority: TicketPriority
    category: TicketCategory
    assignee_id: EmployeeId | None
    created_at: UtcDatetime
    updated_at: UtcDatetime

    @classmethod
    def from_ticket(cls, ticket: Ticket) -> "TicketView":
        # Field by field, not model_validate(ticket, from_attributes=True): the list
        # of what crosses to the model should be readable in one place.
        return cls(
            id=ticket.id,
            title=ticket.title,
            status=ticket.status,
            priority=ticket.priority,
            category=ticket.category,
            assignee_id=ticket.assignee_id,
            created_at=ticket.created_at,
            updated_at=ticket.updated_at,
        )


# ---------------------------------------------------------------- what the model fills


class GetTicketArgs(BaseModel):
    # A plain str, no ``pattern``: the format check happens inside the harness
    # (``parse_ticket_id``) so a bad id becomes ToolResult(invalid) + events, not a
    # LangChain error string the wrapper never sees. See ``tools.wrapper`` docstring.
    ticket_id: str = Field(description="Ticket id, for example T-0001.")


DEFAULT_LIST_LIMIT = 10
MAX_LIST_LIMIT = 20


class ListMyTicketsArgs(BaseModel):
    # No reporter_id: the reporter is always the caller (``principal.user_id``).
    status: TicketStatus | None = Field(
        default=None, description="Only tickets with this status. Omit for all."
    )
    # D6-B: bounded output. Deliberately no ge/le here: an out-of-range value is
    # clamped inside the tool, so it still goes through the harness (same reason as
    # D4-B). Values above MAX_LIST_LIMIT become MAX_LIST_LIMIT, below 1 become 1.
    limit: int = Field(
        default=DEFAULT_LIST_LIMIT,
        description=f"How many tickets to return, oldest first. At most {MAX_LIST_LIMIT}.",
    )


_NOT_FOUND = "I couldn't find a ticket with that id."
_NO_TICKETS = "You have no tickets."
_NO_MATCHING_TICKETS = "You have no tickets with that status."


# ------------------------------------------------------------------------- 🎯 tools


@harness_tool(
    name="get_ticket",
    description=(
        "Look up one IT support ticket by its id (for example T-0001) and return its "
        "title, status, priority, category, assignee and dates. Use it whenever the "
        "user asks about a specific ticket."
    ),
    args_schema=GetTicketArgs,
    scope=Scope.TICKET_READ,
)
async def get_ticket(ctx: ToolContext, args: GetTicketArgs) -> ToolResult[TicketView]:
    """One ticket by id, if the caller may see it (cases T1-T6)."""
    principal = ctx.request.principal

    # D4-B: the format check is here, inside the harness. A bad id raises
    # InvalidIdentifier, which the wrapper maps to invalid/invalid_id (T6); the
    # repository is never called.
    ticket_id = parse_ticket_id(args.ticket_id)

    # D3-A: the repository is tenant-scoped, so another tenant's ticket is simply
    # not found. Same branch, same message as a missing ticket (T4 == T5).
    ticket = await ctx.repos.tickets.get(principal.tenant_id, ticket_id)
    if ticket is None:
        return ToolResult.not_found(_NOT_FOUND, "ticket_not_found")

    # The domain rule needs the Employee (roles, tenant), not just the Principal.
    actor = await ctx.repos.employees.get(principal.tenant_id, principal.user_id)
    if actor is None:
        # A principal without an employee record is a broken invariant, not a user
        # error: fail loudly (D1-A) instead of answering politely.
        raise LookupError(f"principal {principal.user_id} has no employee record")

    decision = can_view_ticket(actor, ticket)  # T2 denied/not_owner, T3 IT allowed
    if not decision.allowed:
        return result_from_decision(decision)

    return ToolResult.ok(TicketView.from_ticket(ticket))  # D5-A: the minimal view


@harness_tool(
    name="list_my_tickets",
    description=(
        "List the IT support tickets the current user reported, oldest first, "
        "optionally only those with a given status. Use it when the user asks about "
        "'my tickets' without naming one."
    ),
    args_schema=ListMyTicketsArgs,
    scope=Scope.TICKET_READ,
)
async def list_my_tickets(
    ctx: ToolContext, args: ListMyTicketsArgs
) -> ToolResult[list[TicketView]]:
    """The caller's own tickets, oldest first, optionally filtered by status (L1-L3)."""
    principal = ctx.request.principal

    # Identity from the server only: the reporter is always the caller.
    tickets = await ctx.repos.tickets.list_by_reporter(principal.tenant_id, principal.user_id)
    if args.status is not None:
        tickets = [t for t in tickets if t.status == args.status]

    if not tickets:
        return ToolResult.empty(_NO_TICKETS if args.status is None else _NO_MATCHING_TICKETS)

    # D6-B: clamp, then cut (the repository already returns oldest first).
    limit = min(max(args.limit, 1), MAX_LIST_LIMIT)
    return ToolResult.ok([TicketView.from_ticket(t) for t in tickets[:limit]])
