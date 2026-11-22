"""Load seed YAML -> validate -> write through the repository ports.

Three stages, and nothing is written unless the first two pass:

1. **Parse + validate each record** with the domain models. Every problem in every
   file is collected, so one run reports all mistakes, not just the first.
2. **Check references across files**: duplicate ids, unknown tenants / employees /
   software, references that cross tenants. Models cannot see other records, so
   these checks live here.
3. **Write** through ``Repositories`` (any adapter).

``seed_database`` builds a fresh SQLite file next to the target and swaps it in with
``os.replace`` (atomic on Windows and Linux). Running it twice therefore gives the
same database, records removed from YAML disappear, and a failed run leaves the old
database untouched.

Run with ``uv run poe seed`` (or ``python -m opsdesk.persistence.seed --help``).
"""

import argparse
import asyncio
import logging
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from opsdesk.core.settings import Settings
from opsdesk.domain.models import AccessRequest, Employee, SoftwareItem, Tenant, Ticket
from opsdesk.domain.ports import Repositories
from opsdesk.persistence.sqlite.repositories import open_sqlite_repositories

logger = logging.getLogger(__name__)

DEFAULT_SEED_DIR = Path("data") / "seed"
DB_FILENAME = "opsdesk.db"


class SeedError(Exception):
    """The seed files are invalid. ``problems`` lists every issue found."""

    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = list(problems)
        super().__init__(f"{len(problems)} seed problem(s):\n  - " + "\n  - ".join(problems))


@dataclass(frozen=True, slots=True)
class SeedData:
    tenants: tuple[Tenant, ...]
    software: tuple[SoftwareItem, ...]
    employees: tuple[Employee, ...]
    tickets: tuple[Ticket, ...]
    access_requests: tuple[AccessRequest, ...]


# ------------------------------------------------------------- 1. parse + validate


def _load_file[M: BaseModel](
    seed_dir: Path, name: str, model: type[M], problems: list[str]
) -> tuple[M, ...]:
    path = seed_dir / f"{name}.yaml"
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        problems.append(f"{path.name}: file not found")
        return ()
    except yaml.YAMLError as exc:
        problems.append(f"{path.name}: invalid YAML: {exc}")
        return ()

    if raw is None:
        return ()  # an empty file is an empty list
    if not isinstance(raw, list):
        problems.append(f"{path.name}: expected a list of records")
        return ()

    items: list[M] = []
    for index, record in enumerate(raw):  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
        label = f"{path.name}[{index}]"
        if isinstance(record, dict) and "id" in record:
            label += f" (id={record['id']})"
        try:
            items.append(model.model_validate(record))
        except ValidationError as exc:
            for err in exc.errors():
                field = ".".join(str(part) for part in err["loc"]) or "<record>"
                problems.append(f"{label}: {field}: {err['msg']}")
    return tuple(items)


# ---------------------------------------------------------------- 2. references


def _duplicates(name: str, keys: Iterable[object], problems: list[str]) -> None:
    for key, count in Counter(keys).items():
        if count > 1:
            problems.append(f"{name}: duplicate id {key}")


