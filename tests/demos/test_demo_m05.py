"""``uv run poe demo m05`` (scripted models) runs inside ``poe check``."""

import io

import pytest

pytestmark = pytest.mark.integration


async def test_demo_m05_all_checks_pass() -> None:
    from demos import m05

    out = io.StringIO()
    checks = await m05.run(live=False, out=out)

    assert {c.scenario for c in checks} == {1, 2, 3, 4, 5, 6}
    assert [c.what for c in checks if not c.ok] == [], out.getvalue()


async def test_demo_m05_main_exit_code() -> None:
    from demos import m05

    out = io.StringIO()
    assert await m05.main(live=False, out=out) == 0
    assert "17/17 checks as expected" in out.getvalue()
