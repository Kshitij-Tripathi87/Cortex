"""Nexus v1.0 P0 / v0.8.3 — Multi-worker realtime bus & Outbox Fabric.

Implements the production realtime fabric on top of Redis Pub/Sub with
outbox durability and exactly-once processing guarantees for clients:

    Outbox (PG tx with in-transaction seq allocation)
       ↓
    Outbox Publisher (FOR UPDATE SKIP LOCKED sweeper)
       ↓
    Redis Pub/Sub (per-workspace channel)
       ↓
    Nexus workers (fan-out)
       ↓
    SSE / WebSocket (with monotonic sequence numbers, gap detection, durable replay)

Guarantees:
    at-least-once delivery     events persist in PG outbox table (`nexus_events`)
    idempotent consumer        clients key off event_id; duplicates are no-ops
    sequence numbers           per-workspace monotonic DB-allocated sequence
    gap detection              clients detect missed sequence numbers and resync
    replay/resync              on connect or gap, client replays from outbox cursor
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import threading
from collections import defaultdict
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

CHANNEL_PREFIX = "nexus:events:"  # + workspace_id
SEQ_KEY_PREFIX = "nexus:seq:"  # + workspace_id (legacy non-outbox paths only)


class Event:
    __slots__ = (
        "event_id",
        "seq",
        "event_type",
        "entity_type",
        "entity_id",
        "payload",
        "world_state_version",
        "correlation_id",
        "timestamp",
    )

    def __init__(
        self,
        event_id: str,
        seq: int,
        event_type: str,
        entity_type: str | None,
        entity_id: str | None,
        payload: dict[str, Any],
        world_state_version: int | None,
        correlation_id: str | None = None,
        timestamp: str | None = None,
    ) -> None:
        self.event_id = event_id
        self.seq = seq
        self.event_type = event_type
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.payload = payload
        self.world_state_version = world_state_version
        self.correlation_id = correlation_id
        self.timestamp = timestamp or datetime.now(UTC).isoformat()

    def to_sse(self) -> str:
        data = {
            "event_id": self.event_id,
            "seq": self.seq,
            "type": self.event_type,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "payload": self.payload,
            "world_state_version": self.world_state_version,
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp,
        }
        return f"event: {self.event_type}\ndata: {json.dumps(data)}\n\n"

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "seq": self.seq,
            "type": self.event_type,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "payload": self.payload,
            "world_state_version": self.world_state_version,
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp,
        }


class IdempotentEventConsumer:
    """Idempotent consumer wrapper keyed off event_id.

    Replays and duplicate deliveries of the same event_id are ignored.
    """

    def __init__(self, max_seen: int = 10000) -> None:
        self._seen: set[str] = set()
        self._order: list[str] = []
        self._max_seen = max_seen
        self._lock = threading.Lock()

    def is_duplicate(self, event_id: str) -> bool:
        with self._lock:
            return event_id in self._seen

    def record(self, event_id: str) -> bool:
        """Record an event_id. Returns True if fresh (applied), False if duplicate."""
        with self._lock:
            if event_id in self._seen:
                return False
            self._seen.add(event_id)
            self._order.append(event_id)
            if len(self._order) > self._max_seen:
                oldest = self._order.pop(0)
                self._seen.discard(oldest)
            return True

    def clear(self) -> None:
        with self._lock:
            self._seen.clear()
            self._order.clear()


class RealtimeBus:
    """Multi-worker realtime event bus.

    In v0.8.3, sequence numbers are allocated in-transaction by the database
    outbox. When `publish_from_outbox` is called by the `OutboxPublisher`:
      1. Sequence number arrives with the event (DB-allocated authority)
      2. Publishes to Redis Pub/Sub for cross-node fanout
      3. Fans out to local subscribers on this worker
      4. Buffers for immediate catch-up replay
    """

    def __init__(self) -> None:
        self._local_subscribers: dict[str, set[asyncio.Queue[Any]]] = defaultdict(set)
        self._lock = threading.RLock()
        self._redis_tasks: dict[str, asyncio.Task[None]] = {}
        self._redis_client: Any = None  # RedisClient | False | None
        self._local_seq_workspaces: set[str] = set()

    def _get_redis(self) -> Any:
        if self._redis_client is False:
            return None
        if self._redis_client is None:
            try:
                import redis.asyncio as _  # noqa: F401  probe for redis lib

                from app.infrastructure.redis_client import get_redis_client

                self._redis_client = get_redis_client()
            except Exception:  # noqa: BLE001
                self._redis_client = False
                return None
        return self._redis_client

    # ── Local subscriber management (SSE connections per worker) ───

    def subscribe(self, workspace_id: str) -> asyncio.Queue[Any]:
        """Subscribe to events for a workspace. Returns an async queue."""
        queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=1000)
        with self._lock:
            self._local_subscribers[workspace_id].add(queue)
            self._ensure_redis_subscription(workspace_id)
        return queue

    def unsubscribe(self, workspace_id: str, queue: asyncio.Queue[Any]) -> None:
        with self._lock:
            subs = self._local_subscribers.get(workspace_id)
            if subs:
                subs.discard(queue)
                if not subs:
                    self._cancel_redis_subscription(workspace_id)

    async def _fan_out_local(self, workspace_id: str, event: Event) -> None:
        with self._lock:
            subs = list(self._local_subscribers.get(workspace_id, set()))
        for q in subs:
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(event)

    # ── Redis pub/sub ──────────────────────────────────────────────

    def _ensure_redis_subscription(self, workspace_id: str) -> None:
        """Start a Redis subscription task if not already running."""
        if workspace_id in self._redis_tasks:
            return
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(self._redis_listener(workspace_id))
            self._redis_tasks[workspace_id] = task
        except RuntimeError:
            # No running loop (startup or tests); subscription will be
            # re-attempted on first publish with a loop.
            pass

    def _cancel_redis_subscription(self, workspace_id: str) -> None:
        task = self._redis_tasks.pop(workspace_id, None)
        if task and not task.done():
            task.cancel()

    async def _redis_listener(self, workspace_id: str) -> None:
        """Listen for Redis messages for a workspace and fan out locally."""
        channel = CHANNEL_PREFIX + workspace_id
        try:
            r = self._get_redis()
            if r is None:
                return  # Redis unavailable; local-only mode
            pubsub = r._redis.pubsub()
            await pubsub.subscribe(channel)
            try:
                async for message in pubsub.listen():
                    if message["type"] != "message":
                        continue
                    try:
                        data = json.loads(message["data"])
                        event = Event(
                            event_id=data["event_id"],
                            seq=data["seq"],
                            event_type=data.get("type") or data.get("event_type", "UNKNOWN"),
                            entity_type=data.get("entity_type"),
                            entity_id=data.get("entity_id"),
                            payload=data.get("payload", {}),
                            world_state_version=data.get("world_state_version"),
                            correlation_id=data.get("correlation_id"),
                            timestamp=data.get("timestamp"),
                        )
                        await self._fan_out_local(workspace_id, event)
                    except Exception:  # noqa: BLE001, PERF203, S112
                        continue
            finally:
                await pubsub.unsubscribe(channel)
        except asyncio.CancelledError:
            pass
        except Exception:  # noqa: BLE001, S110
            pass

    # ── Outbox-First Publishing (v0.8.3 Authority) ─────────────────

    async def publish_from_outbox(
        self,
        event: Any,
        *,
        workspace_id: str | None = None,
        tenant_id: str | None = None,
    ) -> Event:
        """Publish an outbox event. Monotonic sequence is allocated by the DB.

        Accepts an `EventRecordDB` instance, an `Event` object, or a dict.
        """
        if isinstance(event, Event):
            ev = event
            ws = workspace_id or ev.payload.get("workspace_id") or "default"
        elif hasattr(event, "event_id") and hasattr(event, "seq"):
            # EventRecordDB or compatible model
            ev = Event(
                event_id=event.event_id,
                seq=event.seq,
                event_type=getattr(event, "event_type", "outbox_event"),
                entity_type=getattr(event, "entity_type", None),
                entity_id=getattr(event, "entity_id", None),
                payload=getattr(event, "payload", {}) or {},
                world_state_version=getattr(event, "world_state_version", None),
                correlation_id=getattr(event, "correlation_id", None),
                timestamp=(
                    event.created_at.isoformat()
                    if getattr(event, "created_at", None)
                    else datetime.now(UTC).isoformat()
                ),
            )
            ws = workspace_id or getattr(event, "workspace_id", None) or "default"
        elif isinstance(event, dict):
            ev = Event(
                event_id=event["event_id"],
                seq=event["seq"],
                event_type=event.get("event_type") or event.get("type", "outbox_event"),
                entity_type=event.get("entity_type"),
                entity_id=event.get("entity_id"),
                payload=event.get("payload", {}),
                world_state_version=event.get("world_state_version"),
                correlation_id=event.get("correlation_id"),
                timestamp=event.get("timestamp"),
            )
            ws = workspace_id or event.get("workspace_id") or "default"
        else:
            raise TypeError(f"Cannot publish event of type {type(event)}")

        # Publish to Redis fabric
        r = self._get_redis()
        if r is not None and ws:
            channel = CHANNEL_PREFIX + ws
            # If Redis publish fails, exception propagates to OutboxPublisher
            # so publish_attempts can be incremented and retried.
            await r.publish(channel, json.dumps(ev.to_dict()))

        # Local worker fanout
        if ws:
            await self._fan_out_local(ws, ev)
            self.buffer_for_replay(ws, ev)

        return ev

    # ── Legacy/Demo Publishing (Non-outbox paths) ───────────────────

    async def publish(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        event_type: str,
        entity_type: str | None = None,
        entity_id: str | None = None,
        payload: dict[str, Any] | None = None,
        world_state_version: int | None = None,
        correlation_id: str | None = None,
    ) -> Event:
        """Publish an ephemeral event (non-outbox path)."""
        r = None if workspace_id in self._local_seq_workspaces else self._get_redis()
        seq_key = SEQ_KEY_PREFIX + workspace_id
        seq = None
        if r is not None:
            try:
                seq = await r._redis.incr(seq_key)
            except Exception:
                seq = None
        if seq is None:
            self._local_seq_workspaces.add(workspace_id)
            seq = _local_seq(workspace_id)

        event = Event(
            event_id=f"EVT-{uuid4().hex[:10]}",
            seq=seq,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload or {},
            world_state_version=world_state_version,
            correlation_id=correlation_id,
        )

        if r is not None:
            channel = CHANNEL_PREFIX + workspace_id
            with contextlib.suppress(Exception):
                await r.publish(channel, json.dumps(event.to_dict()))

        await self._fan_out_local(workspace_id, event)
        self.buffer_for_replay(workspace_id, event)
        return event

    # ── Replay from DB outbox / in-memory buffer ───────────────────

    async def replay_since(
        self,
        workspace_id: str,
        since_seq: int,
        limit: int = 500,
        session: AsyncSession | None = None,
        tenant_id: str | None = None,
    ) -> list[Event]:
        """Replay events for a workspace since a given sequence number.

        When a database session is provided, queries the durable `nexus_events`
        table. Otherwise, falls back to the in-memory circular replay buffer.
        """
        if session is not None:
            from sqlalchemy import select

            from app.modules.nexus_spine.persistence.models import EventRecordDB

            stmt = select(EventRecordDB).where(
                EventRecordDB.workspace_id == workspace_id,
                EventRecordDB.seq > since_seq,
            )
            if tenant_id is not None:
                stmt = stmt.where(EventRecordDB.tenant_id == tenant_id)

            stmt = stmt.order_by(EventRecordDB.seq.asc()).limit(limit)
            result = await session.execute(stmt)
            records = result.scalars().all()
            return [
                Event(
                    event_id=r.event_id,
                    seq=r.seq,
                    event_type=r.event_type,
                    entity_type=r.entity_type,
                    entity_id=r.entity_id,
                    payload=r.payload or {},
                    world_state_version=r.world_state_version,
                    correlation_id=r.correlation_id,
                    timestamp=r.created_at.isoformat() if r.created_at else None,
                )
                for r in records
            ]

        # In-memory buffer fallback
        with self._lock:
            buf = _replay_buffers.get(workspace_id, [])
        results = [e for e in buf if e.seq > since_seq]
        return results[:limit]

    def buffer_for_replay(self, workspace_id: str, event: Event) -> None:
        """Add event to circular replay buffer."""
        with self._lock:
            buf = _replay_buffers.setdefault(workspace_id, [])
            buf.append(event)
            if len(buf) > 1000:
                del buf[: len(buf) - 1000]


# Per-process fallback sequence counter (for ephemeral non-transactional paths)
_local_counters: dict[str, int] = defaultdict(int)
_counter_lock = threading.Lock()


def _local_seq(workspace_id: str) -> int:
    with _counter_lock:
        _local_counters[workspace_id] += 1
        return 1_000_000_000 + _local_counters[workspace_id]


# In-memory circular replay buffer
_replay_buffers: dict[str, list[Event]] = {}


# SSE streaming helper
async def sse_stream(
    workspace_id: str,
    last_seen_seq: int = 0,
    session: AsyncSession | None = None,
    tenant_id: str | None = None,
    bus: RealtimeBus | None = None,
) -> AsyncIterator[str]:
    """Generate an SSE stream for a workspace with gap-resilient semantics."""
    b = bus or get_realtime_bus()
    queue = b.subscribe(workspace_id)
    try:
        # Initial connection handshake
        yield f"event: connected\ndata: {json.dumps({'workspace_id': workspace_id, 'last_seen_seq': last_seen_seq})}\n\n"

        # Replay missed events from outbox / buffer
        missed = await b.replay_since(
            workspace_id=workspace_id,
            since_seq=last_seen_seq,
            session=session,
            tenant_id=tenant_id,
        )
        for event in missed:
            yield event.to_sse()

        prev_seq = last_seen_seq if not missed else missed[-1].seq
        while True:
            event = await queue.get()
            # Skip events already seen or covered in replay
            if event.seq <= prev_seq:
                continue
            # Gap detection: if next sequence is not strictly prev_seq + 1
            if prev_seq > 0 and event.seq > prev_seq + 1:
                yield f"event: resync_needed\ndata: {json.dumps({'from_seq': prev_seq, 'to_seq': event.seq})}\n\n"
                break
            yield event.to_sse()
            b.buffer_for_replay(workspace_id, event)
            prev_seq = event.seq
    finally:
        b.unsubscribe(workspace_id, queue)


_singleton: RealtimeBus | None = None


def get_realtime_bus() -> RealtimeBus:
    global _singleton
    if _singleton is None:
        _singleton = RealtimeBus()
    return _singleton
