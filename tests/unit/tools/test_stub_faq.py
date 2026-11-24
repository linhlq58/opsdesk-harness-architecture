"""``search_faq`` stub (M05 §5.2): data file, matching, and the tool through the harness."""

from pathlib import Path

import pytest

from opsdesk.observability.events import EventKind
from opsdesk.tools.stubs._loader import StubDataError
from opsdesk.tools.stubs.faq import MAX_LIMIT, FaqEntry, load_faq, make_search_faq, search
from support import CallTool, MakeCaller

REAL_STUBS = Path(__file__).resolve().parents[3] / "data" / "stubs"


@pytest.fixture(scope="module")
def entries() -> tuple[FaqEntry, ...]:
    return load_faq(REAL_STUBS)


# ---------------------------------------------------------------------- data file


def test_real_faq_file_loads_with_unique_ids(entries: tuple[FaqEntry, ...]) -> None:
    ids = [e.id for e in entries]
    assert 6 <= len(ids) <= 8
    assert len(set(ids)) == len(ids)


def test_invalid_faq_file_lists_every_problem(tmp_path: Path) -> None:
    (tmp_path / "faq.yaml").write_text(
        "- id: X\n  title: no keywords, no answer\n  category: c\n", encoding="utf-8"
    )
    with pytest.raises(StubDataError) as exc:
        load_faq(tmp_path)
    assert {p.split(": ")[1] for p in exc.value.problems} == {"keywords", "answer"}


def test_missing_faq_file_is_a_startup_error(tmp_path: Path) -> None:
    with pytest.raises(StubDataError, match="file not found"):
        load_faq(tmp_path)


# ----------------------------------------------------------------------- matching


def test_best_match_first_and_case_insensitive(entries: tuple[FaqEntry, ...]) -> None:
    hits = search(entries, "How do I RESET my VPN Password?", limit=3)
    assert hits[0].id == "FAQ-VPN-01"  # vpn + password + reset


def test_phishing_question_finds_first_steps(entries: tuple[FaqEntry, ...]) -> None:
    hits = search(entries, "I just clicked a link in a suspicious email", limit=3)
    assert hits[0].id == "FAQ-SEC-01"


def test_no_matching_word_returns_nothing(entries: tuple[FaqEntry, ...]) -> None:
    assert search(entries, "what is the canteen menu", limit=3) == []


# ------------------------------------------------------- the tool, through the harness


async def test_tool_returns_hits_without_matching_internals(
    entries: tuple[FaqEntry, ...], make_caller: MakeCaller, call_tool: CallTool
) -> None:
    an = await make_caller("E-001")
    result = await call_tool(
        make_search_faq(entries), {"query": "reset vpn password"}, an.tool_context
    )

    assert result["status"] == "ok"
    assert result["data"][0]["id"] == "FAQ-VPN-01"
    assert set(result["data"][0]) == {"id", "title", "answer"}
    assert [e.payload["status"] for e in an.events(EventKind.TOOL_FINISHED)] == ["ok"]


async def test_tool_says_empty_when_nothing_matches(
    entries: tuple[FaqEntry, ...], make_caller: MakeCaller, call_tool: CallTool
) -> None:
    an = await make_caller("E-001")
    result = await call_tool(make_search_faq(entries), {"query": "canteen menu"}, an.tool_context)

    assert result["status"] == "empty"
    assert result["data"] is None


@pytest.mark.parametrize(("asked", "returned"), [(50, MAX_LIMIT), (0, 1), (-3, 1)])
async def test_limit_is_clamped(
    asked: int,
    returned: int,
    entries: tuple[FaqEntry, ...],
    make_caller: MakeCaller,
    call_tool: CallTool,
) -> None:
    an = await make_caller("E-001")
    # "laptop" alone matches several entries, so the clamp is what limits the count.
    query = "laptop phone vpn password wifi printer lost phishing"
    result = await call_tool(
        make_search_faq(entries), {"query": query, "limit": asked}, an.tool_context
    )
    assert len(result["data"]) == returned
