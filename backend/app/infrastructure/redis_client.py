"""Redis client factory and cache utilities."""

from __future__ import annotations

import json
from typing import Any

import redis.asyncio as redis

from app.config import Settings


class RedisClient:
    """Async Redis client wrapper with JSON serialization."""

    def __init__(self, settings: Settings) -> None:
        self._redis = redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )

    async def get(self, key: str) -> Any | None:
        """Get a value from Redis."""
        raw = await self._redis.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    async def set(
        self,
        key: str,
        value: Any,
        ex: int | None = None,
    ) -> None:
        """Set a value in Redis with optional TTL."""
        await self._redis.set(key, json.dumps(value, default=str), ex=ex)

    async def delete(self, key: str) -> None:
        """Delete a key from Redis."""
        await self._redis.delete(key)

    async def scan_iter(self, match: str | None = None):
        """Iterate over keys matching a pattern."""
        async for key in self._redis.scan_iter(match=match):
            yield key

    async def close(self) -> None:
        """Close the Redis connection."""
        await self._redis.close()


_redis_client: RedisClient | None = None


def get_redis_client(settings: Settings | None = None) -> RedisClient:
    """Get or create the global Redis client."""
    global _redis_client
    if _redis_client is None:
        from app.config import get_settings

        _redis_client = RedisClient(settings or get_settings())
    return _redis_client


def reset_redis_client() -> None:
    """Reset the global Redis client (for testing)."""
    global _redis_client
    if _redis_client is not None:
        import asyncio

        asyncio.get_event_loop().run_until_complete(_redis_client.close())
    _redis_client = None


def make_cache_key(*parts: str) -> str:
    """Build a cache key from parts."""
    return ":".join(parts)
