"""Interactive chat with the ticket agent and the real model.

    uv run poe seed                 # once: build var/opsdesk.db from data/seed
    uv run poe chat --as E-001      # chat as An (Acme)
    uv run poe chat --as G-001      # chat as Minh (Globex)

The employee is chosen on the command line, the way a server would take it from a
verified token (M04): the principal is built from the database record, so typing
"I am the IT manager" in the chat changes nothing.

Each line is one turn through ``run_turn`` (no memory between turns until M04).
Events go to ``var/events/<date>.jsonl``; each answer shows its ``request_id`` so you
can find that turn in the log.

An entry point, outside the layers contract: it may import any layer, nothing imports
it. Chat output goes to stdout (it *is* the program's output); diagnostics use
``logging``.
"""

import argparse
import asyncio
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from opsdesk.agents.ticket_agent import build_ticket_agent
from opsdesk.core.clock import SystemClock
from opsdesk.core.ids import new_request_id, new_thread_id
from opsdesk.core.settings import Settings
from opsdesk.core.workload import Workload
from opsdesk.domain.ids import EmployeeId, TenantId
from opsdesk.llm.factory import LlmConfigError, ModelRole, build_chat_model
from opsdesk.llm.settings import LlmSettings
from opsdesk.observability.bus import EventBus
from opsdesk.observability.sinks.jsonl import JsonlSink
from opsdesk.orchestration.turn import run_turn
from opsdesk.persistence.seed import DB_FILENAME, DEFAULT_SEED_DIR, SeedError, load_seed
from opsdesk.persistence.sqlite.repositories import open_sqlite_repositories
from opsdesk.security.context import RequestContext
from opsdesk.security.principal import principal_for

logger = logging.getLogger("opsdesk.cli")

_QUIT = {"exit", "quit", ":q"}


def _say(text: str) -> None:
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


def _tenant_of(employee_id: str, seed_dir: Path) -> str | None:
    """Find the tenant of a seed employee, so ``--as G-001`` works without ``--tenant``."""
    try:
        employees = load_seed(seed_dir).employees
    except (SeedError, OSError):
        return None
    tenants = {e.tenant_id for e in employees if e.id == employee_id}
    return tenants.pop() if len(tenants) == 1 else None


async def _chat(employee_id: str, tenant_id: str, db_path: Path, settings: Settings) -> int:
    model = build_chat_model(ModelRole.SPECIALIST, LlmSettings())
    agent = build_ticket_agent(model)
    bus = EventBus([JsonlSink(settings.var_dir / "events")])
    clock = SystemClock()

    async with open_sqlite_repositories(db_path) as repos:
        employee = await repos.employees.get(TenantId(tenant_id), EmployeeId(employee_id))
        if employee is None:
            logger.error("no employee %s in tenant %s", employee_id, tenant_id)
            return 1
        principal = principal_for(employee)
        thread_id = new_thread_id()  # one per session; memory arrives in M04
        _say(
            f"OpsDesk: chatting as {employee.full_name} ({employee.id}, {employee.tenant_id}). "
            "Type 'exit' to quit."
        )

        while True:
            try:
                line = (await asyncio.to_thread(input, "you> ")).strip()
            except (EOFError, KeyboardInterrupt):
                _say("")
                return 0
            if not line:
                continue
            if line.lower() in _QUIT:
                return 0

            ctx = RequestContext(
                principal=principal,
                request_id=new_request_id(),
                thread_id=thread_id,
                workload=Workload.CHAT,
            )
            try:
                result = await run_turn(
                    agent,
                    ctx=ctx,
                    message=line,
                    repos=repos,
                    bus=bus,
                    clock=clock,
                    entrypoint="cli",
                )
            except Exception:
                # Keep the session alive; the traceback is for you, the developer.
                logger.exception("turn failed (request %s)", ctx.request_id)
                continue
            _say(f"opsdesk> {result.answer}")
            _say(f"         [{ctx.request_id} · {result.status}]")


def main(argv: Sequence[str] | None = None) -> int:
    settings = Settings()
    parser = argparse.ArgumentParser(prog="poe chat", description="Chat with OpsDesk.")
    parser.add_argument("--as", dest="employee_id", required=True, help="seed employee id")
    parser.add_argument("--tenant", help="tenant id (default: looked up in data/seed)")
    parser.add_argument("--db", type=Path, default=settings.var_dir / DB_FILENAME)
    args = parser.parse_args(argv)
    employee_id: str = args.employee_id
    db_path: Path = args.db

    logging.basicConfig(level=settings.log_level, format="%(levelname)s %(name)s: %(message)s")
    if not db_path.exists():
        logger.error("%s not found: run `uv run poe seed` first", db_path)
        return 1
    tenant_id: str | None = args.tenant or _tenant_of(employee_id, DEFAULT_SEED_DIR)
    if tenant_id is None:
        logger.error("cannot tell the tenant of %s: pass --tenant", employee_id)
        return 1

    try:
        return asyncio.run(_chat(employee_id, tenant_id, db_path, settings))
    except LlmConfigError as exc:
        logger.error("%s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
