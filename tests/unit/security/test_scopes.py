import pytest

from opsdesk.domain.models import Role
from opsdesk.security.scopes import ROLE_SCOPES, Scope, scopes_for

S = Scope
EMPLOYEE = {S.TICKET_READ, S.TICKET_CREATE, S.TICKET_UPDATE, S.ACCESS_REQUEST, S.KB_READ}


def test_every_role_is_in_the_table() -> None:
    # A new Role without a row would make scopes_for raise KeyError at login time.
    assert set(ROLE_SCOPES) == set(Role)


@pytest.mark.parametrize(
    ("roles", "expected"),
    [
        ({Role.EMPLOYEE}, EMPLOYEE),
        ({Role.EMPLOYEE, Role.IT_STAFF}, EMPLOYEE | {S.ASSET_READ}),
        (
            {Role.EMPLOYEE, Role.IT_MANAGER},
            EMPLOYEE | {S.ASSET_READ, S.ACCESS_APPROVE, S.REPORT_READ},
        ),
        ({Role.EMPLOYEE, Role.HR}, EMPLOYEE),  # hr adds no scopes
        ({Role.EMPLOYEE, Role.FINANCE}, EMPLOYEE),  # finance adds no scopes
        (set[Role](), set[Scope]()),
    ],
)
def test_scopes_are_the_union_over_roles(roles: set[Role], expected: set[Scope]) -> None:
    assert scopes_for(roles) == expected


def test_only_it_manager_can_approve() -> None:
    approvers = {role for role, scopes in ROLE_SCOPES.items() if S.ACCESS_APPROVE in scopes}
    assert approvers == {Role.IT_MANAGER}


def test_table_is_read_only() -> None:
    with pytest.raises(TypeError):
        ROLE_SCOPES[Role.EMPLOYEE] = frozenset(Scope)  # type: ignore[index]


def test_scope_values_are_stable() -> None:
    # Stored in tokens and audit records: renaming one is a breaking change.
    assert [s.value for s in Scope] == [
        "ticket:read",
        "ticket:create",
        "ticket:update",
        "access:request",
        "kb:read",
        "asset:read",
        "access:approve",
        "report:read",
    ]
