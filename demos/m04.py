"""M04 demo: the ticket agent behind the API, streamed over SSE.

The whole app runs **in-process** (FastAPI app factory + lifespan), and the demo acts
like the browser: it logs in, opens threads, posts chat messages and prints the SSE
frames it receives, exactly what ``web/app.js`` gets. Six scenarios from the
milestone:

1. An opens thread A and asks about T-0002: tool call + streamed answer.
2. Same thread, follow-up: answered from thread memory (no tool call).
3. Reset (thread B), same follow-up: no memory, the model asks which ticket.
4. Binh posts to An's thread A: ``404``, no run started.
5. An asks something and the client hangs up after the first token: the run is
   cancelled and the log records ``run_finished(cancelled)``.
6. JSONL check: scenario 1 is in the log, without token events.

* Fake mode (default): one ``ScriptedChatModel`` holds the replies for every model
  call of the demo, in order. Each scenario checks its expectations; runs in CI.
  The event log goes to a temporary directory.
* ``--live``: the real model (role ``specialist``) and ``var/events``. Printed, not
  checked.

Normal requests go through ``httpx.ASGITransport``; scenario 5 uses
``demos.asgi_client.stream_post``, which can hang up mid-stream.
"""

import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

import httpx
from fastapi import FastAPI

from demos.asgi_client import SseFrame, parse_sse, stream_post
from opsdesk.api.app import create_app
from opsdesk.api.state import AppState
from opsdesk.core.clock import FixedClock
from opsdesk.core.settings import Settings
from opsdesk.llm.factory import LlmConfigError
from opsdesk.llm.fakes import ScriptedChatModel, tool_call
from opsdesk.observability.events import Event

SEED_DIR = Path(__file__).resolve().parents[1] / "data" / "seed"

ANSWER_1 = "Ticket T-0002 (VPN disconnects every few minutes) is in progress."
ANSWER_2 = "T-0002 is assigned to Hoa Vo (E-005)."
ANSWER_3 = "Which ticket do you mean? Please give me its id, like T-0002."
ANSWER_5 = (
    "Here is everything about your tickets, in a long answer that takes a while to "
    "stream so the client has time to hang up in the middle of it."
)

# Every model call of the demo, in order (scenario 4 makes none).
SCRIPT = (
    tool_call("get_ticket", {"ticket_id": "T-0002"}, call_id="call_demo_1"),  # 1
    ANSWER_1,  # 1
    ANSWER_2,  # 2: from memory, no tool call
    ANSWER_3,  # 3: new thread, no memory
    ANSWER_5,  # 5: cut off after the first token
)


@dataclass
class Check:
    scenario: int
    what: str
    ok: bool


class Browser:
    """Acts like ``web/app.js``: session token, threads, chat requests."""

    def __init__(self, app: FastAPI, client: httpx.AsyncClient, out: TextIO) -> None:
        self.app = app
        self.client = client
        self.out = out

    @property
    def state(self) -> AppState:
        return self.app.state.opsdesk

    async def login(self, employee_id: str) -> str:
        response = await self.client.post("/api/session", json={"employee_id": employee_id})
        response.raise_for_status()
        return response.json()["token"]

    async def new_thread(self, token: str) -> str:
        response = await self.client.post(
            "/api/threads", json={"pattern": "ticket_agent"}, headers=_bearer(token)
        )
        response.raise_for_status()
        return response.json()["thread_id"]

    async def chat(self, token: str, thread_id: str, message: str) -> httpx.Response:
        return await self.client.post(
            "/api/chat",
            json={"thread_id": thread_id, "pattern": "ticket_agent", "message": message},
            headers=_bearer(token),
        )


async def run(*, live: bool, out: TextIO) -> list[Check]:
    """Run the six scenarios; print what the browser receives; return the checks."""
    with tempfile.TemporaryDirectory(prefix="opsdesk-m04-") as tmp:
        settings = Settings() if live else Settings(var_dir=Path(tmp))
        model = None if live else ScriptedChatModel.from_script(*SCRIPT)
        app = create_app(
            settings,
            model=model,
            clock=None if live else FixedClock(),
            seed_dir=SEED_DIR,
            web_dir=Path(tmp) / "no-web",
        )
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://opsdesk", timeout=120
            ) as client,
        ):
            return await _scenarios(Browser(app, client, out), model, live=live)


