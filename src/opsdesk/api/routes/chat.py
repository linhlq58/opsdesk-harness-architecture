"""``POST /api/chat``: one streamed turn, as Server-Sent Events (M04 §8).

Two phases, because once a streaming response has started its status is already
``200`` and can no longer become a ``401`` or ``404``:

**Before the stream** (the ``prepare_turn`` dependency; any failure is a plain HTTP
error and *no run starts*):

1. Bearer token → ``Principal`` (``current_principal``): invalid / expired → ``401``.
2. Body validated (``ChatIn``): empty or over 4,000 characters → ``422``.
3. ``ThreadRegistry.require_owner`` (D5): unknown, foreign *or* other-pattern
   thread (M05) → the same ``404``. A pattern not configured in this process → ``501``.
4. Build the per-request ``RequestContext`` (fresh ``request_id``).

**The stream** (the path operation, a generator FastAPI turns into SSE):

5. Per-request ``EventBus([jsonl, memory, queue])`` (D2): the browser gets the same
   Event v1 objects as the log; the shared JSONL sink drops ``token`` (D4).
6. ``stream_turn`` runs as its **own task**: it publishes into the bus, this
   generator reads the ``QueueSink`` (bounded) and yields ``to_sse(event)``, the
   allowlisted view (D7). The run task closes the queue in a ``finally``, so the
   stream ends right after ``run_finished``.
7. Client disconnect: Starlette cancels this generator; its ``finally`` abandons the
   queue (so nothing can block on it) and cancels the run task (D6). The run's own
   ``finally`` then records ``run_finished(cancelled)``, which still reaches JSONL.

A run that fails (a bug) is logged here with its ``request_id``; the browser has
already received ``run_finished(failed)`` as the last frame.

Tests: ``tests/integration/test_api_chat.py`` (cases H1-H5).
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.sse import EventSourceResponse, ServerSentEvent

from opsdesk.agents.base import TurnGraph
from opsdesk.api.deps import current_principal
from opsdesk.api.schemas import ChatIn
from opsdesk.api.sse import to_sse
from opsdesk.api.state import AppState, app_state
from opsdesk.core.ids import ThreadId, new_request_id
from opsdesk.core.workload import Workload
from opsdesk.observability.bus import EventBus
from opsdesk.observability.sinks.memory import MemorySink
from opsdesk.observability.sinks.queue import QueueSink
from opsdesk.orchestration.streaming import stream_turn
from opsdesk.orchestration.threads import ThreadNotFound
from opsdesk.security.context import RequestContext
from opsdesk.security.principal import Principal

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])

ENTRYPOINT = "api"


@dataclass(frozen=True, slots=True)
class PreparedTurn:
    ctx: RequestContext
    message: str
    graph: TurnGraph  # M05: the pattern's graph (ticket agent or router)


async def prepare_turn(
    body: ChatIn,
    principal: Annotated[Principal, Depends(current_principal)],
    state: Annotated[AppState, Depends(app_state)],
) -> PreparedTurn:
    """Steps 1-4: everything that may refuse the request, before any run starts."""
    thread_id = ThreadId(body.thread_id)
    try:
        state.threads.require_owner(principal, thread_id, body.pattern)
    except ThreadNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="thread not found") from None
    graph = state.graphs.get(body.pattern)
    if graph is None:
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail="pattern not configured")
    ctx = RequestContext(
        principal=principal,
        request_id=new_request_id(),
        thread_id=thread_id,
        workload=Workload.CHAT,
    )
    return PreparedTurn(ctx=ctx, message=body.message, graph=graph)


@router.post("/chat", response_class=EventSourceResponse)
async def chat(
    turn: Annotated[PreparedTurn, Depends(prepare_turn)],
    state: Annotated[AppState, Depends(app_state)],
) -> AsyncIterator[ServerSentEvent]:
    # Step 5: one bus per request; the queue is this browser's pipe.
    queue = QueueSink()
    bus = EventBus([state.jsonl, MemorySink(), queue])

    # Step 6: the run is its own task; it closes the queue when it is over.
    async def run() -> None:
        try:
            await stream_turn(
                turn.graph,
                ctx=turn.ctx,
                message=turn.message,
                repos=state.repos,
                bus=bus,
                clock=state.clock,
                entrypoint=ENTRYPOINT,
            )
        finally:
            await queue.close()

    task = asyncio.create_task(run(), name=f"turn-{turn.ctx.request_id}")
    state.running.add(task)
    task.add_done_callback(state.running.discard)
    task.add_done_callback(_log_failure(turn.ctx))

    finished = False
    try:
        async for event in queue:
            frame = to_sse(event)  # D7: None = not for the browser
            if frame is not None:
                yield frame
        finished = True
    finally:
        # Step 7: the client went away before the end of the run (D6).
        if not finished:
            queue.abandon()  # first: the run's last events must not block on the queue
            task.cancel()  # its finally records run_finished(cancelled)


def _log_failure(ctx: RequestContext) -> Callable[[asyncio.Task[None]], None]:
    def callback(task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return  # disconnect: recorded as run_finished(cancelled), not an error
        exc = task.exception()
        if exc is not None:
            # Like the CLI: the traceback is for the developer; the browser only saw
            # run_finished(failed).
            logger.error("turn failed (request %s)", ctx.request_id, exc_info=exc)

    return callback
