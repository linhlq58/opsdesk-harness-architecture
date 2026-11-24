"""HTTP API cases H1-H5 (M04 §8), plus threads (D5) and personas, in-process.

The app runs with a scripted model. Requests go through ``httpx.ASGITransport`` (a
real HTTP client, response buffered) or through ``demos.asgi_client.stream_post``
when a test must hang up mid-stream (H4).
"""

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from langchain_core.messages import AIMessage

from demos.asgi_client import SseFrame, parse_sse, stream_post
from opsdesk.api.app import create_app
from opsdesk.api.sse import ALLOWED, ENVELOPE_FIELDS
from opsdesk.api.state import AppState
from opsdesk.core.clock import FixedClock
from opsdesk.core.settings import Settings
from opsdesk.llm.fakes import ScriptedChatModel, tool_call
from opsdesk.observability.events import Event

pytestmark = pytest.mark.integration

ANSWER = "Ticket T-0002 is in progress."
STATUS_SCRIPT: tuple[AIMessage | str, ...] = (
    tool_call("get_ticket", {"ticket_id": "T-0002"}, call_id="call_h3"),
    ANSWER,
)


class Api:
    """An in-process app plus helpers that act like the browser."""

    def __init__(self, app: FastAPI, client: httpx.AsyncClient, model: ScriptedChatModel) -> None:
        self.app = app
        self.client = client
        self.model = model

    @property
    def state(self) -> AppState:
        return self.app.state.opsdesk

    async def login(self, employee_id: str) -> str:
        response = await self.client.post("/api/session", json={"employee_id": employee_id})
        assert response.status_code == 200, response.text
        return response.json()["token"]

    async def new_thread(self, token: str, pattern: str = "ticket_agent") -> str:
        response = await self.client.post(
            "/api/threads", json={"pattern": pattern}, headers=_bearer(token)
        )
        assert response.status_code == 201, response.text
        return response.json()["thread_id"]

    async def chat(
        self, token: str | None, thread_id: str, message: str, pattern: str = "ticket_agent"
    ) -> httpx.Response:
        headers = _bearer(token) if token else {}
        return await self.client.post(
            "/api/chat",
            json={"thread_id": thread_id, "pattern": pattern, "message": message},
            headers=headers,
        )

    async def runs_settled(self) -> None:
        await asyncio.gather(*self.state.running, return_exceptions=True)

    def jsonl_events(self) -> list[Event]:
        lines: list[str] = []
        for path in sorted((self.state.settings.var_dir / "events").glob("*.jsonl")):
            lines += path.read_text(encoding="utf-8").splitlines()
        return [Event.model_validate_json(line) for line in lines]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


type MakeApi = Callable[..., Any]


@pytest.fixture
def make_api(tmp_path: Path) -> MakeApi:
    @asynccontextmanager
    async def make(*script: AIMessage | str, chunk_delay: float = 0.0) -> AsyncIterator[Api]:
        model = ScriptedChatModel.from_script(*script)
        model.chunk_delay = chunk_delay
        app = create_app(
            Settings(var_dir=tmp_path), model=model, clock=FixedClock(), web_dir=tmp_path / "no"
        )
        transport = httpx.ASGITransport(app)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(transport=transport, base_url="http://testserver") as client,
        ):
            yield Api(app, client, model)

    return make


def _frames(response: httpx.Response) -> list[SseFrame]:
    return parse_sse(response.text)


# ----------------------------------------------------------------- H1: no token


@pytest.mark.parametrize("token", [None, "not-a-token"])
async def test_h1_missing_or_bad_token_is_401_and_starts_nothing(
    make_api: MakeApi, token: str | None
) -> None:
    async with make_api(*STATUS_SCRIPT) as api:
        an = await api.login("E-001")
        thread = await api.new_thread(an)

        response = await api.chat(token, thread, "Status of T-0002?")

        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        assert api.model.received == []  # no run started
        assert api.jsonl_events() == []


