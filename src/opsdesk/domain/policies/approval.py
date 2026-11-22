"""Who may approve or reject an access request (M01 §3.4).

Checked in this order; the first failing check is the reason:

1. Different tenant                 -> CROSS_TENANT
2. Not an IT manager                -> NOT_APPROVER
3. Deciding on your own request     -> SELF_APPROVAL   (separation of duties)
4. Request is no longer pending     -> NOT_PENDING

``can_decide`` answers the question; ``approve`` / ``reject`` perform the action and
call ``can_decide`` themselves, so there is no way to approve without the check.
"""

from datetime import datetime

from opsdesk.domain.decisions import Decision, ReasonCode
from opsdesk.domain.errors import NotPermitted
from opsdesk.domain.models import AccessRequest, AccessRequestStatus, Employee, Role


def can_decide(approver: Employee, request: AccessRequest) -> Decision:
    if approver.tenant_id != request.tenant_id:
        return Decision.deny(ReasonCode.CROSS_TENANT)
    # Only managers approve. it_staff can work tickets but cannot grant access.
    if Role.IT_MANAGER not in approver.roles:
        return Decision.deny(ReasonCode.NOT_APPROVER)
    # Separation of duties: nobody approves their own request, however senior.
    if approver.id == request.requester_id:
        return Decision.deny(ReasonCode.SELF_APPROVAL)
    if request.status is not AccessRequestStatus.PENDING_APPROVAL:
        return Decision.deny(ReasonCode.NOT_PENDING)
    return Decision.allow()


def approve(request: AccessRequest, approver: Employee, now: datetime) -> AccessRequest:
    return _decide(request, approver, now, AccessRequestStatus.APPROVED)


def reject(request: AccessRequest, approver: Employee, now: datetime) -> AccessRequest:
    return _decide(request, approver, now, AccessRequestStatus.REJECTED)


def _decide(
    request: AccessRequest,
    approver: Employee,
    now: datetime,
    status: AccessRequestStatus,
) -> AccessRequest:
    decision = can_decide(approver, request)
    if not decision.allowed:
        raise NotPermitted(
            f"{approver.id} may not decide on {request.id}: {decision.reason}",
            reason=decision.reason,
        )
    # evolve() re-validates: decided_by / decided_at must be set for approved/rejected,
    # and decided_at must not be earlier than created_at.
    return request.evolve(status=status, decided_by=approver.id, decided_at=now)
