"""World State Caching — Redis-backed cache for snapshots and twins.

Program J (Workstream I) performance layer:

Caching strategy:
- Snapshot Cache: cache frequently accessed snapshots
- Twin Cache: cache active twin state
- Rule Cache: cache compiled knowledge rules

Performance targets:
- Replay: <500 ms (with cache hits)
- Clone: <200 ms (snapshot cache + memory isolation)
- Simulation: <3 s (30 ticks)
- Diff: <100 ms (cached states)

This module provides an in-memory cache implementation that mirrors
the Redis interface, allowing easy migration to Redis in production.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.modules.world.world_models import WorldSnapshot, WorldState


@dataclass(frozen=True)
class CacheStats:
    """Cache hit/miss statistics."""

    hits: int = 0
    misses: int = 0
    evictions: int = 0
    sets: int = 0
    total_size: int = 0
    hit_rate: float = 0.0


@dataclass(frozen=True)
class CacheEntry:
    """A single cache entry with TTL."""

    key: str
    value: Any
    created_at: datetime
    expires_at: datetime | None
    hits: int = 0


class TTLCache:
    """In-memory cache with TTL and LRU eviction.

    Drop-in replacement for Redis cache with same interface:
    - get(key) -> value or None
    - set(key, value, ttl_seconds=None)
    - delete(key)
    - clear()
    - stats()
    """

    def __init__(self, name: str, max_size: int = 1000, default_ttl_seconds: int | None = None):
        self.name = name
        self.max_size = max_size
        self.default_ttl_seconds = default_ttl_seconds
        self._store: OrderedDict[str, CacheEntry] = OrderedDict()
        self._stats = CacheStats()

    def get(self, key: str) -> Any | None:
        """Get value from cache."""
        entry = self._store.get(key)
        if entry is None:
            self._stats = self._stats.__class__(
                **{**self._stats.__dict__, "misses": self._stats.misses + 1}
            )
            self._update_hit_rate()
            return None

        # Check expiration
        if entry.expires_at is not None and datetime.now() > entry.expires_at:
            del self._store[key]
            self._stats = self._stats.__class__(
                **{
                    **self._stats.__dict__,
                    "misses": self._stats.misses + 1,
                    "total_size": len(self._store),
                }
            )
            self._update_hit_rate()
            return None

        # LRU: move to end
        self._store.move_to_end(key)
        self._store[key] = CacheEntry(
            key=entry.key,
            value=entry.value,
            created_at=entry.created_at,
            expires_at=entry.expires_at,
            hits=entry.hits + 1,
        )

        self._stats = self._stats.__class__(
            **{**self._stats.__dict__, "hits": self._stats.hits + 1}
        )
        self._update_hit_rate()
        return entry.value

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        """Set value in cache with optional TTL."""
        ttl = ttl_seconds or self.default_ttl_seconds
        expires_at = None
        if ttl is not None:
            from datetime import timedelta

            expires_at = datetime.now() + timedelta(seconds=ttl)

        self._store[key] = CacheEntry(
            key=key,
            value=value,
            created_at=datetime.now(),
            expires_at=expires_at,
        )
        self._store.move_to_end(key)

        # Evict if over capacity
        while len(self._store) > self.max_size:
            self._store.popitem(last=False)
            self._stats = self._stats.__class__(
                **{**self._stats.__dict__, "evictions": self._stats.evictions + 1}
            )

        self._stats = self._stats.__class__(
            **{**self._stats.__dict__, "sets": self._stats.sets + 1, "total_size": len(self._store)}
        )
        self._update_hit_rate()

    def delete(self, key: str) -> bool:
        """Delete entry from cache. Returns True if deleted."""
        if key in self._store:
            del self._store[key]
            self._stats = self._stats.__class__(
                **{**self._stats.__dict__, "total_size": len(self._store)}
            )
            return True
        return False

    def clear(self) -> None:
        """Clear all entries."""
        self._store.clear()
        self._stats = CacheStats()

    def stats(self) -> CacheStats:
        """Get current cache statistics."""
        return self._stats

    def _update_hit_rate(self) -> None:
        total = self._stats.hits + self._stats.misses
        rate = self._stats.hits / total if total > 0 else 0.0
        self._stats = self._stats.__class__(**{**self._stats.__dict__, "hit_rate": rate})


# ─────────────────────────────────────────────────────────────────────────────
# Specialized Caches
# ─────────────────────────────────────────────────────────────────────────────


class SnapshotCache:
    """Cache for world state snapshots."""

    def __init__(self, max_size: int = 500, ttl_seconds: int = 3600):
        self._cache = TTLCache(
            name="snapshots",
            max_size=max_size,
            default_ttl_seconds=ttl_seconds,
        )

    def get(self, snapshot_id: str) -> WorldSnapshot | None:
        return self._cache.get(snapshot_id)

    def set(self, snapshot: WorldSnapshot, ttl_seconds: int | None = None) -> None:
        self._cache.set(snapshot.snapshot_id, snapshot, ttl_seconds)

    def invalidate(self, snapshot_id: str) -> bool:
        return self._cache.delete(snapshot_id)

    def stats(self) -> CacheStats:
        return self._cache.stats()


class StateCache:
    """Cache for materialized world states."""

    def __init__(self, max_size: int = 200, ttl_seconds: int = 600):
        self._cache = TTLCache(
            name="states",
            max_size=max_size,
            default_ttl_seconds=ttl_seconds,
        )

    def get(self, world_id: str, version: int | None = None) -> WorldState | None:
        key = f"{world_id}:{version}" if version is not None else f"{world_id}:latest"
        return self._cache.get(key)

    def set(self, state: WorldState, ttl_seconds: int | None = None) -> None:
        key = f"{state.world_id}:{state.version}"
        self._cache.set(key, state, ttl_seconds)
        # Also cache as latest
        self._cache.set(f"{state.world_id}:latest", state, ttl_seconds)

    def invalidate(self, world_id: str) -> None:
        self._cache.delete(f"{world_id}:latest")
        # In production, we'd iterate all versions

    def stats(self) -> CacheStats:
        return self._cache.stats()


class TwinCache:
    """Cache for active digital twins."""

    def __init__(self, max_size: int = 100, ttl_seconds: int = 1800):
        self._cache: TTLCache = TTLCache(
            name="twins",
            max_size=max_size,
            default_ttl_seconds=ttl_seconds,
        )

    def get(self, twin_id: str) -> Any | None:
        return self._cache.get(twin_id)

    def set(self, twin_id: str, twin_data: Any, ttl_seconds: int | None = None) -> None:
        self._cache.set(twin_id, twin_data, ttl_seconds)

    def invalidate(self, twin_id: str) -> bool:
        return self._cache.delete(twin_id)

    def stats(self) -> CacheStats:
        return self._cache.stats()


class RuleCache:
    """Cache for compiled knowledge rules."""

    def __init__(self, max_size: int = 500, ttl_seconds: int = 1800):
        self._cache: TTLCache = TTLCache(
            name="rules",
            max_size=max_size,
            default_ttl_seconds=ttl_seconds,
        )

    def get(self, rule_id: str) -> Any | None:
        return self._cache.get(rule_id)

    def set(self, rule_id: str, rule_data: Any, ttl_seconds: int | None = None) -> None:
        self._cache.set(rule_id, rule_data, ttl_seconds)

    def invalidate(self, rule_id: str) -> bool:
        return self._cache.delete(rule_id)

    def stats(self) -> CacheStats:
        return self._cache.stats()


# ─────────────────────────────────────────────────────────────────────────────
# Performance Benchmarks
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BenchmarkResult:
    """Result of a performance benchmark."""

    operation: str
    duration_ms: float
    target_ms: float
    passed: bool
    details: dict[str, Any] = field(default_factory=dict)


class PerformanceBenchmark:
    """Run benchmarks against Program J performance targets.

    Targets:
    - Replay: <500 ms
    - Clone: <200 ms
    - Simulation: <3 s (30 ticks)
    - Diff: <100 ms
    """

    def __init__(self) -> None:
        self._results: list[BenchmarkResult] = []

    def benchmark_replay(
        self, replay_fn: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> BenchmarkResult:
        """Benchmark replay operation. Target: <500 ms."""
        start = time.perf_counter()
        result = replay_fn(*args, **kwargs)
        duration_ms = (time.perf_counter() - start) * 1000

        bench = BenchmarkResult(
            operation="replay",
            duration_ms=duration_ms,
            target_ms=500,
            passed=duration_ms < 500,
            details={"result": str(result)[:100]},
        )
        self._results.append(bench)
        return bench

    def benchmark_clone(
        self, clone_fn: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> BenchmarkResult:
        """Benchmark clone operation. Target: <200 ms."""
        start = time.perf_counter()
        result = clone_fn(*args, **kwargs)
        duration_ms = (time.perf_counter() - start) * 1000

        bench = BenchmarkResult(
            operation="clone",
            duration_ms=duration_ms,
            target_ms=200,
            passed=duration_ms < 200,
            details={"result": str(result)[:100]},
        )
        self._results.append(bench)
        return bench

    def benchmark_diff(
        self, diff_fn: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> BenchmarkResult:
        """Benchmark diff operation. Target: <100 ms."""
        start = time.perf_counter()
        result = diff_fn(*args, **kwargs)
        duration_ms = (time.perf_counter() - start) * 1000

        bench = BenchmarkResult(
            operation="diff",
            duration_ms=duration_ms,
            target_ms=100,
            passed=duration_ms < 100,
            details={"result": str(result)[:100]},
        )
        self._results.append(bench)
        return bench

    def get_results(self) -> list[BenchmarkResult]:
        return list(self._results)

    def all_passed(self) -> bool:
        return all(r.passed for r in self._results)


# ─────────────────────────────────────────────────────────────────────────────
# Cache Manager (singleton-style convenience)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class CacheManager:
    """Manages all caches."""

    snapshots: SnapshotCache = field(default_factory=SnapshotCache)
    states: StateCache = field(default_factory=StateCache)
    twins: TwinCache = field(default_factory=TwinCache)
    rules: RuleCache = field(default_factory=RuleCache)

    def all_stats(self) -> dict[str, CacheStats]:
        return {
            "snapshots": self.snapshots.stats(),
            "states": self.states.stats(),
            "twins": self.twins.stats(),
            "rules": self.rules.stats(),
        }

    def clear_all(self) -> None:
        self.snapshots._cache.clear()
        self.states._cache.clear()
        self.twins._cache.clear()
        self.rules._cache.clear()
