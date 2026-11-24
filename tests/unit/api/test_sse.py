"""SSE allowlist and framing, cases E1-E4 (M04 §7, decision D7)."""

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.sse import format_sse_event

from opsdesk.api.sse import ALLOWED, ENVELOPE_FIELDS, browser_view, to_sse
from opsdesk.core.ids import EventId, RequestId, ThreadId
from opsdesk.observability.events import Event, EventKind


def _event(kind: EventKind, payload: dict[str, Any], seq: int = 7) -> Event:
    return Event.model_validate(
        {
            "seq": seq,
            "event_id": EventId("evt_secret"),
            "ts": datetime(2026, 3, 1, 9, 0, tzinfo=UTC),
            "request_id": RequestId("req_1"),
            "thread_id": ThreadId("thr_internal"),
            "kind": kind,
            "payload": payload,
        }
    )


TOOL_STARTED = _event(
    EventKind.TOOL_STARTED,
    {"tool": "get_ticket", "args": {"ticket_id": "T-0002", "password": "***"}, "call_id": "c1"},
)


def test_e1_tool_started_sends_only_the_listed_fields() -> None:
    view = browser_view(TOOL_STARTED)

    assert view is not None
    assert set(view) == {*ENVELOPE_FIELDS, "payload"}
    assert view["payload"] == {
        "tool": "get_ticket",
        "args": {"ticket_id": "T-0002", "password": "***"},  # as redacted by the recorder
        "call_id": "c1",
    }


def test_envelope_never_carries_event_id_thread_id_or_workload() -> None:
    started = _event(EventKind.RUN_STARTED, {"workload": "chat", "entrypoint": "api"})

    view = browser_view(started)

    assert view is not None
    assert "event_id" not in view and "thread_id" not in view
    assert view["payload"] == {"entrypoint": "api"}  # workload dropped


@pytest.mark.parametrize(
    "kind",
    [k for k in EventKind if k not in ALLOWED],
)
def test_e2_kinds_outside_the_allowlist_are_not_sent(kind: EventKind) -> None:
    # Built without validation: most of these kinds have no payload model yet. The
    # point is the rule, which must hold for kinds added later (usage_recorded, ...).
    event = Event.model_construct(
        **TOOL_STARTED.model_dump(exclude={"kind", "payload"}), kind=kind, payload={}
    )

    assert to_sse(event) is None


def test_e2_a_future_kind_added_to_the_schema_is_invisible_by_default() -> None:
    node = _event(EventKind.NODE_STARTED, {"node": "router"})  # registered, not allowed

    assert to_sse(node) is None


def test_e3_payload_fields_outside_the_allowlist_are_dropped() -> None:
    # Break-it B3: a new internal field on tool_finished must not reach the browser.
    finished = Event.model_construct(
        **TOOL_STARTED.model_dump(exclude={"kind", "payload"}),
        kind=EventKind.TOOL_FINISHED,
        payload={
            "tool": "get_ticket",
            "status": "ok",
            "duration_ms": 12,
            "error_code": None,
            "summary": "1 item",
            "call_id": "c1",
            "internal_note": "cost 1200 VND, model gpt-internal",
        },
    )

    view = browser_view(finished)

    assert view is not None
    assert "internal_note" not in view["payload"]  # type: ignore[operator]
    assert set(view["payload"]) == ALLOWED[EventKind.TOOL_FINISHED]  # type: ignore[arg-type]


def test_e4_sse_id_is_the_seq_and_event_is_the_kind() -> None:
    frame = to_sse(TOOL_STARTED)

    assert frame is not None
    assert frame.id == "7"
    assert frame.event == "tool_started"


def test_wire_format_is_one_json_data_line() -> None:
    token = _event(EventKind.TOKEN, {"text": "Máy in\nbị kẹt", "agent": "ticket"}, seq=3)
    frame = to_sse(token)
    assert frame is not None

    wire = format_sse_event(data_str=frame.raw_data, event=frame.event, id=frame.id).decode("utf-8")

    lines = wire.strip("\n").split("\n")
    assert lines[0] == "event: token"
    assert lines[1].startswith("data: ")
    assert lines[2] == "id: 3"
    data = json.loads(lines[1].removeprefix("data: "))
    assert data["payload"]["text"] == "Máy in\nbị kẹt"  # newline escaped inside JSON
    assert data["seq"] == 3
