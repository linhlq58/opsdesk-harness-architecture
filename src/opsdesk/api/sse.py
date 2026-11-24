"""Event v1 → SSE frame, through an allowlist (M04 §7, decision D7).

The browser is outside the trust boundary: everything sent here is readable by the
user (DevTools), browser extensions and proxies. Redaction (``RunRecorder``) already
removed known secrets from every event; this module decides **which kinds and which
fields leave the server at all**.

* ``ALLOWED`` maps a kind to the payload fields the browser may see. **Default deny**:
  a kind missing from the table is not sent (``to_sse`` returns ``None``), a payload
  field missing from its set is dropped. A kind or field added later (``usage_recorded``
  in M16, an internal note on ``tool_finished``) stays invisible to the UI until
  someone adds it here on purpose, where review sees it.
* Envelope: only ``ENVELOPE_FIELDS``. ``event_id`` (server-side only) and
  ``thread_id`` (the browser sent it) are not repeated.
* Frame: ``id:`` = ``seq`` (ordering, E4), ``event:`` = kind, ``data:`` = one JSON line.

Tests: ``tests/unit/api/test_sse.py`` (cases E1-E4).
"""

import json
from collections.abc import Mapping
from types import MappingProxyType

from fastapi.sse import ServerSentEvent
from pydantic import JsonValue

from opsdesk.observability.events import Event, EventKind

ENVELOPE_FIELDS: tuple[str, ...] = (
    "schema_version",
    "seq",
    "ts",
    "request_id",
    "namespace",
    "kind",
)

ALLOWED: Mapping[EventKind, frozenset[str]] = MappingProxyType(
    {
        EventKind.RUN_STARTED: frozenset({"entrypoint"}),
        EventKind.TOKEN: frozenset({"text", "agent"}),
        EventKind.TOOL_STARTED: frozenset({"tool", "call_id", "args"}),
        EventKind.TOOL_FINISHED: frozenset(
            {"tool", "call_id", "status", "error_code", "duration_ms", "summary"}
        ),
        EventKind.RUN_FINISHED: frozenset({"status", "duration_ms"}),
    }
)


def browser_view(event: Event) -> dict[str, JsonValue] | None:
    """What the browser may see of ``event``; ``None`` = nothing (kind not allowed)."""
    fields = ALLOWED.get(event.kind)
    if fields is None:
        return None
    envelope: dict[str, JsonValue] = event.model_dump(mode="json", include=set(ENVELOPE_FIELDS))
    envelope["payload"] = {k: v for k, v in event.payload.items() if k in fields}
    return envelope


def to_sse(event: Event) -> ServerSentEvent | None:
    """One SSE frame for ``event``, or ``None`` when it must not be sent."""
    view = browser_view(event)
    if view is None:
        return None
    return ServerSentEvent(
        # Pre-serialised: one line, Vietnamese text kept as is.
        raw_data=json.dumps(view, ensure_ascii=False, separators=(",", ":")),
        event=event.kind.value,
        id=str(event.seq),
    )