async def test_threads_need_a_token(make_api: MakeApi) -> None:
    async with make_api() as api:
        response = await api.client.post("/api/threads", json={"pattern": "ticket_agent"})

    assert response.status_code == 401


async def test_a_thread_must_be_created_for_a_known_pattern(make_api: MakeApi) -> None:
    async with make_api() as api:
        an = await api.login("E-001")
        missing = await api.client.post("/api/threads", json={}, headers=_bearer(an))
        unknown = await api.client.post(
            "/api/threads", json={"pattern": "swarm"}, headers=_bearer(an)
        )
        created = await api.client.post(
            "/api/threads", json={"pattern": "router"}, headers=_bearer(an)
        )

    assert missing.status_code == unknown.status_code == 422
    assert created.status_code == 201
    assert created.json()["pattern"] == "router"


async def test_a_thread_used_with_another_pattern_looks_like_an_unknown_one(
    make_api: MakeApi,
) -> None:
    async with make_api(*STATUS_SCRIPT) as api:
        an = await api.login("E-001")
        router_thread = await api.new_thread(an, "router")
        wrong_pattern = await api.chat(an, router_thread, "Status of T-0002?", "ticket_agent")
        unknown = await api.chat(an, "thr_does_not_exist", "Status of T-0002?")

    assert wrong_pattern.status_code == unknown.status_code == 404
    assert wrong_pattern.json() == unknown.json()
    assert api.model.received == []  # no run started


# ------------------------------------------------------- H2: foreign thread (D5)


@pytest.mark.parametrize("intruder", ["E-002", "G-001"])
async def test_h2_foreign_thread_is_404_and_starts_nothing(
    make_api: MakeApi, intruder: str
) -> None:
    async with make_api(*STATUS_SCRIPT) as api:
        ans_thread = await api.new_thread(await api.login("E-001"))

        response = await api.chat(await api.login(intruder), ans_thread, "Show me the chat")

        assert response.status_code == 404
        assert response.json() == {"detail": "thread not found"}
        assert api.model.received == []
        assert api.jsonl_events() == []


async def test_h2_foreign_and_unknown_threads_get_identical_responses(make_api: MakeApi) -> None:
    async with make_api() as api:
        ans_thread = await api.new_thread(await api.login("E-001"))
        binh = await api.login("E-002")

        foreign = await api.chat(binh, ans_thread, "hi")
        unknown = await api.chat(binh, "thr_does_not_exist", "hi")

    assert (foreign.status_code, foreign.content) == (unknown.status_code, unknown.content)


# --------------------------------------------------------------- H3: happy path


async def test_h3_valid_request_streams_allowlisted_frames_in_seq_order(
    make_api: MakeApi,
) -> None:
    async with make_api(*STATUS_SCRIPT) as api:
        an = await api.login("E-001")
        response = await api.chat(an, await api.new_thread(an), "What's the status of T-0002?")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    frames = _frames(response)
    kinds = [f.event for f in frames]
    assert kinds[:3] == ["run_started", "tool_started", "tool_finished"]
    assert kinds[-1] == "run_finished"
    assert frames[-1].data["payload"]["status"] == "completed"
    assert [int(f.id or -1) for f in frames] == list(range(len(frames)))  # id = seq, in order
    text = "".join(f.data["payload"]["text"] for f in frames if f.event == "token")
    assert text == ANSWER
    for frame in frames:  # D7: only allowlisted envelope and payload fields
        assert set(frame.data) == {*ENVELOPE_FIELDS, "payload"}
        assert set(frame.data["payload"]) <= ALLOWED[frame.data["kind"]]


async def test_h3_jsonl_has_the_run_without_tokens(make_api: MakeApi) -> None:
    async with make_api(*STATUS_SCRIPT) as api:
        an = await api.login("E-001")
        response = await api.chat(an, await api.new_thread(an), "Status of T-0002?")
        await api.runs_settled()
        logged = api.jsonl_events()

    streamed = [f.event for f in _frames(response)]
    assert [e.kind.value for e in logged] == [k for k in streamed if k != "token"]  # D4
    assert logged[0].payload["entrypoint"] == "api"


