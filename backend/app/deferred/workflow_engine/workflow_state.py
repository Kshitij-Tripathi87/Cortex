"""DEFERRED -- Workflow & Orchestration Core

Status: FROZEN (ADR-0007)
Phase: 2+
Reason: Excluded from MVP wedge per cortex-mvp-execution-plan.md section 7.2
Action: Do not import into production paths.

Last touched: 2026-08-01

Workflow state — Redis-backed in-flight state snapshots.

Provides fast, real-time access to workflow and stage state for the
engine and the API without querying PostgreSQL on every status poll.

Uses the existing Redis client infrastructure (app/infrastructure/redis_client.py).
"""

from __future__ import annotations

import json
from typing import Any

from app.deferred.workflow_engine.workflow_models import WorkflowInstance
from app.infrastructure.redis_client import RedisClient, get_redis_client

_STATE_PREFIX = "cortex:workflow:state"
_TTL_SECONDS = 3600 * 24


class WorkflowStateStore:
    """Redis-backed state store for active workflow instances."""

    def __init__(self, redis: RedisClient | None = None) -> None:
        self._redis = redis or get_redis_client()

    def _key(self, instance_id: str) -> str:
        return f"{_STATE_PREFIX}:{instance_id}"

    def _serialize_instance(self, instance: WorkflowInstance) -> dict[str, Any]:
        return {
            "instance_id": instance.instance_id,
            "workflow_name": instance.workflow_name,
            "workspace_id": instance.workspace_id,
            "version": instance.version,
            "status": instance.status.value,
            "triggered_by": instance.triggered_by,
            "stages": [
                {
                    "stage_instance_id": s.stage_instance_id,
                    "stage_id": s.stage_id,
                    "name": s.name,
                    "agent": s.agent,
                    "verb": s.verb,
                    "depends_on": list(s.depends_on),
                    "gate": s.gate,
                    "status": s.status.value,
                    "attempt": s.attempt,
                    "retry_count": s.retry_count,
                    "last_error": s.last_error,
                    "started_at": s.started_at.isoformat() if s.started_at else None,
                    "completed_at": s.completed_at.isoformat() if s.completed_at else None,
                }
                for s in instance.stages
            ],
            "started_at": instance.started_at.isoformat(),
            "updated_at": instance.updated_at.isoformat(),
            "completed_at": instance.completed_at.isoformat() if instance.completed_at else None,
        }

    async def save(self, instance: WorkflowInstance) -> None:
        data = self._serialize_instance(instance)
        await self._redis.set(self._key(instance.instance_id), data, ex=_TTL_SECONDS)

    async def get(self, instance_id: str) -> dict[str, Any] | None:
        return await self._redis.get(self._key(instance_id))

    async def delete(self, instance_id: str) -> None:
        await self._redis.delete(self._key(instance_id))

    async def update_stage_status(
        self, instance_id: str, stage_instance_id: str, status: str, error: str | None = None
    ) -> None:
        raw = await self._redis._redis.get(self._key(instance_id))  # noqa: SLF001
        if raw is None:
            return
        data = json.loads(raw)
        for stage in data.get("stages", []):
            if stage["stage_instance_id"] == stage_instance_id:
                stage["status"] = status
                if error:
                    stage["last_error"] = error
                break
        await self._redis.set(self._key(instance_id), data, ex=_TTL_SECONDS)

    async def set_stage_started(self, instance_id: str, stage_instance_id: str) -> None:
        raw = await self._redis._redis.get(self._key(instance_id))  # noqa: SLF001
        if raw is None:
            return
        data = json.loads(raw)
        from datetime import UTC, datetime

        for stage in data.get("stages", []):
            if stage["stage_instance_id"] == stage_instance_id:
                stage["status"] = "running"
                stage["started_at"] = datetime.now(UTC).isoformat()
                break
        await self._redis.set(self._key(instance_id), data, ex=_TTL_SECONDS)
