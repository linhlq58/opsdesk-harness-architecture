"""Router graph (M05 §7-§9): routing, parallel branches, synthesis, streaming X1-X3.

Everything runs for real (graph, ``Send``, checkpointer, specialists, harness tools,
v3 stream, events); only model replies are scripted, one scripted model per job so
parallel specialists never share a script.
"""

import dataclasses
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from opsdesk.agents.specs import SPECIALISTS
from opsdesk.core.ids import new_request_id
from opsdesk.domain.ports import Repositories
from opsdesk.llm.fakes import ScriptedChatModel, tool_call
from opsdesk.observability.events import Event, EventKind
from opsdesk.orchestration.patterns.router import RouterGraph, RouterModels, build_router_graph
from opsdesk.orchestration.streaming import stream_turn
from opsdesk.orchestration.turn import TurnResult
from opsdesk.tools.registry import default_registry
from support import Caller, MakeCaller

pytestmark = pytest.mark.integration

REAL_STUBS = Path(__file__).resolve().parents[2] / "data" / "stubs"
type Script = Sequence[AIMessage | str]


def routes(*pairs: tuple[str, str]) -> AIMessage:
    """The router model's reply: a ``RouteDecision`` tool call."""
    return tool_call("RouteDecision", {"routes": [{"agent": a, "query": q} for a, q in pairs]})


class Models:
    """One scripted model per job; ``received`` tells what each one was sent."""

    def __init__(
        self,
        *,
        router: Script,
        synthesizer: Script = (),
        specialists: Mapping[str, Script] | None = None,
    ) -> None:
        scripts = specialists or {}
        self.router = ScriptedChatModel.from_script(*router)
        self.synthesizer = ScriptedChatModel.from_script(*synthesizer)
        self.specialists = {
            s.name: ScriptedChatModel.from_script(*scripts.get(s.name, ())) for s in SPECIALISTS
        }

    def graph(self) -> RouterGraph:
        return build_router_graph(
            RouterModels(self.router, self.synthesizer, self.specialists),
            default_registry(REAL_STUBS),
            SPECIALISTS,
            checkpointer=InMemorySaver(),
        )


async def _turn(
    graph: RouterGraph, caller: Caller, repos: Repositories, message: str
) -> TurnResult:
    return await stream_turn(
        graph,
        ctx=caller.request,
        message=message,
        repos=repos,
        bus=caller.bus,
        clock=caller.clock,
        entrypoint="test",
    )


def _next_request(caller: Caller) -> Caller:
    """The same employee, same thread, next request; a fresh event list."""
    caller.sink.events.clear()
    request = caller.request.model_copy(update={"request_id": new_request_id()})
    return dataclasses.replace(caller, request=request)


def _nodes(caller: Caller) -> list[str]:
    return [str(e.payload["node"]) for e in caller.events(EventKind.NODE_STARTED)]


def _token_agents(caller: Caller) -> set[str]:
    return {str(e.payload["agent"]) for e in caller.events(EventKind.TOKEN)}


def _tokens(caller: Caller) -> str:
    return "".join(str(e.payload["text"]) for e in caller.events(EventKind.TOKEN))


def _tool_namespaces(events: list[Event]) -> dict[Any, tuple[str, ...]]:
    return {e.payload["tool"]: e.namespace for e in events}


# --------------------------------------------------------------- X1: single route


async def test_x1_single_route_streams_the_specialist_and_skips_synthesis(
    make_caller: MakeCaller, seed_repos: Repositories
) -> None:
    an = await make_caller("E-001")
    answer = "Your laptop LAP-1042 is under warranty until 2027-03-31."
    models = Models(
        router=[routes(("hardware", "Is my laptop under warranty?"))],
        specialists={"hardware": [tool_call("list_my_devices", {}), answer]},
    )

    result = await _turn(models.graph(), an, seed_repos, "Is my laptop still under warranty?")

    assert result.answer == answer
    assert _tokens(an) == answer  # D5: the single specialist's tokens are the answer
    assert _token_agents(an) == {"hardware"}
    assert _nodes(an) == ["classify", "specialist:hardware"]  # D4: no synthesize node
    decided = an.events(EventKind.ROUTE_DECIDED)
    assert [e.payload["agents"] for e in decided] == [["hardware"]]
    assert len(models.synthesizer.received) == 0  # one model call fewer (D4)


