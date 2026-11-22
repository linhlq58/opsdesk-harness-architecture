"""Event v1: the one record of "what happened" during a run.

One contract feeds every consumer: the SSE stream to the UI (M04, through an
allowlist), the local JSONL log (always on), and evaluation (M17 builds ``AgentResult``
from exactly these events). Traces (LangSmith/Langfuse) and audit records are separate
concepts; all three share the ``request_id``.

Envelope fields are fixed; ``payload`` is validated against the model registered for
``kind`` in ``PAYLOAD_MODELS``. A kind without a registered model is rejected ("not
emitted yet"), so nothing untyped can slip out. Payload models are added by the
milestone that first emits the kind.

Events describe *what happened*, not *what was said*: ``run_started`` does not carry
the user's message, and tool arguments / summaries are redacted by the recorder.

Versioning rule
---------------
Within ``opsdesk.event.v1`` you may:

* add a new ``EventKind`` (with its payload model);
* add an **optional** field (with a default) to a payload model.

Renaming or removing a field, changing a field's type, or changing what a kind means
requires ``opsdesk.event.v2``. The UI, stored JSONL files and eval datasets depend on
this. The JSON-schema snapshots in ``tests/contract/snapshots/`` make any change
visible in review.
"""

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, NonNegativeInt, model_validator

from opsdesk.core.clock import UtcDatetime
from opsdesk.core.ids import EventId, RequestId, ThreadId
from opsdesk.core.result import ToolStatus
from opsdesk.core.workload import Workload

SCHEMA_VERSION = "opsdesk.event.v1"


class EventKind(StrEnum):
    RUN_STARTED = "run_started"
    NODE_STARTED = "node_started"
    NODE_FINISHED = "node_finished"
    ROUTE_DECIDED = "route_decided"
    TOKEN = "token"
    TOOL_STARTED = "tool_started"
    TOOL_FINISHED = "tool_finished"
    RETRIEVAL_DONE = "retrieval_done"
    GUARD_VERDICT = "guard_verdict"
    GATE_FIRED = "gate_fired"
    APPROVAL_REQUIRED = "approval_required"
    APPROVAL_RESOLVED = "approval_resolved"
    HANDOFF = "handoff"
    USAGE_RECORDED = "usage_recorded"
    BUDGET_BLOCKED = "budget_blocked"
    RUN_FINISHED = "run_finished"


# ---------------------------------------------------------------------- payloads
# extra="forbid": a typo or an extra field (e.g. the user's message sneaking into
# run_started) is an error at the producer, not a silent leak into every sink.


class _Payload(BaseModel):
    # model_config (not class kwargs) so subclasses inherit it without pyright
    # demanding frozen=True on each one.
    model_config = ConfigDict(frozen=True, extra="forbid")


class RunStarted(_Payload):
    workload: Workload
    entrypoint: str = Field(min_length=1)  # "cli", "router", "eval", ...


class NodeStarted(_Payload):
    node: str = Field(min_length=1)


class NodeFinished(_Payload):
    node: str = Field(min_length=1)
    duration_ms: NonNegativeInt


class Token(_Payload):
    text: str  # one streamed chunk; may be "" (some providers emit empty chunks)
    agent: str = Field(min_length=1)


class ToolStarted(_Payload):
    tool: str = Field(min_length=1)
    args: dict[str, JsonValue]  # redacted by RunRecorder before the event exists


class ToolFinished(_Payload):
    tool: str = Field(min_length=1)
    status: ToolStatus
    duration_ms: NonNegativeInt
    error_code: str | None = None
    summary: str | None = None  # redacted and truncated by RunRecorder


type RunStatus = Literal["completed", "blocked", "interrupted", "failed"]


class RunFinished(_Payload):
    status: RunStatus
    duration_ms: NonNegativeInt


PAYLOAD_MODELS: Mapping[EventKind, type[_Payload]] = MappingProxyType(
    {
        EventKind.RUN_STARTED: RunStarted,
        EventKind.NODE_STARTED: NodeStarted,
        EventKind.NODE_FINISHED: NodeFinished,
        EventKind.TOKEN: Token,
        EventKind.TOOL_STARTED: ToolStarted,
        EventKind.TOOL_FINISHED: ToolFinished,
        EventKind.RUN_FINISHED: RunFinished,
    }
)


# ---------------------------------------------------------------------- envelope


class Event(BaseModel, frozen=True, extra="forbid"):
    schema_version: Literal["opsdesk.event.v1"] = SCHEMA_VERSION
    seq: NonNegativeInt  # 0, 1, 2, ... within one request; ordering never relies on ts
    event_id: EventId
    ts: UtcDatetime
    request_id: RequestId
    thread_id: ThreadId
    namespace: tuple[str, ...] = ()  # () = top level; ("helpdesk", "rag") in a subgraph
    kind: EventKind
    payload: dict[str, JsonValue]

    @model_validator(mode="after")
    def _payload_matches_kind(self) -> Self:
        model = PAYLOAD_MODELS.get(self.kind)
        if model is None:
            raise ValueError(f"no payload model registered for {self.kind!r} (not emitted yet)")
        model.model_validate(self.payload)
        return self
