"""FastAPI app factory (M04).

``create_app()`` returns the app; its **lifespan** builds the process-wide objects
once at startup (``AppState``):

* repositories: in-memory, loaded from ``data/seed`` (the demo starts from a known
  state on every start; durable storage for the API arrives with M14a);
* the session token signer (``settings.session_secret``, or a random per-process key
  outside ``prod``: see ``core.settings``);
* the checkpointer (``InMemorySaver``: threads are lost on restart, like the thread
  registry) and the ticket agent built with it.

Tests and the demo pass a ``ScriptedChatModel`` and a ``FixedClock``; ``poe dev``
passes nothing and gets the real model (role ``specialist``) and the system clock.
A missing LLM configuration fails at startup, not on the first chat.

Routes live in ``api.routes``; ``web/`` is served as static files at ``/`` when it
exists. On shutdown, runs still in flight are cancelled (each records
``run_finished(cancelled)``).
"""

import asyncio
import secrets
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.memory import InMemorySaver

from opsdesk.agents.ticket_agent import build_ticket_agent
from opsdesk.api.auth import SessionTokens
from opsdesk.api.routes import chat, session, threads
from opsdesk.api.state import AppState
from opsdesk.core.clock import Clock, SystemClock
from opsdesk.core.settings import Settings
from opsdesk.llm.factory import ModelRole, build_chat_model
from opsdesk.llm.settings import LlmSettings
from opsdesk.observability.events import EventKind
from opsdesk.observability.sinks.jsonl import JsonlSink
from opsdesk.orchestration.threads import ThreadRegistry
from opsdesk.persistence.memory import in_memory_repositories
from opsdesk.persistence.seed import DEFAULT_SEED_DIR, load_seed, write_seed

WEB_DIR = Path(__file__).resolve().parents[3] / "web"


def create_app(
    settings: Settings | None = None,
    *,
    model: BaseChatModel | None = None,
    clock: Clock | None = None,
    seed_dir: Path = DEFAULT_SEED_DIR,
    web_dir: Path = WEB_DIR,
) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        seed = load_seed(seed_dir)
        repos = in_memory_repositories()
        await write_seed(repos, seed)

        secret = settings.session_secret
        checkpointer = InMemorySaver()
        state = AppState(
            settings=settings,
            clock=clock or SystemClock(),
            repos=repos,
            personas=tuple(seed.employees),
            tokens=SessionTokens(
                secret=secret.get_secret_value() if secret else secrets.token_urlsafe(32),
                ttl=timedelta(minutes=settings.session_ttl_minutes),
                clock=clock or SystemClock(),
            ),
            checkpointer=checkpointer,
            agent=build_ticket_agent(
                model or build_chat_model(ModelRole.SPECIALIST, LlmSettings()),
                checkpointer=checkpointer,
            ),
            threads=ThreadRegistry(),
            jsonl=JsonlSink(settings.var_dir / "events", exclude_kinds={EventKind.TOKEN}),
        )
        app.state.opsdesk = state
        yield
        for task in list(state.running):
            task.cancel()
        await asyncio.gather(*state.running, return_exceptions=True)

    app = FastAPI(title="OpsDesk", version="0.4.0", lifespan=lifespan)

    for module in (session, threads, chat):
        app.include_router(module.router)

    @app.get("/api/health")
    async def health() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {"status": "ok"}

    # Last: a mount at "/" would otherwise shadow the API routes.
    if web_dir.is_dir():
        app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")
    return app
