"""Test helpers for harness code (M03+): act as a seed employee, call a tool.

Plain functions and types; ``conftest.py`` exposes them as fixtures. Kept out of
``conftest`` so test modules can import the types (importing ``conftest`` directly is
fragile in pytest).

Acting as a seed employee mirrors the CLI and the demo: the principal comes from the
repository through ``principal_for``, never from test input.
"""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import BaseTool
from pydantic import JsonValue

from opsdesk.core.clock import FixedClock
from opsdesk.core.ids import new_request_id, new_thread_id
from opsdesk.core.workload import Workload
from opsdesk.domain.ids import EmployeeId, TenantId
from opsdesk.domain.ports import Repositories
from opsdesk.llm.fakes import ScriptedChatModel, tool_call
from opsdesk.observability.bus import EventBus
from opsdesk.observability.events import Event, EventKind
from opsdesk.observability.recorder import RunRecorder
from opsdesk.observability.sinks.memory import MemorySink
from opsdesk.persistence.memory import in_memory_repositories
from opsdesk.persistence.seed import load_seed, write_seed
from opsdesk.security.context import RequestContext
from opsdesk.security.principal import principal_for
from opsdesk.tools.context import ToolContext

REAL_SEED = Path(__file__).resolve().parents[1] / "data" / "seed"


async def seeded_repositories() -> Repositories:
    repos = in_memory_repositories()
    await write_seed(repos, load_seed(REAL_SEED))
    return repos


@dataclass
class Caller:
    """One employee's per-request objects, plus the sink that collects their events."""

    request: RequestContext
    bus: EventBus
    sink: MemorySink
    clock: FixedClock
    tool_context: ToolContext

    def events(self, kind: EventKind) -> list[Event]:
        return [e for e in self.sink.events if e.kind is kind]


type MakeCaller = Callable[..., Awaitable[Caller]]


def make_caller_for(seed_repos: Repositories) -> MakeCaller:
    """``repos=`` swaps the repositories the tools see (e.g. a spy in front of one)."""

    async def make(
        employee_id: str, tenant_id: str = "acme", *, repos: Repositories | None = None
    ) -> Caller:
        employee = await seed_repos.employees.get(TenantId(tenant_id), EmployeeId(employee_id))
        assert employee is not None, f"{tenant_id}/{employee_id} is not in the seed"
        request = RequestContext(
            principal=principal_for(employee),
            request_id=new_request_id(),
            thread_id=new_thread_id(),
            workload=Workload.CHAT,
        )
        sink = MemorySink()
        bus = EventBus([sink])
        clock = FixedClock()
        recorder = RunRecorder(
            request_id=request.request_id, thread_id=request.thread_id, bus=bus, clock=clock
        )
        tool_context = ToolContext(
            request=request, repos=repos or seed_repos, recorder=recorder, clock=clock
        )
        return Caller(request, bus, sink, clock, tool_context)

    return make


type CallTool = Callable[[BaseTool, dict[str, JsonValue], ToolContext], Awaitable[dict[str, Any]]]


async def call_tool_via_agent(
    tool: BaseTool, args: dict[str, JsonValue], ctx: ToolContext
) -> dict[str, Any]:
    """Run one tool call through a real ``create_agent`` loop; return what the model got.

    The scripted model asks for the tool once, then answers "done". Going through the
    agent (instead of calling the tool directly) tests the real path: LangChain's
    argument validation, ``ToolRuntime`` injection, and the ``ToolMessage`` content.
    The return value is that content parsed as JSON (the serialised ``ToolResult``).
    Exceptions the tool lets through propagate out of this call.
    """
    model = ScriptedChatModel.from_script(tool_call(tool.name, args), "done")
    agent = create_agent(model, tools=[tool], context_schema=ToolContext)
    out = await agent.ainvoke({"messages": [HumanMessage("test")]}, context=ctx)
    tool_messages = [m for m in out["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 1
    content = tool_messages[0].content
    assert isinstance(content, str), "the wrapper must return the ToolResult as JSON text"
    result = json.loads(content)
    assert isinstance(result, dict)
    return result
