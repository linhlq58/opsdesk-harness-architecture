import asyncio
from datetime import UTC, datetime

import pytest

from opsdesk.core.ids import EventId, RequestId, ThreadId
from opsdesk.observability.bus import EventBus
from opsdesk.observability.events import Event, EventKind
from opsdesk.observability.sinks.queue import QueueSink, SinkClosed


def _token(seq: int) -> Event:
    return Event.model_validate(
        {
            "seq": seq,
            "event_id": EventId(f"evt_{seq}"),
            "ts": datetime(2026, 3, 1, tzinfo=UTC),
            "request_id": RequestId("req_1"),
            "thread_id": ThreadId("thr_1"),
            "kind": EventKind.TOKEN,
            "payload": {"text": f"w{seq} ", "agent": "ticket"},
        }
    )


async def _drain(sink: QueueSink) -> list[Event]:
    return [event async for event in sink]


async def test_yields_events_in_order_until_closed() -> None:
    sink = QueueSink()
    events = [_token(i) for i in range(3)]
    for event in events:
        await sink.handle(event)
    await sink.close()

    assert await _drain(sink) == events


async def test_consumer_waits_for_the_producer() -> None:
    # The SSE response starts reading before the run has published anything.
    sink = QueueSink()
    consumer = asyncio.create_task(_drain(sink))
    await asyncio.sleep(0)
    assert not consumer.done()

    await sink.handle(_token(0))
    await sink.close()

    assert [e.seq for e in await consumer] == [0]


async def test_queue_is_bounded_and_a_full_queue_blocks_the_producer() -> None:
    sink = QueueSink(maxsize=2)
    await sink.handle(_token(0))
    await sink.handle(_token(1))

    blocked = asyncio.create_task(sink.handle(_token(2)))
    await asyncio.sleep(0)
    assert not blocked.done()  # backpressure: waits for the consumer

    iterator = aiter(sink)
    assert (await anext(iterator)).seq == 0  # consumer takes one → room for one more
    await asyncio.wait_for(blocked, timeout=1)
    await sink.close()
    assert [e.seq async for e in iterator] == [1, 2]


async def test_close_never_blocks_even_on_a_full_queue() -> None:
    # close() runs in the run's ``finally``: it must not hang if the client is slow.
    sink = QueueSink(maxsize=1)
    await sink.handle(_token(0))

    await asyncio.wait_for(sink.close(), timeout=1)

    assert [e.seq for e in await _drain(sink)] == [0]


def test_maxsize_must_be_positive() -> None:
    # asyncio.Queue(maxsize=0) would be unbounded.
    with pytest.raises(ValueError, match="bounded"):
        QueueSink(maxsize=0)


async def test_close_is_idempotent() -> None:
    sink = QueueSink()
    await sink.close()
    await sink.close()

    assert sink.closed
    assert await _drain(sink) == []


async def test_publishing_after_close_is_a_producer_bug() -> None:
    sink = QueueSink()
    await sink.close()

    with pytest.raises(SinkClosed):
        await sink.handle(_token(0))


async def test_through_the_bus_after_close_is_counted_not_raised() -> None:
    sink = QueueSink()
    bus = EventBus([sink])
    await sink.close()

    await bus.publish(_token(0))

    assert bus.failures["queue"] == 1


async def test_abandon_releases_a_blocked_producer_and_drops_later_events() -> None:
    # The browser disconnected while the queue was full: the run must not hang.
    sink = QueueSink(maxsize=1)
    await sink.handle(_token(0))
    blocked = asyncio.create_task(sink.handle(_token(1)))
    await asyncio.sleep(0)
    assert not blocked.done()

    sink.abandon()

    await asyncio.wait_for(blocked, timeout=1)
    await asyncio.wait_for(sink.handle(_token(2)), timeout=1)  # dropped, no error
    assert sink.abandoned
    assert sink.closed


async def test_abandoned_sink_is_not_a_bus_failure() -> None:
    sink = QueueSink()
    bus = EventBus([sink])
    sink.abandon()

    await bus.publish(_token(0))

    assert bus.failures["queue"] == 0
