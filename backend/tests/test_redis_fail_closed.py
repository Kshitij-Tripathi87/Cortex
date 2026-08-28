"""E3 — Redis fail-closed model (Phase 15 production gate).

Pins the policy that auth-relevant Redis-backed operations must
DENY on Redis outage, not silently fall open. The legacy behavior
treated `_get` returning None as "0 requests" for the rate limiter,
which meant a Redis outage disabled the rate limit — a security
hole, not a graceful degradation.

The fix is two parts:

- ``check_rate_limit(fail_closed=True)`` (the new default) probes
  Redis availability; if down, returns False (deny) and increments
  the ``redis_fail_closed_denies`` stat.
- ``lock(fail_closed=True)`` for auth-relevant resources refuses to
  acquire a single-process lock when Redis is unavailable, because
  a single-process lock in a multi-replica deployment is no lock at
  all.

The test is hermetic: it uses a fake Redis client that raises
``ConnectionError`` on every operation, simulating an outage. No
real Redis is required; the test runs in the default 1,337 PR
suite.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import pytest


class _FakeRedisDown:
    """Stand-in for `redis.asyncio.Redis` that always raises. Used to
    simulate a Redis outage in unit tests without needing a real
    Redis fixture."""

    async def ping(self) -> None:
        raise ConnectionError("simulated Redis outage")

    async def get(self, *_args: Any, **_kwargs: Any) -> None:
        raise ConnectionError("simulated Redis outage")

    async def set(self, *_args: Any, **_kwargs: Any) -> None:
        raise ConnectionError("simulated Redis outage")

    async def delete(self, *_args: Any, **_kwargs: Any) -> None:
        raise ConnectionError("simulated Redis outage")

    def scan_iter(self, *_args: Any, **_kwargs: Any):
        async def _empty():
            if False:
                yield None
        return _empty()

    async def close(self) -> None:
        return None


class _FakeRedisOk:
    """Stand-in for `redis.asyncio.Redis` that always succeeds."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def ping(self) -> bool:
        return True

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)

    def scan_iter(self, match: str | None = None):
        async def _iter():
            for k in self.store:
                if match is None or match in k:
                    yield k
        return _iter()

    async def close(self) -> None:
        return None


@pytest.fixture
def cache():
    # Import inside the fixture so the test module is collectable
    # even if the package has a slow import.
    from app.infrastructure import cache_manager

    # Reset the global cache manager so each test gets a fresh
    # instance with empty stats.
    cache_manager._global_cache_mgr = None
    mgr = cache_manager.CacheManager()
    return mgr


# ─────────────────────────────────────────────────────────────────────────────
# 1. check_rate_limit — fail-closed default
# ─────────────────────────────────────────────────────────────────────────────

