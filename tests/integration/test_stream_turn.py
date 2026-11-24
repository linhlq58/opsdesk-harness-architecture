"""``stream_turn`` cases S1-S6 (M04 §6), with the scripted model.

The whole harness runs for real (v3 stream, agent loop, wrapper, checkpointer,
events); only the model's replies are scripted, and the scripted model streams like
a real one (``tool-call-delta``, word-by-word ``text-delta``).
"""

import asyncio
import dataclasses
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from opsdesk.agents.base import HarnessAgent
from opsdesk.agents.ticket_agent import build_ticket_agent
from opsdesk.core.ids import new_request_id, new_thread_id
from opsdesk.domain.ports import Repositories
from opsdesk.llm.fakes import ScriptedChatModel, tool_call
from opsdesk.observability.bus import EventBus
from opsdesk.observability.events import Event, EventKind
from opsdesk.observability.sinks.memory import MemorySink
from opsdesk.orchestration.streaming import stream_turn
from opsdesk.orchestration.turn import TurnResult, run_turn
from support import Caller, MakeCaller

pytestmark = pytest.mark.integration

ANSWER = "Ticket T-0002 is in progress."


def _script() -> tuple[AIMessage | str, ...]:
    return (tool_call("get_ticket", {"ticket_id": "T-0002"}, call_id="call_s1"), ANSWER)


async def _stream(
    agent: HarnessAgent, caller: Caller, repos: Repositories, message: str = "Status of T-0002?"
) -> TurnResult:
    return await stream_turn(
        agent,
        ctx=caller.request,
        message=message,
        repos=repos,
        bus=caller.bus,
        clock=caller.clock,
        entrypoint="test",
    )


def _shape(events: list[Event]) -> list[tuple[str, Any]]:
    """Kind + the payload fields that identify an event (no timings, no ids)."""
    keys = ("tool", "status", "error_code", "call_id", "entrypoint")
    return [(e.kind.value, {k: e.payload[k] for k in keys if k in e.payload}) for e in events]


def _next_turn(caller: Caller, *, same_thread: bool) -> Caller:
    """The same employee's next request, on the same or on a new thread."""
    request = caller.request.model_copy(
        update={
            "request_id": new_request_id(),
            "thread_id": caller.request.thread_id if same_thread else new_thread_id(),
        }
    )
    return dataclasses.replace(caller, request=request)


# ------------------------------------------------------------------ S1: happy path


async def test_s1_events_in_order_and_tokens_spell_the_answer(
    make_caller: MakeCaller, seed_repos: Repositories
) -> None:
    an = await make_caller("E-001")
    agent = build_ticket_agent(ScriptedChatModel.from_script(*_script()))

    result = await _stream(agent, an, seed_repos)

    kinds = an.sink.kinds()
    assert kinds[:3] == [EventKind.RUN_STARTED, EventKind.TOOL_STARTED, EventKind.TOOL_FINISHED]
    assert kinds[-1] is EventKind.RUN_FINISHED
    tokens = an.events(EventKind.TOKEN)
    assert len(tokens) > 1 and kinds[3:-1] == [EventKind.TOKEN] * len(tokens)
    assert "".join(str(t.payload["text"]) for t in tokens) == ANSWER
    assert {str(t.payload["agent"]) for t in tokens} == {"ticket"}
    assert an.sink.events[-1].payload["status"] == "completed"
    assert result == TurnResult(answer=ANSWER, status="completed")
    assert [e.seq for e in an.sink.events] == list(range(len(kinds)))  # one ordered run


async def test_s1_tool_events_come_from_the_wrapper_only(
    make_caller: MakeCaller, seed_repos: Repositories
) -> None:
    # D3: LangGraph's own ``tools`` events are not translated; one pair per call.
    an = await make_caller("E-001")
    agent = build_ticket_agent(ScriptedChatModel.from_script(*_script()))

    await _stream(agent, an, seed_repos)

    started, finished = an.events(EventKind.TOOL_STARTED), an.events(EventKind.TOOL_FINISHED)
    assert len(started) == len(finished) == 1
    assert started[0].payload["call_id"] == finished[0].payload["call_id"] == "call_s1"
    assert finished[0].payload["status"] == "ok"


# ------------------------------------------------------- S2: same as run_turn


