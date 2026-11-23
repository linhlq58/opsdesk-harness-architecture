"""One real-model round trip. Excluded by default; run manually:

    uv run pytest -m live

Needs ``OPENAI_BASE_URL``, ``OPENAI_API_KEY`` and ``OPSDESK_MODEL_SPECIALIST`` in
``.env``. Costs a few tokens. Checks only what a real model should reliably do: call
``get_ticket`` for a direct question, and finish the run.
"""

import pytest

from opsdesk.domain.ports import Repositories
from opsdesk.llm.factory import ModelRole, build_chat_model
from opsdesk.llm.settings import LlmSettings
from opsdesk.observability.events import EventKind
from opsdesk.orchestration.turn import run_turn
from support import MakeCaller

pytestmark = pytest.mark.live


async def test_real_model_uses_get_ticket(
    make_caller: MakeCaller, seed_repos: Repositories
) -> None:
    from opsdesk.agents.ticket_agent import build_ticket_agent

    model = build_chat_model(ModelRole.SPECIALIST, LlmSettings())
    an = await make_caller("E-001")

    result = await run_turn(
        build_ticket_agent(model),
        ctx=an.request,
        message="What's the status of T-0002?",
        repos=seed_repos,
        bus=an.bus,
        clock=an.clock,
        entrypoint="live-test",
    )

    assert result.status == "completed"
    assert result.answer.strip()
    finished = an.events(EventKind.TOOL_FINISHED)
    assert [(e.payload["tool"], e.payload["status"]) for e in finished] == [("get_ticket", "ok")]
