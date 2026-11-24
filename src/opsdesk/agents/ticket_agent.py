"""The ticket agent (M03 §9).

It takes the model as a parameter instead of calling ``build_chat_model``: the CLI
passes a real model, tests and the demo pass a ``ScriptedChatModel``.

The prompt is a file next to this module so it can be reviewed and diffed.

``checkpointer`` (M04) gives the agent conversation memory: after every step LangGraph
saves the graph state (the message list) under ``config["configurable"]["thread_id"]``
and loads it again at the start of the next turn on that thread. ``None`` (the
default) = no memory, each call starts from an empty conversation (M03 behaviour).
The API passes one shared ``InMemorySaver``; M14a swaps it for a durable one.

Tests: ``tests/integration/test_ticket_agent.py``.
Docs: https://docs.langchain.com/oss/python/langchain/agents
"""

from pathlib import Path

from langchain.agents import create_agent  # pyright: ignore[reportUnknownVariableType]
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver

from opsdesk.agents.base import HarnessAgent
from opsdesk.tools.context import ToolContext
from opsdesk.tools.tickets import get_ticket, list_my_tickets

PROMPT_PATH = Path(__file__).parent / "prompts" / "ticket_agent.md"

# The agent's name: ``token`` events carry it (``agent``), and the UI labels answers
# with it. M05 adds more agents with their own names.
AGENT_NAME = "ticket"


def build_ticket_agent(
    model: BaseChatModel, *, checkpointer: BaseCheckpointSaver[str] | None = None
) -> HarnessAgent:
    return create_agent(
        model,
        tools=[get_ticket, list_my_tickets],
        system_prompt=PROMPT_PATH.read_text(encoding="utf-8"),
        # Declares the type of ``ainvoke(..., context=...)``; tools read it through
        # ToolRuntime. The model never sees it.
        context_schema=ToolContext,
        checkpointer=checkpointer,
        name=AGENT_NAME,
    )
