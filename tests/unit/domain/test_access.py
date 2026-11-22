"""Access-request evaluation, cases A1-A8 from M01 §3.3.

Software mirrors the seed catalogue (M01 §5); the threshold is 5,000,000 VND.
"""

from collections.abc import Callable

import pytest

from opsdesk.core.money import Money
from opsdesk.domain.decisions import AccessEvaluation, AccessOutcome, ReasonCode
from opsdesk.domain.models import AccessKind, Employee, SoftwareItem
from opsdesk.domain.policies.access import AccessRules, evaluate_access_request

R = ReasonCode
LICENCE = AccessKind.SOFTWARE_LICENCE
ADMIN = AccessKind.ADMIN_RIGHTS
RULES = AccessRules(licence_review_threshold=Money(5_000_000))


@pytest.fixture
def catalogue(make_software: Callable[..., SoftwareItem]) -> dict[str, SoftwareItem]:
    return {
        "slack": make_software(id="SW-SLACK", name="Slack", annual_cost=1_200_000),
        "figma": make_software(id="SW-FIGMA", name="Figma", annual_cost=5_000_000),
        "just_below": make_software(id="SW-X", name="Just below", annual_cost=4_999_999),
        "jetbrains": make_software(id="SW-JB", name="JetBrains", annual_cost=7_500_000),
        "jetbrains_admin": make_software(
            id="SW-JBA", name="JetBrains (admin)", annual_cost=7_500_000, requires_admin=True
        ),
        "powerbi": make_software(
            id="SW-PBI", name="Power BI Pro", annual_cost=4_000_000, restricted_to=["finance"]
        ),
        "adobe": make_software(
            id="SW-ADOBE", name="Adobe CC", annual_cost=15_000_000, restricted_to=["design"]
        ),
        "docker": make_software(
            id="SW-DOCKER", name="Docker Desktop", annual_cost=2_400_000, requires_admin=True
        ),
    }


@pytest.fixture
def an(make_employee: Callable[..., Employee]) -> Employee:
    """E-001, engineering, regular employee, owns nothing."""
    return make_employee(id="E-001", department="engineering")


# ------------------------------------------------------------------- spec cases A1-A8


def test_a1_cheap_unrestricted_licence_is_auto_approved(
    an: Employee, catalogue: dict[str, SoftwareItem]
) -> None:
    ev = evaluate_access_request(an, LICENCE, catalogue["slack"], RULES)
    assert ev == AccessEvaluation.auto_approve()


def test_a2_cost_exactly_at_threshold_needs_approval(
    an: Employee, catalogue: dict[str, SoftwareItem]
) -> None:
    ev = evaluate_access_request(an, LICENCE, catalogue["figma"], RULES)
    assert ev.outcome is AccessOutcome.NEEDS_APPROVAL
    assert ev.reasons == (R.HIGH_COST,)


def test_a3_one_vnd_below_threshold_is_auto_approved(
    an: Employee, catalogue: dict[str, SoftwareItem]
) -> None:
    ev = evaluate_access_request(an, LICENCE, catalogue["just_below"], RULES)
    assert ev.outcome is AccessOutcome.AUTO_APPROVE


def test_a4_expensive_and_requires_admin_returns_both_reasons(
    an: Employee, catalogue: dict[str, SoftwareItem]
) -> None:
    ev = evaluate_access_request(an, LICENCE, catalogue["jetbrains_admin"], RULES)
    assert ev.outcome is AccessOutcome.NEEDS_APPROVAL
    assert ev.reasons == (R.ADMIN_RIGHTS, R.HIGH_COST)  # all gates, stable order


def test_a5_admin_rights_request_needs_approval(an: Employee) -> None:
    ev = evaluate_access_request(an, ADMIN, None, RULES)
    assert ev.outcome is AccessOutcome.NEEDS_APPROVAL
    assert ev.reasons == (R.ADMIN_RIGHTS,)


def test_a6_department_restricted_tool_is_rejected(
    an: Employee, catalogue: dict[str, SoftwareItem]
) -> None:
    ev = evaluate_access_request(an, LICENCE, catalogue["powerbi"], RULES)
    assert ev == AccessEvaluation.reject(R.DEPARTMENT_RESTRICTED)


def test_a7_reject_wins_over_review_for_owned_expensive_tool(
    make_employee: Callable[..., Employee], catalogue: dict[str, SoftwareItem]
) -> None:
    owner = make_employee(id="E-001", owned_software=["SW-JB"])
    ev = evaluate_access_request(owner, LICENCE, catalogue["jetbrains"], RULES)
    assert ev.outcome is AccessOutcome.REJECT
    assert ev.reasons == (R.ALREADY_OWNED,)  # HIGH_COST is not mixed in


def test_a8_licence_without_software_is_invalid(an: Employee) -> None:
    ev = evaluate_access_request(an, LICENCE, None, RULES)
    assert ev == AccessEvaluation.reject(R.INVALID_REQUEST)


# ------------------------------------------------------------------- additional cases


def test_admin_rights_with_software_is_invalid(
    an: Employee, catalogue: dict[str, SoftwareItem]
) -> None:
    ev = evaluate_access_request(an, ADMIN, catalogue["docker"], RULES)
    assert ev == AccessEvaluation.reject(R.INVALID_REQUEST)


def test_cheap_tool_requiring_admin_needs_approval(
    an: Employee, catalogue: dict[str, SoftwareItem]
) -> None:
    ev = evaluate_access_request(an, LICENCE, catalogue["docker"], RULES)
    assert ev.reasons == (R.ADMIN_RIGHTS,)


def test_all_reject_reasons_are_collected(
    make_employee: Callable[..., Employee], catalogue: dict[str, SoftwareItem]
) -> None:
    # Moved from design to engineering but still holds an Adobe licence.
    moved = make_employee(id="E-009", department="engineering", owned_software=["SW-ADOBE"])
    ev = evaluate_access_request(moved, LICENCE, catalogue["adobe"], RULES)
    assert ev.reasons == (R.DEPARTMENT_RESTRICTED, R.ALREADY_OWNED)


def test_restricted_tool_is_fine_for_its_own_department(
    make_employee: Callable[..., Employee], catalogue: dict[str, SoftwareItem]
) -> None:
    dung = make_employee(id="E-004", department="finance", roles=["employee", "finance"])
    ev = evaluate_access_request(dung, LICENCE, catalogue["powerbi"], RULES)
    assert ev.outcome is AccessOutcome.AUTO_APPROVE


def test_owning_a_different_tool_does_not_matter(
    make_employee: Callable[..., Employee], catalogue: dict[str, SoftwareItem]
) -> None:
    owner = make_employee(id="E-001", owned_software=["SW-JB"])
    ev = evaluate_access_request(owner, LICENCE, catalogue["slack"], RULES)
    assert ev.outcome is AccessOutcome.AUTO_APPROVE


@pytest.mark.parametrize(
    ("threshold", "expected"),
    [(1_000_000, AccessOutcome.NEEDS_APPROVAL), (1_200_001, AccessOutcome.AUTO_APPROVE)],
)
def test_threshold_comes_from_rules_not_code(
    an: Employee, catalogue: dict[str, SoftwareItem], threshold: int, expected: AccessOutcome
) -> None:
    rules = AccessRules(licence_review_threshold=Money(threshold))
    assert evaluate_access_request(an, LICENCE, catalogue["slack"], rules).outcome is expected
