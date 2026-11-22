"""``RunRecorder``: the only way events are created during a run.

One recorder per request. It owns the three things no caller should get wrong:

* **``seq``**: a counter shared by the recorder and all its children, so events are
  totally ordered within a request even when parallel branches (M05) emit in the same
  millisecond. Consumers order by ``seq``, never by ``ts``.
* **``ts``**: read from the injected ``Clock``, never ``datetime.now()``, so tests are
  deterministic.
* **redaction**: ``tool_started.args`` and ``tool_finished.summary`` pass through
  ``redact`` *before* the event exists, so no sink ever sees unredacted tool data.

It takes the correlation ids, not a ``RequestContext``: the event system needs ids, not
identity, and stays reusable by the ingestion job, the MCP client and the eval runner.
Build it from the context: ``RunRecorder(request_id=ctx.request_id,
thread_id=ctx.thread_id, bus=bus, clock=clock)``.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import JsonValue

from opsdesk.core.clock import Clock
from opsdesk.core.ids import RequestId, ThreadId, new_event_id
from opsdesk.observability.bus import EventBus
from opsdesk.observability.events import Event, EventKind
from opsdesk.observability.redaction import redact

DEFAULT_MAX_CHARS = 500


@dataclass(slots=True)
class _SeqCounter:
    """Shared by a recorder and its children (they hold the same instance)."""

    next_value: int = 0


class RunRecorder:
    def __init__(
        self,
        *,
        request_id: RequestId,
        thread_id: ThreadId,
        bus: EventBus,
        clock: Clock,
        max_chars: int = DEFAULT_MAX_CHARS,
        _namespace: tuple[str, ...] = (),
        _counter: _SeqCounter | None = None,
    ) -> None:
        self.request_id = request_id
        self.thread_id = thread_id
        self.namespace = _namespace
        self._bus = bus
        self._clock = clock
        self._max_chars = max_chars
        self._counter = _counter or _SeqCounter()

    def child(self, *namespace: str) -> "RunRecorder":
        """Recorder for a subgraph / sub-agent: same ``seq`` counter, longer namespace."""
        return RunRecorder(
            request_id=self.request_id,
            thread_id=self.thread_id,
            bus=self._bus,
            clock=self._clock,
            max_chars=self._max_chars,
            _namespace=self.namespace + namespace,
            _counter=self._counter,
        )

    async def emit(
        self,
        kind: EventKind,
        payload: Mapping[str, JsonValue],
        *,
        namespace: tuple[str, ...] = (),
    ) -> Event:
        """Create, publish and return one event.

        An invalid payload raises ``ValidationError`` (a producer bug) and consumes no
        ``seq``, so the sequence never has gaps.
        """
        # No ``await`` between reading the counter, building the event and advancing
        # the counter: under asyncio nothing else can run in between, so two
        # concurrent emits can never get the same seq.
        event = Event(
            seq=self._counter.next_value,
            event_id=new_event_id(),
            ts=self._clock.now(),
            request_id=self.request_id,
            thread_id=self.thread_id,
            namespace=self.namespace + namespace,
            kind=kind,
            payload=self._redacted(kind, payload),
        )
        self._counter.next_value += 1
        await self._bus.publish(event)
        return event

    def _redacted(self, kind: EventKind, payload: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
        data = dict(payload)
        if kind is EventKind.TOOL_STARTED and "args" in data:
            data["args"] = redact(data["args"], max_chars=self._max_chars)
        elif kind is EventKind.TOOL_FINISHED and data.get("summary") is not None:
            data["summary"] = redact(data["summary"], max_chars=self._max_chars)
        return data
