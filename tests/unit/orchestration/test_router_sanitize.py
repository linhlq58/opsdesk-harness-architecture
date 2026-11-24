"""``sanitize_routes`` cases C1-C7 (M05 §7.3, decision D3-A).

The model proposes, the code decides: whatever comes in, the result is 1 to 3
allowlisted agents with non-empty queries, and ``route_decided`` never carries a query.
"""

import pytest

from opsdesk.agents.specs import SPECIALISTS, spec_names
from opsdesk.orchestration.patterns.router import (
    Route,
    RouteDecision,
    SanitizedRoutes,
    sanitize_routes,
)

ALLOWED = spec_names(SPECIALISTS)
QUESTION = "the user's message"


def _decision(*pairs: tuple[str, str]) -> RouteDecision:
    return RouteDecision(routes=[Route(agent=a, query=q) for a, q in pairs])


def _run(decision: RouteDecision | None) -> SanitizedRoutes:
    return sanitize_routes(decision, ALLOWED, fallback_query=QUESTION)


def _agents(result: SanitizedRoutes) -> list[str]:
    return [r.agent for r in result.routes]


def test_c1_valid_routes_are_kept_in_order() -> None:
    result = _run(_decision(("ticket", "Status of T-0002?"), ("knowledge", "Reset VPN password?")))

    assert _agents(result) == ["ticket", "knowledge"]
    assert (result.fallback, result.reason, result.dropped) == (False, None, ())
    assert result.routes[0].query == "Status of T-0002?"


def test_c2_no_decision_falls_back_to_general_with_the_users_message() -> None:
    result = _run(None)

    assert _agents(result) == ["general"]
    assert (result.fallback, result.reason) == (True, "no_decision")
    assert result.routes[0].query == QUESTION


def test_c3_only_an_unknown_agent_falls_back() -> None:
    result = _run(_decision(("billing", "Refund my invoice")))

    assert _agents(result) == ["general"]
    assert (result.fallback, result.reason, result.dropped) == (True, "unknown_agent", ("billing",))


def test_c4_unknown_agent_is_dropped_the_rest_is_kept() -> None:
    result = _run(_decision(("ticket", "Status of T-0002?"), ("billing", "Refund")))

    assert _agents(result) == ["ticket"]
    assert (result.fallback, result.reason, result.dropped) == (False, None, ("billing",))


def test_c5_duplicates_keep_the_first() -> None:
    result = _run(_decision(("ticket", "Status of T-0002?"), ("ticket", "Status of T-0005?")))

    assert _agents(result) == ["ticket"]
    assert result.routes[0].query == "Status of T-0002?"
    assert result.dropped == ("ticket",)


def test_c6_more_than_three_routes_are_capped() -> None:
    names = ["ticket", "knowledge", "hardware", "security", "general"]
    result = _run(_decision(*[(n, f"q {n}") for n in names]))

    assert _agents(result) == ["ticket", "knowledge", "hardware"]
    assert (result.fallback, result.reason, result.dropped) == (
        False,
        "capped",
        ("security", "general"),
    )


@pytest.mark.parametrize("empty", ["", "   "])
def test_c7_a_route_with_an_empty_query_is_dropped(empty: str) -> None:
    result = _run(_decision(("ticket", empty), ("knowledge", "Reset VPN password?")))

    assert _agents(result) == ["knowledge"]
    assert result.dropped == ("ticket",)


def test_an_empty_route_list_falls_back() -> None:
    result = _run(RouteDecision(routes=[]))

    assert _agents(result) == ["general"]
    assert (result.fallback, result.reason) == (True, "no_valid_route")


def test_agent_names_are_matched_trimmed_and_case_insensitively() -> None:
    result = _run(_decision((" Ticket ", "Status of T-0002?")))

    assert _agents(result) == ["ticket"]


def test_the_event_payload_has_names_only_never_queries() -> None:
    payload = _run(_decision(("ticket", "Status of T-0002?"), ("billing", "x"))).event_payload()

    assert payload == {
        "agents": ["ticket"],
        "fallback": False,
        "reason": None,
        "dropped": ["billing"],
    }
    assert "Status of T-0002?" not in str(payload)
