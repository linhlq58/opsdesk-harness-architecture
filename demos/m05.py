"""M05 demo: the router pattern, through the API, as the browser sees it.

The app runs in-process; the demo logs in, opens **router** threads and prints what the
SSE stream shows: the route decision, which nodes ran, which tools ran in which
branch, and which node's tokens reached the chat. Six scenarios from the milestone:

1. An: laptop warranty → one route (hardware), no synthesis, specialist tokens.
2. An: T-0002 status + VPN reset → two parallel routes, synthesis, synthesizer tokens.
3. The router names an agent that does not exist → fallback to ``general``.
4. Binh asks for An's ticket → ``denied/not_owner`` inside the ticket specialist.
5. Same thread as 2: "And who is assigned to it?" → the router rewrites the question;
   per-turn state holds only this turn's result.
6. Chi clicked a suspicious link → security specialist, phishing first steps.

* Fake mode (default): one ``ScriptedChatModel`` per job (router, synthesizer, each
  specialist), so parallel branches never share a script. Deterministic; checked; CI.
* ``--live``: the real models (roles ``router`` / ``specialist`` / ``synthesizer``).
  Printed, not checked. Scenario 3 cannot force a real model to invent an agent: it
  asks an off-topic question instead.
"""

import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

import httpx
from fastapi import FastAPI
from langchain_core.messages import AIMessage

from demos.asgi_client import SseFrame, parse_sse
from opsdesk.agents.specs import SPECIALISTS
from opsdesk.api.app import create_app
from opsdesk.api.state import AppState
from opsdesk.core.clock import FixedClock
from opsdesk.core.settings import Settings
from opsdesk.llm.factory import LlmConfigError
from opsdesk.llm.fakes import ScriptedChatModel, tool_call
from opsdesk.orchestration.patterns.router import RouterModels
from opsdesk.orchestration.threads import Pattern

ROOT = Path(__file__).resolve().parents[1]
SEED_DIR = ROOT / "data" / "seed"
STUB_DIR = ROOT / "data" / "stubs"

Q1 = "Is my laptop still under warranty?"
Q2 = "What's the status of T-0002, and how do I reset my VPN password?"
Q3 = "Can you refund my last invoice?"
Q4 = "Show me T-0001"
Q5 = "And who is assigned to it?"
Q6 = "I just clicked a link in a suspicious email"

A1 = "Yes: your laptop LAP-1042 (Dell Latitude 7440) is under warranty until 2027-03-31."
A2_TICKET = "T-0002 (VPN disconnects every few minutes) is in progress, assigned to E-005."
A2_KNOWLEDGE = "Open id.acme.example, choose Reset VPN password, confirm in your app (FAQ-VPN-01)."
A2 = (
    "T-0002 (VPN disconnects every few minutes) is in progress, assigned to E-005. "
    "To reset your VPN password, open id.acme.example, choose Reset VPN password and "
    "confirm in your authenticator app (FAQ-VPN-01)."
)
A3 = "I can only help with IT topics, such as tickets, devices or IT policies."
A4 = "I can't show you T-0001: you can only see your own tickets."
A5 = "Ticket T-0002 is assigned to E-005 (Hoa Vo)."
A6 = (
    "1. Disconnect from the network. 2. Do not enter any password. 3. Report the email "
    "with Report phishing. 4. Call the IT security hotline (ext. 4444) now. (FAQ-SEC-01)"
)
Q5_REWRITTEN = "Who is assigned to ticket T-0002?"


def _routes(*pairs: tuple[str, str]) -> AIMessage:
    return tool_call("RouteDecision", {"routes": [{"agent": a, "query": q} for a, q in pairs]})


