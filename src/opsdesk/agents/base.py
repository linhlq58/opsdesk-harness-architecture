"""The types of what a turn runs, so callers (``run_turn``, demos) can name them.

* ``HarnessAgent``: one ``create_agent`` agent (the M03 ticket agent, M05 specialists).
* ``TurnGraph``: anything ``run_turn`` / ``stream_turn`` can run: a compiled LangGraph
  graph whose runtime context is a ``ToolContext`` and whose state has ``messages``
  (an agent, or the M05 router graph).

``create_agent(..., context_schema=ToolContext)`` returns a ``CompiledStateGraph``
whose runtime context is a ``ToolContext``; pyright then checks that
``agent.ainvoke(..., context=...)`` is given one.
"""

from typing import Any

from langchain.agents import AgentState
from langchain.agents.middleware.types import InputAgentState, OutputAgentState

# langgraph is a namespace package (no __init__.py): pyright strict misses its py.typed.
from langgraph.graph.state import CompiledStateGraph  # pyright: ignore[reportMissingTypeStubs]

from opsdesk.tools.context import ToolContext

type HarnessAgent = CompiledStateGraph[
    AgentState[Any], ToolContext, InputAgentState, OutputAgentState[Any]
]

type TurnGraph = CompiledStateGraph[Any, ToolContext, Any, Any]
