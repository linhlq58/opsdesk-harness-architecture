"""Router pattern (M05 §7): classify → parallel specialists → answer or synthesize.

One turn through the graph::

    START → start_turn   reset per-turn state (R1: Overwrite), keep the conversation
          → classify     router model proposes routes; sanitize_routes decides (D3);
                         emit route_decided
          → Send x N     one "specialist" branch per route, in parallel (D1)
          → specialist   the spec's agent answers route.query only (D2), with only its
                         tools; its tool events carry namespace ("router", <spec>)
          → finalize     1 result → that answer is final (D4); N → synthesize
          → synthesize   merge the answers (synthesizer model)
          → END          the answer is appended to ``messages`` for the next turn

Every node we own emits ``node_started`` / ``node_finished`` through the recorder (D6):
``classify``, ``specialist:<name>``, ``synthesize``. A crash in any branch fails the
whole turn (D7): nothing here catches exceptions.

**Which tokens reach the chat (D5).** A model call whose text must *not* stream is made
with the tag ``INTERNAL_TAG``: the router call (its plain-text reply in case C2 must not
leak) and the specialists of a multi-route turn. The single specialist of a one-route
turn and the synthesizer are untagged. ``orchestration.streaming`` drops tagged
text-deltas. The graph knows which call is final; the adapter only applies the rule.

**State holds plain data only** (TypedDicts and strings). Pydantic models in a
checkpoint trigger langgraph-checkpoint's "unregistered type" warning, which will become
an error; ``Route`` is the model's schema and is converted at the boundary.

Tests: ``tests/unit/orchestration/test_router_sanitize.py`` (C1-C7),
``tests/integration/test_router_graph.py`` (graph, X1-X3).
Docs: https://docs.langchain.com/oss/python/langgraph/graph-api (Send, Overwrite)
"""

import operator
import time
from collections.abc import AsyncGenerator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver

# langgraph is a namespace package (no __init__.py): pyright strict misses its py.typed.
from langgraph.graph import END, START, StateGraph  # pyright: ignore[reportMissingTypeStubs]
from langgraph.graph.message import add_messages  # pyright: ignore[reportMissingTypeStubs]
from langgraph.graph.state import CompiledStateGraph  # pyright: ignore[reportMissingTypeStubs]
from langgraph.runtime import Runtime
from langgraph.types import Overwrite, Send
from pydantic import BaseModel, Field, JsonValue

from opsdesk.agents.base import HarnessAgent
from opsdesk.agents.factory import build_specialist
from opsdesk.agents.specs import (
    FALLBACK_AGENT,
    PROMPTS_DIR,
    AgentSpec,
    spec_names,
    specialist_catalog,
)
from opsdesk.observability.events import EventKind
from opsdesk.observability.recorder import RunRecorder
from opsdesk.tools.context import ToolContext
from opsdesk.tools.registry import ToolRegistry

GRAPH_NAME = "router"
INTERNAL_TAG = "opsdesk:internal"  # D5: the text of a call with this tag never streams

DEFAULT_MAX_ROUTES = 3  # D3: tunable, moves to config/policy.yaml in M14a

# ------------------------------------------------------------- what the model fills
# These two models are the router's tool schema: their docstrings and field
# descriptions are what the model reads.


class Route(BaseModel):
    """One specialist to run, with the question it must answer."""

    agent: str = Field(description="The specialist's name, exactly as listed.")
    query: str = Field(
        description=(
            "A self-contained question for that specialist, in the user's language; "
            "it does not see the conversation."
        )
    )


class RouteDecision(BaseModel):
    """The specialists needed for the user's latest message."""

    routes: list[Route] = Field(description="One entry per specialist, most important first.")


# ------------------------------------------------------------- what the code decides


@dataclass(frozen=True, slots=True)
class SanitizedRoutes:
    routes: tuple[Route, ...]  # never empty
    fallback: bool
    reason: str | None  # set only on fallback or when capped (D3)
    dropped: tuple[str, ...]  # agent names removed, for the log only

    def event_payload(self) -> dict[str, JsonValue]:
        """The ``route_decided`` payload: names only, never the queries."""
        return {
            "agents": [r.agent for r in self.routes],
            "fallback": self.fallback,
            "reason": self.reason,
            "dropped": list(self.dropped),
        }