def scripted_models() -> RouterModels:
    """Every model call of the demo, per job, in order."""
    router = ScriptedChatModel.from_script(
        _routes(("hardware", Q1)),  # 1
        _routes(  # 2
            ("ticket", "What is the status of ticket T-0002?"),
            ("knowledge", "How do I reset my VPN password?"),
        ),
        _routes(("billing", Q3)),  # 3: an agent that does not exist
        _routes(("ticket", "Show me ticket T-0001")),  # 4
        _routes(("ticket", Q5_REWRITTEN)),  # 5: "it" resolved from the conversation
        _routes(("security", "I clicked a link in a suspicious email")),  # 6
    )
    specialists = {
        "hardware": ScriptedChatModel.from_script(tool_call("list_my_devices", {}), A1),
        "ticket": ScriptedChatModel.from_script(
            tool_call("get_ticket", {"ticket_id": "T-0002"}),  # 2
            A2_TICKET,
            tool_call("get_ticket", {"ticket_id": "T-0001"}),  # 4 (Binh)
            A4,
            tool_call("get_ticket", {"ticket_id": "T-0002"}),  # 5
            A5,
        ),
        "knowledge": ScriptedChatModel.from_script(
            tool_call("search_faq", {"query": "reset VPN password"}), A2_KNOWLEDGE
        ),
        "security": ScriptedChatModel.from_script(
            tool_call("search_faq", {"query": "clicked suspicious email link phishing"}), A6
        ),
        "general": ScriptedChatModel.from_script(A3),
    }
    assert set(specialists) == {s.name for s in SPECIALISTS}
    return RouterModels(
        router=router, synthesizer=ScriptedChatModel.from_script(A2), specialists=specialists
    )


@dataclass
class Check:
    scenario: int
    what: str
    ok: bool


class Browser:
    """Acts like ``web/app.js`` in the Router tab."""

    def __init__(self, app: FastAPI, client: httpx.AsyncClient, out: TextIO) -> None:
        self.app = app
        self.client = client
        self.out = out

    @property
    def state(self) -> AppState:
        return self.app.state.opsdesk

    async def login(self, employee_id: str) -> str:
        response = await self.client.post("/api/session", json={"employee_id": employee_id})
        response.raise_for_status()
        return response.json()["token"]

    async def new_thread(self, token: str) -> str:
        response = await self.client.post(
            "/api/threads", json={"pattern": "router"}, headers=_bearer(token)
        )
        response.raise_for_status()
        return response.json()["thread_id"]

    async def ask(self, token: str, thread_id: str, message: str) -> list[SseFrame]:
        response = await self.client.post(
            "/api/chat",
            json={"thread_id": thread_id, "pattern": "router", "message": message},
            headers=_bearer(token),
        )
        response.raise_for_status()
        return parse_sse(response.text)


async def run(*, live: bool, out: TextIO) -> list[Check]:
    """Run the six scenarios; print what the browser receives; return the checks."""
    with tempfile.TemporaryDirectory(prefix="opsdesk-m05-") as tmp:
        models = None if live else scripted_models()
        app = create_app(
            Settings() if live else Settings(var_dir=Path(tmp)),
            model=None if live else ScriptedChatModel.from_script(),  # ticket tab unused
            router_models=models,
            clock=None if live else FixedClock(),
            seed_dir=SEED_DIR,
            stub_dir=STUB_DIR,
            web_dir=Path(tmp) / "no-web",
        )
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://opsdesk", timeout=120
            ) as client,
        ):
            return await _scenarios(Browser(app, client, out), models, live=live)


async def main(*, live: bool, out: TextIO) -> int:
    mode = "live models" if live else "scripted models"
    out.write(f"M05 demo: router pattern through the API ({mode})\n\n")
    try:
        checks = await run(live=live, out=out)
    except LlmConfigError as exc:
        out.write(f"Cannot run live: {exc}\n")
        return 2
    if live:
        return 0
    failed = [c for c in checks if not c.ok]
    for c in failed:
        out.write(f"✗ scenario {c.scenario}: {c.what}\n")
    out.write(f"{len(checks) - len(failed)}/{len(checks)} checks as expected\n")
    return 1 if failed else 0


# ------------------------------------------------------------------------ scenarios