async def test_identity_comes_from_the_token_not_the_body(make_api: MakeApi) -> None:
    # The body has no identity field at all; an extra one is rejected, not trusted.
    async with make_api(*STATUS_SCRIPT) as api:
        an = await api.login("E-001")
        thread = await api.new_thread(an)
        response = await api.client.post(
            "/api/chat",
            json={
                "thread_id": thread,
                "pattern": "ticket_agent",
                "message": "hi",
                "employee_id": "E-005",
            },
            headers=_bearer(an),
        )

    assert response.status_code == 422


# --------------------------------------------------- multi-turn through the API


async def test_second_turn_on_the_thread_remembers_and_reset_forgets(make_api: MakeApi) -> None:
    async with make_api(*STATUS_SCRIPT, "Hoa has it.", "Which ticket do you mean?") as api:
        an = await api.login("E-001")
        thread_a = await api.new_thread(an)
        await api.chat(an, thread_a, "Status of T-0002?")
        await api.chat(an, thread_a, "Who is it assigned to?")
        remembered = [m.text for m in api.model.received[-1]]

        thread_b = await api.new_thread(an)  # Reset
        await api.chat(an, thread_b, "Who is it assigned to?")
        fresh = [m.text for m in api.model.received[-1]]

    assert "Status of T-0002?" in remembered
    assert "Status of T-0002?" not in fresh


# ------------------------------------------------------------- H4: disconnect


async def test_h4_disconnect_after_first_token_records_cancelled(make_api: MakeApi) -> None:
    # A model that takes ~1 s to answer: the disconnect lands mid-answer. (A run that
    # finishes before the server notices the disconnect is, correctly, "completed".)
    long_answer = " ".join(f"word{i}" for i in range(50))
    async with make_api(long_answer, "never used", chunk_delay=0.02) as api:
        an = await api.login("E-001")
        thread = await api.new_thread(an)

        result = await stream_post(
            api.app,
            "/api/chat",
            {"thread_id": thread, "pattern": "ticket_agent", "message": "Tell me everything"},
            token=an,
            stop=lambda frame: frame.event == "token",
        )
        await api.runs_settled()
        logged = api.jsonl_events()

    assert result.status == 200
    assert result.disconnected
    assert [f.event for f in result.frames][-1] == "token"
    assert [e.kind.value for e in logged] == ["run_started", "run_finished"]
    assert logged[-1].payload["status"] == "cancelled"
    assert len(api.model.received) == 1  # no further model call


# ------------------------------------------------------------- H5: bad message


@pytest.mark.parametrize("message", ["", "   ", "x" * 4001])
async def test_h5_empty_or_too_long_message_is_422(make_api: MakeApi, message: str) -> None:
    async with make_api(*STATUS_SCRIPT) as api:
        an = await api.login("E-001")
        response = await api.chat(an, await api.new_thread(an), message)

        assert response.status_code == 422
        assert api.model.received == []


async def test_h5_message_of_exactly_4000_chars_is_accepted(make_api: MakeApi) -> None:
    async with make_api("ok") as api:
        an = await api.login("E-001")
        response = await api.chat(an, await api.new_thread(an), "x" * 4000)

    assert response.status_code == 200


# ----------------------------------------------------------- personas / session


async def test_personas_list_the_seed_employees(make_api: MakeApi) -> None:
    async with make_api() as api:
        personas = (await api.client.get("/api/personas")).json()

    an = next(p for p in personas if p["id"] == "E-001")
    assert an == {
        "id": "E-001",
        "tenant_id": "acme",
        "name": "An Nguyen",
        "department": "engineering",
        "roles": ["employee"],
    }
    assert "email" not in json.dumps(personas)


async def test_session_for_an_unknown_persona_is_404(make_api: MakeApi) -> None:
    async with make_api() as api:
        response = await api.client.post("/api/session", json={"employee_id": "E-999"})

    assert response.status_code == 404