# --------------------------------------------------------------- X2, X3: two routes


async def test_x2_two_routes_stream_only_the_synthesis(
    make_caller: MakeCaller, seed_repos: Repositories
) -> None:
    an = await make_caller("E-001")
    models = Models(
        router=[
            routes(
                ("ticket", "What is the status of ticket T-0002?"),
                ("knowledge", "How do I reset my VPN password?"),
            )
        ],
        specialists={
            "ticket": [tool_call("get_ticket", {"ticket_id": "T-0002"}), "T-0002 is in progress."],
            "knowledge": [
                tool_call("search_faq", {"query": "reset VPN password"}),
                "Use id portal.",
            ],
        },
        synthesizer=["T-0002 is in progress. To reset the VPN password, use the id portal."],
    )

    result = await _turn(models.graph(), an, seed_repos, "Status of T-0002, and VPN reset?")

    assert result.answer.startswith("T-0002 is in progress. To reset")
    assert _token_agents(an) == {"synthesize"}  # X2: no specialist text in the chat
    assert _tokens(an) == result.answer
    assert set(_nodes(an)) == {
        "classify",
        "specialist:ticket",
        "specialist:knowledge",
        "synthesize",
    }
    # X3: tool events carry the branch's namespace (our child recorder).
    assert _tool_namespaces(an.events(EventKind.TOOL_FINISHED)) == {
        "get_ticket": ("router", "ticket"),
        "search_faq": ("router", "knowledge"),
    }
    # Calls: router 1 · specialists 2 x (tool call + answer) · synthesizer 1.
    assert [len(models.router.received), len(models.synthesizer.received)] == [1, 1]


async def test_synthesizer_gets_the_question_and_answers_in_route_order(
    make_caller: MakeCaller, seed_repos: Repositories
) -> None:
    an = await make_caller("E-001")
    models = Models(
        router=[routes(("knowledge", "VPN reset?"), ("ticket", "Status of T-0002?"))],
        specialists={"ticket": ["TICKET-ANSWER"], "knowledge": ["KNOWLEDGE-ANSWER"]},
        synthesizer=["merged"],
    )

    await _turn(models.graph(), an, seed_repos, "VPN reset, and T-0002?")

    sent = models.synthesizer.received[0][-1].text
    assert "VPN reset, and T-0002?" in sent
    assert sent.index("KNOWLEDGE-ANSWER") < sent.index("TICKET-ANSWER")  # router's order
    assert "get_ticket" not in sent  # §8: answers only, never tool results


# ------------------------------------------------------- fallback and the harness inside


async def test_unknown_agent_falls_back_to_general_and_router_text_never_streams(
    make_caller: MakeCaller, seed_repos: Repositories
) -> None:
    an = await make_caller("E-001")
    models = Models(
        router=[routes(("billing", "Refund my invoice"))],
        specialists={"general": ["I can only help with IT topics."]},
    )

    await _turn(models.graph(), an, seed_repos, "Refund my invoice")

    decided = an.events(EventKind.ROUTE_DECIDED)[0].payload
    assert decided == {
        "agents": ["general"],
        "fallback": True,
        "reason": "unknown_agent",
        "dropped": ["billing"],
    }
    # general got the user's message as its question (D3 fallback_query).
    assert models.specialists["general"].received[0][-1].text == "Refund my invoice"


