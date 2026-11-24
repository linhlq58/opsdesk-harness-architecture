"""``uv run poe demo m04`` (scripted model) runs inside ``poe check``."""

import io

import pytest

pytestmark = pytest.mark.integration


async def test_demo_m04_all_checks_pass() -> None:
    from demos import m04

    out = io.StringIO()
    checks = await m04.run(live=False, out=out)

    assert {c.scenario for c in checks} == {1, 2, 3, 4, 5, 6}
    assert [c.what for c in checks if not c.ok] == [], out.getvalue()


async def test_demo_m04_main_exit_code() -> None:
    from demos import m04

    out = io.StringIO()
    assert await m04.main(live=False, out=out) == 0
    assert "11/11 checks as expected" in out.getvalue()
