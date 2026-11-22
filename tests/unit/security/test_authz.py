from typing import Any

import pytest

from opsdesk.domain.decisions import Decision, ReasonCode
from opsdesk.domain.models import Employee
from opsdesk.security.authz import require_scope
from opsdesk.security.principal import principal_for
from opsdesk.security.scopes import Scope

DENY = Decision.deny(ReasonCode.MISSING_SCOPE)


@pytest.mark.parametrize(
    ("roles", "scope", "expected"),
    [
        (["employee"], Scope.TICKET_READ, Decision.allow()),
        (["employee"], Scope.ACCESS_APPROVE, DENY),
        (["employee"], Scope.ASSET_READ, DENY),
        (["employee", "it_staff"], Scope.ASSET_READ, Decision.allow()),
        (["employee", "it_staff"], Scope.ACCESS_APPROVE, DENY),
        (["employee", "it_manager"], Scope.ACCESS_APPROVE, Decision.allow()),
        (["employee", "hr"], Scope.REPORT_READ, DENY),
    ],
)
def test_require_scope(
    make_employee: Any, roles: list[str], scope: Scope, expected: Decision
) -> None:
    employee: Employee = make_employee(roles=roles)
    assert require_scope(principal_for(employee), scope) == expected
