"""``build_specialist``: an ``AgentSpec`` → a running agent (M05 §4).

Same shape as the M03 ticket agent (``create_agent`` + ``context_schema=ToolContext``),
with two differences:

* the tools come from the ``ToolRegistry`` by the names in the spec, so the agent gets
  exactly those (least privilege); an unknown name raises here, at startup;
* **no checkpointer, explicitly** (``checkpointer=False``): a specialist answers one
  self-contained sub-query (D2-A) and forgets it. The conversation lives in the router
  graph's state. ``None`` would not be enough: an agent invoked inside a graph node
  inherits the parent graph's checkpointer and would store its own state there.

The model is a parameter, like the ticket agent: the composition root builds it for
``spec.role``; tests pass a ``ScriptedChatModel``.

Tests: ``tests/unit/agents/test_specialist_factory.py``.
"""

from langchain.agents import create_agent  # pyright: ignore[reportUnknownVariableType]
from langchain_core.language_models import BaseChatModel

from opsdesk.agents.base import HarnessAgent
from opsdesk.agents.specs import AgentSpec
from opsdesk.tools.context import ToolContext
from opsdesk.tools.registry import ToolRegistry


def build_specialist(spec: AgentSpec, model: BaseChatModel, registry: ToolRegistry) -> HarnessAgent:
    return create_agent(
        model,
        tools=registry.select(spec.tool_names),
        system_prompt=spec.prompt(),
        context_schema=ToolContext,
        name=spec.name,
        checkpointer=False,  # never inherit the router graph's checkpointer (D2)
    )