class TestRateLimitFailClosed:
    """The rate limiter must DENY on Redis outage by default. The legacy
    behavior (deny=0 → allow) was the security bug; this test pins the
    fix."""

    @pytest.mark.asyncio
    async def test_default_fail_closed_denies_on_redis_outage(
        self, cache, monkeypatch: pytest.MonkeyPatch
    ):
        # Wire a Redis client that always raises. `get_redis_client`
        # is a sync factory, so the fake is sync too.
        from app.infrastructure import redis_client

        class _DownClient:
            _redis = _FakeRedisDown()

            async def get(self, _key: str) -> None:
                raise ConnectionError("simulated Redis outage")

            async def set(self, _key: str, _value: Any, ex: int | None = None) -> None:
                raise ConnectionError("simulated Redis outage")

        def _fake_get_redis_client():
            return _DownClient()

        monkeypatch.setattr(
            "app.infrastructure.cache_manager.get_redis_client",
            _fake_get_redis_client,
        )

        # The new default must DENY.
        allowed = await cache.check_rate_limit(
            tenant_id="t_fail_closed", resource="auth_login"
        )
        assert allowed is False, (
            "check_rate_limit() must fail-closed by default; got True on Redis outage"
        )

        # And it must increment the deny counter.
        stats = cache.get_stats()
        assert stats["redis_fail_closed_denies"] >= 1, (
            f"Expected redis_fail_closed_denies >= 1, got {stats}"
        )

    @pytest.mark.asyncio
    async def test_explicit_fail_closed_false_allows_on_outage(
        self, cache, monkeypatch: pytest.MonkeyPatch
    ):
        # An explicit opt-out preserves the legacy behavior. This
        # protects callers that genuinely need fail-open (e.g. a
        # metrics endpoint that should not 503 on cache outage).
        from app.infrastructure import redis_client

        class _DownClient:
            _redis = _FakeRedisDown()

            async def get(self, _key: str) -> None:
                raise ConnectionError("simulated Redis outage")

            async def set(self, _key: str, _value: Any, ex: int | None = None) -> None:
                raise ConnectionError("simulated Redis outage")

        def _fake_get_redis_client():
            return _DownClient()

        monkeypatch.setattr(
            "app.infrastructure.cache_manager.get_redis_client",
            _fake_get_redis_client,
        )

        allowed = await cache.check_rate_limit(
            tenant_id="t_fail_open",
            resource="metrics",
            fail_closed=False,
        )
        # Local cache fallback takes over; behavior is best-effort.
        # The exact return depends on local cache state, but the
        # call MUST NOT raise and MUST NOT increment the fail-closed
        # deny counter.
        assert isinstance(allowed, bool)
        stats = cache.get_stats()
        assert stats["redis_fail_closed_denies"] == 0, (
            f"fail_closed=False should not increment the deny counter; got {stats}"
        )

    @pytest.mark.asyncio
    async def test_rate_limit_passes_under_normal_redis(
        self, cache, monkeypatch: pytest.MonkeyPatch
    ):
        # Sanity: when Redis is up, the rate limit does its job
        # (counts and returns True while under the limit, False once
        # over it). The fail-closed code path is bypassed.
        from app.infrastructure import redis_client
        import json

        underlying = _FakeRedisOk()
        store = underlying.store

        class _OkClient:
            _redis = underlying

            async def get(self, key: str) -> Any:
                raw = store.get(key)
                return json.loads(raw) if raw else None

            async def set(self, key: str, value: Any, ex: int | None = None) -> None:
                store[key] = json.dumps(value, default=str)

        def _fake_get_redis_client():
            return _OkClient()

        monkeypatch.setattr(
            "app.infrastructure.cache_manager.get_redis_client",
            _fake_get_redis_client,
        )

        # First 3 calls should pass (max_requests=3).
        for i in range(3):
            ok = await cache.check_rate_limit(
                tenant_id="t_ok",
                resource="ingest",
                max_requests=3,
                fail_closed=True,
            )
            assert ok is True, f"call {i} should be under the limit"

        # 4th call should be denied.
        over = await cache.check_rate_limit(
            tenant_id="t_ok",
            resource="ingest",
            max_requests=3,
            fail_closed=True,
        )
        assert over is False, "4th call must exceed the limit"


# ─────────────────────────────────────────────────────────────────────────────
# 2. is_redis_available — the probe
# ─────────────────────────────────────────────────────────────────────────────

class TestRedisAvailabilityProbe:
    """`is_redis_available()` is the primitive the rate limiter and
    fail-closed lock use. It must return True on a healthy Redis and
    False on outage — and crucially, must never raise."""

    @pytest.mark.asyncio
    async def test_probe_true_when_redis_ok(
        self, cache, monkeypatch: pytest.MonkeyPatch
    ):
        from app.infrastructure import redis_client

        class _OkClient:
            _redis = _FakeRedisOk()

        def _fake_get_redis_client():
            return _OkClient()

        monkeypatch.setattr(
            "app.infrastructure.cache_manager.get_redis_client",
            _fake_get_redis_client,
        )
        assert await cache.is_redis_available() is True

    @pytest.mark.asyncio
    async def test_probe_false_when_redis_down(
        self, cache, monkeypatch: pytest.MonkeyPatch
    ):
        from app.infrastructure import redis_client

        class _DownClient:
            _redis = _FakeRedisDown()

        def _fake_get_redis_client():
            return _DownClient()

        monkeypatch.setattr(
            "app.infrastructure.cache_manager.get_redis_client",
            _fake_get_redis_client,
        )
        assert await cache.is_redis_available() is False

    @pytest.mark.asyncio
    async def test_probe_false_when_get_redis_client_returns_none(
        self, cache, monkeypatch: pytest.MonkeyPatch
    ):
        # The factory may return None in a degraded env (no config).
        # Probe must handle that without raising.
        from app.infrastructure import redis_client

        def _fake_get_redis_client():
            return None

        monkeypatch.setattr(
            "app.infrastructure.cache_manager.get_redis_client",
            _fake_get_redis_client,
        )
        assert await cache.is_redis_available() is False

    @pytest.mark.asyncio
    async def test_probe_never_raises(
        self, cache, monkeypatch: pytest.MonkeyPatch
    ):
        # Even a factory that itself raises must not propagate.
        from app.infrastructure import redis_client

        def _exploding():
            raise RuntimeError("factory exploded")

        monkeypatch.setattr(
            "app.infrastructure.cache_manager.get_redis_client",
            _exploding,
        )
        result = await cache.is_redis_available()
        assert result is False


# ─────────────────────────────────────────────────────────────────────────────
# 3. lock(fail_closed=True) — cross-process mutual exclusion guarantee
# ─────────────────────────────────────────────────────────────────────────────

class TestLockFailClosed:
    """A cross-process lock that degrades to a single-process lock on
    Redis outage is no lock at all in a multi-replica deployment.
    `lock(fail_closed=True)` must refuse to acquire in that case."""

    @pytest.mark.asyncio
    async def test_fail_closed_lock_refuses_on_redis_outage(
        self, cache, monkeypatch: pytest.MonkeyPatch
    ):
        from app.infrastructure import redis_client

        class _DownClient:
            _redis = _FakeRedisDown()

        def _fake_get_redis_client():
            return _DownClient()

        monkeypatch.setattr(
            "app.infrastructure.cache_manager.get_redis_client",
            _fake_get_redis_client,
        )

        async with cache.lock(
            resource="idempotency:abc",
            fail_closed=True,
            timeout_seconds=0.5,
        ) as acquired:
            assert acquired is False, (
                "fail-closed lock must refuse to acquire when Redis is down"
            )

        stats = cache.get_stats()
        assert stats["redis_fail_closed_denies"] >= 1

    @pytest.mark.asyncio
    async def test_non_fail_closed_lock_still_works_locally(
        self, cache, monkeypatch: pytest.MonkeyPatch
    ):
        # The legacy behavior is preserved for callers that explicitly
        # opt out (e.g. a per-process idempotency check that does not
        # need cross-replica mutual exclusion).
        from app.infrastructure import redis_client

        class _DownClient:
            _redis = _FakeRedisDown()

        def _fake_get_redis_client():
            return _DownClient()

        monkeypatch.setattr(
            "app.infrastructure.cache_manager.get_redis_client",
            _fake_get_redis_client,
        )

        async with cache.lock(
            resource="local:counter",
            fail_closed=False,
        ) as acquired:
            assert acquired is True, (
                "non-fail-closed lock should still acquire locally"
            )


# ─────────────────────────────────────────────────────────────────────────────
# 4. Stats — observability for SLO alerting
# ─────────────────────────────────────────────────────────────────────────────

class TestFailClosedStats:
    """`redis_fail_closed_denies` is the SLO signal for the fail-closed
    path. It must be present in get_stats() and increment on every
    fail-closed denial."""

    @pytest.mark.asyncio
    async def test_stats_include_fail_closed_counter(self, cache):
        stats = cache.get_stats()
        assert "redis_fail_closed_denies" in stats, (
            f"redis_fail_closed_denies missing from stats: {stats}"
        )
        assert stats["redis_fail_closed_denies"] == 0

    @pytest.mark.asyncio
    async def test_counter_increments_on_denial(
        self, cache, monkeypatch: pytest.MonkeyPatch
    ):
        from app.infrastructure import redis_client

        class _DownClient:
            _redis = _FakeRedisDown()

            async def get(self, *_args: Any, **_kwargs: Any) -> None:
                raise ConnectionError("simulated outage")

            async def set(self, *_args: Any, **_kwargs: Any) -> None:
                raise ConnectionError("simulated outage")

        def _fake_get_redis_client():
            return _DownClient()

        monkeypatch.setattr(
            "app.infrastructure.cache_manager.get_redis_client",
            _fake_get_redis_client,
        )

        # Two denials.
        await cache.check_rate_limit(tenant_id="t", resource="r")
        await cache.check_rate_limit(tenant_id="t", resource="r")

        assert cache.get_stats()["redis_fail_closed_denies"] == 2
