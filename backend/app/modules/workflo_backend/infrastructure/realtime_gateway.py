"""Nexus Real-Time Gateway — WebSocket Fanout & Multi-Node Clustered Event Streaming.

Provides real-time browser streams for:
- world-state changes
- simulation progress
- agent message deliberation (Decision Room)
- decision approvals & execution updates

Clustering:
- Supports multi-instance horizontal scaling via Redis Pub/Sub coordination
- Local in-memory session tracking with cross-node fanout

Security:
- Scoped at handshake to user's authorized tenant and workspace
- Client subscriptions outside authorized scope are strictly rejected
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from fastapi import WebSocket

from app.infrastructure.redis_client import get_redis_client


class RealtimeChannel(StrEnum):
    WORLD_STATE = "world-state"
    SCENARIOS = "scenarios"
    SIMULATIONS = "simulations"
    AGENT_MESSAGES = "agent-messages"
    DECISIONS = "decisions"
    EXECUTION = "execution"
    MEMORY = "memory"


@dataclass
class ConnectionSession:
    """Active client WebSocket session with strict authorization context."""

    session_id: str
    user_id: str
    tenant_id: str
    workspace_id: str
    websocket: WebSocket
    subscribed_channels: set[str] = field(default_factory=set)
    connected_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def can_subscribe(self, target_workspace_id: str, channel: str) -> bool:
        """Enforce that client can only subscribe to their authorized workspace."""
        return target_workspace_id == self.workspace_id


class RealtimeGateway:
    """Manages active WebSocket connections and broadcasts tenant-scoped events across cluster nodes."""

    def __init__(self, node_id: str = "node_default") -> None:
        self.node_id = node_id
        self._sessions: dict[str, ConnectionSession] = {}
        self._lock = asyncio.Lock()
        self._cluster_channel = "cortex:realtime:cluster_events"
        # Step 4: track fire-and-forget cluster-publish tasks so the
        # asyncio runtime does not warn "Task was destroyed but it is
        # pending" when a publish outlives the caller's coroutine.
        self._fanout_tasks: set[asyncio.Task[Any]] = set()
        # Step 4: observability for silent-failure surfaces. The cluster
        # fanout is best-effort, but a failure must be countable so a
        # persistent outage shows up in metrics instead of vanishing.
        self.cluster_fanout_failures: int = 0

    def _spawn_fanout(self, coro: Any) -> None:
        """Schedule a bounded cluster-publish task and track it."""
        task = asyncio.create_task(coro)
        self._fanout_tasks.add(task)
        task.add_done_callback(self._fanout_tasks.discard)

    async def _cluster_fanout(self, message_data: str) -> None:
        """Best-effort cross-node cluster publish.

        Runs off the caller's hot path (``broadcast`` spawns it), so a
        dead or slow Redis never blocks the real-time state pipeline.
        Failures are swallowed — a cluster fanout miss only means a
        remote node doesn't get the event, which is a latency/consistency
        regression on that node, not a data-integrity failure.
        """
        try:
            redis = get_redis_client()
            if redis:
                await redis.publish(self._cluster_channel, message_data)
        except Exception:
            # Best-effort fanout: a dead Redis means remote nodes miss this
            # event (a cross-node latency regression, not a data-integrity
            # failure). We do not raise, but we DO count it so a sustained
            # outage is observable instead of silent.
            self.cluster_fanout_failures += 1

    async def connect(
        self,
        session_id: str,
        user_id: str,
        tenant_id: str,
        workspace_id: str,
        websocket: WebSocket,
    ) -> ConnectionSession:
        """Register newly authenticated WebSocket connection."""
        await websocket.accept()
        session = ConnectionSession(
            session_id=session_id,
            user_id=user_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            websocket=websocket,
        )
        async with self._lock:
            self._sessions[session_id] = session
        return session

    async def disconnect(self, session_id: str) -> None:
        """Clean up disconnected session."""
        async with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]

    async def subscribe(self, session_id: str, target_workspace_id: str, channel: str) -> bool:
        """Subscribe session to an authorized event channel."""
        async with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return False
            if not session.can_subscribe(target_workspace_id, channel):
                return False
            session.subscribed_channels.add(channel)
            return True

    async def broadcast(
        self,
        tenant_id: str,
        workspace_id: str,
        channel: RealtimeChannel | str,
        event_type: str,
        payload: dict[str, Any],
        origin_node_id: str | None = None,
    ) -> int:
        """Broadcast an event locally and publish to Redis Pub/Sub for cluster synchronization."""
        channel_name = channel.value if isinstance(channel, RealtimeChannel) else channel
        message_data = json.dumps(
            {
                "channel": channel_name,
                "event_type": event_type,
                "workspace_id": workspace_id,
                "tenant_id": tenant_id,
                "origin_node": origin_node_id or self.node_id,
                "timestamp": datetime.now(UTC).isoformat(),
                "payload": payload,
            }
        )

        # 1. Local node fanout
        recipient_count = await self._dispatch_local(
            tenant_id, workspace_id, channel_name, message_data
        )

        # 2. Clustered Redis pub/sub fanout to peer nodes (if not arriving from remote peer).
        # Step 4: fire-and-forget — the cluster publish is best-effort
        # and bounded by the Redis client's socket timeouts. Awaiting it
        # here would block the real-time pipeline on a dead Redis, which
        # was exactly the latency regression fixed in Step 2. The task is
        # tracked so a pending publish can never leak past the caller.
        if origin_node_id is None:
            self._spawn_fanout(self._cluster_fanout(message_data))

        return recipient_count

    async def _dispatch_local(
        self, tenant_id: str, workspace_id: str, channel_name: str, raw_json: str
    ) -> int:
        """Dispatch JSON string to matching local sessions."""
        recipient_count = 0
        dead_sessions: list[str] = []

        async with self._lock:
            for sid, sess in self._sessions.items():
                if (
                    sess.tenant_id == tenant_id
                    and sess.workspace_id == workspace_id
                    and (
                        channel_name in sess.subscribed_channels or "*" in sess.subscribed_channels
                    )
                ):
                    try:
                        await sess.websocket.send_text(raw_json)
                        recipient_count += 1
                    except Exception:
                        dead_sessions.append(sid)

            for dead_sid in dead_sessions:
                if dead_sid in self._sessions:
                    del self._sessions[dead_sid]

        return recipient_count

    async def handle_cluster_message(self, raw_message: str) -> None:
        """Handle incoming broadcast from a remote cluster peer."""
        try:
            msg = json.loads(raw_message)
            if msg.get("origin_node") == self.node_id:
                return  # Avoid duplicate broadcast on originating node

            tenant_id = msg.get("tenant_id", "")
            workspace_id = msg.get("workspace_id", "")
            channel_name = msg.get("channel", "")

            await self._dispatch_local(tenant_id, workspace_id, channel_name, raw_message)
        except Exception:  # noqa: S110 - best-effort cluster message dispatch
            pass

    def get_active_connection_count(self) -> int:
        return len(self._sessions)


# Global singleton
_global_realtime_gateway: RealtimeGateway | None = None


def get_realtime_gateway() -> RealtimeGateway:
    global _global_realtime_gateway
    if _global_realtime_gateway is None:
        _global_realtime_gateway = RealtimeGateway()
    return _global_realtime_gateway