async def main(*, live: bool, out: TextIO) -> int:
    mode = "live model" if live else "scripted model"
    out.write(f"M04 demo: API + SSE, in-process ({mode})\n\n")
    try:
        checks = await run(live=live, out=out)
    except LlmConfigError as exc:
        out.write(f"Cannot run live: {exc}\n")
        return 2
    if live:
        return 0
    failed = [c for c in checks if not c.ok]
    for c in failed:
        out.write(f"✗ scenario {c.scenario}: {c.what}\n")
    out.write(f"{len(checks) - len(failed)}/{len(checks)} checks as expected\n")
    return 1 if failed else 0


# ------------------------------------------------------------------------ scenarios


async def _scenarios(b: Browser, model: ScriptedChatModel | None, *, live: bool) -> list[Check]:
    out = b.out
    checks: list[Check] = []

    def check(scenario: int, what: str, ok: bool) -> None:
        checks.append(Check(scenario, what, ok))
        if not live:
            out.write(f"  [check] {'✓' if ok else '✗'} {what}\n")

    # ---------------------------------------------------------------- 1
    out.write('▶ 1. An logs in, opens thread A, asks "What\'s the status of T-0002?"\n')
    an = await b.login("E-001")
    thread_a = await b.new_thread(an)
    response = await b.chat(an, thread_a, "What's the status of T-0002?")
    out.write(
        f"  [http]  POST /api/session → token · POST /api/threads → {_short(thread_a)}"
        f" · POST /api/chat → {response.status_code} {_media(response)}\n"
    )
    frames_1 = parse_sse(response.text)
    _print_frames(out, frames_1)
    request_1 = frames_1[0].data["request_id"] if frames_1 else ""
    check(1, "200 event-stream", response.status_code == 200 and _media(response) != "")
    check(
        1,
        "tool call, then tokens, then run_finished",
        _kinds(frames_1)[:3] == ["run_started", "tool_started", "tool_finished"]
        and _kinds(frames_1)[-1] == "run_finished",
    )
    if not live:
        check(1, "tokens spell the answer", _text(frames_1) == ANSWER_1)
    out.write("\n")

    # ---------------------------------------------------------------- 2
    out.write('▶ 2. Same thread: "Who is it assigned to?"\n')
    response = await b.chat(an, thread_a, "Who is it assigned to?")
    frames_2 = parse_sse(response.text)
    _print_frames(out, frames_2)
    out.write("  [why]   the checkpointer loaded thread A's history: the model saw turn 1\n")
    check(2, "no tool call: answered from thread memory", "tool_started" not in _kinds(frames_2))
    if model is not None:
        check(2, "model received turn 1", "What's the status of T-0002?" in _seen(model))
    out.write("\n")

    # ---------------------------------------------------------------- 3
    out.write('▶ 3. An presses Reset (thread B) and asks "Who is it assigned to?"\n')
    thread_b = await b.new_thread(an)
    response = await b.chat(an, thread_b, "Who is it assigned to?")
    frames_3 = parse_sse(response.text)
    out.write(f"  [http]  POST /api/threads → {_short(thread_b)} (new thread, empty history)\n")
    _print_frames(out, frames_3)
    if model is not None:
        check(
            3, "model has no memory of T-0002", "What's the status of T-0002?" not in _seen(model)
        )
    out.write("\n")

    # ---------------------------------------------------------------- 4
    out.write("▶ 4. Binh logs in and posts to An's thread A\n")
    binh = await b.login("E-002")
    calls_before = len(model.received) if model is not None else 0
    response = await b.chat(binh, thread_a, "What did An ask?")
    out.write(f"  [http]  POST /api/chat → {response.status_code} {response.json()['detail']}")
    out.write("   (no run started, nothing recorded)\n")
    check(4, "404 thread not found", response.status_code == 404)
    if model is not None:
        check(4, "no model call", len(model.received) == calls_before)
    out.write("\n")

    # ---------------------------------------------------------------- 5
    out.write("▶ 5. An asks a question and the client disconnects after the first token\n")
    if model is not None:
        model.chunk_delay = 0.02  # a slower model, so the hang-up lands mid-answer
    thread_c = await b.new_thread(an)
    result = await stream_post(
        b.app,
        "/api/chat",
        {
            "thread_id": thread_c,
            "pattern": "ticket_agent",
            "message": "Tell me everything about my tickets",
        },
        token=an,
        stop=lambda frame: frame.event == "token",
    )
    await _runs_settled(b.state)
    request_5 = result.frames[0].data["request_id"] if result.frames else ""
    logged_5 = [e for e in _jsonl(b.state) if e.request_id == request_5]
    out.write(f"  [sse]   {_frame_line(result.frames)} · (client hangs up)\n")
    out.write(f"  [jsonl] {' · '.join(_describe(e) for e in logged_5)}   (token excluded)\n")
    check(
        5,
        "run_finished(cancelled) in the log",
        bool(logged_5) and (logged_5[-1].payload.get("status") == "cancelled"),
    )
    out.write("\n")

    # ---------------------------------------------------------------- 6
    events_dir = b.state.settings.var_dir / "events"
    shown_dir = "var/events" if live else "<tmp>/events"
    out.write(f"▶ 6. JSONL check: scenario 1 is in {shown_dir}/<date>.jsonl without token events\n")
    logged_1 = [e for e in _jsonl(b.state) if e.request_id == request_1]
    out.write(f"  [jsonl] {' · '.join(_describe(e) for e in logged_1)}\n")
    out.write(
        f"  [sse]   the browser got {len(frames_1)} frames; the log has {len(logged_1)}"
        f" events: the {len(frames_1) - len(logged_1)} token frames are not on disk\n"
    )
    check(
        6,
        "scenario 1 logged",
        [e.kind.value for e in logged_1] == [k for k in _kinds(frames_1) if k != "token"],
    )
    check(6, "no token events in the log", all(e.kind.value != "token" for e in _jsonl(b.state)))
    if live:
        out.write(f"  [file]  {events_dir}\n")
    out.write("\n")
    return checks


