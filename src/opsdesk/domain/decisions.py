"""Explainable policy results.

A policy never answers with a bare ``bool``. It answers *what* was decided and *why*,
as a stable machine-readable code. The same result later feeds:

* the model (M03+): a safe explanation instead of a raw exception,
* the UI timeline (M04): "denied: cross_tenant",
* the audit log (M15) and the evaluation suite (M17): assertions on reason codes.

Reason codes are part of the public contract: renaming one breaks audits and eval
datasets, so add new codes rather than changing existing values.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Self


class ReasonCode(StrEnum):
    OK = "ok"

    # visibility / approval (who is asking)
    CROSS_TENANT = "cross_tenant"
    NOT_OWNER = "not_owner"
    NOT_APPROVER = "not_approver"
    SELF_APPROVAL = "self_approval"
    NOT_PENDING = "not_pending"

    # access-request evaluation: reject rules
    INVALID_REQUEST = "invalid_request"
    DEPARTMENT_RESTRICTED = "department_restricted"
    ALREADY_OWNED = "already_owned"

    # access-request evaluation: review rules
    ADMIN_RIGHTS = "admin_rights"
    HIGH_COST = "high_cost"


@dataclass(frozen=True, slots=True)
class Decision:
    """Yes/no answer with the reason. ``allowed`` is True exactly when reason is ``OK``."""

    allowed: bool
    reason: ReasonCode

    def __post_init__(self) -> None:
        if self.allowed != (self.reason is ReasonCode.OK):
            raise ValueError(f"inconsistent decision: allowed={self.allowed}, {self.reason}")

    @classmethod
    def allow(cls) -> Self:
        return cls(allowed=True, reason=ReasonCode.OK)

    @classmethod
    def deny(cls, reason: ReasonCode) -> Self:
        return cls(allowed=False, reason=reason)

    def __bool__(self) -> bool:
        # Explicit is better: force callers to write `decision.allowed`, so a Decision
        # can never be silently used as a truthy object (a dataclass is always truthy).
        raise TypeError("use `decision.allowed` instead of truth-testing a Decision")


class AccessOutcome(StrEnum):
    AUTO_APPROVE = "auto_approve"
    NEEDS_APPROVAL = "needs_approval"
    REJECT = "reject"


@dataclass(frozen=True, slots=True)
class AccessEvaluation:
    """Result of evaluating an access request.

    ``reasons`` lists **every** triggered rule of the winning outcome (not just the
    first), without duplicates, in a stable order. ``AUTO_APPROVE`` always has ``(OK,)``.
    """

    outcome: AccessOutcome
    reasons: tuple[ReasonCode, ...]

    def __post_init__(self) -> None:
        if not self.reasons:
            raise ValueError("an evaluation needs at least one reason")
        if len(set(self.reasons)) != len(self.reasons):
            raise ValueError(f"duplicate reasons: {self.reasons}")
        is_auto = self.outcome is AccessOutcome.AUTO_APPROVE
        if is_auto != (self.reasons == (ReasonCode.OK,)):
            raise ValueError(f"{self.outcome} is inconsistent with reasons {self.reasons}")

    @classmethod
    def auto_approve(cls) -> Self:
        return cls(AccessOutcome.AUTO_APPROVE, (ReasonCode.OK,))

    @classmethod
    def needs_approval(cls, *reasons: ReasonCode) -> Self:
        return cls(AccessOutcome.NEEDS_APPROVAL, _dedupe(reasons))

    @classmethod
    def reject(cls, *reasons: ReasonCode) -> Self:
        return cls(AccessOutcome.REJECT, _dedupe(reasons))


def _dedupe(reasons: tuple[ReasonCode, ...]) -> tuple[ReasonCode, ...]:
    """Drop repeats, keep first-seen order (dict preserves insertion order)."""
    return tuple(dict.fromkeys(reasons))
