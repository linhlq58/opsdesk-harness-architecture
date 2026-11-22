"""Deliver each event to every sink. A failing sink never breaks the run.

Sinks are where events go: in-memory (tests, evaluation), JSONL (local log, always
on), SSE (M04), remote tracers later. Observability must never be the reason a user's
request fails: if the JSONL disk is full or a remote backend is down, the bus logs the
failure (sink name + event kind, never the payload), counts it in ``failures``, and
keeps delivering to the other sinks.

Sinks are called one after another, in the order given, so every sink sees events in
the order they were published.
"""

import logging
from collections import Counter
from collections.abc import Sequence
from typing import Protocol

from opsdesk.observability.events import Event

logger = logging.getLogger(__name__)


class EventSink(Protocol):
    @property
    def name(self) -> str: ...

    async def handle(self, event: Event) -> None: ...


class EventBus:
    def __init__(self, sinks: Sequence[EventSink]) -> None:
        names = [sink.name for sink in sinks]
        if len(set(names)) != len(names):
            raise ValueError(f"sink names must be unique: {names}")
        self._sinks = tuple(sinks)
        self.failures: Counter[str] = Counter()

    async def publish(self, event: Event) -> None:
        for sink in self._sinks:
            try:
                await sink.handle(event)
            # Exception, not BaseException: task cancellation (CancelledError) and
            # KeyboardInterrupt must still stop the run.
            except Exception as exc:
                self.failures[sink.name] += 1
                # Exception type only: its message could quote the event payload.
                logger.warning(
                    "event sink %r failed on %s (seq=%d): %s",
                    sink.name,
                    event.kind,
                    event.seq,
                    type(exc).__name__,
                )
