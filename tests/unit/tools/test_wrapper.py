"""``harness_tool`` cases W1-W6 (M03 §6), plus the contract details they rely on.

Each test wraps a tiny fake business function, so a failure points at the wrapper,
not at ticket logic. Tools are called through a real ``create_agent`` loop
(``call_tool`` in conftest), so ``ToolRuntime`` injection is exercised for real.
"""

import json
from dataclasses import dataclass, field
from typing import Any

import pytest
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel

from opsdesk.core.result import ToolResult
from opsdesk.domain.decisions import ReasonCode
from opsdesk.domain.errors import InvalidIdentifier, NotPermitted
from opsdesk.observability.events import EventKind
from opsdesk.observability.redaction import REDACTED
from opsdesk.security.scopes import Scope
from opsdesk.tools.context import ToolContext
from opsdesk.tools.wrapper import harness_tool
from support import CallTool, MakeCaller


class EchoArgs(BaseModel):
    text: str
    password: str | None = None


@dataclass
class Spy:
    """Records how the business function was called and decides what it does."""

    raises: Exception | None = None
    calls: list[tuple[ToolContext, EchoArgs]] = field(
        default_factory=list[tuple[ToolContext, EchoArgs]]
    )

    def tool(self, scope: Scope = Scope.TICKET_READ) -> BaseTool:
        @harness_tool(
            name="echo", description="Echo the text back.", args_schema=EchoArgs, scope=scope
        )
        async def echo(ctx: ToolContext, args: EchoArgs) -> ToolResult[dict[str, str]]:
            self.calls.append((ctx, args))
            if self.raises is not None:
                raise self.raises
            return ToolResult.ok({"echo": args.text})

        return echo


# ------------------------------------------------------------------------ W1: ok


async def test_w1_ok_result_reaches_the_model_as_json(
    make_caller: MakeCaller, call_tool: CallTool
) -> None:
    an = await make_caller("E-001")
    result = await call_tool(Spy().tool(), {"text": "hi"}, an.tool_context)

    assert result == {
        "status": "ok",
        "data": {"echo": "hi"},
        "safe_message": None,
        "error_code": None,
    }
    ToolResult[dict[str, str]].model_validate(result)  # the model gets a valid ToolResult


async def test_w1_business_function_gets_context_and_validated_args(
    make_caller: MakeCaller, call_tool: CallTool
) -> None:
    an = await make_caller("E-001")
    spy = Spy()
    await call_tool(spy.tool(), {"text": "hi"}, an.tool_context)

    [(ctx, args)] = spy.calls
    assert ctx is an.tool_context  # the object passed as context= to the agent
    assert isinstance(args, EchoArgs)
    assert args.text == "hi"


async def test_w1_emits_started_then_finished_ok(
    make_caller: MakeCaller, call_tool: CallTool
) -> None:
    an = await make_caller("E-001")
    await call_tool(Spy().tool(), {"text": "hi"}, an.tool_context)

    assert an.sink.kinds() == [EventKind.TOOL_STARTED, EventKind.TOOL_FINISHED]
    started, finished = an.sink.events
    assert started.payload["tool"] == "echo"
    assert isinstance(started.payload["args"], dict)
    assert started.payload["args"]["text"] == "hi"
    assert finished.payload["tool"] == "echo"
    assert finished.payload["status"] == "ok"
    assert finished.payload["error_code"] is None
    assert isinstance(finished.payload["duration_ms"], int)
    assert finished.payload["duration_ms"] >= 0
    # Events carry the turn's correlation ids (the recorder from the context was used).
    assert {e.request_id for e in an.sink.events} == {an.request.request_id}


@pytest.mark.parametrize("scope", [Scope.TICKET_READ, Scope.ACCESS_APPROVE])
async def test_started_and_finished_share_the_models_call_id(
    make_caller: MakeCaller, call_tool: CallTool, scope: Scope
) -> None:
    # M04: call_id pairs the two rows in the UI timeline, for ok and denied calls alike.
    an = await make_caller("E-001")  # plain employee: ACCESS_APPROVE is denied
    await call_tool(Spy().tool(scope), {"text": "hi"}, an.tool_context)

    started, finished = an.sink.events
    call_id = started.payload["call_id"]
    assert isinstance(call_id, str)
    assert call_id.startswith("call_")  # the id ScriptedChatModel put on the tool call
    assert finished.payload["call_id"] == call_id


