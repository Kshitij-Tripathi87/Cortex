"""Graph Cache — optional caching layer for traversal results.

The cache stores the result of expensive operations (neighborhoods,
shortest paths, reachability sets) keyed by (workspace_id, snapshot_version,
operation, args). The cache is invalidated whenever a new snapshot is
sealed for a workspace.

Two implementations are provided:
  - NoOpCache     — does nothing; default in tests and dev
  - RedisCache    — backed by Redis in staging/prod

The Protocol is async so swapping implementations is transparent.
Programs C–E (features, signals, propagation) should construct a cache
once and pass it through.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

# Cache TTL — 1 hour. Traversals don't change between snapshots.
CACHE_TTL_SECONDS = 3600


class GraphCache(Protocol):
    """Async cache for graph traversal results."""

    async def get(self, key: str) -> Any | None: ...
    async def set(self, key: str, value: Any, ttl: int = CACHE_TTL_SECONDS) -> None: ...
    async def invalidate_workspace(self, workspace_id: str) -> None: ...
    async def invalidate_snapshot(self, workspace_id: str, version: int) -> None: ...


class NoOpCache:
    """Default cache — does nothing. Use in tests and dev environments."""

    async def get(self, key: str) -> Any | None:
        return None

    async def set(self, key: str, value: Any, ttl: int = CACHE_TTL_SECONDS) -> None:
        pass

    async def invalidate_workspace(self, workspace_id: str) -> None:
        pass

    async def invalidate_snapshot(self, workspace_id: str, version: int) -> None:
        pass


class RedisCache:
    """Redis-backed cache for staging and prod.

    Stores values as JSON. Key prefix: `cortex:graph:{workspace}:{version}:{op}:{args_hash}`.
    Invalidates by deleting keys matching the workspace prefix when a new
    snapshot is sealed.

    Usage:
        from app.infrastructure.redis_client import get_redis_client
        redis_client = get_redis_client()
        cache = RedisCache(redis_client)
        await cache.set("ws-1:1:neighbors:SUP-001", [...])
        result = await cache.get("ws-1:1:neighbors:SUP-001")
    """

    KEY_PREFIX = "cortex:graph"

    def __init__(self, redis_client: Any) -> None:
        self._redis = redis_client

    def _build_key(
        self,
        workspace_id: str,
        version: int,
        operation: str,
        args_hash: str,
    ) -> str:
        return f"{self.KEY_PREFIX}:{workspace_id}:{version}:{operation}:{args_hash}"

    async def get(self, key: str) -> Any | None:
        raw = await self._redis.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    async def set(self, key: str, value: Any, ttl: int = CACHE_TTL_SECONDS) -> None:
        await self._redis.set(key, json.dumps(value, default=str), ex=ttl)

    async def invalidate_workspace(self, workspace_id: str) -> None:
        """Delete every cache entry for a workspace.

        Uses SCAN with the workspace prefix to avoid blocking on KEYS.
        """
        pattern = f"{self.KEY_PREFIX}:{workspace_id}:*"
        async for key in self._redis.scan_iter(pattern):
            await self._redis.delete(key)

    async def invalidate_snapshot(
        self,
        workspace_id: str,
        version: int,
    ) -> None:
        """Invalidate everything for a specific snapshot version."""
        pattern = f"{self.KEY_PREFIX}:{workspace_id}:{version}:*"
        async for key in self._redis.scan_iter(pattern):
            await self._redis.delete(key)


def make_cache_key(
    workspace_id: str,
    version: int,
    operation: str,
    args: dict[str, Any],
) -> str:
    """Deterministic cache key builder.

    args is JSON-serialized with sorted keys so equivalent args produce
    identical keys. This means the cache is order-invariant in its
    arguments — same operation with same args hits cache.
    """
    import hashlib

    args_str = json.dumps(args, sort_keys=True, default=str, separators=(",", ":"))
    args_hash = hashlib.sha256(args_str.encode("utf-8")).hexdigest()[:16]
    return f"cortex:graph:{workspace_id}:{version}:{operation}:{args_hash}"


def create_cache(settings: Any | None = None) -> GraphCache:
    """Create appropriate cache implementation based on configuration.

    Returns RedisCache if Redis is configured, NoOpCache otherwise.

    Usage:
        from app.config import get_settings
        settings = get_settings()
        cache = create_cache(settings)
    """
    if settings is None:
        from app.config import get_settings

        settings = get_settings()

    # Check if Redis URL is configured
    if not settings.redis_url:
        return NoOpCache()

    try:
        from app.infrastructure.redis_client import get_redis_client

        redis_client = get_redis_client(settings)
        return RedisCache(redis_client)
    except Exception:
        # Redis connection failed, fall back to NoOpCache
        return NoOpCache()
