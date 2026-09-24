"""Nexus MAF-4 — durable task runtime models.

PostgreSQL is the authoritative store for the orchestration runtime; Redis is
never consulted for task state. Tables follow the dependency order:

    nexus_tasks -> nexus_task_intents -> nexus_task_plans
        -> nexus_task_runs -> nexus_task_steps -> nexus_task_invocations
        -> nexus_task_evidence -> nexus_task_proposals
        -> nexus_task_approvals -> nexus_task_executions -> nexus_task_outcomes

Immutable/event-like records (transitions, invocations, approvals) provide
auditability; current-state columns on ``nexus_tasks`` (and companions)
provide efficient scoped queries.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database import Base


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _uuid() -> str:
    return str(uuid4())


# ─────────────────────────────────────────────────────────────────────────────
# Tasks — the durable lifecycle root
# ─────────────────────────────────────────────────────────────────────────────


class TaskDB(Base):
    """Authoritative task record: identity, scope, and current lifecycle state."""

    __tablename__ = "nexus_tasks"

    task_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    world_state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    budget: Mapped[float] = mapped_column(Float, nullable=False, default=100.0)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    policy_context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, onupdate=_utc_now, nullable=False
    )

    __table_args__ = (
        Index("ix_nexus_tasks_tenant_workspace_status", "tenant_id", "workspace_id", "status"),
    )


class TaskTransitionDB(Base):
    """Append-only lifecycle transitions (audit trail; never mutated)."""

    __tablename__ = "nexus_task_transitions"

    transition_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("nexus_tasks.task_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    from_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    to_status: Mapped[str] = mapped_column(String(40), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )


# ─────────────────────────────────────────────────────────────────────────────
# Intent / Plan checkpoints
# ─────────────────────────────────────────────────────────────────────────────


class TaskIntentDB(Base):
    """Committed intent checkpoint: no re-resolution after this row exists."""

    __tablename__ = "nexus_task_intents"

    intent_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("nexus_tasks.task_id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    intent_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )


class TaskPlanDB(Base):
    """Committed plan checkpoint; one active plan per task in MAF-4."""

    __tablename__ = "nexus_task_plans"

    plan_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("nexus_tasks.task_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    plan_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    assumptions: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )


# ─────────────────────────────────────────────────────────────────────────────
# Runs / Steps / Invocations
# ─────────────────────────────────────────────────────────────────────────────


class TaskRunDB(Base):
    """One execution run of a plan; captures the World State version used."""

    __tablename__ = "nexus_task_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("nexus_tasks.task_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    run_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    world_state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    checkpoint_step: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("task_id", "run_number"),)


class TaskStepDB(Base):
    """Per-step outcome; failure, blocking, and skipping are explicit states."""

    __tablename__ = "nexus_task_steps"

    step_run_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("nexus_task_runs.run_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    task_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    step_id: Mapped[str] = mapped_column(String(64), nullable=False)
    agent_role: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    error: Mapped[str | None] = mapped_column(String(128), nullable=True)
    invocation_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    evidence_refs: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    outputs: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("run_id", "step_id"),)


class TaskInvocationDB(Base):
    """Durable gateway invocation; ``invocation_id`` is the idempotency key."""

    __tablename__ = "nexus_task_invocations"

    invocation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("nexus_tasks.task_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    run_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    step_id: Mapped[str] = mapped_column(String(64), nullable=False)
    capability_id: Mapped[str] = mapped_column(String(128), nullable=False)
    capability_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    side_effect: Mapped[str] = mapped_column(String(40), nullable=False)
    world_state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    arguments_sha256: Mapped[str] = mapped_column(String(128), nullable=False)
    authorization: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    evidence_refs: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    result_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )

    __table_args__ = (
        Index(
            "ix_nexus_task_invocations_resume",
            "task_id",
            "step_id",
            "capability_id",
            "arguments_sha256",
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Evidence / Proposals
# ─────────────────────────────────────────────────────────────────────────────


class TaskEvidenceDB(Base):
    """Established evidence reference for a task, with its source invocation."""

    __tablename__ = "nexus_task_evidence"

    evidence_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("nexus_tasks.task_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    ref: Mapped[str] = mapped_column(String(160), nullable=False)
    source_invocation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload_digest: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )

    __table_args__ = (UniqueConstraint("task_id", "ref"),)


class TaskProposalDB(Base):
    """Durable specialist proposal produced by synthesis."""

    __tablename__ = "nexus_task_proposals"

    proposal_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("nexus_tasks.task_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    agent_role: Mapped[str] = mapped_column(String(64), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    actions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    evidence_refs: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    assumptions: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )


# ─────────────────────────────────────────────────────────────────────────────
# Approvals / Execution / Outcome
# ─────────────────────────────────────────────────────────────────────────────


class TaskApprovalDB(Base):
    """Append-only approval events; APPROVED is the only key into EXECUTING."""

    __tablename__ = "nexus_task_approvals"

    approval_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("nexus_tasks.task_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    approver_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )


class TaskExecutionDB(Base):
    """Execution bookkeeping with idempotency key and attempt counter."""

    __tablename__ = "nexus_task_executions"

    execution_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("nexus_tasks.task_id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Widen from 128 to match the world-state idempotency key width: keys
    # derived from (task, capability, arguments digest) reach ~140 chars.
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TaskOutcomeDB(Base):
    """Terminal outcome; the reconstruction source for NexusTrace."""

    __tablename__ = "nexus_task_outcomes"

    outcome_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("nexus_tasks.task_id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    recommendation: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )
