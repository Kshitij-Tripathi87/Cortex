"""DEFERRED -- Workflow & Orchestration Core

Status: FROZEN (ADR-0007)
Phase: 2+
Reason: Excluded from MVP wedge per cortex-mvp-execution-plan.md section 7.2
Action: Do not import into production paths.

Last touched: 2026-08-01

Workflow service — public API layer for workflow lifecycle.

The service layer bridges REST endpoints to the engine and repository.
Every operation is async and transactional.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.deferred.workflow_engine.workflow_engine import WorkflowEngine
from app.deferred.workflow_engine.workflow_models import (
    StageInstance,
    StageStatus,
    WorkflowInstance,
    WorkflowStatus,
)
from app.deferred.workflow_engine.workflow_registry import WorkflowRegistry
from app.deferred.workflow_engine.workflow_repository import WorkflowRepository
from app.deferred.workflow_engine.workflow_state import WorkflowStateStore


class WorkflowService:
    """Public API for workflow lifecycle."""

    def __init__(
        self,
        registry: WorkflowRegistry,
        engine: WorkflowEngine,
    ) -> None:
        self._registry = registry
        self._engine = engine

    async def start(
        self,
        db: AsyncSession,
        workflow_name: str,
        workspace_id: str,
        triggered_by: str | None = None,
        version: str | None = None,
        params: dict | None = None,
    ) -> WorkflowInstance:
        definition = self._registry.get(workflow_name, version)
        if definition is None:
            raise ValueError(
                f"Unknown workflow '{workflow_name}'" + (f" version {version}" if version else "")
            )

        from app.common.ids import uuid7

        instance_id = uuid7()
        stages = self._engine.build_stages(definition, instance_id)

        instance = WorkflowInstance(
            instance_id=instance_id,
            workflow_name=definition.name,
            workspace_id=workspace_id,
            version=definition.version,
            status=WorkflowStatus.RUNNING,
            triggered_by=triggered_by,
            stages=stages,
        )

        repo = WorkflowRepository(db)
        await repo.save_workflow(instance)
        await WorkflowStateStore().save(instance)

        from app.deferred.workflow_engine.workflow_events import workflow_event_bus

        await workflow_event_bus.publish(
            {
                "event_type": "workflow.started",
                "workflow_instance_id": instance_id,
                "workflow_name": workflow_name,
                "workspace_id": workspace_id,
                "triggered_by": triggered_by,
            }
        )

        return instance

    async def get_instance(self, db: AsyncSession, instance_id: str) -> WorkflowInstance | None:
        repo = WorkflowRepository(db)
        return await repo.get_run(instance_id)

    async def cancel(self, db: AsyncSession, instance_id: str) -> WorkflowInstance:
        repo = WorkflowRepository(db)
        instance = await repo.get_run(instance_id)
        if instance is None:
            raise ValueError(f"Workflow instance {instance_id} not found")
        if instance.status in {WorkflowStatus.COMPLETED, WorkflowStatus.CANCELLED}:
            raise ValueError(f"Cannot cancel workflow in status {instance.status.value}")
        await repo.update_run_status(instance_id, WorkflowStatus.CANCELLED, datetime.now(UTC))
        return await repo.get_run(instance_id)

    async def retry(self, db: AsyncSession, instance_id: str) -> WorkflowInstance:
        repo = WorkflowRepository(db)
        instance = await repo.get_run(instance_id)
        if instance is None:
            raise ValueError(f"Workflow instance {instance_id} not found")
        if instance.status != WorkflowStatus.FAILED:
            raise ValueError("Only failed workflows can be retried")

        replayed = self._engine.replay_from_instance(
            self._registry.get(instance.workflow_name, instance.version),
            instance,
        )
        await repo.save_workflow(replayed)
        await WorkflowStateStore().save(replayed)
        return replayed

    async def resume(self, db: AsyncSession, instance_id: str) -> WorkflowInstance:
        repo = WorkflowRepository(db)
        instance = await repo.get_run(instance_id)
        if instance is None:
            raise ValueError(f"Workflow instance {instance_id} not found")
        if instance.status != WorkflowStatus.AWAITING_APPROVAL:
            raise ValueError(f"Cannot resume instance in status {instance.status.value}")
        await repo.update_run_status(instance_id, WorkflowStatus.RUNNING)
        return await repo.get_run(instance_id)

    async def approve_gate(
        self,
        db: AsyncSession,
        instance_id: str,
        stage_instance_id: str,
        approved_by: str,
        rationale: str | None = None,
    ) -> WorkflowInstance:
        repo = WorkflowRepository(db)
        instance = await repo.get_run(instance_id)
        if instance is None:
            raise ValueError(f"Workflow instance {instance_id} not found")

        stage = await repo.get_stage(stage_instance_id)
        if stage is None:
            raise ValueError(f"Stage {stage_instance_id} not found")
        if not stage.gate:
            raise ValueError(f"Stage {stage_instance_id} is not a gate stage")
        if stage.status != StageStatus.AWAITING_APPROVAL:
            raise ValueError(f"Stage {stage_instance_id} is not awaiting approval")

        await repo.update_stage(
            StageInstance(
                stage_instance_id=stage.stage_instance_id,
                workflow_instance_id=stage.workflow_instance_id,
                stage_id=stage.stage_id,
                name=stage.name,
                agent=stage.agent,
                verb=stage.verb,
                depends_on=stage.depends_on,
                gate=stage.gate,
                status=StageStatus.COMPLETED,
                completed_at=datetime.now(UTC),
            )
        )

        return await repo.get_run(instance_id)

    async def list_instances(
        self, db: AsyncSession, workspace_id: str, limit: int = 50, offset: int = 0
    ) -> list[WorkflowInstance]:
        repo = WorkflowRepository(db)
        return await repo.list_runs(workspace_id, limit, offset)
