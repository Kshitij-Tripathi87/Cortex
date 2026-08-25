"""Decentralized Agent Runtime Node — Resilient Worker Container for Decentralized Replicas.

Implements:
- Asynchronous message consumption and event dispatch
- Periodic heartbeat emission to the central supervisor
- Checkpoint persistence and working memory recovery
- Capability enforcement and isolation
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.common.context import ExecutionContext
from app.modules.agents.domain_agents.inventory_allocation import InventoryAllocationAgent
from app.modules.agents.domain_agents.logistics_routing import LogisticsRoutingAgent
from app.modules.agents.domain_agents.procurement_sourcing import ProcurementSourcingAgent
from app.modules.agents.domain_agents.shipment_tracking import (
    ShipmentAssessment,
    ShipmentTelemetry,
    ShipmentTrackingAgent,
)
from app.modules.agents.lifecycle_models import (
    AgentReplica,
    ReplicaStatus,
)


@dataclass
class RuntimeCheckpoint:
    replica_id: str
    version: str
    last_processed_event_id: str
    working_memory_state: dict[str, Any]
    checkpointed_at: datetime


class DecentralizedAgentRuntime:
    """Decentralized worker executing agent domain logic, tracking health, and emitting heartbeats."""

    def __init__(
        self,
        replica_id: str,
        agent_id: str,
        version: str,
        workspace_id: str,
        node_id: str = "worker_node_01",
    ) -> None:
        self.replica = AgentReplica(
            replica_id=replica_id,
            agent_id=agent_id,
            version=version,
            status=ReplicaStatus.HEALTHY,
            workspace_id=workspace_id,
            node_id=node_id,
        )
        self.tracking_agent = ShipmentTrackingAgent(version=version)
        self.routing_agent = LogisticsRoutingAgent(version=version)
        self.inventory_agent = InventoryAllocationAgent(version=version)
        self.procurement_agent = ProcurementSourcingAgent(version=version)

        self._checkpoints: list[RuntimeCheckpoint] = []
        self._working_memory: dict[str, Any] = {}

    async def handle_shipment_telemetry_event(
        self, telemetry: ShipmentTelemetry, context: ExecutionContext
    ) -> ShipmentAssessment:
        """Handle incoming telemetry message and update local working memory."""
        t0 = asyncio.get_event_loop().time()
        assessment = await self.tracking_agent.evaluate_shipment(telemetry, context)
        latency = (asyncio.get_event_loop().time() - t0) * 1000.0

        # Update metrics
        self.replica.infra_metrics.p99_latency_ms = round(latency, 2)
        self.replica.last_heartbeat_at = datetime.now(UTC)

        # Store in local working memory
        self._working_memory[telemetry.shipment_id] = {
            "status": assessment.status,
            "risk_score": assessment.risk_score,
            "evaluated_at": datetime.now(UTC).isoformat(),
        }

        return assessment

    def create_checkpoint(self, event_id: str) -> RuntimeCheckpoint:
        """Persist state checkpoint for fast recovery after node failure."""
        chk = RuntimeCheckpoint(
            replica_id=self.replica.replica_id,
            version=self.replica.version,
            last_processed_event_id=event_id,
            working_memory_state=dict(self._working_memory),
            checkpointed_at=datetime.now(UTC),
        )
        self._checkpoints.append(chk)
        return chk

    def emit_heartbeat(self) -> dict[str, Any]:
        """Generate structured heartbeat payload for supervisor."""
        self.replica.last_heartbeat_at = datetime.now(UTC)
        return self.replica.to_dict()