def _check_references(data: SeedData, problems: list[str]) -> None:
    _duplicates("tenants.yaml", (t.id for t in data.tenants), problems)
    _duplicates("software.yaml", (s.id for s in data.software), problems)
    _duplicates("employees.yaml", ((e.tenant_id, e.id) for e in data.employees), problems)
    _duplicates("tickets.yaml", ((t.tenant_id, t.id) for t in data.tickets), problems)
    _duplicates(
        "access_requests.yaml", ((r.tenant_id, r.id) for r in data.access_requests), problems
    )

    tenants = {t.id for t in data.tenants}
    software = {s.id for s in data.software}
    employees = {(e.tenant_id, e.id) for e in data.employees}

    def need_employee(where: str, tenant_id: str, employee_id: str | None, role: str) -> None:
        # Looking up (tenant, id) catches both unknown ids and cross-tenant references.
        if employee_id is not None and (tenant_id, employee_id) not in employees:
            problems.append(f"{where}: {role} {employee_id} is not an employee of {tenant_id}")

    for e in data.employees:
        where = f"employees.yaml (id={e.id})"
        if e.tenant_id not in tenants:
            problems.append(f"{where}: unknown tenant {e.tenant_id}")
        for sw in sorted(e.owned_software - software):
            problems.append(f"{where}: owns unknown software {sw}")

    for t in data.tickets:
        where = f"tickets.yaml (id={t.id})"
        if t.tenant_id not in tenants:
            problems.append(f"{where}: unknown tenant {t.tenant_id}")
        need_employee(where, t.tenant_id, t.reporter_id, "reporter")
        need_employee(where, t.tenant_id, t.assignee_id, "assignee")

    for r in data.access_requests:
        where = f"access_requests.yaml (id={r.id})"
        if r.tenant_id not in tenants:
            problems.append(f"{where}: unknown tenant {r.tenant_id}")
        need_employee(where, r.tenant_id, r.requester_id, "requester")
        need_employee(where, r.tenant_id, r.decided_by, "decided_by")
        if r.software_id is not None and r.software_id not in software:
            problems.append(f"{where}: unknown software {r.software_id}")


def load_seed(seed_dir: Path) -> SeedData:
    """Read and fully validate the seed directory. Raises ``SeedError`` listing all issues."""
    problems: list[str] = []
    data = SeedData(
        tenants=_load_file(seed_dir, "tenants", Tenant, problems),
        software=_load_file(seed_dir, "software", SoftwareItem, problems),
        employees=_load_file(seed_dir, "employees", Employee, problems),
        tickets=_load_file(seed_dir, "tickets", Ticket, problems),
        access_requests=_load_file(seed_dir, "access_requests", AccessRequest, problems),
    )
    # Reference checks on half-loaded data would report noise, so only run them on
    # records that parsed. They still run when some records failed, to report more.
    _check_references(data, problems)
    if problems:
        raise SeedError(problems)
    return data


# ------------------------------------------------------------------------ 3. write


async def write_seed(repos: Repositories, data: SeedData) -> None:
    """Save every record through the ports. Works with any adapter."""
    for tenant in data.tenants:
        await repos.tenants.save(tenant)
    for item in data.software:
        await repos.software.save(item)
    for employee in data.employees:
        await repos.employees.save(employee)
    for ticket in data.tickets:
        await repos.tickets.save(ticket)
    for request in data.access_requests:
        await repos.access_requests.save(request)


async def seed_database(seed_dir: Path, db_path: Path) -> SeedData:
    """Rebuild ``db_path`` from ``seed_dir``, atomically. Returns what was loaded."""
    data = load_seed(seed_dir)  # validate everything before touching the disk

    tmp_path = db_path.with_name(db_path.name + ".tmp")
    tmp_path.unlink(missing_ok=True)  # leftover from an interrupted run
    try:
        async with open_sqlite_repositories(tmp_path) as repos:
            await write_seed(repos, data)
        # The connection is closed here, so Windows allows the rename. Path.replace is
        # os.replace: atomic, readers see either the old database or the new one.
        tmp_path.replace(db_path)
    finally:
        tmp_path.unlink(missing_ok=True)
    return data


# --------------------------------------------------------------------------- CLI


def _summary(data: SeedData) -> str:
    return ", ".join(f"{len(getattr(data, f.name))} {f.name}" for f in fields(data))


def main(argv: Sequence[str] | None = None) -> int:
    settings = Settings()
    parser = argparse.ArgumentParser(
        description="Rebuild the OpsDesk SQLite database from seed YAML."
    )
    parser.add_argument("--seed-dir", type=Path, default=DEFAULT_SEED_DIR)
    parser.add_argument("--db", type=Path, default=settings.var_dir / DB_FILENAME)
    args = parser.parse_args(argv)
    seed_dir: Path = args.seed_dir
    db_path: Path = args.db

    logging.basicConfig(level=settings.log_level, format="%(levelname)s %(message)s")
    try:
        data = asyncio.run(seed_database(seed_dir, db_path))
    except SeedError as exc:
        logger.error("%s", exc)
        return 1
    logger.info("Seeded %s from %s: %s", db_path, seed_dir, _summary(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
