"""Ticket visibility, cases V1-V6 from M01 §3.1.

Ticket T-0001 belongs to Acme, reported by E-001, assigned to E-005 (IT staff).
"""

from collections.abc import Callable

import pytest

from opsdesk.domain.decisions import Decision, ReasonCode
from opsdesk.domain.models import Employee, Ticket
from opsdesk.domain.policies.visibility import can_view_ticket


@pytest.fixture
def ticket(make_ticket: Callable[..., Ticket]) -> Ticket:
    return make_ticket(reporter_id="E-001", assignee_id="E-005")


def test_v1_other_tenant_is_denied_even_for_it_manager(
    make_employee: Callable[..., Employee], ticket: Ticket
) -> None:
    minh = make_employee(
        id="G-001", tenant_id="globex", department="it", roles=["employee", "it_manager"]
    )
    assert can_view_ticket(minh, ticket) == Decision.deny(ReasonCode.CROSS_TENANT)


def test_v1_same_employee_id_in_other_tenant_is_denied(
    make_employee: Callable[..., Employee], ticket: Ticket
) -> None:
    # Ids are unique per tenant only. Globex may also have an "E-001".
    globex_e001 = make_employee(id="E-001", tenant_id="globex")
    assert can_view_ticket(globex_e001, ticket) == Decision.deny(ReasonCode.CROSS_TENANT)


def test_v2_reporter_can_view(make_employee: Callable[..., Employee], ticket: Ticket) -> None:
    an = make_employee(id="E-001")
    assert can_view_ticket(an, ticket) == Decision.allow()


def test_v3_assignee_can_view(make_employee: Callable[..., Employee], ticket: Ticket) -> None:
    # Assignee without an IT role: allowed through ownership, not through role.
    assignee = make_employee(id="E-005", roles=["employee"])
    assert can_view_ticket(assignee, ticket) == Decision.allow()


@pytest.mark.parametrize("it_role", ["it_staff", "it_manager"])
def test_v4_it_in_same_tenant_can_view(
    make_employee: Callable[..., Employee], ticket: Ticket, it_role: str
) -> None:
    it_person = make_employee(id="E-006", department="it", roles=["employee", it_role])
    assert can_view_ticket(it_person, ticket) == Decision.allow()


def test_v5_regular_employee_not_involved_is_denied(
    make_employee: Callable[..., Employee], ticket: Ticket
) -> None:
    binh = make_employee(id="E-002", department="design")
    assert can_view_ticket(binh, ticket) == Decision.deny(ReasonCode.NOT_OWNER)


@pytest.mark.parametrize(
    ("emp_id", "department", "role"),
    [("E-003", "hr", "hr"), ("E-004", "finance", "finance")],
)
def test_v6_business_roles_do_not_grant_access(
    make_employee: Callable[..., Employee], ticket: Ticket, emp_id: str, department: str, role: str
) -> None:
    person = make_employee(id=emp_id, department=department, roles=["employee", role])
    assert can_view_ticket(person, ticket) == Decision.deny(ReasonCode.NOT_OWNER)


def test_unassigned_ticket_does_not_match_anyone_as_assignee(
    make_employee: Callable[..., Employee], make_ticket: Callable[..., Ticket]
) -> None:
    unassigned = make_ticket(assignee_id=None)
    binh = make_employee(id="E-002")
    assert can_view_ticket(binh, unassigned).reason is ReasonCode.NOT_OWNER
