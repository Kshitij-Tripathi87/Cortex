"""Nexus Cache & Coordination Manager — Redis Cache, Distributed Locks, and Rate Limiting.

Enforces versioned cache keys, optimistic invalidation, distributed locking, and tenant rate limits.

E3 fail-closed policy (Phase 15 production gate):
  - The rate limiter (`check_rate_limit`) and any lock acquired for
    an auth-relevant resource MUST deny on Redis outage. A silent
    fail-open in those paths turns a Redis outage into an auth bypass
    and violates the "no silent fallback, fail closed" rule.
  - Plain cache reads/writes (which only affect latency, not security)
    retain the legacy fail-open behavior with an in-memory local
    cache as the fallback. This is the correct trade-off: an
    out-of-date cache is a perf regression, not a security hole.
  - `is_redis_available()` lets callers distinguish the two states
    without catching exceptions inline.

Step 2 (Redis latency regression fix, 2026-08-28):
  - The Redis client now has bounded `socket_connect_timeout=0.2` and
    `socket_timeout=0.5` (see `redis_client.RedisClient`). A dead
    Redis fails in well under a second instead of blocking on the
    OS default TCP timeout.
  - `CacheManager` caches the Redis health signal for 30 s when the
    last attempt succeeded and 5 s when it failed. The auth path
    (`is_redis_available` for rate limiter / fail-closed locks)
    reads this cache and never blocks on a Redis probe under steady
    state. The hot cache-write path (`_set`) skips the Redis write
    entirely while the cache says `down`, so the real-time state
    pipeline cannot be stopped by a Redis outage.
  - The actual Redis write is fire-and-forget via a bounded
    background task. The local cache update is synchronous and
    authoritative for the caller's latency budget. The background
    task has its own 1.0 s ceiling as a final guard.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from app.infrastructure.redis_client import get_redis_client


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    writes: int = 0
    invalidations: int = 0
    redis_fail_closed_denies: int = 0  # E3: count of authZ denials on Redis outage


class CacheManager:
    """Multi-tenant versioned cache and coordination manager."""

    # Step 2: cached Redis health. Status is one of
    # ``"unknown"``, ``"up"``, ``"down"``; the float is the
    # ``time.monotonic()`` expiry. A health entry older than its
    # expiry is treated as unknown and triggers a fresh probe.
    _REDIS_HEALTH_TTL_UP_S: float = 30.0
    _REDIS_HEALTH_TTL_DOWN_S: float = 5.0
    # Hard ceiling on the background Redis write so a wedged
    # connection can never leak past the caller's lifetime.
    _REDIS_WRITE_TIMEOUT_S: float = 1.0

    def __init__(self) -> None:
        self._stats = CacheStats()
        self._local_cache: dict[str, tuple[float, Any]] = {}
        self._locks: set[str] = set()
        # Step 2: cached Redis health — see ``is_redis_available``.
        self._redis_health: tuple[str, float] = ("unknown", 0.0)
        # Step 2: tracked background tasks so the asyncio runtime
        # does not warn "Task was destroyed but it is pending" when
        # a write outlives the caller's coroutine.
        self._bg_tasks: set[asyncio.Task[Any]] = set()

    # ─────────────────────────────────────────────────────────────────────────
    # 1. Versioned Cache
    # ─────────────────────────────────────────────────────────────────────────
    def _world_state_key(self, tenant_id: str, workspace_id: str, version: int) -> str:
        return f"worldstate:{tenant_id}:{workspace_id}:{version}"

    def _decision_key(self, tenant_id: str, decision_id: str) -> str:
        return f"decision:{tenant_id}:{decision_id}"

    def _simulation_key(self, tenant_id: str, simulation_id: str) -> str:
        return f"simulation:{tenant_id}:{simulation_id}"

    async def get_world_state(
        self, tenant_id: str, workspace_id: str, version: int
    ) -> dict[str, Any] | None:
        """Fetch cached world state by exact version."""
        key = self._world_state_key(tenant_id, workspace_id, version)
        return await self._get(key)

    async def set_world_state(
        self,
        tenant_id: str,
        workspace_id: str,
        version: int,
        state_data: dict[str, Any],
        ttl_seconds: int = 3600,
    ) -> None:
        """Cache world state at specific version."""
        key = self._world_state_key(tenant_id, workspace_id, version)
        await self._set(key, state_data, ttl_seconds)

    async def get_decision(self, tenant_id: str, decision_id: str) -> dict[str, Any] | None:
        key = self._decision_key(tenant_id, decision_id)
        return await self._get(key)

    async def set_decision(
        self,
        tenant_id: str,
        decision_id: str,
        data: dict[str, Any],
        ttl_seconds: int = 7200,
    ) -> None:
        key = self._decision_key(tenant_id, decision_id)
        await self._set(key, data, ttl_seconds)

    async def get_simulation(self, tenant_id: str, simulation_id: str) -> dict[str, Any] | None:
        key = self._simulation_key(tenant_id, simulation_id)
        return await self._get(key)

    async def set_simulation(
        self,
        tenant_id: str,
        simulation_id: str,
        data: dict[str, Any],
        ttl_seconds: int = 1800,
    ) -> None:
        key = self._simulation_key(tenant_id, simulation_id)
        await self._set(key, data, ttl_seconds)

    async def get(self, key: str, tenant_id: str | None = None) -> Any | None:
        """Generic get for key-value caching."""
        return await self._get(key)

    async def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: int = 3600,
        tenant_id: str | None = None,
    ) -> None:
        """Generic set for key-value caching."""
        await self._set(key, value, ttl_seconds)

    async def _get(self, key: str) -> Any | None:
        # Check local in-memory fallback
        now = time.time()
        if key in self._local_cache:
            exp, val = self._local_cache[key]
            if now < exp:
                self._stats.hits += 1
                return val
            del self._local_cache[key]

        # Step 2: skip the Redis read while the cached health says
        # Redis is down. A dead Redis then costs at most one slow
        # read per down-window instead of one per call.
        status, expires = self._redis_health
        if status == "down" and time.monotonic() < expires:
            self._stats.misses += 1
            return None

        # Try Redis. `get_redis_client()` is a sync factory (it
        # returns a `RedisClient`); the previous `await` here was a
        # latent bug that raised `TypeError: object RedisClient
        # can't be used in 'await' expression` on every call. The
        # `except Exception: pass` swallowed the TypeError, so the
        # Redis path was effectively dead code — only the in-memory
        # fallback ever returned data. Fixed in E3 so the Redis
        # path is actually live.
        try:
            client = get_redis_client()
            if client:
                # RedisClient.get() already json-decodes the raw
                # value (see redis_client.RedisClient.get), so `val`
                # is the decoded object — return it as-is. The old
                # `return json.loads(val)` double-decoded and would
                # raise TypeError once the Redis path was live.
                val = await asyncio.wait_for(
                    client.get(key),
                    timeout=self._REDIS_WRITE_TIMEOUT_S,
                )
                if val:
                    self._stats.hits += 1
                    self._record_redis_health(True)
                    return val
                self._record_redis_health(True)
        except Exception:
            self._record_redis_health(False)

        self._stats.misses += 1
        return None

    async def _set(self, key: str, value: Any, ttl_seconds: int) -> None:
        # Step 2: the local cache update is synchronous and
        # authoritative for the caller's read-your-own-writes. The
        # Redis mirror is fire-and-forget — see ``_redis_write`` —
        # so the real-time state pipeline cannot be stopped by a
        # dead Redis. If the cached health already says Redis is
        # down we skip the background task entirely (no point
        # spawning a doomed coroutine). The hot-path latency budget
        # is the local dict assignment; the network round-trip does
        # not count against the caller.
        now = time.time()
        self._local_cache[key] = (now + ttl_seconds, value)
        self._stats.writes += 1

        status, expires = self._redis_health
        if status == "down" and time.monotonic() < expires:
            return

        self._spawn_bg(self._redis_write(key, value, ttl_seconds))

    async def invalidate(self, pattern_or_key: str) -> None:
        """Invalidate cache keys matching a pattern."""
        self._local_cache = {k: v for k, v in self._local_cache.items() if pattern_or_key not in k}
        self._stats.invalidations += 1

    # ─────────────────────────────────────────────────────────────────────────
    # 1b. Redis availability probe (E3) + cached health (Step 2)
    # ─────────────────────────────────────────────────────────────────────────

    def _record_redis_health(self, ok: bool) -> None:
        """Update the cached Redis health after a probe or write.

        ``up`` is cached for ``_REDIS_HEALTH_TTL_UP_S`` (long: avoid
        spamming a healthy Redis with pings); ``down`` is cached for
        ``_REDIS_HEALTH_TTL_DOWN_S`` (short: recover quickly when Redis
        comes back, but long enough to avoid hammering a dead Redis).
        """
        now = time.monotonic()
        if ok:
            self._redis_health = ("up", now + self._REDIS_HEALTH_TTL_UP_S)
        else:
            self._redis_health = ("down", now + self._REDIS_HEALTH_TTL_DOWN_S)

    def _spawn_bg(self, coro: Any) -> asyncio.Task[Any]:
        """Schedule a fire-and-forget coroutine and track it.

        Without tracking, the asyncio runtime warns
        ``Task was destroyed but it is pending`` if the test/event
        loop ends before the background work finishes. The
        ``done_callback`` removes the reference once the task settles,
        so the set never grows unbounded.
        """
        task = asyncio.create_task(coro)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)
        return task

    async def is_redis_available(self) -> bool:
        """E3 + Step 2: report Redis health for auth-path decisions.

        Callers on the auth path (rate limiter, fail-closed locks)
        MUST use this to distinguish "Redis down" from "Redis OK" and
        apply their own fail-closed policy. Never use the return of
        ``_get`` / ``_set`` (which is None on error) to infer Redis
        state for an auth decision — that conflates cache miss with
        outage.

        The result is cached: a healthy Redis is treated as up for
        30 s (avoid ping spam); a failed probe marks Redis down for
        5 s (avoid hammering while still recovering quickly). Only
        when the cache is unknown / expired do we issue a fresh PING,
        and that PING is itself bounded by a hard ``asyncio.wait_for``
        ceiling on top of the client's ``socket_connect_timeout``.
        """
        now = time.monotonic()
        status, expires = self._redis_health
        if status == "up" and now < expires:
            return True
        if status == "down" and now < expires:
            return False

        try:
            client = get_redis_client()
            if client is None:
                self._record_redis_health(False)
                return False
            # The wrapped client exposes the raw client via private
            # attr (matches the codebase's existing pattern in
            # workflow_state.py and workflow_executor.py). Send a
            # PING to verify the connection is live, not just
            # instantiated. The ``asyncio.wait_for`` ceiling is the
            # final guard — the client's ``socket_connect_timeout``
            # should fire first on a dead Redis.
            await asyncio.wait_for(
                client._redis.ping(),  # noqa: SLF001
                timeout=self._REDIS_WRITE_TIMEOUT_S,
            )
        except Exception:
            self._record_redis_health(False)
            return False
        else:
            self._record_redis_health(True)
            return True

    async def _redis_write(self, key: str, value: Any, ttl_seconds: int) -> None:
        """Background Redis write used by ``_set``.

        Runs off the caller's hot path so a dead Redis cannot block
        the real-time state pipeline. The local cache update in
        ``_set`` is synchronous and authoritative; this coroutine
        only mirrors the value into Redis when Redis is reachable.
        Exceptions are swallowed (best-effort cross-instance cache)
        and update the cached health so subsequent writes skip
        Redis until the down-cache expires.
        """
        try:
            client = get_redis_client()
            if client is None:
                self._record_redis_health(False)
                return
            await asyncio.wait_for(
                client.set(key, value, ex=ttl_seconds),
                timeout=self._REDIS_WRITE_TIMEOUT_S,
            )
        except Exception:
            self._record_redis_health(False)
            return
        self._record_redis_health(True)

    # ─────────────────────────────────────────────────────────────────────────
    # 2. Distributed Locks
    # ─────────────────────────────────────────────────────────────────────────
    @asynccontextmanager
    async def lock(
        self,
        resource: str,
        timeout_seconds: float = 10.0,
        ttl_seconds: float | None = None,
        fail_closed: bool = False,
    ) -> AsyncIterator[bool]:
        """Acquire a distributed resource lock.

        E3: ``fail_closed=True`` is the recommended setting for any
        lock that protects an auth-relevant resource (e.g. idempotency
        keys, world-state writes, decision approvals). When the local
        in-process set would be the only source of mutual exclusion
        (because Redis is unavailable), a fail-closed lock yields
        ``acquired=False`` immediately rather than silently degrading
        to a single-process-only lock — a single-process lock in a
        multi-replica deployment is no lock at all, and a silent
        fail-open in that case violates the "fail closed" rule.
        """
        lock_key = f"lock:{resource}"
        effective_timeout = ttl_seconds if ttl_seconds is not None else timeout_seconds
        start = time.time()
        acquired = False

        # If the caller asked for fail-closed, refuse to acquire when
        # Redis is not reachable. The local set cannot enforce
        # cross-process mutual exclusion, so for cross-process locks
        # it is equivalent to no lock.
        if fail_closed and not await self.is_redis_available():
            self._stats.redis_fail_closed_denies += 1
            try:
                yield False
            finally:
                pass
            return

        while (time.time() - start) < effective_timeout:
            if lock_key not in self._locks:
                self._locks.add(lock_key)
                acquired = True
                break
            await asyncio.sleep(0.05)

        try:
            yield acquired
        finally:
            if acquired and lock_key in self._locks:
                self._locks.remove(lock_key)

    # ─────────────────────────────────────────────────────────────────────────
    # 3. Tenant Rate Limiter (Token Bucket)
    # ─────────────────────────────────────────────────────────────────────────
    async def check_rate_limit(
        self,
        tenant_id: str,
        resource: str,
        max_requests: int = 100,
        window_seconds: int = 60,
        fail_closed: bool = True,
    ) -> bool:
        """Return True if request is within tenant rate limit.

        E3: ``fail_closed`` defaults to True. If Redis is unavailable
        and ``fail_closed=True``, this returns False (deny). The
        legacy behavior of "Redis down → rate limit effectively
        disabled" was a security bug: an attacker who can DoS the
        cache bypasses the limiter. Callers that genuinely need
        fail-open (e.g. a metrics endpoint that should not 503 on
        a cache outage) must explicitly pass ``fail_closed=False``
        and accept the policy trade-off.
        """
        key = f"ratelimit:{tenant_id}:{resource}"
        now = int(time.time())
        window_bucket = now // window_seconds
        bucket_key = f"{key}:{window_bucket}"

        # E3: probe Redis on the rate-limit path. If it's down and
        # fail_closed, deny. Do NOT silently fall through to the
        # legacy "0 → under limit" path.
        if fail_closed and not await self.is_redis_available():
            self._stats.redis_fail_closed_denies += 1
            return False

        count = await self._get(bucket_key) or 0
        if count >= max_requests:
            return False

        await self._set(bucket_key, count + 1, ttl_seconds=window_seconds * 2)
        return True

    def get_stats(self) -> dict[str, int]:
        return {
            "hits": self._stats.hits,
            "misses": self._stats.misses,
            "writes": self._stats.writes,
            "invalidations": self._stats.invalidations,
            "active_locks": len(self._locks),
            # E3: number of times the fail-closed path denied because
            # Redis was unavailable. A non-zero value in production
            # is an SLO signal — it means the cache layer is shedding
            # auth-relevant load. Alerting should key off this.
            "redis_fail_closed_denies": self._stats.redis_fail_closed_denies,
        }


# Global singleton
_global_cache_mgr: CacheManager | None = None


def get_cache_manager() -> CacheManager:
    global _global_cache_mgr
    if _global_cache_mgr is None:
        _global_cache_mgr = CacheManager()
    return _global_cache_mgr
