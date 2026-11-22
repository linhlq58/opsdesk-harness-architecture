from typing import Any

import pytest

from opsdesk.core.errors import BudgetExceeded
from opsdesk.core.result import ErrorClass, ToolResult, ToolStatus
from opsdesk.domain.decisions import Decision, ReasonCode
from opsdesk.domain.errors import DomainError, InvalidTransition, NotPermitted
from opsdesk.tools.taxonomy import result_from_decision, result_from_domain_error

# ------------------------------------------------------------------ the mapping table


@pytest.mark.parametrize(
    ("exc", "status", "code"),
    [
        (
            InvalidTransition("closed -> open is not a valid transition"),
            "invalid",
            "invalid_transition",
        ),
        (
            NotPermitted("E-006 may not decide", reason=ReasonCode.SELF_APPROVAL),
            "denied",
            "self_approval",
        ),
        (NotPermitted("E-099 is not in tenant acme"), "denied", "not_permitted"),
        (DomainError("something else"), "invalid", "domain_error"),
    ],
)
def test_domain_error_mapping(exc: DomainError, status: str, code: str) -> None:
    r = result_from_domain_error(exc)
    assert r.status == status
    assert r.error_code == code
    assert r.data is None
    assert r.safe_message


@pytest.mark.parametrize("reason", [r for r in ReasonCode if r is not ReasonCode.OK])
def test_every_denied_decision_maps_to_denied_with_its_code(reason: ReasonCode) -> None:
    # Also proves every non-OK reason code has a safe message (no KeyError).
    r = result_from_decision(Decision.deny(reason))
    assert r.status is ToolStatus.DENIED
    assert r.status.error_class is ErrorClass.POLICY
    assert r.error_code == reason.value


def test_allowed_decision_is_a_caller_bug() -> None:
    with pytest.raises(ValueError, match="denied"):
        result_from_decision(Decision.allow())


def test_mapped_results_are_assignable_to_any_tool_result() -> None:
    # The point of ToolResult[Never]: usable as the return of a typed tool.
    def tool() -> ToolResult[list[str]]:
        return result_from_decision(Decision.deny(ReasonCode.NOT_OWNER))

    assert tool().error_code == "not_owner"


# ------------------------------------------------------------------- safe messages


@pytest.mark.parametrize(
    "exc",
    [
        NotPermitted("E-006 is not in tenant acme"),
        NotPermitted(
            "E-006 may not decide on AR-0003: cross_tenant", reason=ReasonCode.CROSS_TENANT
        ),
        InvalidTransition("closed -> open is not a valid transition"),
        DomainError("secret detail T-0042"),
    ],
)
def test_safe_message_never_contains_exception_text(exc: DomainError) -> None:
    r = result_from_domain_error(exc)
    assert r.safe_message is not None
    assert str(exc) not in r.safe_message
    for leak in ("acme", "E-006", "AR-0003", "T-0042"):
        assert leak not in r.safe_message


def test_cross_tenant_message_does_not_confirm_existence() -> None:
    r = result_from_decision(Decision.deny(ReasonCode.CROSS_TENANT))
    assert r.safe_message is not None
    assert "tenant" not in r.safe_message.lower()
    assert "exist" not in r.safe_message.lower()


def test_caller_can_override_the_safe_message() -> None:
    r = result_from_decision(
        Decision.deny(ReasonCode.NOT_OWNER), safe_message="You can only view your own tickets."
    )
    assert r.safe_message == "You can only view your own tickets."
    assert r.error_code == "not_owner"


# ------------------------------------------------------------- bugs are not swallowed


def test_non_domain_exception_is_not_swallowed_by_a_tool() -> None:
    # How M03 tools use it: catch DomainError only. A bug passes straight through.
    def tool() -> ToolResult[str]:
        try:
            raise KeyError("T-0042")
        except DomainError as exc:
            return result_from_domain_error(exc)

    with pytest.raises(KeyError):
        tool()


@pytest.mark.parametrize("exc", [KeyError("x"), AttributeError("x"), BudgetExceeded("turn")])
def test_mapping_refuses_non_domain_exceptions_at_runtime(exc: Any) -> None:
    # Even if an untyped caller passes one in, it is not turned into "invalid".
    with pytest.raises(TypeError, match="not a DomainError"):
        result_from_domain_error(exc)
