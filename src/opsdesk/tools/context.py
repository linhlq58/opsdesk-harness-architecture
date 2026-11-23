"""What a tool receives besides its arguments (M03 §5).

The fields are given by the milestone. The 🎯 part is *how it travels*, and you write
that in the wrapper, the agent and the turn runner:

* ``run_turn`` builds one ``ToolContext`` per turn and passes it as
  ``agent.ainvoke(..., context=tool_context)``;
* the agent declares ``context_schema=ToolContext``;
* each tool reads it from a ``runtime: ToolRuntime[ToolContext]`` parameter.

LangChain removes ``runtime`` from the schema the model sees, so the model can neither
read nor forge identity. Tools get their dependencies handed to them (dependency
injection) instead of importing global state, which is also what lets tests swap
SQLite for in-memory repositories.

Docs: https://docs.langchain.com/oss/python/langchain/tools (section "ToolRuntime")
"""

from dataclasses import dataclass

from opsdesk.core.clock import Clock
from opsdesk.domain.ports import Repositories
from opsdesk.observability.recorder import RunRecorder
from opsdesk.security.context import RequestContext


@dataclass(frozen=True, slots=True)
class ToolContext:
    request: RequestContext  # who, which turn, which thread
    repos: Repositories  # data access (in-memory in tests, SQLite in the CLI)
    recorder: RunRecorder  # events for this turn
    clock: Clock