# ------------------------------------------------------------- W2: missing scope


async def test_w2_missing_scope_denies_without_calling_the_function(
    make_caller: MakeCaller, call_tool: CallTool
) -> None:
    an = await make_caller("E-001")  # employee: no access:approve
    spy = Spy()
    result = await call_tool(spy.tool(scope=Scope.ACCESS_APPROVE), {"text": "hi"}, an.tool_context)

    assert spy.calls == []
    assert result["status"] == "denied"
    assert result["error_code"] == ReasonCode.MISSING_SCOPE.value
    assert result["safe_message"]
    [finished] = an.events(EventKind.TOOL_FINISHED)
    assert finished.payload["status"] == "denied"
    assert finished.payload["error_code"] == "missing_scope"


# ------------------------------------------------------------ W3: domain errors


async def test_w3_not_permitted_maps_to_denied_with_its_reason(
    make_caller: MakeCaller, call_tool: CallTool
) -> None:
    an = await make_caller("E-001")
    spy = Spy(raises=NotPermitted("E-001 may not touch T-0003", reason=ReasonCode.NOT_OWNER))
    result = await call_tool(spy.tool(), {"text": "hi"}, an.tool_context)

    assert result["status"] == "denied"
    assert result["error_code"] == "not_owner"
    assert "T-0003" not in json.dumps(result)  # exception text never reaches the model
    [finished] = an.events(EventKind.TOOL_FINISHED)
    assert (finished.payload["status"], finished.payload["error_code"]) == ("denied", "not_owner")


async def test_w3_any_domain_error_is_mapped(make_caller: MakeCaller, call_tool: CallTool) -> None:
    an = await make_caller("E-001")
    spy = Spy(raises=InvalidIdentifier("ticket", "abc"))
    result = await call_tool(spy.tool(), {"text": "hi"}, an.tool_context)

    assert (result["status"], result["error_code"]) == ("invalid", "invalid_id")


# ------------------------------------------------------------------- W4: bugs


async def test_w4_unexpected_exception_propagates(
    make_caller: MakeCaller, call_tool: CallTool
) -> None:
    an = await make_caller("E-001")
    spy = Spy(raises=KeyError("oops"))

    with pytest.raises(KeyError):
        await call_tool(spy.tool(), {"text": "hi"}, an.tool_context)

    assert an.sink.kinds()[0] is EventKind.TOOL_STARTED
    # Whatever you decided for W4, the log must never claim success.
    assert all(e.payload["status"] != "ok" for e in an.events(EventKind.TOOL_FINISHED))


# -------------------------------------------------------------- W5: redaction


async def test_w5_sensitive_arguments_are_redacted_in_events(
    make_caller: MakeCaller, call_tool: CallTool
) -> None:
    an = await make_caller("E-001")
    await call_tool(Spy().tool(), {"text": "hi", "password": "hunter2"}, an.tool_context)

    [started] = an.events(EventKind.TOOL_STARTED)
    assert isinstance(started.payload["args"], dict)
    assert started.payload["args"]["password"] == REDACTED
    assert "hunter2" not in "".join(e.model_dump_json() for e in an.sink.events)


# --------------------------------------------------------- W6: model-visible schema


def _model_view(tool: BaseTool) -> dict[str, Any]:
    """What the provider receives for this tool (OpenAI function format)."""
    return convert_to_openai_tool(tool)["function"]


def test_w6_schema_shows_only_business_arguments() -> None:
    view = _model_view(Spy().tool())

    assert view["name"] == "echo"
    assert view["description"] == "Echo the text back."
    assert set(view["parameters"]["properties"]) == {"text", "password"}
    dumped = json.dumps(view).lower()
    for hidden in ("runtime", "context", "ctx", "principal", "recorder"):
        assert hidden not in dumped


class _NoArgs(BaseModel):
    pass


def test_w7_empty_args_schema_is_rejected_when_the_tool_is_defined() -> None:
    # langchain-core drops the injected runtime for a schema without fields (M05).
    with pytest.raises(TypeError, match="has no fields"):

        @harness_tool(name="no_args", description="d", args_schema=_NoArgs, scope=Scope.KB_READ)
        async def no_args(  # pyright: ignore[reportUnusedFunction]
            ctx: ToolContext, args: _NoArgs
        ) -> ToolResult[str]:
            return ToolResult.ok("never")
