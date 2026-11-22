from datetime import UTC, datetime, timedelta, timezone

import pytest

from opsdesk.core.clock import Clock, FixedClock, SystemClock


def test_system_clock_is_timezone_aware_utc() -> None:
    now = SystemClock().now()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)


def test_fixed_clock_stands_still_until_advanced() -> None:
    start = datetime(2026, 3, 1, 8, 0, tzinfo=UTC)
    clock = FixedClock(start)
    assert clock.now() == start
    assert clock.now() == start

    clock.advance(timedelta(minutes=30))
    assert clock.now() == start + timedelta(minutes=30)


def test_fixed_clock_normalises_to_utc() -> None:
    ict = timezone(timedelta(hours=7))
    clock = FixedClock(datetime(2026, 3, 1, 15, 0, tzinfo=ict))
    assert clock.now() == datetime(2026, 3, 1, 8, 0, tzinfo=UTC)
    assert clock.now().tzinfo is UTC


def test_fixed_clock_rejects_naive_datetimes() -> None:
    naive = datetime(2026, 3, 1, 8, 0)  # noqa: DTZ001 - deliberately naive
    with pytest.raises(ValueError, match="timezone-aware"):
        FixedClock(naive)
    clock = FixedClock()
    with pytest.raises(ValueError, match="timezone-aware"):
        clock.set(naive)


def test_fixed_clock_cannot_go_backwards() -> None:
    with pytest.raises(ValueError, match="backwards"):
        FixedClock().advance(timedelta(seconds=-1))


def test_both_clocks_satisfy_the_protocol() -> None:
    clocks: list[Clock] = [SystemClock(), FixedClock()]
    assert all(isinstance(c.now(), datetime) for c in clocks)
