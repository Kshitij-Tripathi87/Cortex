"""Operational Multi-Agent Task Graph & Execution Engine.

Decomposes complex supply chain disruptions into a directed acyclic task graph (DAG)
with typed inputs, dependencies, parallel stage executions, and audit records.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class TaskStatus(StrEnum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    BLOCKED = "BLOCKED"


@dataclass
class TaskStep:
    step_id: str
    name: str
    assigned_agent_id: str
    domain_group: str
    status: TaskStatus = TaskStatus.PENDING
    started_at: datetime | None = None
    completed_at: datetime | None = None
    output_data: dict[str, Any] = field(default_factory=dict)
    evidence_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "name": self.name,
            "assigned_agent_id": self.assigned_agent_id,
            "domain_group": self.domain_group,
            "status": self.status.value,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "output_data": self.output_data,
            "evidence_refs": self.evidence_refs,
        }


@dataclass
class OperationalTaskGraph:
    task_id: str
    title: str
    incident_entity_id: str
    world_state_version: int
    steps: list[TaskStep] = field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    consensus_score: float = 0.0
    recommended_action: str | None = None
    is_vetoed: bool = False
    veto_reason: str | None = None

    def add_step(self, name: str, agent_id: str, domain_group: str) -> TaskStep:
        step = TaskStep(
            step_id=f"step_{len(self.steps) + 1}",
            name=name,
            assigned_agent_id=agent_id,
            domain_group=domain_group,
        )
        self.steps.append(step)
        return step

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "incident_entity_id": self.incident_entity_id,
            "world_state_version": self.world_state_version,
            "status": self.status.value,
            "steps": [s.to_dict() for s in self.steps],
            "consensus_score": self.consensus_score,
            "recommended_action": self.recommended_action,
            "is_vetoed": self.is_vetoed,
            "veto_reason": self.veto_reason,
            "created_at": self.created_at.isoformat(),
        }
