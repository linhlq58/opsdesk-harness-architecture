"""Shared pytest fixtures."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest


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
