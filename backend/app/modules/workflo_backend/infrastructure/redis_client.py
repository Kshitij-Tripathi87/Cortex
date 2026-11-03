"""Redis client factory and cache utilities."""

from __future__ import annotations

import json
from typing import Any

import redis.asyncio as redis

from app.config import Settings


class RedisClient:
    """Async Redis client wrapper with JSON serialization."""

    # Step 2 (Redis latency regression): every Redis attempt is bounded.
    # Without these timeouts a dead `redis://localhost:6379` blocks for
    # the OS default TCP timeout (seconds to minutes depending on the
    # resolver) and turns the cache layer into a multi-second stop-the-
    # world on every hot-path call. 200 ms connect / 500 ms command is
    # generous for a healthy in-VPC Redis and lethal for a dead one:
    # the worst-case single attempt is 700 ms and the caller already
    # short-circuits on a cached `down` health signal.
    _SOCKET_CONNECT_TIMEOUT_S: float = 0.2
    _SOCKET_TIMEOUT_S: float = 0.5

    def __init__(self, settings: Settings) -> None:
        self._redis = redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=self._SOCKET_CONNECT_TIMEOUT_S,
            socket_timeout=self._SOCKET_TIMEOUT_S,
            # Do not retry timeouts: a 200 ms connect that times out is
            # a real outage, not a transient blip. Retrying would
            # multiply the latency by N backoff cycles and re-introduce
            # the regression we are fixing.
            retry_on_timeout=False,
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

    async def publish(self, channel: str, message: str) -> None:
        """Publish a message to a Redis Pub/Sub channel.

        Used by the realtime gateway for cross-node cluster fanout
        (see ``RealtimeGateway.broadcast``). Before this method
        existed the gateway called ``redis.publish(...)`` on the
        wrapper, which raised ``AttributeError`` — the raw client
        is what actually exposes ``publish``.
        """
        await self._redis.publish(channel, message)

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
