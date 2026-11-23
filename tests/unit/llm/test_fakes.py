import pytest
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

from opsdesk.llm.fakes import ScriptedChatModel, ScriptExhausted, tool_call


async def test_replays_replies_in_order() -> None:
    model = ScriptedChatModel.from_script("first", AIMessage(content="second"))
    assert (await model.ainvoke("anything")).content == "first"
    assert (await model.ainvoke("anything")).content == "second"


async def test_exhausted_script_fails_loudly() -> None:
    model = ScriptedChatModel.from_script("only one")
    await model.ainvoke("q")
    with pytest.raises(ScriptExhausted):
        await model.ainvoke("q")


def test_tool_call_builds_a_tool_calling_reply() -> None:
    msg = tool_call("get_ticket", {"ticket_id": "T-0002"}, call_id="c1")
    assert msg.tool_calls == [
        {"name": "get_ticket", "args": {"ticket_id": "T-0002"}, "id": "c1", "type": "tool_call"}
    ]


def test_generated_call_ids_are_unique() -> None:
    a = tool_call("x", {})
    b = tool_call("x", {})
    assert a.tool_calls[0]["id"] != b.tool_calls[0]["id"]


async def test_drives_a_real_create_agent_loop() -> None:
    @tool
    async def echo(text: str) -> str:
        """Echo the text."""
        return text.upper()

    model = ScriptedChatModel.from_script(tool_call("echo", {"text": "hi"}), "done")
    out = await create_agent(model, tools=[echo]).ainvoke({"messages": [HumanMessage("q")]})

    tool_messages = [m for m in out["messages"] if isinstance(m, ToolMessage)]
    assert [m.content for m in tool_messages] == ["HI"]
    assert out["messages"][-1].content == "done"
