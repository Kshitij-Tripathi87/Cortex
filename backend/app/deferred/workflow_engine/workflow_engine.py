"""DEFERRED -- Workflow & Orchestration Core

Status: FROZEN (ADR-0007)
Phase: 2+
Reason: Excluded from MVP wedge per cortex-mvp-execution-plan.md section 7.2
Action: Do not import into production paths.

Last touched: 2026-08-01

Workflow engine — DAG execution engine and state machine.

The engine is the heart of the workflow system.  It:

1.  Receives a WorkflowInstance with its stages as a DAG.
2.  Propagates stage execution via topological order (ready when all deps complete).
3.  Applies state transitions for each stage:
      pending → running → completed / failed / awaiting_approval.
4.  Rolls back completed stages when a failure is unrecoverable.
5.  Produces deterministic execution — same input → same output order.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from app.deferred.workflow_engine.workflow_models import (
    StageInstance,
    StageStatus,
    WorkflowDefinition,
    WorkflowInstance,
    WorkflowStatus,
)

logger = logging.getLogger("cortex.workflow.engine")

StageExecutor = Callable[
    [WorkflowInstance, StageInstance, dict[str, Any]],
    Awaitable[dict[str, Any]],
]


class StageExecutionError(Exception):
    """Raised when a stage fails execution and cannot be retried."""


class WorkflowEngine:
    """DAG-based workflow engine with retry and deterministic replay."""

    def __init__(self) -> None:
        self._pending_callbacks: dict[str, asyncio.Event] = {}

    def build_stages(
        self, definition: WorkflowDefinition, instance_id: str
    ) -> tuple[StageInstance, ...]:
        return tuple(
            StageInstance(
                workflow_instance_id=instance_id,
                stage_id=s.stage_id,
                name=s.name,
                agent=s.agent,
                verb=s.verb,
                depends_on=s.depends_on,
                gate=s.gate,
                retry_count=s.retry_count,
                status=StageStatus.PENDING,
            )
            for s in definition.stages
        )

    def ready_stages(self, instance: WorkflowInstance) -> tuple[StageInstance, ...]:
        completed_ids = {
            s.stage_id
            for s in instance.stages
            if s.status in {StageStatus.COMPLETED, StageStatus.SKIPPED}
        }
        result: list[StageInstance] = []
        for stage in instance.stages:
            if stage.status != StageStatus.PENDING:
                continue
            if not stage.depends_on or all(dep in completed_ids for dep in stage.depends_on):
                result.append(stage)
        return tuple(result)

    def finished(self, instance: WorkflowInstance) -> bool:
        return all(
            s.status
            in {
                StageStatus.COMPLETED,
                StageStatus.SKIPPED,
                StageStatus.ROLLED_BACK,
                StageStatus.REJECTED,
                StageStatus.FAILED,
            }
            for s in instance.stages
            if not s.gate
        )

    def determine_status(self, instance: WorkflowInstance) -> WorkflowStatus:
        if any(s.status == StageStatus.FAILED for s in instance.stages):
            return WorkflowStatus.FAILED
        if any(s.status == StageStatus.AWAITING_APPROVAL for s in instance.stages):
            return WorkflowStatus.AWAITING_APPROVAL
        if all(
            s.status
            in {
                StageStatus.COMPLETED,
                StageStatus.SKIPPED,
                StageStatus.REJECTED,
            }
            for s in instance.stages
        ):
            return WorkflowStatus.COMPLETED
        return WorkflowStatus.RUNNING

    def rollback_stages(
        self, instance: WorkflowInstance, failed_stage_id: str
    ) -> tuple[StageInstance, ...]:
        stages = list(instance.stages)
        rolled_back: list[StageInstance] = []
        for stage in stages:
            if stage.stage_id == failed_stage_id:
                continue
            if stage.status in {StageStatus.COMPLETED, StageStatus.RUNNING}:
                rolled_back.append(
                    StageInstance(
                        stage_instance_id=stage.stage_instance_id,
                        workflow_instance_id=stage.workflow_instance_id,
                        stage_id=stage.stage_id,
                        name=stage.name,
                        agent=stage.agent,
                        verb=stage.verb,
                        depends_on=stage.depends_on,
                        gate=stage.gate,
                        status=StageStatus.ROLLED_BACK,
                        attempt=stage.attempt,
                        retry_count=stage.retry_count,
                        completed_at=datetime.now(UTC),
                    )
                )
        return tuple(rolled_back)

    def replay_from_instance(
        self, definition: WorkflowDefinition, instance: WorkflowInstance
    ) -> WorkflowInstance:
        from app.common.ids import uuid7

        new_id = uuid7()
        stages: list[StageInstance] = []
        for s in instance.stages:
            stages.append(
                StageInstance(
                    workflow_instance_id=new_id,
                    stage_id=s.stage_id,
                    name=s.name,
                    agent=s.agent,
                    verb=s.verb,
                    depends_on=s.depends_on,
                    gate=s.gate,
                    retry_count=s.retry_count,
                    status=StageStatus.PENDING,
                    input_payload=s.input_payload,
                )
            )
        return WorkflowInstance(
            instance_id=new_id,
            workflow_name=instance.workflow_name,
            workspace_id=instance.workspace_id,
            version=instance.version,
            status=WorkflowStatus.CREATED,
            triggered_by=instance.triggered_by,
            stages=tuple(stages),
        )


engine = WorkflowEngine()
