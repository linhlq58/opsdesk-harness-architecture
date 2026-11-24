"""``ToolRegistry`` (M05 §5.1): one registry, unique names, unknown names fail early."""

from pathlib import Path

import pytest

from opsdesk.tools.registry import ToolRegistry, ToolRegistryError, default_registry
from opsdesk.tools.tickets import get_ticket, list_my_tickets

REAL_STUBS = Path(__file__).resolve().parents[3] / "data" / "stubs"


def test_select_returns_the_named_tools_in_the_given_order() -> None:
    registry = ToolRegistry()
    registry.register(get_ticket)
    registry.register(list_my_tickets)

    tools = registry.select(["list_my_tickets", "get_ticket"])

    assert [t.name for t in tools] == ["list_my_tickets", "get_ticket"]
    assert registry.names() == {"get_ticket", "list_my_tickets"}


def test_duplicate_name_is_rejected_at_registration() -> None:
    registry = ToolRegistry()
    registry.register(get_ticket)

    with pytest.raises(ToolRegistryError, match="already registered"):
        registry.register(get_ticket, source="mcp:assets")


def test_unknown_name_is_rejected_and_named() -> None:
    registry = ToolRegistry()
    registry.register(get_ticket)

    with pytest.raises(ToolRegistryError, match="get_tickets"):
        registry.select(["get_ticket", "get_tickets"])


def test_select_nothing_is_allowed() -> None:
    assert ToolRegistry().select([]) == []  # the general specialist has no tools


def test_default_registry_has_every_tool_of_m05() -> None:
    assert default_registry(REAL_STUBS).names() == {
        "get_ticket",
        "list_my_tickets",
        "search_faq",
        "list_my_devices",
    }
