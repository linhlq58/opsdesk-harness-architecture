"""Specialists as data (M05 §6).

An ``AgentSpec`` says everything that makes one specialist different from another:
its name, the one line the router reads to choose it, its prompt file and the names of
its tools. ``agents.factory.build_specialist`` turns a spec into a running agent.

Rules:

* **Adding a specialist = adding a spec** (and its prompt file). The router prompt is
  generated from the specs (``specialist_catalog``), and the allowlist of valid routes
  is ``spec_names(SPECIALISTS)``: the router can never invent an agent.
* **A specialist's tools are exactly** ``tool_names`` (least privilege per agent): the
  ticket specialist cannot see devices, the hardware specialist cannot see tickets.
  Names, not tool objects: the ``ToolRegistry`` resolves them at startup.
* ``knowledge`` and ``security`` share ``search_faq`` but have different prompts:
  same data, different job (how-to vs. first steps in an incident).

Tests: ``tests/unit/agents/test_specs.py``.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from opsdesk.llm.factory import ModelRole

PROMPTS_DIR = Path(__file__).parent / "prompts"


@dataclass(frozen=True, slots=True)
class AgentSpec:
    name: str  # "ticket", "knowledge", ...: the route name and the node label
    description: str  # one line the router reads to choose
    prompt_file: str  # a file in agents/prompts/
    tool_names: tuple[str, ...]
    role: ModelRole = ModelRole.SPECIALIST

    def prompt(self) -> str:
        return (PROMPTS_DIR / self.prompt_file).read_text(encoding="utf-8")


TICKET = AgentSpec(
    name="ticket",
    description="Status and list of the user's own IT tickets.",
    prompt_file="ticket_agent.md",  # the M03 ticket agent's prompt, unchanged
    tool_names=("get_ticket", "list_my_tickets"),
)
KNOWLEDGE = AgentSpec(
    name="knowledge",
    description=(
        "How-to questions and IT policies (VPN, passwords, Wi-Fi, printers, laptop policy)."
    ),
    prompt_file="knowledge.md",
    tool_names=("search_faq",),
)
HARDWARE = AgentSpec(
    name="hardware",
    description="The user's own devices: models, asset tags, warranty.",
    prompt_file="hardware.md",
    tool_names=("list_my_devices",),
)
SECURITY = AgentSpec(
    name="security",
    description=(
        "Suspected phishing, malware, lost or stolen devices, account compromise: first steps."
    ),
    prompt_file="security.md",
    tool_names=("search_faq",),
)
GENERAL = AgentSpec(
    name="general",
    description="Greetings, unclear or out-of-scope questions; asks for clarification.",
    prompt_file="general.md",
    tool_names=(),
)

SPECIALISTS: tuple[AgentSpec, ...] = (TICKET, KNOWLEDGE, HARDWARE, SECURITY, GENERAL)

# Where an invalid or empty router decision ends up (D3-A).
FALLBACK_AGENT = GENERAL.name


def spec_names(specs: Iterable[AgentSpec]) -> frozenset[str]:
    """The allowlist of valid routes."""
    return frozenset(s.name for s in specs)


def specialist_catalog(specs: Iterable[AgentSpec]) -> str:
    """The specialists as the router prompt lists them: ``- name: description``."""
    return "\n".join(f"- {s.name}: {s.description}" for s in specs)
