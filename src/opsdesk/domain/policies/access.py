"""Access-request evaluation (M01 §3.3).

Decides what should happen to a request *before* anyone approves it:

1. **Reject** if any reject rule fires (the request can never be granted).
2. Otherwise **needs approval** if any review rule fires (a human must look).
3. Otherwise **auto-approve**.

Every triggered rule of the winning outcome is returned, in a fixed order, so the
approver (and later the model, audit and eval) sees *all* the reasons at once.

Thresholds are a parameter (``AccessRules``), not a constant: in M14 they are loaded
from ``config/policy.yaml``. Keeping them out of this module keeps it pure and lets
tests try any threshold.
"""

from dataclasses import dataclass

from opsdesk.core.money import Money
from opsdesk.domain.decisions import AccessEvaluation, ReasonCode
from opsdesk.domain.models import AccessKind, Employee, SoftwareItem


@dataclass(frozen=True, slots=True)
class AccessRules:
    licence_review_threshold: Money  # annual cost >= this needs a human (e.g. 5,000,000)


def evaluate_access_request(
    requester: Employee,
    kind: AccessKind,
    software: SoftwareItem | None,
    rules: AccessRules,
) -> AccessEvaluation:
    # Malformed request: nothing else can be judged meaningfully, stop here.
    if (kind is AccessKind.SOFTWARE_LICENCE) != (software is not None):
        return AccessEvaluation.reject(ReasonCode.INVALID_REQUEST)

    reject: list[ReasonCode] = []
    review: list[ReasonCode] = []

    # The order of the checks below *is* the order of `reasons`. Keep it stable:
    # audit records and eval datasets compare these tuples.
    if kind is AccessKind.ADMIN_RIGHTS:
        review.append(ReasonCode.ADMIN_RIGHTS)

    if software is not None:
        if not software.is_available_to(requester.department):
            reject.append(ReasonCode.DEPARTMENT_RESTRICTED)
        if software.id in requester.owned_software:
            reject.append(ReasonCode.ALREADY_OWNED)
        if software.requires_admin:
            review.append(ReasonCode.ADMIN_RIGHTS)
        if software.annual_cost >= rules.licence_review_threshold:
            review.append(ReasonCode.HIGH_COST)

    # Reject beats review: an expensive tool you already own is simply refused,
    # there is nothing for an approver to decide.
    if reject:
        return AccessEvaluation.reject(*reject)
    if review:
        return AccessEvaluation.needs_approval(*review)
    return AccessEvaluation.auto_approve()
