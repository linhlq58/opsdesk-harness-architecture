from datetime import UTC, datetime

from opsdesk.core.ids import EventId, RequestId, ThreadId
from opsdesk.observability.events import Event, EventKind
from opsdesk.observability.sinks.memory import MemorySink


def _event(seq: int, kind: EventKind, payload: dict[str, object]) -> Event:
    return Event.model_validate(
        {
            "seq": seq,
            "event_id": EventId(f"evt_{seq}"),
            "ts": datetime(2026, 3, 1, tzinfo=UTC),
            "request_id": RequestId("req_1"),
            "thread_id": ThreadId("thr_1"),
            "kind": kind,
            "payload": payload,
        }
    )


async def test_memory_sink_keeps_events_in_order() -> None:
    sink = MemorySink()
    a = _event(0, EventKind.NODE_STARTED, {"node": "router"})
    b = _event(1, EventKind.NODE_FINISHED, {"node": "router", "duration_ms": 1})
    await sink.handle(a)
    await sink.handle(b)
    assert sink.name == "memory"
    assert sink.events == [a, b]
    assert sink.kinds() == [EventKind.NODE_STARTED, EventKind.NODE_FINISHED]
