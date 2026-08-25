"""Shadow Deployment Pipeline — Zero-Risk Live Traffic Evaluation.

Receives live production message streams, evaluates both Active and Shadow versions, and tracks divergence metrics without impacting production state.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.common.context import ExecutionContext
from app.modules.agents.domain_agents.shipment_tracking import (
    ShipmentAssessment,
    ShipmentTelemetry,
    ShipmentTrackingAgent,
)


@dataclass
class ShadowDivergenceMetric:
    event_id: str
    active_version: str
    shadow_version: str
    active_status: str
    shadow_status: str
    is_divergent: bool
    active_risk_score: float
    shadow_risk_score: float
    active_latency_ms: float
    shadow_latency_ms: float
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class ShadowDeploymentPipeline:
    """Pipelines live production events to both active and shadow agent replicas."""

    def __init__(self) -> None:
        self._divergence_log: list[ShadowDivergenceMetric] = []

    async def evaluate_live_event(
        self,
        event_id: str,
        telemetry: ShipmentTelemetry,
        active_version: str,
        shadow_version: str,
        context: ExecutionContext,
    ) -> tuple[ShipmentAssessment, ShipmentAssessment, ShadowDivergenceMetric]:
        """Run active and shadow agents concurrently on live event."""
        active_agent = ShipmentTrackingAgent(version=active_version)
        shadow_agent = ShipmentTrackingAgent(version=shadow_version)

        t0 = asyncio.get_event_loop().time()
        active_res = await active_agent.evaluate_shipment(telemetry, context)
        t_active = (asyncio.get_event_loop().time() - t0) * 1000.0

        t1 = asyncio.get_event_loop().time()
        shadow_res = await shadow_agent.evaluate_shipment(telemetry, context)
        t_shadow = (asyncio.get_event_loop().time() - t1) * 1000.0

        is_divergent = active_res.status != shadow_res.status

        metric = ShadowDivergenceMetric(
            event_id=event_id,
            active_version=active_version,
            shadow_version=shadow_version,
            active_status=active_res.status,
            shadow_status=shadow_res.status,
            is_divergent=is_divergent,
            active_risk_score=active_res.risk_score,
            shadow_risk_score=shadow_res.risk_score,
            active_latency_ms=round(t_active, 2),
            shadow_latency_ms=round(t_shadow, 2),
        )

        self._divergence_log.append(metric)
        return active_res, shadow_res, metric

    def get_summary_metrics(self) -> dict[str, Any]:
        """Aggregate divergence and performance statistics across shadow runs."""
        total = len(self._divergence_log)
        if total == 0:
            return {"total_events": 0, "divergence_rate_pct": 0.0, "avg_shadow_latency_ms": 0.0}

        divergent_count = sum(1 for m in self._divergence_log if m.is_divergent)
        avg_shadow_lat = sum(m.shadow_latency_ms for m in self._divergence_log) / total

        return {
            "total_events": total,
            "divergent_events": divergent_count,
            "divergence_rate_pct": round((divergent_count / total) * 100.0, 2),
            "avg_shadow_latency_ms": round(avg_shadow_lat, 2),
        }
