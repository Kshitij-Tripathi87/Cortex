"""Canonical Agent Message Envelope — Standard Envelope per Section 8 of Architecture Spec.

Every agent message carries:
- Provenance (agent_id, agent_version)
- Tenant scope (tenant_id, organization_id, workspace_id, project_id)
- Traceability (correlation_id, causation_id, conversation_id)
- Ordering & replay (world_state_version, occurred_at, deadline_at)
- Idempotency & payload validation
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from app.common.ids import uuid7


class MessageType(StrEnum):
    """Standard message types per Section 9 of Architecture Spec."""

    TASK_CREATED = "agent.task.created"
    TASK_ACCEPTED = "agent.task.accepted"
    TASK_FAILED = "agent.task.failed"
    TASK_CANCELLED = "agent.task.cancelled"
    OBSERVATION = "agent.observation"
    PROPOSAL = "agent.proposal"
    CHALLENGE = "agent.challenge"
    REVISION = "agent.revision"
    CONSENSUS_REQUESTED = "agent.consensus.requested"
    CONSENSUS_REACHED = "agent.consensus.reached"
    WORLD_STATE_CHANGED = "world.state.changed"
    SCENARIO_CREATED = "scenario.created"
    SIMULATION_STARTED = "simulation.started"
    SIMULATION_COMPLETED = "simulation.completed"
    DECISION_CREATED = "decision.created"
    DECISION_APPROVED = "decision.approved"
    DECISION_REJECTED = "decision.rejected"
    EXECUTION_REQUESTED = "execution.requested"
    EXECUTION_STARTED = "execution.started"
    EXECUTION_COMPLETED = "execution.completed"
    EXECUTION_FAILED = "execution.failed"
    OUTCOME_RECORDED = "memory.outcome.recorded"


@dataclass(frozen=True)
class AgentMessageEnvelope:
    """Canonical envelope wrapping all cross-agent and platform bus messages."""

    message_id: str
    message_type: MessageType
    organization_id: str
    workspace_id: str
    agent_id: str
    agent_version: str
    correlation_id: str
    causation_id: str
    conversation_id: str
    world_state_version: int
    idempotency_key: str
    payload: dict[str, Any]
    tenant_id: str
    project_id: str | None = None
    scenario_id: str | None = None
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    deadline_at: datetime | None = None
    schema_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        """Serialize envelope to standard dict representation."""
        return {
            "message_id": self.message_id,
            "message_type": self.message_type.value,
            "schema_version": self.schema_version,
            "organization_id": self.organization_id,
            "workspace_id": self.workspace_id,
            "project_id": self.project_id,
            "agent_id": self.agent_id,
            "agent_version": self.agent_version,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "conversation_id": self.conversation_id,
            "world_state_version": self.world_state_version,
            "scenario_id": self.scenario_id,
            "occurred_at": self.occurred_at.isoformat(),
            "deadline_at": self.deadline_at.isoformat() if self.deadline_at else None,
            "idempotency_key": self.idempotency_key,
            "payload": dict(self.payload),
            "tenant_id": self.tenant_id,
        }


def create_envelope(
    message_type: MessageType,
    organization_id: str,
    workspace_id: str,
    agent_id: str,
    agent_version: str,
    correlation_id: str,
    causation_id: str,
    conversation_id: str,
    world_state_version: int,
    payload: dict[str, Any],
    tenant_id: str,
    idempotency_key: str | None = None,
    project_id: str | None = None,
    scenario_id: str | None = None,
    deadline_at: datetime | None = None,
) -> AgentMessageEnvelope:
    """Factory function for creating a new independent message envelope."""
    return AgentMessageEnvelope(
        message_id=str(uuid7()),
        message_type=message_type,
        organization_id=organization_id,
        workspace_id=workspace_id,
        project_id=project_id,
        agent_id=agent_id,
        agent_version=agent_version,
        correlation_id=correlation_id,
        causation_id=causation_id,
        conversation_id=conversation_id,
        world_state_version=world_state_version,
        scenario_id=scenario_id,
        occurred_at=datetime.now(UTC),
        deadline_at=deadline_at,
        idempotency_key=idempotency_key or str(uuid7()),
        payload=payload,
        tenant_id=tenant_id,
    )


def create_reply(
    original: AgentMessageEnvelope,
    message_type: MessageType,
    agent_id: str,
    agent_version: str,
    payload: dict[str, Any],
    idempotency_key: str | None = None,
) -> AgentMessageEnvelope:
    """Derive a reply message envelope preserving correlation and conversation context."""
    return AgentMessageEnvelope(
        message_id=str(uuid7()),
        message_type=message_type,
        organization_id=original.organization_id,
        workspace_id=original.workspace_id,
        project_id=original.project_id,
        agent_id=agent_id,
        agent_version=agent_version,
        correlation_id=original.correlation_id,
        causation_id=original.message_id,
        conversation_id=original.conversation_id,
        world_state_version=original.world_state_version,
        scenario_id=original.scenario_id,
        occurred_at=datetime.now(UTC),
        deadline_at=original.deadline_at,
        idempotency_key=idempotency_key or str(uuid7()),
        payload=payload,
        tenant_id=original.tenant_id,
    )
