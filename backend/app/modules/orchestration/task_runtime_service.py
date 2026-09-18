"""Durable orchestration task runtime for Cortex Nexus.

PostgreSQL is authoritative for every task lifecycle transition. Each service
operation commits before returning, so a worker crash can never make a task
appear to have advanced beyond what the database says. Redis is not consulted
at any point in the task lifecycle.

The approval boundary is enforced here: ``APPROVED`` is reachable only
through an explicit human decision recorded with an approver identity, and
``EXECUTING`` only from ``APPROVED``. Nothing turns ``PROPOSED`` into
``EXECUTING`` autonomously.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .contracts import AgentProposal, TaskPlan, TaskPlanStep
from .task_intent import TaskIntent
from .task_lifecycle import TERMINAL_STATUSES, TaskLifecycleError, TaskStatus
from .task_runtime_models import TaskDB
from .task_runtime_repository import TaskNotFound, TaskRuntimeRepository


@dataclass(frozen=True)
class TaskScope:
    """Tenant/workspace identity every runtime operation is revalidated against."""

    tenant_id: UUID
    workspace_id: UUID


def rehydrate_plan(payload: dict[str, Any]) -> TaskPlan:
    """Rebuild the frozen TaskPlan contract from its durable JSON payload."""

    return TaskPlan(
        task_id=UUID(payload["task_id"]),
        objective=payload["objective"],
        steps=tuple(TaskPlanStep(**step) for step in payload["steps"]),
        assumptions=tuple(payload.get("assumptions", ())),
    )


class NexusTaskRuntime:
    """Session-scoped durable operations for one-task-at-a-time drivers."""

    def __init__(self, *, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @asynccontextmanager
    async def _repository(self) -> AsyncGenerator[TaskRuntimeRepository]:
        async with self._session_factory() as session:
            yield TaskRuntimeRepository(session=session)

    # ── Creation and lookups ─────────────────────────────────────────────────

    async def create_task(
        self,
        *,
        scope: TaskScope,
        actor_id: UUID,
        trace_id: UUID,
        objective: str,
        world_state_version: int,
        requires_approval: bool,
        policy_context: dict[str, Any],
        budget: float = 100.0,
        deadline: datetime | None = None,
    ) -> str:
        async with self._repository() as repo:
            task = await repo.create_task(
                tenant_id=scope.tenant_id,
                workspace_id=scope.workspace_id,
                actor_id=actor_id,
                trace_id=trace_id,
                objective=objective,
                world_state_version=world_state_version,
                requires_approval=requires_approval,
                policy_context=policy_context,
                budget=budget,
                deadline=deadline,
            )
            return task.task_id

    async def get_task(self, task_id: str, *, scope: TaskScope) -> TaskDB:
        async with self._repository() as repo:
            return await repo.get_task(
                task_id, tenant_id=scope.tenant_id, workspace_id=scope.workspace_id
            )

    async def get_status(self, task_id: str, *, scope: TaskScope) -> TaskStatus:
        task = await self.get_task(task_id, scope=scope)
        return cast(TaskStatus, task.status)

    # ── Phase checkpoints (idempotent) ──────────────────────────────────────

    async def resolve_intent(self, task_id: str, *, scope: TaskScope, intent: TaskIntent) -> bool:
        """Checkpoint task understanding. Returns False when already resolved.

        The intent row is committed before the status transition; a resume
        that finds the row never re-runs intent resolution.
        """

        async with self._repository() as repo:
            task = await repo.get_task(
                task_id, tenant_id=scope.tenant_id, workspace_id=scope.workspace_id
            )
            existing = await repo.get_intent(task)
            if existing is not None:
                if task.status == "CREATED":
                    await repo.transition_task(
                        task, target="INTENT_RESOLVED", actor_id=UUID(task.actor_id)
                    )
                return False
            await repo.save_intent(
                task, objective=intent.objective, intent_payload=intent.model_dump(mode="json")
            )
            await repo.transition_task(task, target="INTENT_RESOLVED", actor_id=UUID(task.actor_id))
            return True

    async def checkpoint_plan(self, task_id: str, *, scope: TaskScope, plan: TaskPlan) -> bool:
        """Checkpoint planning. Returns False when a plan already exists."""

        async with self._repository() as repo:
            task = await repo.get_task(
                task_id, tenant_id=scope.tenant_id, workspace_id=scope.workspace_id
            )
            existing = await repo.get_latest_plan(task)
            if existing is not None:
                if task.status == "INTENT_RESOLVED":
                    await repo.transition_task(task, target="PLANNED", actor_id=UUID(task.actor_id))
                return False
            payload = {
                "task_id": task.task_id,
                "objective": plan.objective,
                "steps": [
                    {
                        "step_id": step.step_id,
                        "title": step.title,
                        "agent_role": step.agent_role,
                        "dependencies": list(step.dependencies),
                        "required_capabilities": list(step.required_capabilities),
                        "expected_outputs": list(step.expected_outputs),
                    }
                    for step in plan.steps
                ],
                "assumptions": list(plan.assumptions),
            }
            await repo.save_plan(task, plan_payload=payload, assumptions=list(plan.assumptions))
            await repo.transition_task(task, target="PLANNED", actor_id=UUID(task.actor_id))
            return True

    async def get_plan(self, task_id: str, *, scope: TaskScope) -> TaskPlan | None:
        async with self._repository() as repo:
            task = await repo.get_task(
                task_id, tenant_id=scope.tenant_id, workspace_id=scope.workspace_id
            )
            record = await repo.get_latest_plan(task)
            if record is None:
                return None
            return rehydrate_plan(record.plan_payload)

    async def start_run(self, task_id: str, *, scope: TaskScope) -> str:
        """PLANNED -> RUNNING with a durable run row; resumable when RUNNING."""

        async with self._repository() as repo:
            task = await repo.get_task(
                task_id, tenant_id=scope.tenant_id, workspace_id=scope.workspace_id
            )
            if task.status == "PLANNED":
                run = await repo.create_run(task, world_state_version=task.world_state_version)
                await repo.transition_task(task, target="RUNNING", actor_id=UUID(task.actor_id))
                return run.run_id
            if task.status == "RUNNING":
                existing_run = await repo.get_latest_run(task)
                if existing_run is not None:
                    return existing_run.run_id
                raise TaskLifecycleError(f"Task {task_id} is RUNNING without a durable run row.")
            raise TaskLifecycleError(f"Task {task_id} cannot start a run from {task.status}.")

    async def get_run_id(self, task_id: str, *, scope: TaskScope) -> str:
        async with self._repository() as repo:
            task = await repo.get_task(
                task_id, tenant_id=scope.tenant_id, workspace_id=scope.workspace_id
            )
            run = await repo.get_latest_run(task)
            if run is None:
                raise TaskNotFound(f"Task {task_id} has no run yet.")
            return run.run_id

    # ── Durable execution records ───────────────────────────────────────────

    async def record_step(
        self,
        task_id: str,
        *,
        scope: TaskScope,
        run_id: str,
        step_id: str,
        agent_role: str,
        status: str,
        error: str | None,
        invocation_ids: list[str],
        evidence_refs: list[str],
        outputs: list[dict[str, Any]],
    ) -> None:
        async with self._repository() as repo:
            task = await repo.get_task(
                task_id, tenant_id=scope.tenant_id, workspace_id=scope.workspace_id
            )
            run = await repo.get_latest_run(task)
            if run is None or run.run_id != run_id:
                raise TaskNotFound(f"Run {run_id} is not visible in this scope.")
            await repo.upsert_step(
                run,
                step_id=step_id,
                agent_role=agent_role,
                status=status,
                error=error,
                invocation_ids=invocation_ids,
                evidence_refs=evidence_refs,
                outputs=outputs,
            )
            await repo.finish_run(run, status=run.status, checkpoint_step=step_id)

    async def record_invocation(
        self,
        task_id: str,
        *,
        scope: TaskScope,
        run_id: str,
        step_id: str,
        result: Any,
    ) -> None:
        """Persist one gateway invocation; idempotent by invocation id."""

        async with self._repository() as repo:
            task = await repo.get_task(
                task_id, tenant_id=scope.tenant_id, workspace_id=scope.workspace_id
            )
            await repo.record_invocation(task, run_id=run_id, step_id=step_id, result=result)

    async def record_evidence(
        self,
        task_id: str,
        *,
        scope: TaskScope,
        ref: str,
        source_invocation_id: str | None,
        payload_digest: str | None = None,
    ) -> None:
        async with self._repository() as repo:
            task = await repo.get_task(
                task_id, tenant_id=scope.tenant_id, workspace_id=scope.workspace_id
            )
            await repo.record_evidence(
                task,
                ref=ref,
                source_invocation_id=source_invocation_id,
                payload_digest=payload_digest,
            )

    async def record_proposals(
        self, task_id: str, *, scope: TaskScope, proposals: tuple[AgentProposal, ...]
    ) -> None:
        """Persist synthesized proposals; idempotent (never duplicated)."""

        async with self._repository() as repo:
            task = await repo.get_task(
                task_id, tenant_id=scope.tenant_id, workspace_id=scope.workspace_id
            )
            await repo.save_proposals(task, proposals=proposals)

    async def mark_proposed(self, task_id: str, *, scope: TaskScope) -> None:
        async with self._repository() as repo:
            task = await repo.get_task(
                task_id, tenant_id=scope.tenant_id, workspace_id=scope.workspace_id
            )
            await repo.transition_task(task, target="PROPOSED", actor_id=UUID(task.actor_id))

    # ── Approval boundary ────────────────────────────────────────────────────

    async def request_approval(self, task_id: str, *, scope: TaskScope, reason: str) -> None:
        async with self._repository() as repo:
            task = await repo.get_task(
                task_id, tenant_id=scope.tenant_id, workspace_id=scope.workspace_id
            )
            await repo.transition_task(
                task, target="AWAITING_APPROVAL", actor_id=UUID(task.actor_id), reason=reason
            )
            await repo.append_approval(task, decision="REQUESTED", approver_id=None, reason=reason)

    async def decide_approval(
        self,
        task_id: str,
        *,
        scope: TaskScope,
        approved: bool,
        approver_id: UUID,
        reason: str | None = None,
    ) -> None:
        """Record the human decision. APPROVED requires an approver identity."""

        async with self._repository() as repo:
            task = await repo.get_task(
                task_id, tenant_id=scope.tenant_id, workspace_id=scope.workspace_id
            )
            if approved and approver_id is None:
                raise TaskLifecycleError("Approval requires a human approver identity.")
            await repo.append_approval(
                task,
                decision="APPROVED" if approved else "REJECTED",
                approver_id=approver_id,
                reason=reason,
            )
            await repo.transition_task(
                task,
                target="APPROVED" if approved else "REJECTED",
                actor_id=approver_id,
                reason=reason,
            )

    # ── Execution and completion ──────────────────────────────────────────────

    async def start_execution(self, task_id: str, *, scope: TaskScope) -> str:
        """APPROVED -> EXECUTING. Idempotent: resuming returns the same row."""

        async with self._repository() as repo:
            task = await repo.get_task(
                task_id, tenant_id=scope.tenant_id, workspace_id=scope.workspace_id
            )
            if task.status == "APPROVED":
                execution = await repo.start_execution(
                    task, idempotency_key=f"execute:{task.task_id}"
                )
                await repo.transition_task(task, target="EXECUTING", actor_id=UUID(task.actor_id))
                return execution.execution_id
            if task.status == "EXECUTING":
                existing_execution = await repo.get_execution(task)
                if existing_execution is not None:
                    return existing_execution.execution_id
                raise TaskLifecycleError(f"Task {task_id} is EXECUTING without an execution row.")
            raise TaskLifecycleError(
                f"Task {task_id} cannot execute from {task.status}: approval is a hard boundary."
            )

    async def finish_execution(
        self,
        task_id: str,
        *,
        scope: TaskScope,
        success: bool,
        failure_reason: str | None = None,
    ) -> None:
        """EXECUTING -> COMPLETED or FAILED with a durable outcome record."""

        async with self._repository() as repo:
            task = await repo.get_task(
                task_id, tenant_id=scope.tenant_id, workspace_id=scope.workspace_id
            )
            execution = await repo.get_execution(task)
            if execution is None:
                raise TaskLifecycleError(f"Task {task_id} has no execution record.")
            await repo.finish_execution(
                execution,
                status="SUCCEEDED" if success else "FAILED",
                failure_reason=failure_reason,
            )
            await repo.transition_task(
                task,
                target="COMPLETED" if success else "FAILED",
                actor_id=UUID(task.actor_id),
                reason=failure_reason,
            )
            await repo.save_outcome(
                task,
                status="COMPLETED" if success else "FAILED",
                recommendation=None,
                result_payload={
                    "executed_via": execution.idempotency_key,
                    "attempts": execution.attempts,
                    "failure_reason": failure_reason,
                },
            )

    async def complete_task(
        self,
        task_id: str,
        *,
        scope: TaskScope,
        recommendation: str | None,
        result_payload: dict[str, Any],
    ) -> None:
        """PROPOSED -> COMPLETED for tasks with nothing consequential to execute."""

        async with self._repository() as repo:
            task = await repo.get_task(
                task_id, tenant_id=scope.tenant_id, workspace_id=scope.workspace_id
            )
            await repo.transition_task(task, target="COMPLETED", actor_id=UUID(task.actor_id))
            await repo.save_outcome(
                task,
                status="COMPLETED",
                recommendation=recommendation,
                result_payload=result_payload,
            )

    async def block_task(self, task_id: str, *, scope: TaskScope, reason: str) -> None:
        """Explicit BLOCKED terminal state; silence is never a valid state."""

        async with self._repository() as repo:
            task = await repo.get_task(
                task_id, tenant_id=scope.tenant_id, workspace_id=scope.workspace_id
            )
            if task.status in TERMINAL_STATUSES:
                raise TaskLifecycleError(f"Task {task_id} is already terminal: {task.status}")
            await repo.transition_task(
                task, target="BLOCKED", actor_id=UUID(task.actor_id), reason=reason
            )
            await repo.set_terminal_reasons(task, blocked_reason=reason)

    async def fail_task(self, task_id: str, *, scope: TaskScope, reason: str) -> None:
        async with self._repository() as repo:
            task = await repo.get_task(
                task_id, tenant_id=scope.tenant_id, workspace_id=scope.workspace_id
            )
            if task.status in TERMINAL_STATUSES:
                raise TaskLifecycleError(f"Task {task_id} is already terminal: {task.status}")
            await repo.transition_task(
                task, target="FAILED", actor_id=UUID(task.actor_id), reason=reason
            )
            await repo.set_terminal_reasons(task, failure_reason=reason)

    # ── NexusTrace reconstruction ─────────────────────────────────────────────

    async def build_nexus_trace(self, task_id: str, *, scope: TaskScope) -> dict[str, Any]:
        """Assemble the full task trace from durable records only."""

        async with self._repository() as repo:
            task = await repo.get_task(
                task_id, tenant_id=scope.tenant_id, workspace_id=scope.workspace_id
            )
            intent = await repo.get_intent(task)
            plan = await repo.get_latest_plan(task)
            runs = []
            steps = []
            for run in await repo.list_runs(task):
                runs.append(
                    {
                        "run_id": run.run_id,
                        "run_number": run.run_number,
                        "status": run.status,
                        "world_state_version": run.world_state_version,
                        "checkpoint_step": run.checkpoint_step,
                    }
                )
                for step in await repo.list_steps(run):
                    steps.append(
                        {
                            "run_id": run.run_id,
                            "step_id": step.step_id,
                            "agent_role": step.agent_role,
                            "status": step.status,
                            "error": step.error,
                            "invocation_ids": list(step.invocation_ids),
                            "evidence_refs": list(step.evidence_refs),
                        }
                    )
            invocations = [
                {
                    "invocation_id": record.invocation_id,
                    "step_id": record.step_id,
                    "capability_id": record.capability_id,
                    "capability_version": record.capability_version,
                    "status": record.status,
                    "side_effect": record.side_effect,
                    "world_state_version": record.world_state_version,
                    "arguments_sha256": record.arguments_sha256,
                    "evidence_refs": list(record.evidence_refs),
                    "error": record.error,
                    "authorization": dict(record.authorization),
                }
                for record in await repo.list_invocations(task)
            ]
            evidence = [
                {
                    "ref": record.ref,
                    "source_invocation_id": record.source_invocation_id,
                    "payload_digest": record.payload_digest,
                }
                for record in await repo.list_evidence(task)
            ]
            proposals = [
                {
                    "agent_id": record.agent_id,
                    "agent_role": record.agent_role,
                    "statement": record.statement,
                    "actions": list(record.actions),
                    "evidence_refs": list(record.evidence_refs),
                    "confidence": record.confidence,
                    "assumptions": list(record.assumptions),
                }
                for record in await repo.list_proposals(task)
            ]
            approvals = [
                {
                    "decision": record.decision,
                    "approver_id": record.approver_id,
                    "reason": record.reason,
                    "decided_at": record.created_at.isoformat(),
                }
                for record in await repo.list_approvals(task)
            ]
            execution = await repo.get_execution(task)
            outcome = await repo.get_outcome(task)
            return {
                "task_id": task.task_id,
                "tenant_id": task.tenant_id,
                "workspace_id": task.workspace_id,
                "actor_id": task.actor_id,
                "trace_id": task.trace_id,
                "status": task.status,
                "objective": task.objective,
                "world_state_version": task.world_state_version,
                "budget": task.budget,
                "deadline": task.deadline.isoformat() if task.deadline else None,
                "requires_approval": task.requires_approval,
                "transitions": [
                    {
                        "from_status": transition.from_status,
                        "to_status": transition.to_status,
                        "reason": transition.reason,
                        "at": transition.created_at.isoformat(),
                    }
                    for transition in await repo.list_transitions(task)
                ],
                "intent": dict(intent.intent_payload) if intent is not None else None,
                "plan": dict(plan.plan_payload) if plan is not None else None,
                "runs": runs,
                "steps": steps,
                "invocations": invocations,
                "evidence": evidence,
                "proposals": proposals,
                "approvals": approvals,
                "execution": (
                    {
                        "execution_id": execution.execution_id,
                        "status": execution.status,
                        "attempts": execution.attempts,
                        "idempotency_key": execution.idempotency_key,
                        "failure_reason": execution.failure_reason,
                    }
                    if execution is not None
                    else None
                ),
                "outcome": (
                    {
                        "status": outcome.status,
                        "recommendation": outcome.recommendation,
                        "result_payload": dict(outcome.result_payload),
                        "completed_at": outcome.completed_at.isoformat(),
                    }
                    if outcome is not None
                    else None
                ),
            }
