"""SQLite-only behaviour that the shared contract cannot express.

Durability across connections and schema versioning only make sense for a real file.
"""

from collections.abc import Callable
from pathlib import Path

import aiosqlite
import pytest

from opsdesk.domain.models import Ticket
from opsdesk.persistence.sqlite.repositories import (
    SchemaVersionError,
    open_sqlite_repositories,
)


async def test_data_survives_closing_and_reopening(
    tmp_path: Path, make_ticket: Callable[..., Ticket]
) -> None:
    db = tmp_path / "opsdesk.db"
    ticket = make_ticket()
    async with open_sqlite_repositories(db) as repos:
        await repos.tickets.save(ticket)
    async with open_sqlite_repositories(db) as repos:
        assert await repos.tickets.get(ticket.tenant_id, ticket.id) == ticket


async def test_opening_twice_applies_schema_idempotently(tmp_path: Path) -> None:
    db = tmp_path / "opsdesk.db"
    for _ in range(2):
        async with open_sqlite_repositories(db):
            pass
    async with (
        aiosqlite.connect(db) as conn,
        conn.execute("SELECT version FROM schema_version") as cur,
    ):
        assert list(await cur.fetchall()) == [(1,)]


async def test_creates_missing_parent_directory(tmp_path: Path) -> None:
    db = tmp_path / "nested" / "var" / "opsdesk.db"
    async with open_sqlite_repositories(db):
        pass
    assert db.exists()


async def test_wrong_schema_version_is_refused(tmp_path: Path) -> None:
    db = tmp_path / "opsdesk.db"
    async with open_sqlite_repositories(db):
        pass
    async with aiosqlite.connect(db) as conn:
        await conn.execute("UPDATE schema_version SET version = 99")
        await conn.commit()
    with pytest.raises(SchemaVersionError, match="99"):
        async with open_sqlite_repositories(db):
            pass


async def test_corrupt_row_fails_loudly_on_read(
    tmp_path: Path, make_ticket: Callable[..., Ticket]
) -> None:
    db = tmp_path / "opsdesk.db"
    ticket = make_ticket()
    async with open_sqlite_repositories(db) as repos:
        await repos.tickets.save(ticket)
    async with aiosqlite.connect(db) as conn:
        # Bypass the domain: a priority the model does not know.
        await conn.execute("UPDATE tickets SET priority = 'urgent!!'")
        await conn.commit()
    async with open_sqlite_repositories(db) as repos:
        with pytest.raises(ValueError, match="priority"):
            await repos.tickets.get(ticket.tenant_id, ticket.id)
