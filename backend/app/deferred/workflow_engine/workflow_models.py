"""DEFERRED -- Workflow & Orchestration Core

Status: FROZEN (ADR-0007)
Phase: 2+
Reason: Excluded from MVP wedge per cortex-mvp-execution-plan.md section 7.2
Action: Do not import into production paths.

Last touched: 2026-08-01

Workflow domain models — dataclasses, enums, and ORM persistence models.

These are pure-Python domain types.  The repository layer (workflow_repository.py)
bridges them to the database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from app.common.ids import uuid7

# ─────────────────────────────────────────────────────────────────────────────
# Enumerations
# ─────────────────────────────────────────────────────────────────────────────


class WorkflowStatus(StrEnum):
    """Lifecycle status of a workflow instance."""

    CREATED = "created"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLING_BACK = "rolling_back"
    ROLLED_BACK = "rolled_back"
    CANCELLED = "cancelled"


class StageStatus(StrEnum):
    """Execution status of a single workflow stage."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    SKIPPED = "skipped"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"


# ─────────────────────────────────────────────────────────────────────────────
# Domain dataclasses
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StageDefinition:
    stage_id: str
    name: str
    agent: str
    verb: str
    depends_on: tuple[str, ...] = ()
    timeout_ms: int = 60000
    retry_count: int = 3
    rollback_verb: str | None = None
    gate: bool = False


@dataclass(frozen=True)
class WorkflowDefinition:
    workflow_id: str
    name: str
    version: str
    stages: tuple[StageDefinition, ...]

    @property
    def stage_ids(self) -> frozenset[str]:
        return frozenset(s.stage_id for s in self.stages)

    @property
    def entry_stages(self) -> tuple[StageDefinition, ...]:
        return tuple(s for s in self.stages if not s.depends_on)

    @property
    def gate_stages(self) -> tuple[StageDefinition, ...]:
        return tuple(s for s in self.stages if s.gate)

    def get_stage(self, stage_id: str) -> StageDefinition | None:
        for s in self.stages:
            if s.stage_id == stage_id:
                return s
        return None

    def downstream_stages(self, stage_id: str) -> tuple[StageDefinition, ...]:
        return tuple(s for s in self.stages if stage_id in s.depends_on)


@dataclass(frozen=True)
class StageInstance:
    stage_instance_id: str = field(default_factory=uuid7)
    workflow_instance_id: str = ""
    stage_id: str = ""
    name: str = ""
    agent: str = ""
    verb: str = ""
    depends_on: tuple[str, ...] = ()
    gate: bool = False
    status: StageStatus = StageStatus.PENDING
    attempt: int = 0
    retry_count: int = 3
    input_payload: dict | None = None
    output_payload: dict | None = None
    last_error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


@dataclass(frozen=True)
class WorkflowInstance:
    instance_id: str = field(default_factory=uuid7)
    workflow_name: str = ""
    workspace_id: str = ""
    version: str = ""
    status: WorkflowStatus = WorkflowStatus.CREATED
    triggered_by: str | None = None
    stages: tuple[StageInstance, ...] = ()
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None

    @property
    def current_stage(self) -> StageInstance | None:
        for s in self.stages:
            if s.status == StageStatus.RUNNING:
                return s
        return None

    @property
    def pending_stages(self) -> tuple[StageInstance, ...]:
        return tuple(s for s in self.stages if s.status == StageStatus.PENDING)

    @property
    def failed_stages(self) -> tuple[StageInstance, ...]:
        return tuple(s for s in self.stages if s.status == StageStatus.FAILED)


@dataclass(frozen=True)
class GateApproval:
    approval_id: str = field(default_factory=uuid7)
    workflow_instance_id: str = ""
    stage_instance_id: str = ""
    approved_by: str = ""
    decision: str = ""
    rationale: str | None = None
    decided_at: datetime | None = None
