"""``build_specialist`` (M05 §4): a spec becomes an agent with exactly its tools."""

import json
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import HumanMessage, ToolMessage

from opsdesk.agents.factory import build_specialist
from opsdesk.agents.specs import GENERAL, HARDWARE, TICKET, AgentSpec
from opsdesk.llm.fakes import ScriptedChatModel, tool_call
from opsdesk.tools.registry import ToolRegistryError, default_registry
from support import MakeCaller

REAL_STUBS = Path(__file__).resolve().parents[3] / "data" / "stubs"


async def test_hardware_specialist_runs_its_tool_through_the_harness(
    make_caller: MakeCaller,
) -> None:
    an = await make_caller("E-001")
    model = ScriptedChatModel.from_script(tool_call("list_my_devices", {}), "You have 2 devices.")
    agent = build_specialist(HARDWARE, model, default_registry(REAL_STUBS))

    out = await agent.ainvoke(
        {"messages": [HumanMessage("Is my laptop under warranty?")]}, context=an.tool_context
    )

    tool_messages = [m for m in out["messages"] if isinstance(m, ToolMessage)]
    assert json.loads(str(tool_messages[0].content))["status"] == "ok"
    assert out["messages"][-1].text == "You have 2 devices."
    assert agent.name == "hardware"


@pytest.mark.parametrize(
    ("spec", "expected"),
    [(TICKET, {"get_ticket", "list_my_tickets"}), (HARDWARE, {"list_my_devices"})],
    ids=lambda v: v.name if isinstance(v, AgentSpec) else "",
)
def test_specialist_can_run_only_its_own_tools(spec: AgentSpec, expected: set[str]) -> None:
    agent = build_specialist(spec, ScriptedChatModel.from_script("x"), default_registry(REAL_STUBS))
    # The agent's tool node is the only place a tool call can be executed.
    tool_node: Any = agent.nodes["tools"].bound
    assert set(tool_node.tools_by_name) == expected


def test_general_has_no_tool_node_at_all() -> None:
    agent = build_specialist(
        GENERAL, ScriptedChatModel.from_script("x"), default_registry(REAL_STUBS)
    )
    assert "tools" not in agent.nodes


def test_a_spec_naming_an_unknown_tool_fails_at_build_time() -> None:
    broken = AgentSpec(
        name="broken", description="d", prompt_file="general.md", tool_names=("get_tickets",)
    )
    with pytest.raises(ToolRegistryError, match="get_tickets"):
        build_specialist(broken, ScriptedChatModel.from_script("x"), default_registry(REAL_STUBS))
