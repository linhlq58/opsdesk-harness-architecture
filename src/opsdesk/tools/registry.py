"""``ToolRegistry``: the one place agents get their tools from (M05 §5.1).

* **One registry per app**, built at startup (``default_registry``). Specialists never
  import tools; their ``AgentSpec`` lists tool *names* and the factory asks the
  registry for exactly those (least privilege per agent).
* **Duplicate name → error at registration.** Two tools with one name would make the
  model's tool call ambiguous. M08 adds MCP tools with namespaced names; the collision
  check starts now.
* **Unknown name → error at selection.** Specialists are built at startup, so a typo
  in a spec stops the app from starting instead of surprising a user later.
* ``source`` records where a tool comes from (``"internal"`` now, an MCP server in
  M08). Nothing reads it yet; it is part of the contract so M08 does not change it.

Swapping a capability (M08: ``list_my_devices`` from MCP, M10: ``search_faq`` from
retrieval) means registering a different tool under the same name; no agent changes.

Tests: ``tests/unit/tools/test_registry.py``.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from langchain_core.tools import BaseTool

from opsdesk.tools.stubs._loader import DEFAULT_STUB_DIR
from opsdesk.tools.stubs.devices import load_devices, make_list_my_devices
from opsdesk.tools.stubs.faq import load_faq, make_search_faq
from opsdesk.tools.tickets import get_ticket, list_my_tickets


class ToolRegistryError(ValueError):
    """A duplicate or unknown tool name: a wiring bug, raised at startup."""


@dataclass(frozen=True, slots=True)
class _Entry:
    tool: BaseTool
    source: str


class ToolRegistry:
    def __init__(self) -> None:
        self._entries: dict[str, _Entry] = {}

    def register(self, tool: BaseTool, *, source: str = "internal") -> None:
        """Add ``tool``; a name that is already registered raises."""
        existing = self._entries.get(tool.name)
        if existing is not None:
            raise ToolRegistryError(
                f"tool {tool.name!r} is already registered (source {existing.source!r})"
            )
        self._entries[tool.name] = _Entry(tool, source)

    def select(self, names: Iterable[str]) -> list[BaseTool]:
        """The tools with these names, in the order given; any unknown name raises."""
        wanted = list(names)
        unknown = [n for n in wanted if n not in self._entries]
        if unknown:
            raise ToolRegistryError(f"unknown tool(s): {', '.join(sorted(unknown))}")
        return [self._entries[n].tool for n in wanted]

    def names(self) -> frozenset[str]:
        return frozenset(self._entries)


def default_registry(stub_dir: Path = DEFAULT_STUB_DIR) -> ToolRegistry:
    """Every OpsDesk tool, as the app runs it today (stub data loaded once, here)."""
    registry = ToolRegistry()
    registry.register(get_ticket)
    registry.register(list_my_tickets)
    registry.register(make_search_faq(load_faq(stub_dir)))  # M10: retrieval
    registry.register(make_list_my_devices(load_devices(stub_dir)))  # M08: MCP
    return registry
