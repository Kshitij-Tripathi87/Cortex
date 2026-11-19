"""The service clock is UTC and can be pinned by a test."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.core import clock


def test_utcnow_is_timezone_aware_utc() -> None:
    now = clock.utcnow()

    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)


def test_clock_can_be_frozen_and_is_restored() -> None:
    moment = datetime(2026, 11, 19, 7, 30, tzinfo=UTC)

    with clock.frozen_at(moment):
        assert clock.utcnow() == moment
        assert clock.utcnow() == moment

    assert clock.utcnow() != moment


def test_clock_is_restored_after_an_error() -> None:
    moment = datetime(2026, 11, 19, tzinfo=UTC)

    with pytest.raises(RuntimeError), clock.frozen_at(moment):
        raise RuntimeError("boom")

    assert clock.utcnow() != moment


@pytest.mark.parametrize(
    "bad",
    [
        datetime(2026, 11, 19, 7, 30),  # noqa: DTZ001 - a naive value is the point of the test
        datetime(2026, 11, 19, 7, 30, tzinfo=timezone(timedelta(hours=5, minutes=30))),
    ],
)
def test_a_clock_that_is_not_utc_is_rejected(bad: datetime) -> None:
    with clock.use_clock(lambda: bad), pytest.raises(ValueError, match="UTC"):
        clock.utcnow()
