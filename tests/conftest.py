"""Shared pytest fixtures."""

import os
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from opsdesk.domain.models import AccessRequest, Employee, SoftwareItem, Ticket
from opsdesk.domain.ports import Repositories
from support import (
    CallTool,
    MakeCaller,
    call_tool_via_agent,
    make_caller_for,
    seeded_repositories,
)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[pytest.MonkeyPatch]:
    """Isolate a test from the developer's real environment.

    Removes every ``OPSDESK_*`` variable and switches to an empty temporary
    directory, so a local ``.env`` file cannot leak into the test.
    """
    for key in list(os.environ):
        if key.startswith("OPSDESK_"):
            monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path)
    yield monkeypatch


# ----------------------------------------------------------- domain entity factories
# Each factory returns a valid entity and accepts keyword overrides, so a test only
# spells out the fields that matter for the case it checks.

T0 = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)

type Factory[T] = Callable[..., T]


@pytest.fixture
def make_employee() -> Factory[Employee]:
    def make(**overrides: Any) -> Employee:
        data: dict[str, Any] = {
            "id": "E-001",
            "tenant_id": "acme",
            "full_name": "An Nguyen",
            "email": "an@acme.test",
            "department": "engineering",
            "roles": ["employee"],
        }
        return Employee.model_validate(data | overrides)

    return make


@pytest.fixture
def make_ticket() -> Factory[Ticket]:
    def make(**overrides: Any) -> Ticket:
        data: dict[str, Any] = {
            "id": "T-0001",
            "tenant_id": "acme",
            "reporter_id": "E-001",
            "assignee_id": None,
            "title": "Laptop will not boot",
            "description": "Black screen after update",
            "category": "hardware",
            "priority": "high",
            "created_at": T0,
            "updated_at": T0,
        }
        return Ticket.model_validate(data | overrides)

    return make


@pytest.fixture
def make_software() -> Factory[SoftwareItem]:
    def make(**overrides: Any) -> SoftwareItem:
        data: dict[str, Any] = {"id": "SW-SLACK", "name": "Slack", "annual_cost": 1_200_000}
        return SoftwareItem.model_validate(data | overrides)

    return make


@pytest.fixture
def make_access_request() -> Factory[AccessRequest]:
    def make(**overrides: Any) -> AccessRequest:
        data: dict[str, Any] = {
            "id": "AR-001",
            "tenant_id": "acme",
            "requester_id": "E-001",
            "kind": "software_licence",
            "software_id": "SW-FIGMA",
            "justification": "Design reviews",
            "created_at": T0,
        }
        return AccessRequest.model_validate(data | overrides)

    return make


# ------------------------------------------------------------- harness fixtures (M03)
# Helpers live in ``tests/support.py`` so test modules can import their types.


@pytest.fixture
async def seed_repos() -> Repositories:
    """Fresh in-memory repositories loaded with the real seed (data/seed)."""
    return await seeded_repositories()


@pytest.fixture
def make_caller(seed_repos: Repositories) -> MakeCaller:
    """``await make_caller("E-001")``; Globex: ``await make_caller("G-001", "globex")``.

    ``repos=`` swaps the repositories the tools see (e.g. a spy in front of one).
    """
    return make_caller_for(seed_repos)


@pytest.fixture
def call_tool() -> CallTool:
    """Run one tool call through a real ``create_agent`` loop (see ``support``)."""
    return call_tool_via_agent
