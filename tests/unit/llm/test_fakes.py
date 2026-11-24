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


# ------------------------------------------------------------------ streaming (M04)


def test_text_reply_streams_word_by_word() -> None:
    model = ScriptedChatModel.from_script("Ticket T-0002 is  in progress.")

    chunks = [chunk.text for chunk in model.stream("q")]

    assert chunks == ["Ticket ", "T-0002 ", "is  ", "in ", "progress."]
    assert "".join(chunks) == "Ticket T-0002 is  in progress."


async def test_streamed_tool_call_reassembles_into_the_scripted_call() -> None:
    model = ScriptedChatModel.from_script(
        tool_call("get_ticket", {"ticket_id": "T-0002"}, call_id="c1")
    )

    merged = None
    async for chunk in model.astream("q"):
        merged = chunk if merged is None else merged + chunk

    assert merged is not None
    assert merged.tool_calls == [
        {"name": "get_ticket", "args": {"ticket_id": "T-0002"}, "id": "c1", "type": "tool_call"}
    ]


async def test_streaming_also_fails_loudly_when_the_script_runs_out() -> None:
    model = ScriptedChatModel.from_script("only one")
    await model.ainvoke("q")

    with pytest.raises(ScriptExhausted):
        async for _ in model.astream("q"):
            pass


@pytest.mark.filterwarnings("ignore::langchain_core._api.beta_decorator.LangChainBetaWarning")
async def test_v3_event_stream_looks_like_a_real_model() -> None:
    # The shape stream_turn (M04 §6) consumes: tool-call-delta for the tool call,
    # text-delta per word for the answer, plus LangGraph's own tool events.
    @tool
    async def echo(text: str) -> str:
        """Echo the text."""
        return text.upper()

    model = ScriptedChatModel.from_script(tool_call("echo", {"text": "hi"}), "Done, all good.")
    agent = create_agent(model, tools=[echo])

    deltas: list[str] = []
    text = ""
    tool_events: list[str] = []
    stream = await agent.astream_events({"messages": [HumanMessage("q")]}, version="v3")
    async for event in stream:
        data = event["params"]["data"]
        if event["method"] == "messages":
            protocol_event, metadata = data
            assert metadata["langgraph_node"] == "model"
            if protocol_event["event"] == "content-block-delta":
                delta = protocol_event["delta"]
                deltas.append(delta["type"])
                if delta["type"] == "text-delta":
                    text += delta["text"]
        elif event["method"] == "tools":
            tool_events.append(data["event"])

    assert deltas == ["tool-call-delta", "text-delta", "text-delta", "text-delta"]
    assert text == "Done, all good."
    assert tool_events == ["tool-started", "tool-finished"]


async def test_records_what_each_call_received() -> None:
    model = ScriptedChatModel.from_script("a", "b")
    await model.ainvoke([HumanMessage("first")])
    async for _ in model.astream([HumanMessage("second")]):
        pass

    assert [[m.text for m in call] for call in model.received] == [["first"], ["second"]]
