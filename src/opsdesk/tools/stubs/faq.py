"""``search_faq``: keyword search over a static FAQ (M05 §5.2). TEMPORARY until M10.

Matching is deliberately simple and deterministic: the query is split into lower-case
words; an entry scores one point per word found in its ``keywords``; entries with at
least one point are returned, best score first (file order breaks ties). M10 replaces
the inside of this tool with retrieval; the name, arguments and ``ToolResult`` stay.

Scope ``kb:read`` (every employee has it, M02).

Tests: ``tests/unit/tools/test_stub_faq.py``.
"""

import re
from collections.abc import Sequence
from pathlib import Path

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from opsdesk.core.result import ToolResult
from opsdesk.security.scopes import Scope
from opsdesk.tools.context import ToolContext
from opsdesk.tools.stubs._loader import DEFAULT_STUB_DIR, load_records
from opsdesk.tools.wrapper import harness_tool

TOOL_NAME = "search_faq"
DEFAULT_LIMIT = 3
MAX_LIMIT = 5

_WORD = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")  # "wi-fi" stays one word
_NO_MATCH = "No FAQ entry matches that question."


class FaqEntry(BaseModel):
    """One record of ``data/stubs/faq.yaml``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    title: str = Field(min_length=1)
    keywords: tuple[str, ...] = Field(min_length=1)
    answer: str = Field(min_length=1)


class FaqHit(BaseModel):
    """What the model sees: no ``keywords`` / ``category`` (matching internals)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    title: str
    answer: str


class SearchFaqArgs(BaseModel):
    query: str = Field(
        description="The question, in a few words, for example 'reset VPN password'."
    )
    # Clamped inside the tool, not with ge/le (same reason as M03 D4-B/D6-B).
    limit: int = Field(
        default=DEFAULT_LIMIT, description=f"How many entries to return. At most {MAX_LIMIT}."
    )


def load_faq(stub_dir: Path = DEFAULT_STUB_DIR) -> tuple[FaqEntry, ...]:
    return load_records(stub_dir / "faq.yaml", FaqEntry)


def search(entries: Sequence[FaqEntry], query: str, limit: int) -> list[FaqEntry]:
    """Best-matching entries (pure function: the tool below adds the harness)."""
    words = set(_WORD.findall(query.lower()))
    scored: list[tuple[int, int, FaqEntry]] = []
    for position, entry in enumerate(entries):
        keywords = {k.lower() for k in entry.keywords}
        score = len(words & keywords)
        if score > 0:
            scored.append((-score, position, entry))  # best score first, then file order
    scored.sort(key=lambda item: (item[0], item[1]))
    return [entry for _, _, entry in scored[:limit]]


def make_search_faq(entries: Sequence[FaqEntry]) -> BaseTool:
    """The ``search_faq`` tool over ``entries`` (loaded once at startup)."""
    frozen = tuple(entries)

    @harness_tool(
        name=TOOL_NAME,
        description=(
            "Search the IT help FAQ (VPN, passwords, Wi-Fi, printers, laptop policy, "
            "phishing, lost devices) and return matching entries with their answers. "
            "Use it for how-to and policy questions."
        ),
        args_schema=SearchFaqArgs,
        scope=Scope.KB_READ,
    )
    async def search_faq(ctx: ToolContext, args: SearchFaqArgs) -> ToolResult[list[FaqHit]]:
        limit = min(max(args.limit, 1), MAX_LIMIT)
        hits = search(frozen, args.query, limit)
        if not hits:
            return ToolResult.empty(_NO_MATCH)
        return ToolResult.ok([FaqHit(id=e.id, title=e.title, answer=e.answer) for e in hits])

    return search_faq
