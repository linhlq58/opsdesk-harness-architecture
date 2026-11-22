import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import JsonValue, ValidationError

from opsdesk.core.clock import FixedClock
from opsdesk.core.ids import RequestId, ThreadId
from opsdesk.observability.bus import EventBus
from opsdesk.observability.events import EventKind
from opsdesk.observability.recorder import RunRecorder
from opsdesk.observability.redaction import REDACTED
from opsdesk.observability.sinks.memory import MemorySink

T0 = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)


@pytest.fixture
def sink() -> MemorySink:
    return MemorySink()


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(T0)


@pytest.fixture
def recorder(sink: MemorySink, clock: FixedClock) -> RunRecorder:
    return RunRecorder(
        request_id=RequestId("req_1"),
        thread_id=ThreadId("thr_1"),
        bus=EventBus([sink]),
        clock=clock,
    )


async def test_emit_builds_publishes_and_returns_the_event(
    recorder: RunRecorder, sink: MemorySink
) -> None:
    event = await recorder.emit(EventKind.RUN_STARTED, {"workload": "chat", "entrypoint": "cli"})
    assert sink.events == [event]
    assert event.seq == 0
    assert event.request_id == "req_1"
    assert event.thread_id == "thr_1"
    assert event.namespace == ()
    assert event.event_id.startswith("evt_")


async def test_ts_comes_from_the_clock(recorder: RunRecorder, clock: FixedClock) -> None:
    first = await recorder.emit(EventKind.NODE_STARTED, {"node": "router"})
    clock.advance(timedelta(milliseconds=250))
    second = await recorder.emit(EventKind.NODE_FINISHED, {"node": "router", "duration_ms": 250})
    assert first.ts == T0
    assert second.ts == T0 + timedelta(milliseconds=250)


async def test_seq_is_shared_by_parent_and_children(
    recorder: RunRecorder, sink: MemorySink
) -> None:
    rag = recorder.child("helpdesk", "rag")
    tickets = recorder.child("helpdesk").child("tickets")

    await recorder.emit(EventKind.NODE_STARTED, {"node": "router"})
    await rag.emit(EventKind.NODE_STARTED, {"node": "retrieve"})
    await tickets.emit(EventKind.NODE_STARTED, {"node": "lookup"})
    await rag.emit(EventKind.NODE_FINISHED, {"node": "retrieve", "duration_ms": 5})
    await recorder.emit(EventKind.NODE_FINISHED, {"node": "router", "duration_ms": 9})

    assert [e.seq for e in sink.events] == [0, 1, 2, 3, 4]
    assert [e.namespace for e in sink.events] == [
        (),
        ("helpdesk", "rag"),
        ("helpdesk", "tickets"),
        ("helpdesk", "rag"),
        (),
    ]


async def test_same_timestamp_still_totally_ordered_by_seq(
    recorder: RunRecorder, sink: MemorySink
) -> None:
    # The clock does not move: every event has the same ts. seq still orders them.
    a, b = recorder.child("a"), recorder.child("b")
    await asyncio.gather(
        *(a.emit(EventKind.NODE_STARTED, {"node": f"a{i}"}) for i in range(10)),
        *(b.emit(EventKind.NODE_STARTED, {"node": f"b{i}"}) for i in range(10)),
    )
    assert len({e.ts for e in sink.events}) == 1
    assert sorted(e.seq for e in sink.events) == list(range(20))


async def test_emit_namespace_extends_the_recorder_namespace(
    recorder: RunRecorder,
) -> None:
    event = await recorder.child("helpdesk").emit(
        EventKind.NODE_STARTED, {"node": "x"}, namespace=("kb",)
    )
    assert event.namespace == ("helpdesk", "kb")


async def test_invalid_payload_raises_and_consumes_no_seq(
    recorder: RunRecorder, sink: MemorySink
) -> None:
    with pytest.raises(ValidationError):
        await recorder.emit(EventKind.NODE_STARTED, {"wrong": "field"})
    with pytest.raises(ValidationError, match="not emitted yet"):
        await recorder.emit(EventKind.GUARD_VERDICT, {})
    ok = await recorder.emit(EventKind.NODE_STARTED, {"node": "router"})
    assert ok.seq == 0
    assert sink.events == [ok]


# ----------------------------------------------------------------------- redaction


async def test_tool_args_are_redacted_before_any_sink_sees_them(
    recorder: RunRecorder, sink: MemorySink
) -> None:
    args: dict[str, JsonValue] = {
        "ticket_id": "T-0001",
        "api_key": "sk-123",
        "contact": "an.nguyen@acme.example",
    }
    event = await recorder.emit(EventKind.TOOL_STARTED, {"tool": "get_ticket", "args": args})
    assert event.payload["args"] == {
        "ticket_id": "T-0001",
        "api_key": REDACTED,
        "contact": "a***@acme.example",
    }
    assert sink.events[0].payload == event.payload
    assert args["api_key"] == "sk-123"  # caller's dict untouched


async def test_tool_summary_is_redacted_and_truncated(sink: MemorySink, clock: FixedClock) -> None:
    recorder = RunRecorder(
        request_id=RequestId("req_1"),
        thread_id=ThreadId("thr_1"),
        bus=EventBus([sink]),
        clock=clock,
        max_chars=20,
    )
    event = await recorder.emit(
        EventKind.TOOL_FINISHED,
        {
            "tool": "get_ticket",
            "status": "ok",
            "duration_ms": 4,
            "summary": "Reporter 0901234567, printer jams on every second page",
        },
    )
    summary = event.payload["summary"]
    assert isinstance(summary, str)
    assert "0901234567" not in summary
    assert summary.startswith("Reporter ***567")
    assert "…[+" in summary


async def test_token_text_is_not_redacted(recorder: RunRecorder) -> None:
    # Streamed model text is the answer itself; redact() is for tool data only.
    event = await recorder.emit(EventKind.TOKEN, {"text": "token: abc", "agent": "helpdesk"})
    assert event.payload["text"] == "token: abc"
