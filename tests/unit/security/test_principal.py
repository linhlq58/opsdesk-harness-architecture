from pathlib import Path

import pytest
from pydantic import ValidationError

from opsdesk.domain.models import Employee
from opsdesk.persistence.seed import load_seed
from opsdesk.security.principal import Principal, principal_for
from opsdesk.security.scopes import Scope

REAL_SEED = Path(__file__).resolve().parents[3] / "data" / "seed"
S = Scope
EMPLOYEE = {S.TICKET_READ, S.TICKET_CREATE, S.TICKET_UPDATE, S.ACCESS_REQUEST, S.KB_READ}
IT_STAFF = EMPLOYEE | {S.ASSET_READ}
IT_MANAGER = IT_STAFF | {S.ACCESS_APPROVE, S.REPORT_READ}


@pytest.fixture(scope="module")
def seed_employees() -> dict[str, Employee]:
    return {e.id: e for e in load_seed(REAL_SEED).employees}


@pytest.mark.parametrize(
    ("employee_id", "tenant", "scopes", "groups"),
    [
        ("E-001", "acme", EMPLOYEE, {"employee", "dept:engineering"}),
        ("E-002", "acme", EMPLOYEE, {"employee", "dept:design"}),
        ("E-003", "acme", EMPLOYEE, {"employee", "hr", "dept:hr"}),
        ("E-004", "acme", EMPLOYEE, {"employee", "finance", "dept:finance"}),
        ("E-005", "acme", IT_STAFF, {"employee", "it_staff", "dept:it"}),
        ("E-006", "acme", IT_MANAGER, {"employee", "it_manager", "dept:it"}),
        ("E-007", "acme", IT_MANAGER, {"employee", "it_manager", "dept:it"}),
        ("G-001", "globex", IT_MANAGER, {"employee", "it_manager", "dept:it"}),
    ],
)
def test_principal_for_every_seed_employee(
    seed_employees: dict[str, Employee],
    employee_id: str,
    tenant: str,
    scopes: set[Scope],
    groups: set[str],
) -> None:
    p = principal_for(seed_employees[employee_id])
    assert p.user_id == employee_id
    assert p.tenant_id == tenant
    assert p.scopes == scopes
    assert p.groups == groups


def test_every_seed_employee_is_covered(seed_employees: dict[str, Employee]) -> None:
    # A new seed persona should get a row in the table above.
    assert set(seed_employees) == {f"E-00{i}" for i in range(1, 8)} | {"G-001"}


def test_principal_contains_no_pii(seed_employees: dict[str, Employee]) -> None:
    employee = seed_employees["E-004"]
    dumped = principal_for(employee).model_dump_json()
    assert employee.full_name not in dumped
    assert employee.email not in dumped


def test_hand_crafted_extra_scope_is_rejected(seed_employees: dict[str, Employee]) -> None:
    # An employee cannot be given access:approve by building a Principal by hand.
    data = principal_for(seed_employees["E-001"]).model_dump()
    data["scopes"] = data["scopes"] | {Scope.ACCESS_APPROVE}
    with pytest.raises(ValidationError, match="scopes must be derived"):
        Principal.model_validate(data)


def test_hand_crafted_group_is_rejected(seed_employees: dict[str, Employee]) -> None:
    data = principal_for(seed_employees["E-001"]).model_dump()
    data["groups"] = data["groups"] | {"finance"}
    with pytest.raises(ValidationError, match="groups must be derived"):
        Principal.model_validate(data)


def test_principal_round_trips_through_json(seed_employees: dict[str, Employee]) -> None:
    p = principal_for(seed_employees["E-006"])
    assert Principal.model_validate_json(p.model_dump_json()) == p


def test_principal_is_immutable(seed_employees: dict[str, Employee]) -> None:
    p = principal_for(seed_employees["E-001"])
    with pytest.raises(ValidationError):
        p.scopes = frozenset(Scope)  # type: ignore[misc]
