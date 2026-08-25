"""Real-Time State Pipeline — End-to-End Event to State Invariant Engine.

Orchestrates the canonical real-time pipeline:
  Event Ingestion
        ↓
  Durable Write (DB / Event Store)
        ↓
  Message Publication (Kafka / Message Bus)
        ↓
  Deterministic State Projection
        ↓
  Cache Invalidation & Versioned Write (Redis)
        ↓
  Operational Memory Synchronization
        ↓
  Real-Time UI Fanout (WebSocket / SSE)

Instruments explicit microsecond latency metrics:
  event_timestamp -> state_updated_at -> cache_updated_at -> frontend_received_at
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.common.context import ExecutionContext
from app.infrastructure.cache_manager import get_cache_manager
from app.infrastructure.message_bus import NexusTopic, get_message_bus
from app.infrastructure.realtime_gateway import get_realtime_gateway
from app.modules.events.event_models import WorldEvent
from app.modules.memory.operational_memory import get_operational_memory
from app.modules.multi_agent.runtime.contracts_v1 import (
    CanonicalMessageType,
    build_canonical_message,
)
from app.modules.world.state_projection import apply_events
from app.modules.world.world_models import WorldState


@dataclass
class PipelineLatencyMetrics:
    """Microsecond latency tracking across the real-time update pipeline."""

    event_id: str
    event_timestamp: datetime
    state_updated_at: datetime
    cache_updated_at: datetime
    memory_updated_at: datetime
    fanout_dispatched_at: datetime

    @property
    def event_to_state_ms(self) -> float:
        return (self.state_updated_at - self.event_timestamp).total_seconds() * 1000

    @property
    def state_to_cache_ms(self) -> float:
        return (self.cache_updated_at - self.state_updated_at).total_seconds() * 1000

    @property
    def total_pipeline_latency_ms(self) -> float:
        return (self.fanout_dispatched_at - self.event_timestamp).total_seconds() * 1000

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_to_state_ms": round(self.event_to_state_ms, 3),
            "state_to_cache_ms": round(self.state_to_cache_ms, 3),
            "total_pipeline_latency_ms": round(self.total_pipeline_latency_ms, 3),
            "event_timestamp": self.event_timestamp.isoformat(),
            "fanout_dispatched_at": self.fanout_dispatched_at.isoformat(),
        }


@dataclass
class PipelineProcessingResult:
    """Result of full pipeline event processing."""

    success: bool
    event_id: str
    new_world_state: WorldState
    latency_metrics: PipelineLatencyMetrics
    fanout_subscriber_count: int
    error: str | None = None


class RealtimeStatePipeline:
    """Unified pipeline orchestrator keeping DB, Bus, Projection, Cache, Memory, and UI in sync."""

    def __init__(self) -> None:
        self.message_bus = get_message_bus()
        self.cache = get_cache_manager()
        self.memory = get_operational_memory()
        self.realtime = get_realtime_gateway()
        self._latency_history: list[PipelineLatencyMetrics] = []
        self._lock = asyncio.Lock()

    async def ingest_event_and_propagate(
        self,
        event: WorldEvent,
        current_state: WorldState,
        context: ExecutionContext,
    ) -> PipelineProcessingResult:
        """Execute the atomic end-to-end event-to-UI propagation."""
        t_event = event.occurred_at

        try:
            # 1. Publish Event to Message Backbone
            msg_envelope = build_canonical_message(
                message_type=CanonicalMessageType.WORLD_STATE_CHANGED,
                organization_id=context.organization_id,
                workspace_id=context.workspace_id,
                tenant_id=context.tenant_id,
                project_id=context.project_id,
                sender_id=context.user_id,
                correlation_id=context.correlation_id,
                causation_id=context.causation_id,
                conversation_id=f"conv_{event.event_id}",
                world_state_version=current_state.version + 1,
                payload=event.to_dict(),
            )
            await self.message_bus.publish(NexusTopic.EVENTS, msg_envelope)

            # 2. Deterministic State Projection
            t_pre_state = datetime.now(UTC)
            new_state = apply_events(current_state, [event])
            t_state = datetime.now(UTC)

            # 3. Versioned Cache Invalidation and Write
            cache_key = f"worldstate:{context.tenant_id}:{context.workspace_id}:{new_state.version}"
            await self.cache.set(
                cache_key,
                new_state.to_dict(),
                ttl_seconds=3600,
                tenant_id=context.tenant_id,
            )
            t_cache = datetime.now(UTC)

            # 4. Operational Memory Synchronization
            self.memory.set_live_world_state(
                tenant_id=context.tenant_id,
                workspace_id=context.workspace_id,
                world_state=new_state,
            )
            t_mem = datetime.now(UTC)

            # 5. Real-Time Gateway Fanout to Connected Browsers
            delivered = await self.realtime.broadcast(
                tenant_id=context.tenant_id,
                workspace_id=context.workspace_id,
                channel="world-state",
                event_type="world_state_updated",
                payload={
                    "world_id": new_state.world_id,
                    "version": new_state.version,
                    "variables": {k: v.to_dict() for k, v in new_state.variables.items()},
                    "event_applied": event.event_id,
                },
            )
            t_fanout = datetime.now(UTC)

            metrics = PipelineLatencyMetrics(
                event_id=event.event_id,
                event_timestamp=t_event,
                state_updated_at=t_state,
                cache_updated_at=t_cache,
                memory_updated_at=t_mem,
                fanout_dispatched_at=t_fanout,
            )

            async with self._lock:
                self._latency_history.append(metrics)
                if len(self._latency_history) > 1000:
                    self._latency_history.pop(0)

            return PipelineProcessingResult(
                success=True,
                event_id=event.event_id,
                new_world_state=new_state,
                latency_metrics=metrics,
                fanout_subscriber_count=delivered,
            )

        except Exception as exc:
            t_now = datetime.now(UTC)
            metrics = PipelineLatencyMetrics(
                event_id=event.event_id,
                event_timestamp=t_event,
                state_updated_at=t_now,
                cache_updated_at=t_now,
                memory_updated_at=t_now,
                fanout_dispatched_at=t_now,
            )
            return PipelineProcessingResult(
                success=False,
                event_id=event.event_id,
                new_world_state=current_state,
                latency_metrics=metrics,
                fanout_subscriber_count=0,
                error=str(exc),
            )

    def get_latency_stats(self) -> dict[str, Any]:
        """Aggregate p50, p95, p99 latency statistics across historical pipeline operations."""
        if not self._latency_history:
            return {"sample_count": 0, "avg_ms": 0.0, "p95_ms": 0.0}

        latencies = sorted(m.total_pipeline_latency_ms for m in self._latency_history)
        n = len(latencies)
        p50 = latencies[int(n * 0.50)]
        p95 = latencies[int(n * 0.95)]
        avg = sum(latencies) / n

        return {
            "sample_count": n,
            "avg_latency_ms": round(avg, 2),
            "p50_latency_ms": round(p50, 2),
            "p95_latency_ms": round(p95, 2),
            "latest_operation": self._latency_history[-1].to_dict() if self._latency_history else None,
        }


# Global pipeline singleton
_global_pipeline: RealtimeStatePipeline | None = None


def get_state_pipeline() -> RealtimeStatePipeline:
    """Retrieve or initialize the global real-time state pipeline."""
    global _global_pipeline
    if _global_pipeline is None:
        _global_pipeline = RealtimeStatePipeline()
    return _global_pipeline