def sanitize_routes(
    decision: RouteDecision | None,
    allowed: frozenset[str],
    *,
    max_routes: int = DEFAULT_MAX_ROUTES,
    fallback_query: str = "",
) -> SanitizedRoutes:
    """The model's proposal → a valid route set (D3-A, cases C1-C7).

    Steps, in order: no decision → fallback; drop unknown agents, empty queries and
    duplicates (first one kept); cap at ``max_routes``; nothing left → fallback.
    Agent names are compared trimmed and lower-cased ("Ticket " is ``ticket``): a
    formatting slip is not a reason to lose a valid route.

    ``fallback_query`` is what the fallback agent receives (the caller passes the
    user's message: ``general`` asks for clarification about it).
    """
    if decision is None:  # C2: no tool call (``parsed`` is None)
        return _fallback("no_decision", (), fallback_query)

    kept: list[Route] = []
    dropped: list[str] = []
    seen: set[str] = set()
    unknown = False
    for route in decision.routes:
        name = route.agent.strip().lower()
        query = route.query.strip()
        if name not in allowed:  # C3, C4: the model invented an agent
            unknown = True
            dropped.append(route.agent)
        elif not query or name in seen:
            # C7: an empty query has nothing to answer. C5: a duplicate would cost a
            # second call and repeat the answer; the first one is kept.
            dropped.append(name)
        else:
            seen.add(name)
            kept.append(Route(agent=name, query=query))

    if not kept:  # C3 (and an empty list): nothing valid left
        return _fallback("unknown_agent" if unknown else "no_valid_route", dropped, fallback_query)

    reason: str | None = None
    if len(kept) > max_routes:  # C6: bounded cost per turn
        dropped += [r.agent for r in kept[max_routes:]]
        kept = kept[:max_routes]
        reason = "capped"

    return SanitizedRoutes(
        routes=tuple(kept), fallback=False, reason=reason, dropped=tuple(dropped)
    )


def _fallback(reason: str, dropped: Sequence[str], query: str) -> SanitizedRoutes:
    return SanitizedRoutes(
        routes=(Route(agent=FALLBACK_AGENT, query=query),),
        fallback=True,
        reason=reason,
        dropped=tuple(dropped),
    )


# ------------------------------------------------------------------- state (§7.1)


class RouteItem(TypedDict):
    agent: str
    query: str


class SpecialistResult(TypedDict):
    agent: str
    answer: str


class RouterState(TypedDict):
    # Conversation: kept across turns by the checkpointer.
    messages: Annotated[list[AnyMessage], add_messages]
    # This turn only: reset by start_turn.
    routes: list[RouteItem]
    # Append reducer: parallel branches add their result without overwriting each other.
    # Which is exactly why start_turn must clear it explicitly (R1, break-it B1).
    results: Annotated[list[SpecialistResult], operator.add]
    answer: str


class SpecialistTask(TypedDict):
    """What one ``Send`` gives one specialist branch: its route and nothing else (D2)."""

    route: RouteItem
    final: bool  # True when this is the only route: its answer is final (D4, D5)


@dataclass(frozen=True, slots=True)
class RouterModels:
    """The models the graph calls, one per job. The composition root builds them from
    roles (``build_chat_model``); tests and the demo pass a scripted model per job, so
    parallel specialists never share one script."""

    router: BaseChatModel
    synthesizer: BaseChatModel
    specialists: Mapping[str, BaseChatModel]  # spec name → model


type RouterGraph = CompiledStateGraph[RouterState, ToolContext, RouterState, RouterState]


# ------------------------------------------------------------------- the graph


