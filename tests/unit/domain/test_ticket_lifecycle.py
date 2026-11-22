"""Ticket lifecycle, the transition table from M01 §3.2.

The expected table is written out again here, independently of the code, and every
one of the 5 x 5 status pairs is checked for three kinds of actor. If someone edits
TRANSITIONS by mistake, a test fails.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from itertools import product

import pytest
from pydantic import ValidationError

from opsdesk.domain.errors import InvalidTransition, NotPermitted
from opsdesk.domain.models import Employee, Ticket, TicketStatus
from opsdesk.domain.policies.ticket_lifecycle import available_transitions, transition

S = TicketStatus
T0 = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)  # same as conftest factories
NOW = T0 + timedelta(hours=2)

# Spec table: (from, to) -> who may do it. "it", "reporter".
EXPECTED: dict[tuple[S, S], set[str]] = {
    (S.OPEN, S.IN_PROGRESS): {"it"},
    (S.IN_PROGRESS, S.WAITING_ON_USER): {"it"},
    (S.WAITING_ON_USER, S.IN_PROGRESS): {"it", "reporter"},
    (S.IN_PROGRESS, S.RESOLVED): {"it"},
    (S.RESOLVED, S.CLOSED): {"it", "reporter"},
    (S.RESOLVED, S.IN_PROGRESS): {"reporter"},
    (S.OPEN, S.CLOSED): {"reporter"},
}

ACTORS = ["it", "reporter", "other"]


@pytest.fixture
def people(make_employee: Callable[..., Employee]) -> dict[str, Employee]:
    return {
        # E-001 reports the ticket; E-005 is IT staff; E-002 is an unrelated employee.
        "reporter": make_employee(id="E-001"),
        "it": make_employee(id="E-005", department="it", roles=["employee", "it_staff"]),
        "other": make_employee(id="E-002", department="design"),
    }


@pytest.mark.parametrize(("frm", "to", "who"), list(product(S, S, ACTORS)))
def test_full_transition_table(
    make_ticket: Callable[..., Ticket],
    people: dict[str, Employee],
    frm: S,
    to: S,
    who: str,
) -> None:
    ticket = make_ticket(reporter_id="E-001", status=frm)
    actor = people[who]

    if (frm, to) not in EXPECTED:
        with pytest.raises(InvalidTransition):
            transition(ticket, to, actor, NOW)
    elif who not in EXPECTED[(frm, to)]:
        with pytest.raises(NotPermitted):
            transition(ticket, to, actor, NOW)
    else:
        moved = transition(ticket, to, actor, NOW)
        assert moved.status is to
        assert moved.updated_at == NOW
        assert ticket.status is frm  # original untouched


def test_same_status_is_invalid(
    make_ticket: Callable[..., Ticket], people: dict[str, Employee]
) -> None:
    t = make_ticket(status=S.IN_PROGRESS)
    with pytest.raises(InvalidTransition):
        transition(t, S.IN_PROGRESS, people["it"], NOW)


@pytest.mark.parametrize("to", list(S))
def test_closed_is_terminal(
    make_ticket: Callable[..., Ticket], people: dict[str, Employee], to: S
) -> None:
    t = make_ticket(status=S.CLOSED)
    for actor in people.values():
        with pytest.raises(InvalidTransition):
            transition(t, to, actor, NOW)


def test_other_tenant_is_not_permitted_even_for_it_manager(
    make_ticket: Callable[..., Ticket], make_employee: Callable[..., Employee]
) -> None:
    minh = make_employee(
        id="G-001", tenant_id="globex", department="it", roles=["employee", "it_manager"]
    )
    with pytest.raises(NotPermitted, match="tenant"):
        transition(make_ticket(status=S.OPEN), S.IN_PROGRESS, minh, NOW)


def test_other_tenant_learns_nothing_about_valid_moves(
    make_ticket: Callable[..., Ticket], make_employee: Callable[..., Employee]
) -> None:
    # An invalid move from another tenant still says NotPermitted, not
    # InvalidTransition: the tenant check runs before the table lookup.
    outsider = make_employee(id="G-001", tenant_id="globex")
    with pytest.raises(NotPermitted):
        transition(make_ticket(status=S.CLOSED), S.OPEN, outsider, NOW)


def test_reporter_who_is_also_it_has_both_powers(
    make_ticket: Callable[..., Ticket], make_employee: Callable[..., Employee]
) -> None:
    hoa = make_employee(id="E-005", department="it", roles=["employee", "it_staff"])
    own_ticket = make_ticket(reporter_id="E-005", status=S.RESOLVED)
    assert transition(own_ticket, S.IN_PROGRESS, hoa, NOW).status is S.IN_PROGRESS  # reporter
    assert transition(own_ticket, S.CLOSED, hoa, NOW).status is S.CLOSED  # IT


def test_assignee_without_it_role_gets_no_extra_power(
    make_ticket: Callable[..., Ticket], make_employee: Callable[..., Employee]
) -> None:
    assignee = make_employee(id="E-002")
    t = make_ticket(assignee_id="E-002", status=S.OPEN)
    with pytest.raises(NotPermitted):
        transition(t, S.IN_PROGRESS, assignee, NOW)


def test_now_before_creation_is_rejected_by_model_validation(
    make_ticket: Callable[..., Ticket], people: dict[str, Employee]
) -> None:
    with pytest.raises(ValidationError, match="updated_at"):
        transition(make_ticket(status=S.OPEN), S.IN_PROGRESS, people["it"], T0 - timedelta(1))


# ------------------------------------------------------------- available_transitions


@pytest.mark.parametrize(
    ("status", "who", "expected"),
    [
        (S.OPEN, "it", {S.IN_PROGRESS}),
        (S.OPEN, "reporter", {S.CLOSED}),
        (S.OPEN, "other", set()),
        (S.RESOLVED, "reporter", {S.CLOSED, S.IN_PROGRESS}),
        (S.RESOLVED, "it", {S.CLOSED}),
        (S.CLOSED, "it", set()),
    ],
)
def test_available_transitions(
    make_ticket: Callable[..., Ticket],
    people: dict[str, Employee],
    status: S,
    who: str,
    expected: set[S],
) -> None:
    t = make_ticket(reporter_id="E-001", status=status)
    assert available_transitions(t, people[who]) == expected


def test_available_transitions_empty_for_other_tenant(
    make_ticket: Callable[..., Ticket], make_employee: Callable[..., Employee]
) -> None:
    minh = make_employee(id="G-001", tenant_id="globex", roles=["employee", "it_manager"])
    assert available_transitions(make_ticket(), minh) == frozenset()
