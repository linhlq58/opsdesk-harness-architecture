import pytest

from opsdesk.domain.decisions import AccessEvaluation, AccessOutcome, Decision, ReasonCode

# -------------------------------------------------------------------------- Decision


def test_allow_and_deny() -> None:
    assert Decision.allow() == Decision(allowed=True, reason=ReasonCode.OK)
    denied = Decision.deny(ReasonCode.CROSS_TENANT)
    assert not denied.allowed
    assert denied.reason is ReasonCode.CROSS_TENANT


@pytest.mark.parametrize(
    ("allowed", "reason"),
    [(True, ReasonCode.NOT_OWNER), (False, ReasonCode.OK)],
)
def test_inconsistent_decision_is_rejected(allowed: bool, reason: ReasonCode) -> None:
    with pytest.raises(ValueError, match="inconsistent"):
        Decision(allowed=allowed, reason=reason)


def test_decision_cannot_be_truth_tested() -> None:
    # `if decision:` would always be True for a plain dataclass, even when denied.
    with pytest.raises(TypeError, match="allowed"):
        bool(Decision.deny(ReasonCode.NOT_OWNER))


def test_reason_codes_are_stable_strings() -> None:
    # These values end up in audit logs and eval datasets.
    assert ReasonCode.CROSS_TENANT == "cross_tenant"
    assert ReasonCode.SELF_APPROVAL.value == "self_approval"


# ------------------------------------------------------------------ AccessEvaluation


def test_auto_approve_has_ok_reason() -> None:
    ev = AccessEvaluation.auto_approve()
    assert ev.outcome is AccessOutcome.AUTO_APPROVE
    assert ev.reasons == (ReasonCode.OK,)


def test_reasons_are_deduplicated_in_first_seen_order() -> None:
    ev = AccessEvaluation.needs_approval(
        ReasonCode.ADMIN_RIGHTS, ReasonCode.HIGH_COST, ReasonCode.ADMIN_RIGHTS
    )
    assert ev.reasons == (ReasonCode.ADMIN_RIGHTS, ReasonCode.HIGH_COST)


def test_reject_keeps_every_reason() -> None:
    ev = AccessEvaluation.reject(ReasonCode.DEPARTMENT_RESTRICTED, ReasonCode.ALREADY_OWNED)
    assert ev.outcome is AccessOutcome.REJECT
    assert ev.reasons == (ReasonCode.DEPARTMENT_RESTRICTED, ReasonCode.ALREADY_OWNED)


def test_evaluation_needs_a_reason() -> None:
    with pytest.raises(ValueError, match="at least one"):
        AccessEvaluation.needs_approval()


def test_raw_constructor_rejects_duplicates() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        AccessEvaluation(AccessOutcome.REJECT, (ReasonCode.HIGH_COST, ReasonCode.HIGH_COST))


@pytest.mark.parametrize(
    ("outcome", "reasons"),
    [
        (AccessOutcome.AUTO_APPROVE, (ReasonCode.HIGH_COST,)),
        (AccessOutcome.NEEDS_APPROVAL, (ReasonCode.OK,)),
        (AccessOutcome.REJECT, (ReasonCode.OK,)),
        (AccessOutcome.AUTO_APPROVE, (ReasonCode.OK, ReasonCode.HIGH_COST)),
    ],
)
def test_outcome_and_reasons_must_agree(
    outcome: AccessOutcome, reasons: tuple[ReasonCode, ...]
) -> None:
    with pytest.raises(ValueError, match="inconsistent"):
        AccessEvaluation(outcome, reasons)
