import logging
from datetime import UTC, datetime

import pytest

from opsdesk.core.ids import EventId, RequestId, ThreadId
from opsdesk.observability.bus import EventBus
from opsdesk.observability.events import Event, EventKind
from opsdesk.observability.sinks.memory import MemorySink


def _event(seq: int = 0) -> Event:
    return Event(
        seq=seq,
        event_id=EventId(f"evt_{seq}"),
        ts=datetime(2026, 3, 1, 9, 0, tzinfo=UTC),
        request_id=RequestId("req_1"),
        thread_id=ThreadId("thr_1"),
        kind=EventKind.TOOL_STARTED,
        payload={"tool": "get_ticket", "args": {"note": "SECRET-PAYLOAD"}},
    )


class ExplodingSink:
    name = "exploding"

    async def handle(self, event: Event) -> None:
        raise OSError(f"disk full while writing {event.payload}")


class CancellingSink:
    name = "cancelling"

    async def handle(self, event: Event) -> None:
        raise KeyboardInterrupt


async def test_delivers_to_every_sink_in_order() -> None:
    first, second = MemorySink("first"), MemorySink("second")
    bus = EventBus([first, second])
    events = [_event(0), _event(1)]
    for e in events:
        await bus.publish(e)
    assert first.events == events
    assert second.events == events


async def test_failing_sink_does_not_stop_delivery_and_is_counted(
    caplog: pytest.LogCaptureFixture,
) -> None:
    before, after = MemorySink("before"), MemorySink("after")
    bus = EventBus([before, ExplodingSink(), after])

    with caplog.at_level(logging.WARNING):
        await bus.publish(_event(0))
        await bus.publish(_event(1))

    assert len(before.events) == 2
    assert len(after.events) == 2  # the sink after the broken one still receives
    assert bus.failures["exploding"] == 2
    assert bus.failures["before"] == 0


async def test_failure_log_names_sink_and_kind_but_not_payload(
    caplog: pytest.LogCaptureFixture,
) -> None:
    bus = EventBus([ExplodingSink()])
    with caplog.at_level(logging.WARNING):
        await bus.publish(_event(0))
    assert "exploding" in caplog.text
    assert "tool_started" in caplog.text
    assert "OSError" in caplog.text
    assert "SECRET-PAYLOAD" not in caplog.text  # the exception message quoted it


async def test_base_exceptions_are_not_swallowed() -> None:
    bus = EventBus([CancellingSink()])
    with pytest.raises(KeyboardInterrupt):
        await bus.publish(_event(0))


def test_sink_names_must_be_unique() -> None:
    with pytest.raises(ValueError, match="unique"):
        EventBus([MemorySink("x"), MemorySink("x")])


async def test_bus_without_sinks_is_a_no_op() -> None:
    await EventBus([]).publish(_event(0))
