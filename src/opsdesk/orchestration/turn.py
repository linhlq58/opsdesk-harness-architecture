"""Single-turn runner (M03 §10).

What every entry point (CLI, demo, later the API and the eval runner) calls to run one
user turn through an agent:

* Build the ``RunRecorder`` from ``ctx.request_id`` / ``ctx.thread_id`` and emit
  ``run_started`` (``workload``, ``entrypoint``; never the user's message).
* Invoke the agent with the message and ``context=ToolContext(...)``.
* Emit ``run_finished`` with ``completed`` or ``failed`` and ``duration_ms`` **in a
  ``finally``**, so a crash still closes the run in the event log.
* On failure the exception propagates after ``run_finished(failed)``; a
  ``TurnResult(status="failed")`` is never returned (same spirit as D1-A: a bug fails
  loudly, and the entry point decides what the user sees).
* Single turn: no conversation memory yet (M04).

Tests: ``tests/integration/test_ticket_agent.py``.
"""

import time
from dataclasses import dataclass
from typing import Literal

from langchain_core.messages import BaseMessage, HumanMessage

from opsdesk.agents.base import HarnessAgent
from opsdesk.core.clock import Clock
from opsdesk.domain.ports import Repositories
from opsdesk.observability.bus import EventBus
from opsdesk.observability.events import EventKind, RunStatus
from opsdesk.observability.recorder import RunRecorder
from opsdesk.security.context import RequestContext
from opsdesk.tools.context import ToolContext


@dataclass(frozen=True, slots=True)
class TurnResult:
    answer: str
    status: Literal["completed", "failed"]


async def run_turn(
    agent: HarnessAgent,
    *,
    ctx: RequestContext,
    message: str,
    repos: Repositories,
    bus: EventBus,
    clock: Clock,
    entrypoint: str,
) -> TurnResult:
    # Open the run: one recorder per turn, carrying the request/thread ids.
    recorder = RunRecorder(request_id=ctx.request_id, thread_id=ctx.thread_id, bus=bus, clock=clock)
    await recorder.emit(
        EventKind.RUN_STARTED,
        {"workload": ctx.workload.value, "entrypoint": entrypoint},  # no user message
    )
    started = time.perf_counter()
    status: RunStatus = "failed"  # stays "failed" unless the agent returns normally

    try:
        # Run the agent loop. The ToolContext travels as ``context``: tools get it,
        # the model never sees it.
        tool_context = ToolContext(request=ctx, repos=repos, recorder=recorder, clock=clock)
        state = await agent.ainvoke(  # pyright: ignore[reportUnknownMemberType]
            {"messages": [HumanMessage(message)]}, context=tool_context
        )
        messages: list[BaseMessage] = state["messages"]
        answer = messages[-1].text
        status = "completed"
        return TurnResult(answer=answer, status="completed")
    finally:
        # Close the run whatever happened, so a crash is visible in the log.
        await recorder.emit(
            EventKind.RUN_FINISHED,
            {"status": status, "duration_ms": int((time.perf_counter() - started) * 1000)},
        )