async def test_s2_run_turn_gives_the_same_events_without_tokens(
    make_caller: MakeCaller, seed_repos: Repositories
) -> None:
    streamed, invoked = await make_caller("E-001"), await make_caller("E-001")

    await _stream(
        build_ticket_agent(ScriptedChatModel.from_script(*_script())), streamed, seed_repos
    )
    await run_turn(
        build_ticket_agent(ScriptedChatModel.from_script(*_script())),
        ctx=invoked.request,
        message="Status of T-0002?",
        repos=seed_repos,
        bus=invoked.bus,
        clock=invoked.clock,
        entrypoint="test",
    )

    non_token = [e for e in streamed.sink.events if e.kind is not EventKind.TOKEN]
    assert _shape(non_token) == _shape(invoked.sink.events)
    assert invoked.events(EventKind.TOKEN) == []


# ------------------------------------------------------------ S3/S4: threads


async def test_s3_second_turn_on_the_same_thread_sends_the_history(
    make_caller: MakeCaller, seed_repos: Repositories
) -> None:
    an = await make_caller("E-001")
    model = ScriptedChatModel.from_script(*_script(), "It is assigned to Hoa.")
    agent = build_ticket_agent(model, checkpointer=InMemorySaver())

    await _stream(agent, an, seed_repos, "Status of T-0002?")
    second = await _stream(agent, _next_turn(an, same_thread=True), seed_repos, "Who has it?")

    last_call = [m.text for m in model.received[-1]]
    assert "Status of T-0002?" in last_call
    assert ANSWER in last_call
    assert last_call[-1] == "Who has it?"
    assert second.answer == "It is assigned to Hoa."


async def test_s4_second_turn_on_a_new_thread_has_no_history(
    make_caller: MakeCaller, seed_repos: Repositories
) -> None:
    an = await make_caller("E-001")
    model = ScriptedChatModel.from_script(*_script(), "Which ticket do you mean?")
    agent = build_ticket_agent(model, checkpointer=InMemorySaver())

    await _stream(agent, an, seed_repos, "Status of T-0002?")
    await _stream(agent, _next_turn(an, same_thread=False), seed_repos, "Who has it?")

    last_call = [m.text for m in model.received[-1]]
    assert "Status of T-0002?" not in last_call
    assert last_call[-1] == "Who has it?"


# ---------------------------------------------------------------- S5: cancelled


class _CancelOnFirstToken:
    """A sink that cancels the run's task when the first token arrives (= disconnect)."""

    name = "canceller"

    def __init__(self) -> None:
        self.task: asyncio.Task[TurnResult] | None = None

    async def handle(self, event: Event) -> None:
        if event.kind is EventKind.TOKEN and self.task is not None:
            self.task.cancel()
            self.task = None


async def test_s5_cancel_after_first_token_records_cancelled_and_stops_the_model(
    make_caller: MakeCaller, seed_repos: Repositories
) -> None:
    an = await make_caller("E-001")
    # First reply: some text, then a tool call. Without the cancel, the tool would run
    # and the model would be called a second time.
    first = AIMessage(
        content="Let me check. ",
        tool_calls=[{"name": "get_ticket", "args": {"ticket_id": "T-0002"}, "id": "c1"}],
    )
    model = ScriptedChatModel.from_script(first, "never sent")
    canceller = _CancelOnFirstToken()
    sink = MemorySink()
    task = asyncio.create_task(
        stream_turn(
            build_ticket_agent(model),
            ctx=an.request,
            message="Status of T-0002?",
            repos=seed_repos,
            bus=EventBus([sink, canceller]),
            clock=an.clock,
            entrypoint="test",
        )
    )
    canceller.task = task

    with pytest.raises(asyncio.CancelledError):
        await task

    assert sink.kinds() == [EventKind.RUN_STARTED, EventKind.TOKEN, EventKind.RUN_FINISHED]
    assert sink.events[-1].payload["status"] == "cancelled"
    assert len(model.received) == 1  # no further model call
    assert EventKind.TOOL_STARTED not in sink.kinds()  # the tool never ran


# ----------------------------------------------------------------- S6: tool bug


class _BrokenTickets:
    async def get(self, *args: object) -> None:
        raise RuntimeError("database driver bug")


async def test_s6_tool_bug_fails_the_run_and_propagates(
    make_caller: MakeCaller, seed_repos: Repositories
) -> None:
    an = await make_caller("E-001")
    broken = dataclasses.replace(seed_repos, tickets=_BrokenTickets())  # type: ignore[arg-type]
    agent = build_ticket_agent(ScriptedChatModel.from_script(*_script()))

    with pytest.raises(RuntimeError, match="database driver bug"):
        await _stream(agent, an, broken)

    assert an.sink.kinds() == [
        EventKind.RUN_STARTED,
        EventKind.TOOL_STARTED,  # ...and no tool_finished: the signal of a bug (M03 D1)
        EventKind.RUN_FINISHED,
    ]
    assert an.sink.events[-1].payload["status"] == "failed"
