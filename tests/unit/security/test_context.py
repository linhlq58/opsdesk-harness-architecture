from typing import Any

import pytest
from pydantic import ValidationError

from opsdesk.core.ids import new_request_id, new_thread_id
from opsdesk.core.workload import Workload
from opsdesk.security.context import RequestContext
from opsdesk.security.principal import principal_for


def _ctx(make_employee: Any, workload: Workload = Workload.CHAT) -> RequestContext:
    return RequestContext(
        principal=principal_for(make_employee()),
        request_id=new_request_id(),
        thread_id=new_thread_id(),
        workload=workload,
    )


def test_request_context_holds_identity_and_correlation_ids(make_employee: Any) -> None:
    ctx = _ctx(make_employee)
    assert ctx.principal.user_id == "E-001"
    assert ctx.request_id.startswith("req_")
    assert RequestContext.model_validate_json(ctx.model_dump_json()) == ctx


def test_request_context_is_immutable(make_employee: Any) -> None:
    ctx = _ctx(make_employee, Workload.EVAL)
    with pytest.raises(ValidationError):
        ctx.workload = Workload.CHAT  # type: ignore[misc]


def test_request_context_rejects_unknown_fields(make_employee: Any) -> None:
    ctx = _ctx(make_employee)
    with pytest.raises(ValidationError):
        RequestContext.model_validate(ctx.model_dump() | {"note": "x"})
