"""DEFERRED -- Workflow & Orchestration Core

Status: FROZEN (ADR-0007)
Phase: 2+
Reason: Excluded from MVP wedge per cortex-mvp-execution-plan.md section 7.2
Action: Do not import into production paths.

Last touched: 2026-08-01

Workflow repository — ORM models and persistence operations.

Bridges the domain dataclasses (workflow_models.py) to the PostgreSQL
persistence layer.  All DB operations are async and transactional.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.common.ids import uuid7
from app.deferred.workflow_engine.workflow_models import (
    StageInstance,
    StageStatus,
    WorkflowInstance,
    WorkflowStatus,
)
from app.infrastructure.database import Base

# ─────────────────────────────────────────────────────────────────────────────
# ORM models
# ─────────────────────────────────────────────────────────────────────────────


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    instance_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    workflow_name: Mapped[str] = mapped_column(String(128), nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=WorkflowStatus.CREATED.value, index=True
    )
    triggered_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def to_domain(self, stages: list[StageInstance]) -> WorkflowInstance:
        return WorkflowInstance(
            instance_id=self.instance_id,
            workflow_name=self.workflow_name,
            workspace_id=self.workspace_id,
            version=self.version,
            status=WorkflowStatus(self.status),
            triggered_by=self.triggered_by,
            stages=tuple(stages),
            started_at=self.started_at,
            updated_at=self.updated_at,
            completed_at=self.completed_at or None,
        )


class WorkflowStepRun(Base):
    __tablename__ = "workflow_step_runs"

    stage_instance_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    workflow_instance_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    stage_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    agent: Mapped[str] = mapped_column(String(64), nullable=False)
    verb: Mapped[str] = mapped_column(String(64), nullable=False)
    depends_on: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    gate: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=StageStatus.PENDING.value, index=True
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    input_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    output_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def to_domain(self) -> StageInstance:
        return StageInstance(
            stage_instance_id=self.stage_instance_id,
            workflow_instance_id=self.workflow_instance_id,
            stage_id=self.stage_id,
            name=self.name,
            agent=self.agent,
            verb=self.verb,
            depends_on=tuple(self.depends_on),
            gate=self.gate,
            status=StageStatus(self.status),
            attempt=self.attempt,
            retry_count=self.retry_count,
            input_payload=self.input_payload or {},
            output_payload=self.output_payload or {},
            last_error=self.last_error,
            started_at=self.started_at or None,
            completed_at=self.completed_at or None,
        )


class WorkflowStepArtifact(Base):
    __tablename__ = "workflow_step_artifacts"

    artifact_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    workflow_instance_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    stage_instance_id: Mapped[str] = mapped_column(String(36), nullable=False)
    artifact_key: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


# ─────────────────────────────────────────────────────────────────────────────
# Persistence operations
# ─────────────────────────────────────────────────────────────────────────────


class WorkflowRepository:
    """Async repository for workflow persistence."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def save_workflow(self, instance: WorkflowInstance) -> WorkflowInstance:
        run = WorkflowRun(
            instance_id=instance.instance_id,
            workflow_name=instance.workflow_name,
            workspace_id=instance.workspace_id,
            version=instance.version,
            status=instance.status.value,
            triggered_by=instance.triggered_by,
            params={},
            started_at=instance.started_at,
            completed_at=instance.completed_at,
        )
        self._db.add(run)

        for stage in instance.stages:
            self._db.add(
                WorkflowStepRun(
                    stage_instance_id=stage.stage_instance_id,
                    workflow_instance_id=instance.instance_id,
                    stage_id=stage.stage_id,
                    name=stage.name,
                    agent=stage.agent,
                    verb=stage.verb,
                    depends_on=list(stage.depends_on),
                    gate=stage.gate,
                    status=stage.status.value,
                    attempt=stage.attempt,
                    retry_count=stage.retry_count,
                    input_payload=stage.input_payload,
                )
            )
        await self._db.flush()
        return instance

    async def update_run_status(
        self, instance_id: str, status: WorkflowStatus, completed_at: datetime | None = None
    ) -> None:
        run = await self._db.get(WorkflowRun, instance_id)
        if run is None:
            raise ValueError(f"WorkflowRun {instance_id} not found")
        run.status = status.value
        run.updated_at = datetime.now(UTC)
        if completed_at:
            run.completed_at = completed_at
        await self._db.flush()

    async def get_run(self, instance_id: str) -> WorkflowInstance | None:
        run = await self._db.get(WorkflowRun, instance_id)
        if run is None:
            return None
        stmt = (
            select(WorkflowStepRun)
            .where(WorkflowStepRun.workflow_instance_id == instance_id)
            .order_by(WorkflowStepRun.stage_id)
        )
        result = await self._db.execute(stmt)
        step_runs = list(result.scalars().all())
        stages = [s.to_domain() for s in step_runs]
        return run.to_domain(stages)

    async def list_runs(
        self, workspace_id: str, limit: int = 50, offset: int = 0
    ) -> list[WorkflowInstance]:
        stmt = (
            select(WorkflowRun)
            .where(WorkflowRun.workspace_id == workspace_id)
            .order_by(WorkflowRun.started_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._db.execute(stmt)
        runs = list(result.scalars().all())
        instances: list[WorkflowInstance] = []
        for run in runs:
            step_stmt = (
                select(WorkflowStepRun)
                .where(WorkflowStepRun.workflow_instance_id == run.instance_id)
                .order_by(WorkflowStepRun.stage_id)
            )
            step_result = await self._db.execute(step_stmt)
            step_runs = list(step_result.scalars().all())
            instances.append(run.to_domain([s.to_domain() for s in step_runs]))
        return instances

    async def update_stage(self, stage: StageInstance) -> None:
        step = await self._db.get(WorkflowStepRun, stage.stage_instance_id)
        if step is None:
            raise ValueError(f"WorkflowStepRun {stage.stage_instance_id} not found")
        step.status = stage.status.value
        step.attempt = stage.attempt
        step.last_error = stage.last_error
        step.output_payload = stage.output_payload
        step.started_at = stage.started_at
        step.completed_at = stage.completed_at
        await self._db.flush()

    async def get_stage(self, stage_instance_id: str) -> StageInstance | None:
        step = await self._db.get(WorkflowStepRun, stage_instance_id)
        if step is None:
            return None
        return step.to_domain()

    async def save_artifact(
        self,
        workflow_instance_id: str,
        stage_instance_id: str,
        artifact_key: str,
        payload: dict[str, Any],
        content_type: str = "application/json",
    ) -> None:
        self._db.add(
            WorkflowStepArtifact(
                workflow_instance_id=workflow_instance_id,
                stage_instance_id=stage_instance_id,
                artifact_key=artifact_key,
                content_type=content_type,
                payload=payload,
            )
        )
        await self._db.flush()
