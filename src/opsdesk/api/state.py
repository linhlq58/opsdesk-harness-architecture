"""Process-wide objects the API needs, built once by the app's lifespan.

Routes never build these themselves: they ask for ``AppState`` through the
``app_state`` dependency, so tests and the demo can swap any piece (scripted model,
fixed clock) by passing it to ``create_app``.

Per-request objects (``RequestContext``, ``EventBus``, ``QueueSink``) are *not* here:
they are built for each chat request (M04 §8).
"""

import asyncio
from dataclasses import dataclass, field

from fastapi import Request
from langgraph.checkpoint.base import BaseCheckpointSaver

from opsdesk.agents.base import HarnessAgent
from opsdesk.api.auth import SessionTokens
from opsdesk.core.clock import Clock
from opsdesk.core.settings import Settings
from opsdesk.domain.models import Employee
from opsdesk.domain.ports import Repositories
from opsdesk.observability.sinks.jsonl import JsonlSink
from opsdesk.orchestration.threads import ThreadRegistry


@dataclass(frozen=True, slots=True)
class AppState:
    settings: Settings
    clock: Clock
    repos: Repositories
    personas: tuple[Employee, ...]  # seed employees offered by the persona picker
    tokens: SessionTokens
    checkpointer: BaseCheckpointSaver[str]  # conversation memory, shared by all threads
    agent: HarnessAgent
    threads: ThreadRegistry  # who owns which thread (D5)
    jsonl: JsonlSink  # shared by all requests (one lock per file); excludes token (D4)
    # Runs in flight. asyncio keeps only weak references to tasks: without this set a
    # run whose client disconnected could be garbage-collected before its finally ran.
    running: set[asyncio.Task[None]] = field(default_factory=set[asyncio.Task[None]])


def app_state(request: Request) -> AppState:
    """FastAPI dependency: the ``AppState`` built by the lifespan."""
    state: AppState = request.app.state.opsdesk
    return state
