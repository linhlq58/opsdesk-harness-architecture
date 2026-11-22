"""Ticket status state machine (M01 §3.2).

The transition table is **data**, not a chain of ``if``s: each allowed move maps to
the kinds of actor who may make it. Anything not in the table does not exist.

    open ──IT──▶ in_progress ──IT──▶ waiting_on_user
      │            ▲    │  ◀──IT/reporter──┘
      │            │    │
      │   reporter │    IT
      │   (reopen) │    ▼
      │            └─ resolved ──IT/reporter──▶ closed (terminal)
      └──────────reporter (withdraw)──────────────▶ closed
"""

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType

from opsdesk.domain.errors import InvalidTransition, NotPermitted
from opsdesk.domain.models import Employee, Ticket, TicketStatus


class ActorKind(StrEnum):
    """How an employee relates to a given ticket. One person can be several kinds."""

    IT = "it"  # it_staff or it_manager in the ticket's tenant
    REPORTER = "reporter"  # the employee who opened the ticket


_IT = frozenset({ActorKind.IT})
_REPORTER = frozenset({ActorKind.REPORTER})
_IT_OR_REPORTER = _IT | _REPORTER

S = TicketStatus

# (from, to) -> who may do it. Read it exactly like the table in M01 §3.2.
# MappingProxyType makes the module-level table read-only at runtime.
TRANSITIONS: Mapping[tuple[TicketStatus, TicketStatus], frozenset[ActorKind]] = MappingProxyType(
    {
        (S.OPEN, S.IN_PROGRESS): _IT,
        (S.IN_PROGRESS, S.WAITING_ON_USER): _IT,
        (S.WAITING_ON_USER, S.IN_PROGRESS): _IT_OR_REPORTER,
        (S.IN_PROGRESS, S.RESOLVED): _IT,
        (S.RESOLVED, S.CLOSED): _IT_OR_REPORTER,
        (S.RESOLVED, S.IN_PROGRESS): _REPORTER,  # reopen
        (S.OPEN, S.CLOSED): _REPORTER,  # withdraw
    }
)


def actor_kinds(actor: Employee, ticket: Ticket) -> frozenset[ActorKind]:
    """Every role ``actor`` plays for ``ticket``. Assumes the tenant was checked."""
    kinds: set[ActorKind] = set()
    if actor.is_it:
        kinds.add(ActorKind.IT)
    if actor.id == ticket.reporter_id:
        kinds.add(ActorKind.REPORTER)
    return frozenset(kinds)


def available_transitions(ticket: Ticket, actor: Employee) -> frozenset[TicketStatus]:
    """Statuses ``actor`` may move ``ticket`` to right now (empty if none / other tenant).

    Useful to tell a UI or a model which actions are valid *before* it tries one.
    """
    if actor.tenant_id != ticket.tenant_id:
        return frozenset()
    kinds = actor_kinds(actor, ticket)
    return frozenset(
        to
        for (frm, to), allowed in TRANSITIONS.items()
        if frm is ticket.status and not allowed.isdisjoint(kinds)
    )


def transition(ticket: Ticket, to: TicketStatus, actor: Employee, now: datetime) -> Ticket:
    """Move ``ticket`` to ``to`` on behalf of ``actor``.

    Returns a new ticket with the new status and ``updated_at = now``.
    Raises ``NotPermitted`` (wrong tenant / wrong actor) or ``InvalidTransition``
    (the move is not in the table, including same-status and anything from closed).
    """
    # 1. Tenant first, and before revealing anything about the ticket's state: an
    #    outsider must not learn whether a move would have been valid.
    if actor.tenant_id != ticket.tenant_id:
        raise NotPermitted(f"{actor.id} is not in tenant {ticket.tenant_id}")

    # 2. Does this move exist at all? Same-status and "closed -> x" are simply
    #    absent from the table, so they need no special case.
    allowed = TRANSITIONS.get((ticket.status, to))
    if allowed is None:
        raise InvalidTransition(f"{ticket.status} -> {to} is not a valid transition")

    # 3. Is this actor one of the kinds allowed to make it?
    if allowed.isdisjoint(actor_kinds(actor, ticket)):
        who = " or ".join(sorted(allowed))
        raise NotPermitted(f"{ticket.status} -> {to} requires {who}")

    # evolve() re-validates, e.g. rejects a `now` earlier than created_at.
    return ticket.evolve(status=to, updated_at=now)