async def _scenarios(b: Browser, models: RouterModels | None, *, live: bool) -> list[Check]:
    out = b.out
    checks: list[Check] = []

    def check(scenario: int, what: str, ok: bool) -> None:
        checks.append(Check(scenario, what, ok))
        out.write(f"  [check]  {'✓' if ok else '✗'} {what}\n")

    def calls() -> dict[str, int]:
        if models is None:
            return {}
        counts = {"router": len(_received(models.router))}
        counts["synthesizer"] = len(_received(models.synthesizer))
        for name, model in models.specialists.items():
            counts[name] = len(_received(model))
        return counts

    an = await b.login("E-001")

    # ---------------------------------------------------------------- 1
    out.write(f'▶ 1. An: "{Q1}"\n')
    thread_1 = await b.new_thread(an)
    frames = await b.ask(an, thread_1, Q1)
    _print_turn(out, frames)
    if not live:
        check(1, "one route: hardware", _agents(frames) == ["hardware"])
        check(1, "no synthesize node (D4)", "synthesize" not in _nodes(frames))
        check(1, "tokens come from the specialist (D5)", _token_agents(frames) == {"hardware"})
        check(1, "answer streamed", _text(frames) == A1)
    out.write("\n")

    # ---------------------------------------------------------------- 2
    out.write(f'▶ 2. An: "{Q2}"\n')
    thread_2 = await b.new_thread(an)
    before = calls()
    frames = await b.ask(an, thread_2, Q2)
    after = calls()
    _print_turn(out, frames)
    if models is not None:
        spent = {k: after[k] - before.get(k, 0) for k in after if after[k] != before.get(k, 0)}
        specialists = [k for k in spent if k not in ("router", "synthesizer")]
        out.write(
            f"  [calls]  router {spent.get('router', 0)} · specialists {len(specialists)}"
            f" ({sum(spent[k] for k in specialists)} model calls, tool loop included)"
            f" · synthesizer {spent.get('synthesizer', 0)}\n"
        )
    if not live:
        check(2, "two routes: ticket, knowledge", _agents(frames) == ["ticket", "knowledge"])
        check(
            2,
            "tool events carry the branch namespace (X3)",
            _tool_namespaces(frames)
            == {"get_ticket": ["router", "ticket"], "search_faq": ["router", "knowledge"]},
        )
        check(
            2, "only synthesize tokens reach the chat (D5)", _token_agents(frames) == {"synthesize"}
        )
        check(2, "merged answer streamed", _text(frames) == A2)
    out.write("\n")

    # ---------------------------------------------------------------- 3
    if live:
        out.write(f'▶ 3. An: "{Q3}" (live: an off-topic question)\n')
    else:
        out.write(f'▶ 3. An: "{Q3}" (the scripted router answers with agent "billing")\n')
    frames = await b.ask(an, await b.new_thread(an), Q3)
    _print_turn(out, frames)
    if not live:
        decided = _route_payload(frames)
        check(3, "fallback to general", decided.get("agents") == ["general"])
        check(
            3,
            "fallback badge data: fallback=true, reason=unknown_agent",
            (decided.get("fallback"), decided.get("reason")) == (True, "unknown_agent"),
        )
        check(3, "'dropped' never reaches the browser (X4)", "dropped" not in decided)
    out.write("\n")

    # ---------------------------------------------------------------- 4
    out.write(f'▶ 4. Binh: "{Q4}" (T-0001 is An\'s ticket)\n')
    binh = await b.login("E-002")
    frames = await b.ask(binh, await b.new_thread(binh), Q4)
    _print_turn(out, frames)
    out.write(
        "  [why]    the router and the specialist only proposed; get_ticket's policy decided\n"
    )
    if not live:
        finished = [f for f in frames if f.event == "tool_finished"]
        check(
            4,
            "get_ticket denied / not_owner inside the specialist",
            [(f.data["payload"]["status"], f.data["payload"]["error_code"]) for f in finished]
            == [("denied", "not_owner")],
        )
    out.write("\n")

    # ---------------------------------------------------------------- 5
    out.write(f'▶ 5. Same thread as 2: "{Q5}"\n')
    frames = await b.ask(an, thread_2, Q5)
    _print_turn(out, frames)
    router_graph = b.state.graphs[Pattern.ROUTER]
    snapshot: Any = await router_graph.aget_state({"configurable": {"thread_id": thread_2}})
    state_routes = snapshot.values["routes"]
    results = snapshot.values["results"]
    out.write(f"  [state]  routes: {[(r['agent'], r['query']) for r in state_routes]}\n")
    out.write(f"  [state]  results: {[r['agent'] for r in results]}   (this turn only)\n")
    if models is not None:
        ticket_saw = [m.text for m in _received(models.specialists["ticket"])[-2]][1:]
        out.write(f"  [state]  the ticket specialist saw: {ticket_saw}   (sub-query only, D2)\n")
        check(5, "query rewritten by the router", state_routes[0]["query"] == Q5_REWRITTEN)
        check(5, "per-turn state reset: one result", [r["agent"] for r in results] == ["ticket"])
        check(5, "specialist saw only the sub-query (D2)", ticket_saw == [Q5_REWRITTEN])
    out.write("\n")

    # ---------------------------------------------------------------- 6
    out.write(f'▶ 6. Chi: "{Q6}"\n')
    chi = await b.login("E-003")
    frames = await b.ask(chi, await b.new_thread(chi), Q6)
    _print_turn(out, frames)
    if not live:
        check(6, "one route: security", _agents(frames) == ["security"])
        check(
            6,
            "search_faq ok in the security branch",
            _tool_namespaces(frames) == {"search_faq": ["router", "security"]},
        )
    out.write("\n")
    return checks


