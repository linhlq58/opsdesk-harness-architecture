"""``stream_turn``: the streaming sibling of ``run_turn`` (M04 §6).

This is the **only** module that knows LangGraph's v3 stream protocol (decision D1).
Everything downstream (bus, sinks, SSE, UI, evals) sees Event v1 only. If LangGraph
changes v3, this file changes and nothing else.

One turn:

1. Emit ``run_started`` (no user message, as in ``run_turn``).
2. ``await agent.astream_events(..., version="v3")`` with the thread's config (the
   checkpointer loads this thread's history) and ``context=ToolContext(...)``, then
   iterate the raw events. v3 has no background task: the graph only advances while
   this loop pulls, so cancelling this task stops the graph mid-step.
3. Translate each raw event:

   ==========================================  ======================================
   raw v3 event                                OpsDesk
   ==========================================  ======================================
   ``messages`` / ``content-block-delta`` /     ``token`` (``text``, ``agent``), unless
   ``text-delta``                               the model call is tagged internal (M05)
   ``messages`` / ``tool-call-delta`` and the   ignored: the wrapper records the call
   other protocol events                        (D3)
   ``tools`` (``tool-started`` / ...)           ignored: unredacted duplicates of the
                                                wrapper's events (D3)
   ``values`` (full graph state)                ignored in M04
   ==========================================  ======================================

4. The answer is the last message of the final state (the router graph appends its
   answer to ``messages`` too, so both kinds of graph work the same way).

M05: ``stream_turn`` runs any ``TurnGraph``: the ticket agent or the router graph.

* **Token filter (D5).** The router graph tags every model call whose text is not the
  final answer with ``INTERNAL_TAG`` (the router call, and the specialists of a
  multi-route turn). Their text-deltas are dropped here. Untagged text streams, so the
  ticket agent behaves exactly as in M04. The rule ("tagged = internal") is generic:
  this module does not know router state, route counts or node names.
* **Token label.** ``agent`` = the ``create_agent`` name from the event metadata
  (``lc_agent_name``: ``ticket``, ``hardware``, ...), else the LangGraph node
  (``synthesize``), else the graph's name.
5. ``run_finished`` in a ``finally``: ``completed``; ``failed`` (the exception is
   re-raised, like ``run_turn``); or ``cancelled`` when the task is cancelled (the
   client went away, D6), after which ``CancelledError`` is re-raised: swallowing it
   would tell the caller the run ended normally.

``run_turn`` and ``stream_turn`` produce the same non-token events for the same
scripted run (case S2).

Tests: ``tests/integration/test_stream_turn.py`` (cases S1-S6).
Docs: https://docs.langchain.com/oss/python/langgraph/streaming
"""

import asyncio
import time
from collections.abc import Mapping
from typing import Any

from langchain_core._api import suppress_langchain_beta_warning
from langchain_core.messages import BaseMessage, HumanMessage

from opsdesk.agents.base import TurnGraph
from opsdesk.core.clock import Clock
from opsdesk.domain.ports import Repositories
from opsdesk.observability.bus import EventBus
from opsdesk.observability.events import EventKind, RunStatus
from opsdesk.observability.recorder import RunRecorder
from opsdesk.orchestration.patterns.router import INTERNAL_TAG
from opsdesk.orchestration.turn import TurnResult, thread_config
from opsdesk.security.context import RequestContext
from opsdesk.tools.context import ToolContext


async def stream_turn(
    agent: TurnGraph,
    *,
    ctx: RequestContext,
    message: str,
    repos: Repositories,
    bus: EventBus,
    clock: Clock,
    entrypoint: str,
) -> TurnResult:
    # 1. Open the run (same as run_turn).
    recorder = RunRecorder(request_id=ctx.request_id, thread_id=ctx.thread_id, bus=bus, clock=clock)
    await recorder.emit(
        EventKind.RUN_STARTED,
        {"workload": ctx.workload.value, "entrypoint": entrypoint},  # no user message
    )
    started = time.perf_counter()
    status: RunStatus = "failed"  # stays "failed" unless the run completes or is cancelled
    agent_name = agent.name or "agent"

    try:
        # 2. Stream the agent. D1: v3 is experimental and warns on every call; we accept
        # that knowingly, so silence the beta warning for this call only. The
        # suppression is a context variable (this task only), not a process-wide
        # warnings filter. ``async with`` aborts the graph on any early exit.
        tool_context = ToolContext(request=ctx, repos=repos, recorder=recorder, clock=clock)
        with suppress_langchain_beta_warning():
            run_stream = await agent.astream_events(  # pyright: ignore[reportUnknownMemberType]
                {"messages": [HumanMessage(message)]},
                thread_config(ctx),
                context=tool_context,
                version="v3",
            )
        async with run_stream as run:
            async for raw in run:
                # 3. Translate: only model text becomes an OpsDesk event.
                delta = _answer_delta(raw)
                if delta is not None:
                    text, label = delta
                    await recorder.emit(
                        EventKind.TOKEN, {"text": text, "agent": label or agent_name}
                    )
            # 4. The answer: last message of the final state.
            final = await run.output()

        messages: list[BaseMessage] = final["messages"] if final else []
        answer = messages[-1].text if messages else ""
        status = "completed"
        return TurnResult(answer=answer, status="completed")
    except asyncio.CancelledError:
        status = "cancelled"  # D6: the client went away; not a failure
        raise
    finally:
        # 5. Close the run whatever happened.
        await recorder.emit(
            EventKind.RUN_FINISHED,
            {"status": status, "duration_ms": int((time.perf_counter() - started) * 1000)},
        )


def _answer_delta(raw: Mapping[str, Any]) -> tuple[str, str | None] | None:
    """``(text, agent label)`` of a v3 ``text-delta`` that belongs to the answer;
    ``None`` for every other raw event (M04 D3) and for internal model calls (M05 D5)."""
    if raw.get("method") != "messages":
        return None
    data: Any = raw["params"]["data"][0]
    metadata: Mapping[str, Any] = raw["params"]["data"][1]
    if not isinstance(data, Mapping):
        # A whole message a node wrote to the state (the router appends its answer to
        # ``messages``): its text already streamed as deltas, or deliberately did not.
        return None
    protocol_event: Mapping[str, Any] = data  # pyright: ignore[reportUnknownVariableType]
    if protocol_event.get("event") != "content-block-delta":
        return None
    if INTERNAL_TAG in (metadata.get("tags") or ()):
        return None  # D5: router call, or a specialist of a multi-route turn
    delta: Mapping[str, Any] = protocol_event.get("delta") or {}
    if delta.get("type") != "text-delta":
        return None  # tool-call-delta: the wrapper records tool calls (D3)
    text: object = delta.get("text")
    if not isinstance(text, str):
        return None
    label: object = metadata.get("lc_agent_name") or metadata.get("langgraph_node")
    return text, label if isinstance(label, str) else None