def build_router_graph(
    models: RouterModels,
    registry: ToolRegistry,
    specs: Sequence[AgentSpec],
    *,
    checkpointer: BaseCheckpointSaver[str] | None = None,
    max_routes: int = DEFAULT_MAX_ROUTES,
) -> RouterGraph:
    """Build the router graph. Every specialist is built here, at startup: an unknown
    tool name in a spec raises now (``ToolRegistry.select``)."""
    allowed = spec_names(specs)
    agents: dict[str, HarnessAgent] = {
        spec.name: build_specialist(spec, models.specialists[spec.name], registry) for spec in specs
    }
    router_prompt = (
        (PROMPTS_DIR / "router.md")
        .read_text(encoding="utf-8")
        .format(specialists=specialist_catalog(specs), max_routes=max_routes)
    )
    synthesizer_prompt = (PROMPTS_DIR / "synthesizer.md").read_text(encoding="utf-8")
    # include_raw: a reply without a tool call gives parsed=None instead of raising (C2).
    router_model = models.router.with_structured_output(
        RouteDecision, method="function_calling", include_raw=True
    )
    internal: RunnableConfig = {"tags": [INTERNAL_TAG]}

    async def start_turn(state: RouterState) -> dict[str, Any]:
        # R1: Overwrite bypasses the append reducer; returning [] would keep last turn's
        # results (old + [] == old). messages is not touched: conversation state.
        return {"routes": [], "results": Overwrite([]), "answer": ""}

    async def classify(state: RouterState, runtime: Runtime[ToolContext]) -> dict[str, Any]:
        recorder = runtime.context.recorder
        async with _node_events(recorder, "classify"):
            # The router sees the whole conversation, so it can resolve "it" (D2).
            reply: Any = await router_model.ainvoke(
                [SystemMessage(router_prompt), *state["messages"]], internal
            )
            parsed: object = reply["parsed"]
            decision = parsed if isinstance(parsed, RouteDecision) else None
            # The model proposed; this line decides (D3).
            sanitized = sanitize_routes(
                decision,
                allowed,
                max_routes=max_routes,
                fallback_query=_last_user_text(state["messages"]),
            )
            await recorder.emit(EventKind.ROUTE_DECIDED, sanitized.event_payload())
        return {"routes": [RouteItem(agent=r.agent, query=r.query) for r in sanitized.routes]}

    def fan_out(state: RouterState) -> list[Send]:
        # D1: one parallel branch per route; each gets only its own route (D2).
        final = len(state["routes"]) == 1
        return [
            Send("specialist", SpecialistTask(route=route, final=final))
            for route in state["routes"]
        ]

    # The parameter must be named ``state`` (LangGraph's node signature), but what a
    # Send delivers is the SpecialistTask, not the RouterState.
    async def specialist(state: SpecialistTask, runtime: Runtime[ToolContext]) -> dict[str, Any]:
        task = state
        name = task["route"]["agent"]
        ctx = runtime.context
        async with _node_events(ctx.recorder, f"specialist:{name}"):
            # X3: the branch's tool events carry ("router", <spec>) through a child
            # recorder (same seq counter). LangGraph's own namespace for this branch is
            # a task id, not the spec name.
            branch_ctx = replace(ctx, recorder=ctx.recorder.child(GRAPH_NAME, name))
            out = await agents[name].ainvoke(  # pyright: ignore[reportUnknownMemberType]
                {"messages": [HumanMessage(task["route"]["query"])]},  # D2: sub-query only
                {} if task["final"] else internal,  # D5: only a final answer streams
                context=branch_ctx,
            )
        messages: list[AnyMessage] = out["messages"]
        return {"results": [SpecialistResult(agent=name, answer=messages[-1].text)]}

    async def finalize(state: RouterState) -> dict[str, Any]:
        # Runs once, after every branch is done (superstep barrier). D4: one result is
        # the final answer; several go to synthesize.
        if len(state["results"]) == 1:
            return _answer(state["results"][0]["answer"])
        return {}

    def after_finalize(state: RouterState) -> Literal["synthesize", "__end__"]:
        return "synthesize" if len(state["results"]) > 1 else "__end__"

    async def synthesize(state: RouterState, runtime: Runtime[ToolContext]) -> dict[str, Any]:
        async with _node_events(runtime.context.recorder, "synthesize"):
            # Parallel branches append in completion order: put the answers back in the
            # order the router chose (the order of the user's questions).
            order = {r["agent"]: i for i, r in enumerate(state["routes"])}
            results = sorted(state["results"], key=lambda r: order.get(r["agent"], len(order)))
            answers = "\n\n".join(f"[{r['agent']}]\n{r['answer']}" for r in results)
            # §8: the question and the specialists' answers, never their tool results.
            reply = await models.synthesizer.ainvoke(
                [
                    SystemMessage(synthesizer_prompt),
                    HumanMessage(
                        f"User's question:\n{_last_user_text(state['messages'])}\n\n"
                        f"Specialist answers:\n{answers}"
                    ),
                ]
            )
        return _answer(reply.text)

    # StateGraph's signatures mention CachePolicy[Unknown]: pyright strict reports
    # add_node/compile as "partially unknown"; hence the ignores.
    graph = StateGraph(RouterState, context_schema=ToolContext)
    graph.add_node("start_turn", start_turn)  # pyright: ignore[reportUnknownMemberType]
    graph.add_node("classify", classify)  # pyright: ignore[reportUnknownMemberType]
    graph.add_node("specialist", specialist)  # pyright: ignore[reportUnknownMemberType]
    graph.add_node("finalize", finalize)  # pyright: ignore[reportUnknownMemberType]
    graph.add_node("synthesize", synthesize)  # pyright: ignore[reportUnknownMemberType]
    graph.add_edge(START, "start_turn")
    graph.add_edge("start_turn", "classify")
    graph.add_conditional_edges("classify", fan_out, ["specialist"])
    graph.add_edge("specialist", "finalize")
    graph.add_conditional_edges("finalize", after_finalize, ["synthesize", END])
    graph.add_edge("synthesize", END)
    return graph.compile(checkpointer=checkpointer, name=GRAPH_NAME)  # pyright: ignore[reportUnknownMemberType]


# ------------------------------------------------------------------- helpers


@asynccontextmanager
async def _node_events(recorder: RunRecorder, node: str) -> AsyncGenerator[None]:
    """D6: ``node_started`` now, ``node_finished`` on success. A crash leaves the node
    without ``node_finished`` (the signal, as for tools) and fails the turn (D7)."""
    await recorder.emit(EventKind.NODE_STARTED, {"node": node})
    started = time.perf_counter()
    yield
    duration_ms = int((time.perf_counter() - started) * 1000)
    await recorder.emit(EventKind.NODE_FINISHED, {"node": node, "duration_ms": duration_ms})


def _answer(text: str) -> dict[str, Any]:
    # Appended to messages so the next turn's router sees the answer.
    return {"answer": text, "messages": [AIMessage(text)]}


def _last_user_text(messages: Sequence[AnyMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return message.text
    return ""
