"""Realtime bus sequence-source stickiness (v0.8.2 CI-green follow-up).

Regression test for the mixed-sequence-space bug found by the first
Redis-enabled CI run (PR #1, ci.yml ``test`` job):

    test_sequence_numbers_monotonic failed with ``assert 1000000001 < 2``

Root cause: ``RealtimeBus.publish`` allocated the FIRST event's seq via
Redis INCR, the command timed out on a cold connect (200 ms budget), the
code fell back to the local counter (1e9+1), and the NEXT publishes
reached Redis fine and got seqs 2, 3. Two sequence spaces mixed within
one workspace — the documented per-workspace monotonicity contract
(docs/NEXUS_v0.8_P0_ARCHITECTURE.md, realtime bus section) was violated
by construction on any transient Redis blip.

Fix under test: once a workspace's first allocation falls back to the
local counter, that workspace stays on the local counter for the process
lifetime (monotonic by construction). Cross-process unification is the
v0.8.3 outbox milestone (DB-backed monotonic seq).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest

from app.infrastructure.realtime_bus import RealtimeBus, get_realtime_bus


class _FlakyRedis:
    """Redis client proxy whose INCR fails exactly N times, then succeeds.

    This reproduces the CI failure mode: the command executes (or the
    connection times out) on a cold connect, then subsequent commands
    reach a healthy Redis.
    """

    def __init__(self, fail_first: int) -> None:
        self._fail_first = fail_first
        self._incr_calls = 0

    async def incr(self, _key: str) -> int:
        self._incr_calls += 1
        if self._incr_calls <= self._fail_first:
            raise TimeoutError("simulated cold-connect timeout on first INCR")
        return self._incr_calls - self._fail_first


class _FlakyRedisClient:
    def __init__(self, fail_first: int) -> None:
        self._redis = _FlakyRedis(fail_first)

    async def publish(self, _channel: str, _payload: str) -> None:
        return None


@pytest.fixture
def fresh_bus(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[RealtimeBus]:
    """An isolated bus with the global client wired to a flaky Redis."""
    bus = RealtimeBus()
    client = _FlakyRedisClient(fail_first=1)
    monkeypatch.setattr(bus, "_get_redis", lambda: client)
    monkeypatch.setattr("app.infrastructure.realtime_bus._realtime_bus", bus, raising=False)
    yield bus


async def test_first_incr_timeout_does_not_mix_sequence_spaces(fresh_bus: RealtimeBus) -> None:
    """The exact CI failure: first INCR times out, later ones succeed.

    Before the fix: seqs were 1_000_000_001 (local), 2, 3 (Redis) —
    non-monotonic within the workspace. After: the workspace pins to the
    local counter and all seqs stay monotonic.
    """
    q = fresh_bus.subscribe("WS-SEQ-STICKY")
    try:
        e1 = await fresh_bus.publish(tenant_id="T", workspace_id="WS-SEQ-STICKY", event_type="a")
        e2 = await fresh_bus.publish(tenant_id="T", workspace_id="WS-SEQ-STICKY", event_type="b")
        e3 = await fresh_bus.publish(tenant_id="T", workspace_id="WS-SEQ-STICKY", event_type="c")
        assert e1.seq < e2.seq < e3.seq, (
            f"sequence numbers must be monotonic per workspace even when the "
            f"first Redis INCR fails and later ones succeed; got {e1.seq}, {e2.seq}, {e3.seq}"
        )
        # The subscriber sees exactly the events published, in order.
        r1 = await asyncio.wait_for(q.get(), timeout=2.0)
        r2 = await asyncio.wait_for(q.get(), timeout=2.0)
        assert (r1.seq, r2.seq) == (e1.seq, e2.seq)
    finally:
        fresh_bus.unsubscribe("WS-SEQ-STICKY", q)


async def test_healthy_redis_keeps_redis_sequence_space(fresh_bus: RealtimeBus) -> None:
    """With a fully healthy Redis the workspace stays in the Redis space.

    Pins that the stickiness does not silently degrade everyone to the
    local counter: the first successful INCR keeps the workspace on
    Redis (seqs 1, 2, 3 — NOT the 1e9+n local space).
    """
    # Re-wire with a never-failing client for this test (the fixture's
    # patched method wins over _redis_client, so patch the method again).
    healthy = _FlakyRedisClient(fail_first=0)
    fresh_bus._get_redis = lambda: healthy  # type: ignore[method-assign]
    fresh_bus._local_seq_workspaces.clear()

    e1 = await fresh_bus.publish(tenant_id="T", workspace_id="WS-SEQ-REDIS", event_type="a")
    e2 = await fresh_bus.publish(tenant_id="T", workspace_id="WS-SEQ-REDIS", event_type="b")
    assert 0 < e1.seq < e2.seq < 1_000_000_000, (
        f"healthy-Redis workspaces must use the Redis sequence space; got {e1.seq}, {e2.seq}"
    )


async def test_stickiness_is_per_workspace(fresh_bus: RealtimeBus) -> None:
    """A fallback for one workspace does not pin unrelated workspaces."""
    e1 = await fresh_bus.publish(tenant_id="T", workspace_id="WS-SEQ-A", event_type="a")
    # WS-SEQ-A burned the single flaky failure; the next workspace gets a
    # healthy INCR path (call #2 on the flaky client succeeds).
    e2 = await fresh_bus.publish(tenant_id="T", workspace_id="WS-SEQ-B", event_type="b")
    assert e1.seq >= 1_000_000_000, f"first workspace should have fallen back locally: {e1.seq}"
    assert 0 < e2.seq < 1_000_000_000, f"second workspace should use Redis space: {e2.seq}"


def test_global_bus_accessible() -> None:
    """The module-level accessor still returns a bus instance."""
    bus: Any = get_realtime_bus()
    assert bus is not None
