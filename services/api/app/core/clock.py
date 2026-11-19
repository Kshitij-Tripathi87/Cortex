"""The one clock of the service.

Business code asks :func:`utcnow` for the time instead of calling
``datetime.now()``, so a test can pin it and assert exact timestamps.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

Clock = Callable[[], datetime]


def _system_clock() -> datetime:
    return datetime.now(UTC)


_clock: Clock = _system_clock


def utcnow() -> datetime:
    """Current time as a timezone-aware UTC datetime."""
    now = _clock()
    if now.tzinfo is None or now.utcoffset() != timedelta(0):
        raise ValueError("the configured clock must return timezone-aware UTC datetimes")
    return now


@contextmanager
def use_clock(clock: Clock) -> Iterator[None]:
    """Replace the clock inside a ``with`` block (tests only)."""
    global _clock
    previous = _clock
    _clock = clock
    try:
        yield
    finally:
        _clock = previous


@contextmanager
def frozen_at(moment: datetime) -> Iterator[None]:
    """Pin the clock to one instant inside a ``with`` block (tests only)."""
    with use_clock(lambda: moment):
        yield
