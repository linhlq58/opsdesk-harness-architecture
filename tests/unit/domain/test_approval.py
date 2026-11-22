"""Approval eligibility, cases P1-P5 from M01 §3.4.

Request AR-001 is pending, in Acme, requested by E-001.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from opsdesk.domain.decisions import Decision, ReasonCode
from opsdesk.domain.errors import NotPermitted
from opsdesk.domain.models import AccessRequest, AccessRequestStatus, Employee
from opsdesk.domain.policies.approval import approve, can_decide, reject

R = ReasonCode
T0 = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)  # same as conftest factories
NOW = T0 + timedelta(hours=3)


@pytest.fixture
def request_(make_access_request: Callable[..., AccessRequest]) -> AccessRequest:
    return make_access_request(id="AR-001", requester_id="E-001")


@pytest.fixture
def khanh(make_employee: Callable[..., Employee]) -> Employee:
    """E-006, IT manager in Acme: the normal approver."""
    return make_employee(id="E-006", department="it", roles=["employee", "it_manager"])


# ------------------------------------------------------------------- spec cases P1-P5


def test_p1_manager_same_tenant_pending_other_person_is_allowed(
    khanh: Employee, request_: AccessRequest
) -> None:
    assert can_decide(khanh, request_) == Decision.allow()


def test_p2_approver_from_other_tenant_is_denied(
    make_employee: Callable[..., Employee], request_: AccessRequest
) -> None:
    minh = make_employee(
        id="G-001", tenant_id="globex", department="it", roles=["employee", "it_manager"]
    )
    assert can_decide(minh, request_) == Decision.deny(R.CROSS_TENANT)


def test_p3_it_staff_is_not_an_approver(
    make_employee: Callable[..., Employee], request_: AccessRequest
) -> None:
    hoa = make_employee(id="E-005", department="it", roles=["employee", "it_staff"])
    assert can_decide(hoa, request_) == Decision.deny(R.NOT_APPROVER)


def test_p4_manager_cannot_approve_own_request(
    khanh: Employee, make_access_request: Callable[..., AccessRequest]
) -> None:
    own = make_access_request(id="AR-004", requester_id="E-006")
    assert can_decide(khanh, own) == Decision.deny(R.SELF_APPROVAL)


def test_p4_a_second_manager_can_approve_it(
    make_employee: Callable[..., Employee], make_access_request: Callable[..., AccessRequest]
) -> None:
    lan = make_employee(id="E-007", department="it", roles=["employee", "it_manager"])
    khanhs_request = make_access_request(id="AR-004", requester_id="E-006")
    assert can_decide(lan, khanhs_request).allowed


@pytest.mark.parametrize(
    ("status", "extra"),
    [
        ("approved", {"decided_by": "E-007", "decided_at": T0}),
        ("rejected", {"decided_by": "E-007", "decided_at": T0}),
        ("cancelled", {}),
    ],
)
def test_p5_request_not_pending_is_denied(
    khanh: Employee,
    make_access_request: Callable[..., AccessRequest],
    status: str,
    extra: dict[str, object],
) -> None:
    done = make_access_request(status=status, **extra)
    assert can_decide(khanh, done) == Decision.deny(R.NOT_PENDING)


# ------------------------------------------------------------------- check ordering


def test_business_roles_are_not_approvers(
    make_employee: Callable[..., Employee], request_: AccessRequest
) -> None:
    dung = make_employee(id="E-004", department="finance", roles=["employee", "finance"])
    assert can_decide(dung, request_).reason is R.NOT_APPROVER


def test_tenant_is_checked_before_role(
    make_employee: Callable[..., Employee], request_: AccessRequest
) -> None:
    outsider = make_employee(id="G-002", tenant_id="globex")  # also not a manager
    assert can_decide(outsider, request_).reason is R.CROSS_TENANT


def test_self_approval_is_reported_even_when_not_pending(
    khanh: Employee, make_access_request: Callable[..., AccessRequest]
) -> None:
    own_done = make_access_request(
        requester_id="E-006", status="approved", decided_by="E-007", decided_at=T0
    )
    assert can_decide(khanh, own_done).reason is R.SELF_APPROVAL


# --------------------------------------------------------------------- approve/reject


def test_approve_returns_decided_request(khanh: Employee, request_: AccessRequest) -> None:
    approved = approve(request_, khanh, NOW)
    assert approved.status is AccessRequestStatus.APPROVED
    assert approved.decided_by == "E-006"
    assert approved.decided_at == NOW
    assert request_.status is AccessRequestStatus.PENDING_APPROVAL  # original untouched


def test_reject_returns_decided_request(khanh: Employee, request_: AccessRequest) -> None:
    rejected = reject(request_, khanh, NOW)
    assert rejected.status is AccessRequestStatus.REJECTED
    assert rejected.decided_by == "E-006"
    assert rejected.decided_at == NOW


@pytest.mark.parametrize("action", [approve, reject])
def test_denied_action_raises_with_reason_code(
    action: Callable[[AccessRequest, Employee, datetime], AccessRequest],
    khanh: Employee,
    make_access_request: Callable[..., AccessRequest],
) -> None:
    own = make_access_request(requester_id="E-006")
    with pytest.raises(NotPermitted) as exc_info:
        action(own, khanh, NOW)
    assert exc_info.value.reason is R.SELF_APPROVAL


def test_cannot_approve_twice(
    khanh: Employee, make_employee: Callable[..., Employee], request_: AccessRequest
) -> None:
    lan = make_employee(id="E-007", department="it", roles=["employee", "it_manager"])
    approved = approve(request_, khanh, NOW)
    with pytest.raises(NotPermitted) as exc_info:
        reject(approved, lan, NOW)
    assert exc_info.value.reason is R.NOT_PENDING


def test_decision_time_before_request_is_rejected(khanh: Employee, request_: AccessRequest) -> None:
    with pytest.raises(ValidationError, match="decided_at"):
        approve(request_, khanh, T0 - timedelta(minutes=1))
