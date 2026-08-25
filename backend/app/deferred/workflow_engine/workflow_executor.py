"""DEFERRED -- Workflow & Orchestration Core

Status: FROZEN (ADR-0007)
Phase: 2+
Reason: Excluded from MVP wedge per cortex-mvp-execution-plan.md section 7.2
Action: Do not import into production paths.

Last touched: 2026-08-01

Workflow executor — launches stages as tasks via Redis queue.

Each ready stage is enqueued as a task on the Redis queue for the
appropriate agent. The executor polls for stage completions and advances
the workflow state machine.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from app.deferred.workflow_engine.workflow_engine import WorkflowEngine
from app.deferred.workflow_engine.workflow_events import workflow_event_bus
from app.deferred.workflow_engine.workflow_models import (
    StageInstance,
    StageStatus,
    WorkflowInstance,
    WorkflowStatus,
)
from app.deferred.workflow_engine.workflow_repository import WorkflowRepository
from app.deferred.workflow_engine.workflow_state import WorkflowStateStore
from app.infrastructure.redis_client import get_redis_client

logger = logging.getLogger("cortex.workflow.executor")

_TASK_QUEUE_PREFIX = "cortex:task:queue"
_TASK_META_PREFIX = "cortex:task:meta"
_TASK_LOCK_PREFIX = "cortex:task:lock"


class WorkflowExecutor:
    """Advances a workflow by launching ready stages and polling results."""

    def __init__(
        self,
        repository: WorkflowRepository,
        state_store: WorkflowStateStore,
        engine: WorkflowEngine,
    ) -> None:
        self._repo = repository
        self._state = state_store
        self._engine = engine
        self._redis = get_redis_client()

    async def launch_ready_stages(self, instance: WorkflowInstance) -> list[str]:
        launched: list[str] = []
        ready = self._engine.ready_stages(instance)
        if not ready:
            return launched

        for stage in ready:
            task_id = stage.stage_instance_id
            task_key = f"{_TASK_QUEUE_PREFIX}:{stage.agent}"
            task_payload = json.dumps(
                {
                    "task_id": task_id,
                    "workflow_instance_id": instance.instance_id,
                    "stage_instance_id": stage.stage_instance_id,
                    "agent_id": stage.agent,
                    "verb": stage.verb,
                    "payload": stage.input_payload or {},
                    "workspace_id": instance.workspace_id,
                    "priority": _priority_for_agent(stage.agent),
                }
            )

            await self._redis._redis.zadd(task_key, {task_payload: 0})  # noqa: SLF001
            await self._redis.set(
                f"{_TASK_META_PREFIX}:{task_id}",
                {"status": "queued", "created_at": datetime.now(UTC).isoformat()},
                ex=3600,
            )

            await self._repo.update_stage(
                StageInstance(
                    stage_instance_id=stage.stage_instance_id,
                    workflow_instance_id=stage.workflow_instance_id,
                    stage_id=stage.stage_id,
                    name=stage.name,
                    agent=stage.agent,
                    verb=stage.verb,
                    depends_on=stage.depends_on,
                    gate=stage.gate,
                    status=StageStatus.RUNNING,
                    attempt=stage.attempt + 1,
                    retry_count=stage.retry_count,
                    started_at=datetime.now(UTC),
                )
            )
            await self._state.update_stage_status(
                instance.instance_id, stage.stage_instance_id, "running"
            )

            launched.append(task_id)

        return launched

    async def advance(self, instance: WorkflowInstance) -> WorkflowInstance:
        for stage in instance.stages:
            if stage.gate and stage.status == StageStatus.AWAITING_APPROVAL:
                return instance
            if stage.status in {StageStatus.RUNNING, StageStatus.PENDING}:
                task_status = await self._redis.get(
                    f"{_TASK_META_PREFIX}:{stage.stage_instance_id}"
                )
                if task_status and task_status.get("status") == "completed":
                    await self._repo.update_stage(
                        StageInstance(
                            stage_instance_id=stage.stage_instance_id,
                            workflow_instance_id=instance.instance_id,
                            stage_id=stage.stage_id,
                            name=stage.name,
                            agent=stage.agent,
                            verb=stage.verb,
                            depends_on=stage.depends_on,
                            gate=stage.gate,
                            status=StageStatus.COMPLETED,
                            output_payload=task_status.get("output"),
                            completed_at=datetime.now(UTC),
                        )
                    )
                    await self._state.update_stage_status(
                        instance.instance_id,
                        stage.stage_instance_id,
                        "completed",
                    )
                    await workflow_event_bus.publish(
                        {
                            "event_type": "workflow.stage.completed",
                            "workflow_instance_id": instance.instance_id,
                            "stage_id": stage.stage_id,
                            "workspace_id": instance.workspace_id,
                        }
                    )

        new_status = self._engine.determine_status(instance)
        current = await self._repo.get_run(instance.instance_id)
        if current is None:
            raise ValueError(f"WorkflowInstance {instance.instance_id} not found")
        if new_status == WorkflowStatus.COMPLETED:
            await self._repo.update_run_status(instance.instance_id, new_status, datetime.now(UTC))
        elif new_status != current.status:
            await self._repo.update_run_status(instance.instance_id, new_status)
        return current

    async def handle_failure(
        self, instance: WorkflowInstance, failed_stage: StageInstance, error: str
    ) -> WorkflowInstance:
        if failed_stage.attempt < failed_stage.retry_count:
            new_stage = StageInstance(
                stage_instance_id=failed_stage.stage_instance_id,
                workflow_instance_id=failed_stage.workflow_instance_id,
                stage_id=failed_stage.stage_id,
                name=failed_stage.name,
                agent=failed_stage.agent,
                verb=failed_stage.verb,
                depends_on=failed_stage.depends_on,
                gate=failed_stage.gate,
                status=StageStatus.PENDING,
                attempt=failed_stage.attempt + 1,
                retry_count=failed_stage.retry_count,
                last_error=error,
            )
            await self._repo.update_stage(new_stage)
            return instance

        rolled = self._engine.rollback_stages(instance, failed_stage.stage_id)
        for r in rolled:
            await self._repo.update_stage(
                StageInstance(
                    stage_instance_id=r.stage_instance_id,
                    workflow_instance_id=r.workflow_instance_id,
                    stage_id=r.stage_id,
                    name=r.name,
                    agent=r.agent,
                    verb=r.verb,
                    depends_on=r.depends_on,
                    gate=r.gate,
                    status=StageStatus.ROLLED_BACK,
                    completed_at=datetime.now(UTC),
                )
            )
        await self._repo.update_run_status(instance.instance_id, WorkflowStatus.FAILED)
        return instance


def _priority_for_agent(agent_id: str) -> int:
    _base = {
        "evidence": 10,
        "knowledge": 10,
        "operations": 8,
        "simulation": 7,
        "learning": 5,
        "deployment": 3,
    }
    return _base.get(agent_id, 5)