# ------------------------------------------------------------------------ printing


def _print_frames(out: TextIO, frames: Sequence[SseFrame]) -> None:
    out.write(f"  [sse]   {_frame_line(frames)}\n")
    answer = _text(frames)
    if answer:
        out.write(f'  [ui]    assistant: "{answer}"\n')


def _frame_line(frames: Sequence[SseFrame]) -> str:
    """``seq0 run_started · seq1 tool_started get_ticket · seq3..8 token "a" "b" ...``"""
    parts: list[str] = []
    tokens: list[SseFrame] = []

    def flush() -> None:
        if not tokens:
            return
        first, last = tokens[0].data["seq"], tokens[-1].data["seq"]
        shown = " ".join(f'"{t.data["payload"]["text"]}"' for t in tokens[:3])
        more = " ..." if len(tokens) > 3 else ""
        span = f"seq{first}" if first == last else f"seq{first}..{last}"
        parts.append(f"{span} token {shown}{more}")
        tokens.clear()

    for frame in frames:
        if frame.event == "token":
            tokens.append(frame)
            continue
        flush()
        parts.append(f"seq{frame.data['seq']} {frame.event}{_detail(frame.data['payload'])}")
    flush()
    return " · ".join(parts)


def _detail(payload: dict[str, Any]) -> str:
    bits: list[str] = []
    if "tool" in payload:
        bits.append(str(payload["tool"]))
    if "status" in payload:
        bits.append(str(payload["status"]))
    if payload.get("error_code"):
        bits.append(str(payload["error_code"]))
    if "duration_ms" in payload and "tool" in payload:
        bits.append(f"({payload['duration_ms']} ms)")
    return (" " + " ".join(bits)) if bits else ""


def _describe(event: Event) -> str:
    status = event.payload.get("status")
    return f"seq{event.seq} {event.kind.value}" + (f" {status}" if status is not None else "")


# ------------------------------------------------------------------------ helpers


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _media(response: httpx.Response) -> str:
    content_type = response.headers.get("content-type", "")
    return "event-stream" if content_type.startswith("text/event-stream") else ""


def _kinds(frames: Sequence[SseFrame]) -> list[str | None]:
    return [f.event for f in frames]


def _text(frames: Sequence[SseFrame]) -> str:
    return "".join(str(f.data["payload"]["text"]) for f in frames if f.event == "token")


def _short(thread_id: str) -> str:
    return thread_id[:12] + "…"


def _seen(model: ScriptedChatModel) -> list[str]:
    """Texts of the messages the model received on its latest call."""
    return [m.text for m in model.received[-1]] if model.received else []


async def _runs_settled(state: AppState) -> None:
    import asyncio

    await asyncio.gather(*state.running, return_exceptions=True)


def _jsonl(state: AppState) -> list[Event]:
    events: list[Event] = []
    for path in sorted((state.settings.var_dir / "events").glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            events.append(Event.model_validate_json(line))
    return events
