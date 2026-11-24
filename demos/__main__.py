"""Milestone demo runner: ``uv run poe demo m03`` (fake model) or ``... m03 --live``.

Each milestone adds a ``demos/mNN.py`` exposing ``async def main(*, live: bool,
out: TextIO) -> int`` and registers it in ``DEMOS``. Fake-model runs are deterministic,
check their own expectations, and run in CI (``tests/demos/``). Live runs talk to the
real model; their output is printed, not checked.

``demos`` is an entry point outside the ``opsdesk`` package: it may import any layer,
and no layer may import it.
"""

import argparse
import asyncio
import importlib
import logging
import sys
from collections.abc import Sequence
from typing import TextIO, cast

DEMOS = {"m03": "demos.m03", "m04": "demos.m04"}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="poe demo", description="Run a milestone demo.")
    parser.add_argument("milestone", choices=sorted(DEMOS))
    parser.add_argument("--live", action="store_true", help="use the real model (needs .env)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    # Windows consoles default to a legacy code page; the demo prints ▶ ✓ and Vietnamese.
    out = cast(TextIO, sys.stdout)
    if hasattr(out, "reconfigure"):
        out.reconfigure(encoding="utf-8")  # pyright: ignore[reportAttributeAccessIssue]

    module = importlib.import_module(DEMOS[args.milestone])
    return asyncio.run(module.main(live=args.live, out=out))


if __name__ == "__main__":
    sys.exit(main())
