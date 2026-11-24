"""App factory skeleton (M04 §4): lifespan wiring and static files."""

from pathlib import Path

import httpx
from fastapi import FastAPI

from opsdesk.api.app import create_app
from opsdesk.api.state import AppState
from opsdesk.core.clock import FixedClock
from opsdesk.core.settings import Settings
from opsdesk.llm.fakes import ScriptedChatModel


def _app(tmp_path: Path, *, web_dir: Path | None = None) -> FastAPI:
    return create_app(
        Settings(var_dir=tmp_path),
        model=ScriptedChatModel.from_script(),
        clock=FixedClock(),
        web_dir=web_dir or tmp_path / "no-web",
    )


async def test_lifespan_builds_the_app_state(tmp_path: Path) -> None:
    app = _app(tmp_path)

    async with app.router.lifespan_context(app):
        state = app.state.opsdesk
        assert isinstance(state, AppState)
        assert "E-001" in {p.id for p in state.personas}
        assert await state.repos.employees.get("acme", "E-001") is not None  # type: ignore[arg-type]
        assert state.agent.checkpointer is state.checkpointer  # memory wired into the agent


async def test_health(tmp_path: Path) -> None:
    app = _app(tmp_path)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://t") as client,
    ):
        response = await client.get("/api/health")

    assert response.json() == {"status": "ok"}


async def test_serves_the_web_ui_when_present(tmp_path: Path) -> None:
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<h1>OpsDesk</h1>", encoding="utf-8")
    app = _app(tmp_path, web_dir=web)

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://t") as client,
    ):
        page = await client.get("/")
        api = await client.get("/api/health")  # the "/" mount must not shadow the API

    assert "OpsDesk" in page.text
    assert api.json() == {"status": "ok"}