async def test_router_reply_without_tool_call_is_not_shown_to_the_user(
    make_caller: MakeCaller, seed_repos: Repositories
) -> None:
    an = await make_caller("E-001")
    models = Models(
        router=["SECRET ROUTER MUSINGS"],  # C2: plain text, no RouteDecision
        specialists={"general": ["Could you tell me more?"]},
    )

    await _turn(models.graph(), an, seed_repos, "hmm")

    assert "SECRET" not in _tokens(an)  # tagged internal: never streamed (D5)
    assert an.events(EventKind.ROUTE_DECIDED)[0].payload["reason"] == "no_decision"


async def test_harness_still_denies_inside_a_specialist(
    make_caller: MakeCaller, seed_repos: Repositories
) -> None:
    binh = await make_caller("E-002")
    models = Models(
        router=[routes(("ticket", "Show me ticket T-0001"))],
        specialists={
            "ticket": [tool_call("get_ticket", {"ticket_id": "T-0001"}), "You can't see it."]
        },
    )

    await _turn(models.graph(), binh, seed_repos, "Show me T-0001")

    finished = binh.events(EventKind.TOOL_FINISHED)[0]
    assert (finished.payload["status"], finished.payload["error_code"]) == ("denied", "not_owner")


# ------------------------------------------------------------ multi-turn state contract


async def test_second_turn_resets_results_and_specialists_see_only_the_sub_query(
    make_caller: MakeCaller, seed_repos: Repositories
) -> None:
    an = await make_caller("E-001")
    models = Models(
        router=[
            routes(("ticket", "Status of T-0002?"), ("knowledge", "VPN reset?")),
            routes(("ticket", "Who is assigned to ticket T-0002?")),
        ],
        specialists={
            "ticket": ["T-0002 is in progress.", "Hoa Vo (E-005) is assigned to T-0002."],
            "knowledge": ["Use the id portal."],
        },
        synthesizer=["Merged answer of turn 1."],
    )
    graph = models.graph()
    await _turn(graph, an, seed_repos, "Status of T-0002, and VPN reset?")

    an2 = _next_request(an)
    result = await _turn(graph, an2, seed_repos, "And who is assigned to it?")

    # R1: only this turn's result; one route, so it is the answer (no synthesis).
    state: Any = await graph.aget_state({"configurable": {"thread_id": an.request.thread_id}})
    assert state.values["results"] == [
        {"agent": "ticket", "answer": "Hoa Vo (E-005) is assigned to T-0002."}
    ]
    assert result.answer == "Hoa Vo (E-005) is assigned to T-0002."
    # The router saw the whole conversation, including turn 1's merged answer...
    router_saw = [m.text for m in models.router.received[1]]
    assert "Merged answer of turn 1." in router_saw
    # ...the ticket specialist only its system prompt and the rewritten question (D2).
    ticket_saw = [m.text for m in models.specialists["ticket"].received[1]]
    assert ticket_saw[1:] == ["Who is assigned to ticket T-0002?"]
    # Specialists store nothing in the thread's checkpoints (checkpointer=False).
    saver = graph.checkpointer
    assert isinstance(saver, InMemorySaver)
    thread: Any = {"configurable": {"thread_id": an.request.thread_id}}
    namespaces = {
        c.config.get("configurable", {}).get("checkpoint_ns", "") async for c in saver.alist(thread)
    }
    assert namespaces == {""}


# ------------------------------------------------------------------- D7: a crash


async def test_a_crashing_specialist_fails_the_whole_turn(
    make_caller: MakeCaller, seed_repos: Repositories
) -> None:
    an = await make_caller("E-001")
    models = Models(
        router=[routes(("ticket", "Status of T-0002?"), ("knowledge", "VPN reset?"))],
        specialists={"ticket": ["fine"], "knowledge": []},  # empty script: the model raises
    )

    with pytest.raises(AssertionError):  # ScriptExhausted is an AssertionError
        await _turn(models.graph(), an, seed_repos, "Status of T-0002, and VPN reset?")

    assert an.events(EventKind.RUN_FINISHED)[-1].payload["status"] == "failed"
    assert "synthesize" not in _nodes(an)
