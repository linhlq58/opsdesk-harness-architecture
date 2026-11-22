"""Time source for the whole application.

Code never calls ``datetime.now()`` / ``datetime.utcnow()`` directly. It receives a
``Clock`` and asks it for the time, so tests can freeze or advance time at will.

Domain policies go one step further: they do not even take a ``Clock``, they take
``now: datetime`` as a parameter. The caller (a service or workflow) reads the clock.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    """Anything that can tell the current time as a timezone-aware UTC ``datetime``."""

    def now(self) -> datetime: ...


class SystemClock:
    """The real clock. Use this in production wiring."""

    def now(self) -> datetime:
        return datetime.now(UTC)


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC)


@dataclass(slots=True)
class FixedClock:
    """A clock that only moves when told to. For tests.

    >>> clock = FixedClock(datetime(2026, 1, 1, tzinfo=UTC))
    >>> clock.advance(timedelta(hours=1))
    """

    current: datetime = field(default_factory=lambda: datetime(2026, 1, 1, 9, 0, tzinfo=UTC))

    def __post_init__(self) -> None:
        self.current = _require_aware(self.current)

    def now(self) -> datetime:
        return self.current

    def set(self, value: datetime) -> None:
        self.current = _require_aware(value)

    def advance(self, delta: timedelta) -> None:
        if delta < timedelta(0):
            raise ValueError("a clock cannot go backwards")
        self.current += delta
