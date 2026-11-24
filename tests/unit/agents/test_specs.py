"""Specialist specs (M05 §6): allowlist, least privilege, prompts exist."""

from pathlib import Path

import pytest

from opsdesk.agents.specs import (
    FALLBACK_AGENT,
    SPECIALISTS,
    AgentSpec,
    spec_names,
    specialist_catalog,
)
from opsdesk.tools.registry import default_registry

REAL_STUBS = Path(__file__).resolve().parents[3] / "data" / "stubs"
TOOLS = {s.name: set(s.tool_names) for s in SPECIALISTS}


def test_the_five_specialists_are_the_route_allowlist() -> None:
    assert spec_names(SPECIALISTS) == {"ticket", "knowledge", "hardware", "security", "general"}
    assert len(SPECIALISTS) == len(spec_names(SPECIALISTS))  # names are unique
    assert FALLBACK_AGENT in spec_names(SPECIALISTS)


def test_each_specialist_has_exactly_its_tools() -> None:
    assert {
        "ticket": {"get_ticket", "list_my_tickets"},
        "knowledge": {"search_faq"},
        "hardware": {"list_my_devices"},
        "security": {"search_faq"},
        "general": set(),
    } == TOOLS


def test_ticket_and_device_data_never_share_a_specialist() -> None:
    for tools in TOOLS.values():
        assert not ({"get_ticket", "list_my_tickets"} & tools and "list_my_devices" in tools)


def test_every_tool_name_exists_in_the_registry() -> None:
    names = default_registry(REAL_STUBS).names()
    for spec in SPECIALISTS:
        assert set(spec.tool_names) <= names, spec.name


@pytest.mark.parametrize("spec", SPECIALISTS, ids=lambda s: s.name)
def test_every_prompt_file_exists_and_is_not_empty(spec: AgentSpec) -> None:
    assert spec.prompt().strip()


def test_router_catalog_is_generated_from_the_specs() -> None:
    catalog = specialist_catalog(SPECIALISTS)
    assert catalog.splitlines()[0].startswith("- ticket: ")
    assert len(catalog.splitlines()) == len(SPECIALISTS)
