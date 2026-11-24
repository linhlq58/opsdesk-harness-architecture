from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from opsdesk.core.ids import EventId, RequestId, ThreadId
from opsdesk.observability.events import PAYLOAD_MODELS, SCHEMA_VERSION, Event, EventKind

T0 = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)

VALID_PAYLOADS: dict[EventKind, dict[str, Any]] = {
    EventKind.RUN_STARTED: {"workload": "chat", "entrypoint": "cli"},
    EventKind.NODE_STARTED: {"node": "router"},
    EventKind.NODE_FINISHED: {"node": "router", "duration_ms": 12},
    EventKind.ROUTE_DECIDED: {"agents": ["ticket", "knowledge"], "fallback": False},
    EventKind.TOKEN: {"text": "Xin chào", "agent": "helpdesk"},
    EventKind.TOOL_STARTED: {"tool": "get_ticket", "args": {"ticket_id": "T-0001"}},
    EventKind.TOOL_FINISHED: {
        "tool": "get_ticket",
        "status": "denied",
        "duration_ms": 3,
        "error_code": "not_owner",
        "summary": None,
    },
    EventKind.RUN_FINISHED: {"status": "completed", "duration_ms": 1200},
}


def make_event(**overrides: Any) -> Event:
    data: dict[str, Any] = {
        "seq": 0,
        "event_id": EventId("evt_1"),
        "ts": T0,
        "request_id": RequestId("req_1"),
        "thread_id": ThreadId("thr_1"),
        "kind": EventKind.RUN_STARTED,
        "payload": VALID_PAYLOADS[EventKind.RUN_STARTED],
    }
    return Event.model_validate(data | overrides)


# ---------------------------------------------------------------------- envelope


def test_defaults() -> None:
    e = make_event()
    assert e.schema_version == SCHEMA_VERSION == "opsdesk.event.v1"
    assert e.namespace == ()


@pytest.mark.parametrize("kind", list(VALID_PAYLOADS))
def test_every_registered_kind_accepts_its_payload(kind: EventKind) -> None:
    e = make_event(kind=kind, payload=VALID_PAYLOADS[kind])
    assert e.kind is kind


def test_test_table_covers_every_registered_kind() -> None:
    assert set(VALID_PAYLOADS) == set(PAYLOAD_MODELS)


@pytest.mark.parametrize("kind", [k for k in EventKind if k not in PAYLOAD_MODELS])
def test_kind_without_payload_model_is_rejected(kind: EventKind) -> None:
    with pytest.raises(ValidationError, match="not emitted yet"):
        make_event(kind=kind, payload={})


def test_unknown_kind_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_event(kind="user_mood", payload={})


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_event(ts=datetime(2026, 3, 1, 9, 0))  # noqa: DTZ001


def test_ts_is_normalised_to_utc() -> None:
    ict = timezone(timedelta(hours=7))
    e = make_event(ts=datetime(2026, 3, 1, 16, 0, tzinfo=ict))
    assert e.ts == T0
    assert e.ts.tzinfo is UTC


@pytest.mark.parametrize(
    "overrides",
    [
        {"seq": -1},
        {"schema_version": "opsdesk.event.v2"},
        {"surprise": "field"},
    ],
)
def test_bad_envelope_is_rejected(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        make_event(**overrides)


def test_event_is_immutable() -> None:
    e = make_event()
    with pytest.raises(ValidationError):
        e.seq = 5  # type: ignore[misc]


def test_json_round_trip() -> None:
    e = make_event(
        kind=EventKind.TOOL_FINISHED,
        payload=VALID_PAYLOADS[EventKind.TOOL_FINISHED],
        namespace=("helpdesk", "tickets"),
    )
    assert Event.model_validate_json(e.model_dump_json()) == e


# ---------------------------------------------------------------------- payloads


@pytest.mark.parametrize(
    ("kind", "payload"),
    [
        (EventKind.RUN_STARTED, {"workload": "chat"}),  # missing entrypoint
        (EventKind.RUN_STARTED, {"workload": "fun", "entrypoint": "cli"}),  # bad enum
        # The user's message must never ride along in run_started.
        (EventKind.RUN_STARTED, {"workload": "chat", "entrypoint": "cli", "message": "hi"}),
        (EventKind.NODE_FINISHED, {"node": "router", "duration_ms": -1}),
        (EventKind.NODE_STARTED, {"node": ""}),
        (EventKind.TOOL_FINISHED, {"tool": "t", "status": "exploded", "duration_ms": 1}),
        (EventKind.RUN_FINISHED, {"status": "done", "duration_ms": 1}),
    ],
)
def test_payload_failing_its_model_is_rejected(kind: EventKind, payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        make_event(kind=kind, payload=payload)


def test_optional_payload_fields_have_defaults() -> None:
    # Adding optional fields is allowed within v1; old events stay valid.
    e = make_event(
        kind=EventKind.TOOL_FINISHED,
        payload={"tool": "get_ticket", "status": "ok", "duration_ms": 5},
    )
    assert e.kind is EventKind.TOOL_FINISHED


# ------------------------------------------------------------- route_decided (M05)


def test_route_decided_defaults_and_fallback_payload() -> None:
    e = make_event(
        kind=EventKind.ROUTE_DECIDED,
        payload={
            "agents": ["general"],
            "fallback": True,
            "reason": "unknown_agent",
            "dropped": ["billing"],
        },
    )
    assert e.payload["dropped"] == ["billing"]


@pytest.mark.parametrize(
    "payload",
    [
        {"agents": [], "fallback": False},  # a route set is never empty
        {"agents": ["ticket"], "fallback": False, "queries": ["status of T-0002?"]},  # no text
    ],
)
def test_route_decided_rejects_empty_routes_and_sub_queries(payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        make_event(kind=EventKind.ROUTE_DECIDED, payload=payload)
