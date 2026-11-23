"""The ticket agent (M03 §9).

It takes the model as a parameter instead of calling ``build_chat_model``: the CLI
passes a real model, tests and the demo pass a ``ScriptedChatModel``.

The prompt is a file next to this module so it can be reviewed and diffed.

Tests: ``tests/integration/test_ticket_agent.py``.
Docs: https://docs.langchain.com/oss/python/langchain/agents
"""

from pathlib import Path

from langchain.agents import create_agent  # pyright: ignore[reportUnknownVariableType]
from langchain_core.language_models import BaseChatModel

from opsdesk.agents.base import HarnessAgent
from opsdesk.tools.context import ToolContext
from opsdesk.tools.tickets import get_ticket, list_my_tickets

PROMPT_PATH = Path(__file__).parent / "prompts" / "ticket_agent.md"


def build_ticket_agent(model: BaseChatModel) -> HarnessAgent:
    return create_agent(
        model,
        tools=[get_ticket, list_my_tickets],
        system_prompt=PROMPT_PATH.read_text(encoding="utf-8"),
        # Declares the type of ``ainvoke(..., context=...)``; tools read it through
        # ToolRuntime. The model never sees it.
        context_schema=ToolContext,
    )