# ------------------------------------------------------------------------ printing


def _print_turn(out: TextIO, frames: Sequence[SseFrame]) -> None:
    decided = _route_payload(frames)
    if decided:
        agents = ", ".join(decided.get("agents", []))
        note = "single route → no synthesis" if len(decided.get("agents", [])) == 1 else "parallel"
        if decided.get("fallback"):
            note = f"fallback: {decided.get('reason')}"
        elif decided.get("reason"):
            note += f"; {decided.get('reason')}"
        out.write(f"  [route]  {agents}   ({note})\n")
    out.write(f"  [nodes]  {' · '.join(_nodes(frames))}\n")
    for frame in frames:
        if frame.event == "tool_finished":
            p = frame.data["payload"]
            where = "/".join(frame.data["namespace"]) or "top"
            code = f" / {p['error_code']}" if p.get("error_code") else ""
            out.write(f"  [tool]   {where} · {p['tool']} {p['status']}{code}\n")
    sources = ", ".join(sorted(_token_agents(frames))) or "-"
    out.write(f'  [answer] streamed from {sources}: "{_text(frames)}"\n')


# ------------------------------------------------------------------------ helpers


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _route_payload(frames: Sequence[SseFrame]) -> dict[str, Any]:
    for frame in frames:
        if frame.event == "route_decided":
            return dict(frame.data["payload"])
    return {}


def _agents(frames: Sequence[SseFrame]) -> list[str]:
    return list(_route_payload(frames).get("agents", []))


def _nodes(frames: Sequence[SseFrame]) -> list[str]:
    return [str(f.data["payload"]["node"]) for f in frames if f.event == "node_started"]


def _token_agents(frames: Sequence[SseFrame]) -> set[str]:
    return {str(f.data["payload"]["agent"]) for f in frames if f.event == "token"}


def _text(frames: Sequence[SseFrame]) -> str:
    return "".join(str(f.data["payload"]["text"]) for f in frames if f.event == "token")


def _tool_namespaces(frames: Sequence[SseFrame]) -> dict[str, list[str]]:
    return {
        str(f.data["payload"]["tool"]): list(f.data["namespace"])
        for f in frames
        if f.event == "tool_finished"
    }


def _received(model: Any) -> list[Any]:
    return list(getattr(model, "received", []))
