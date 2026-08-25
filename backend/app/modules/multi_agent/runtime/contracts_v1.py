"""Nexus Agent Message Protocol — Frozen Canonical Schema Version 1.0.

Immutable message contract per Section 10 of Architecture Spec.
All platform agents, message buses, memory stores, audit loggers,
and the frontend Decision Room must strictly adhere to this schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from app.common.ids import uuid7


class CanonicalMessageType(StrEnum):
    """Closed vocabulary of agent and platform message types."""

    # Task Lifecycle
    TASK_CREATED = "nexus.agent.task.created"
    TASK_DECOMPOSED = "nexus.agent.task.decomposed"
    TASK_ASSIGNED = "nexus.agent.task.assigned"
    TASK_ACCEPTED = "nexus.agent.task.accepted"
    TASK_FAILED = "nexus.agent.task.failed"
    TASK_CANCELLED = "nexus.agent.task.cancelled"

    # Agent Deliberation Protocol
    OBSERVATION = "nexus.agent.observation"
    PROPOSAL = "nexus.agent.proposal"
    CHALLENGE = "nexus.agent.challenge"
    REVISION = "nexus.agent.revision"
    CONSENSUS_REQUESTED = "nexus.agent.consensus.requested"
    CONSENSUS_REACHED = "nexus.agent.consensus.reached"

    # World State & Scenarios
    WORLD_STATE_CHANGED = "nexus.world.state.changed"
    SCENARIO_CREATED = "nexus.scenario.created"
    SIMULATION_STARTED = "nexus.simulation.started"
    SIMULATION_PROGRESS = "nexus.simulation.progress"
    SIMULATION_COMPLETED = "nexus.simulation.completed"

    # Decisions & Policy Gates
    POLICY_EVALUATED = "nexus.policy.evaluated"
    DECISION_CARD_GENERATED = "nexus.decision.card.generated"
    DECISION_APPROVED = "nexus.decision.approved"
    DECISION_REJECTED = "nexus.decision.rejected"
    DECISION_MODIFIED = "nexus.decision.modified"

    # Execution & Memory Feedback
    EXECUTION_REQUESTED = "nexus.execution.requested"
    EXECUTION_STARTED = "nexus.execution.started"
    EXECUTION_COMPLETED = "nexus.execution.completed"
    EXECUTION_FAILED = "nexus.execution.failed"
    OUTCOME_RECORDED = "nexus.memory.outcome.recorded"
    CALIBRATION_UPDATED = "nexus.governance.calibration.updated"


# JSON Schema for wire validation
CANONICAL_MESSAGE_SCHEMA_V1 = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "NexusAgentMessageV1",
    "type": "object",
    "required": [
        "message_id",
        "message_type",
        "schema_version",
        "organization_id",
        "workspace_id",
        "sender_id",
        "correlation_id",
        "causation_id",
        "conversation_id",
        "world_state_version",
        "occurred_at",
        "idempotency_key",
        "payload",
    ],
    "properties": {
        "message_id": {"type": "string", "pattern": "^[0-9a-fA-F-]{36}$"},
        "message_type": {"type": "string"},
        "schema_version": {"type": "string", "enum": ["1.0"]},
        "organization_id": {"type": "string", "minLength": 1},
        "workspace_id": {"type": "string", "minLength": 1},
        "project_id": {"type": ["string", "null"]},
        "sender_id": {"type": "string", "minLength": 1},
        "sender_role": {"type": ["string", "null"]},
        "sender_version": {"type": "string", "default": "1.0.0"},
        "correlation_id": {"type": "string", "minLength": 1},
        "causation_id": {"type": "string", "minLength": 1},
        "conversation_id": {"type": "string", "minLength": 1},
        "world_state_version": {"type": "integer", "minimum": 0},
        "scenario_id": {"type": ["string", "null"]},
        "occurred_at": {"type": "string", "format": "date-time"},
        "deadline_at": {"type": ["string", "null"], "format": "date-time"},
        "idempotency_key": {"type": "string", "minLength": 1},
        "tenant_id": {"type": "string", "default": "default_tenant"},
        "payload": {"type": "object"},
    },
    "additionalProperties": True,
}


@dataclass(frozen=True)
class CanonicalAgentMessage:
    """Immutable Canonical Agent Message Envelope (v1.0)."""

    message_id: str
    message_type: CanonicalMessageType
    organization_id: str
    workspace_id: str
    sender_id: str
    correlation_id: str
    causation_id: str
    conversation_id: str
    world_state_version: int
    idempotency_key: str
    payload: dict[str, Any]
    schema_version: str = "1.0"
    tenant_id: str = "default_tenant"
    project_id: str | None = None
    sender_role: str | None = None
    sender_version: str = "1.0.0"
    scenario_id: str | None = None
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    deadline_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to wire dictionary."""
        return {
            "message_id": self.message_id,
            "message_type": self.message_type.value,
            "schema_version": self.schema_version,
            "organization_id": self.organization_id,
            "workspace_id": self.workspace_id,
            "project_id": self.project_id,
            "sender_id": self.sender_id,
            "sender_role": self.sender_role,
            "sender_version": self.sender_version,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "conversation_id": self.conversation_id,
            "world_state_version": self.world_state_version,
            "scenario_id": self.scenario_id,
            "occurred_at": self.occurred_at.isoformat(),
            "deadline_at": self.deadline_at.isoformat() if self.deadline_at else None,
            "idempotency_key": self.idempotency_key,
            "tenant_id": self.tenant_id,
            "payload": dict(self.payload),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CanonicalAgentMessage:
        """Hydrate from wire dictionary with validation."""
        occurred = (
            datetime.fromisoformat(data["occurred_at"])
            if isinstance(data.get("occurred_at"), str)
            else datetime.now(UTC)
        )
        deadline = (
            datetime.fromisoformat(data["deadline_at"])
            if data.get("deadline_at") and isinstance(data["deadline_at"], str)
            else None
        )
        msg_type_str = data.get("message_type", CanonicalMessageType.OBSERVATION.value)
        try:
            msg_type = CanonicalMessageType(msg_type_str)
        except ValueError:
            msg_type = CanonicalMessageType.OBSERVATION

        sender = data.get("sender_id") or data.get("agent_id") or "unknown_agent"

        return cls(
            message_id=data.get("message_id") or str(uuid7()),
            message_type=msg_type,
            schema_version=data.get("schema_version", "1.0"),
            organization_id=data.get("organization_id", "default_org"),
            workspace_id=data.get("workspace_id", "default_workspace"),
            project_id=data.get("project_id"),
            sender_id=sender,
            sender_role=data.get("sender_role"),
            sender_version=data.get("sender_version") or data.get("agent_version", "1.0.0"),
            correlation_id=data.get("correlation_id", str(uuid7())),
            causation_id=data.get("causation_id", str(uuid7())),
            conversation_id=data.get("conversation_id", str(uuid7())),
            world_state_version=int(data.get("world_state_version", 1)),
            scenario_id=data.get("scenario_id"),
            occurred_at=occurred,
            deadline_at=deadline,
            idempotency_key=data.get("idempotency_key") or str(uuid7()),
            tenant_id=data.get("tenant_id", "default_tenant"),
            payload=data.get("payload", {}),
        )


def build_canonical_message(
    message_type: CanonicalMessageType,
    organization_id: str,
    workspace_id: str,
    sender_id: str,
    correlation_id: str,
    causation_id: str,
    conversation_id: str,
    world_state_version: int,
    payload: dict[str, Any],
    tenant_id: str = "default_tenant",
    project_id: str | None = None,
    sender_role: str | None = None,
    sender_version: str = "1.0.0",
    scenario_id: str | None = None,
    deadline_at: datetime | None = None,
    idempotency_key: str | None = None,
) -> CanonicalAgentMessage:
    """Factory helper to build a validated canonical agent message."""
    return CanonicalAgentMessage(
        message_id=str(uuid7()),
        message_type=message_type,
        schema_version="1.0",
        organization_id=organization_id,
        workspace_id=workspace_id,
        project_id=project_id,
        sender_id=sender_id,
        sender_role=sender_role,
        sender_version=sender_version,
        correlation_id=correlation_id,
        causation_id=causation_id,
        conversation_id=conversation_id,
        world_state_version=world_state_version,
        scenario_id=scenario_id,
        occurred_at=datetime.now(UTC),
        deadline_at=deadline_at,
        idempotency_key=idempotency_key or str(uuid7()),
        tenant_id=tenant_id,
        payload=payload,
    )
