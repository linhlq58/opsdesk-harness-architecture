"""Hand events to one consumer (M04: the SSE response of one browser request).

A run publishes into the bus; the HTTP response reads from this sink. They run as two
asyncio tasks, so the sink sits between them as a **bounded** queue:

* ``maxsize`` caps how many events may wait for the consumer. When the queue is full,
  ``handle`` waits until the consumer catches up (backpressure): a slow client slows
  its own run down instead of growing memory without limit. A client that has gone
  away does not hold the run forever, because the API cancels the run on disconnect.
* ``close()`` marks the end of the stream. The producer calls it once the run is over
  (in a ``finally``); ``async for`` over the sink then ends after the last event.
  ``close()`` never waits: if the queue is full, the end marker is not queued and the
  consumer stops when it has drained the queue. A blocking ``close()`` in the run's
  ``finally`` could hang the run on a full queue.
* Events published after ``close()`` are a producer bug and raise ``SinkClosed``
  (the bus logs and counts it, like any failing sink).
* ``abandon()``: the consumer has gone (M04: the browser disconnected). Queued events
  are dropped, a producer blocked on a full queue is released, and every later event
  is dropped silently. The API calls it *before* cancelling the run, so the run's
  final ``run_finished(cancelled)`` cannot get stuck here and still reaches the other
  sinks (JSONL).

One sink per request, one consumer per sink: it is a pipe, not a broadcast.
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Final

from opsdesk.observability.events import Event

DEFAULT_MAXSIZE = 256


class SinkClosed(RuntimeError):
    """An event was published after ``close()``."""


class _EndOfStream:
    """Marker put in the queue by ``close()``."""


_END: Final = _EndOfStream()


class QueueSink:
    def __init__(self, name: str = "queue", *, maxsize: int = DEFAULT_MAXSIZE) -> None:
        if maxsize < 1:
            raise ValueError("maxsize must be at least 1 (the queue must be bounded)")
        self._name = name
        self._queue: asyncio.Queue[Event | _EndOfStream] = asyncio.Queue(maxsize=maxsize)
        self._closed = False
        self._abandoned = False

    @property
    def name(self) -> str:
        return self._name

    @property
    def maxsize(self) -> int:
        return self._queue.maxsize

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def abandoned(self) -> bool:
        return self._abandoned

    async def handle(self, event: Event) -> None:
        if self._abandoned:
            return  # nobody is listening any more
        if self._closed:
            raise SinkClosed(f"queue sink {self._name!r} is closed")
        await self._queue.put(event)  # waits while the queue is full (backpressure)

    async def close(self) -> None:
        """End the stream. Never waits; safe to call more than once."""
        if self._closed:
            return
        self._closed = True
        # Wakes a consumer blocked on an empty queue. If the queue is full there is no
        # room, and none is needed: the consumer is not blocked, and stops once it
        # finds the queue empty and closed.
        with contextlib.suppress(asyncio.QueueFull):
            self._queue.put_nowait(_END)

    def abandon(self) -> None:
        """The consumer is gone: drop queued and future events, never block again."""
        self._abandoned = True
        self._closed = True
        while not self._queue.empty():  # frees a producer waiting in put()
            self._queue.get_nowait()

    async def __aiter__(self) -> AsyncIterator[Event]:
        """Yield events in publish order until ``close()``."""
        while not (self._closed and self._queue.empty()):
            item = await self._queue.get()
            if isinstance(item, _EndOfStream):
                return
            yield item
