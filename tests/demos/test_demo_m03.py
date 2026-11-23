"""``uv run poe demo m03`` (scripted model) runs inside ``poe check``.

``demos.m03`` is imported inside the test because it imports the ticket agent, which
needs the 🎯 pieces at import time (see ``tests/unit/tools/test_tickets.py``).
"""

import io

import pytest

pytestmark = pytest.mark.integration


async def test_demo_m03_all_scenarios_as_expected() -> None:
    from demos import m03

    out = io.StringIO()
    outcomes = await m03.run(live=False, out=out)

    assert len(outcomes) == 6
    unexpected = [o.scenario.message for o in outcomes if not o.matched]
    assert unexpected == [], out.getvalue()


async def test_demo_m03_every_run_is_closed_in_the_event_log() -> None:
    from demos import m03

    outcomes = await m03.run(live=False, out=io.StringIO())

    for o in outcomes:
        kinds = [e.kind.value for e in o.events]
        assert kinds[0] == "run_started"
        assert kinds[-1] == "run_finished"
        assert o.events[-1].payload["status"] == "completed"


async def test_demo_m03_main_exit_code() -> None:
    from demos import m03

    out = io.StringIO()
    assert await m03.main(live=False, out=out) == 0
    assert "6/6 scenarios as expected" in out.getvalue()
