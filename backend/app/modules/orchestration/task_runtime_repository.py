"""Scoped, transactional persistence for the Nexus task runtime.

PostgreSQL (via the injected async session) is authoritative. Every mutation
commits before the caller proceeds, every query is tenant/workspace scoped,
lifecycle transitions are guarded by the expected current status (a crashed
or duplicate worker can never phantom-advance a task), and idempotent writes
key on natural identifiers (invocation id, task+ref, unique task columns).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .contracts import AgentProposal
from .task_lifecycle import TaskStatus, assert_transition
from .task_runtime_models import (
    TaskApprovalDB,
    TaskDB,
    TaskEvidenceDB,
    TaskExecutionDB,
    TaskIntentDB,
    TaskInvocationDB,
    TaskOutcomeDB,
    TaskPlanDB,
    TaskProposalDB,
    TaskRunDB,
    TaskStepDB,
    TaskTransitionDB,
)
from .tool_gateway import ToolInvocationResult


class TaskNotFound(LookupError):
    """Raised when a task does not exist inside the requesting scope."""


class TaskStateConflictError(RuntimeError):
    """Raised when a guarded transition did not match the expected state."""


def _new_task_id() -> str:
    return str(uuid4())


class TaskRuntimeRepository:
    """Durable state store for one orchestration task lifecycle."""

    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session

    # ── Task root and guarded lifecycle transitions ─────────────────────────

    async def get_task(self, task_id: str, *, tenant_id: UUID, workspace_id: UUID) -> TaskDB:
        task = await self._session.get(TaskDB, task_id)
        if (
            task is None
            or task.tenant_id != str(tenant_id)
            or task.workspace_id != str(workspace_id)
        ):
            raise TaskNotFound(f"Task {task_id} is not visible in this workspace.")
        return task

    async def create_task(
        self,
        *,
        tenant_id: UUID,
        workspace_id: UUID,
        actor_id: UUID,
        trace_id: UUID,
        objective: str,
        world_state_version: int,
        requires_approval: bool,
        policy_context: dict[str, Any],
        budget: float = 100.0,
        deadline: datetime | None = None,
        task_id: str | None = None,
    ) -> TaskDB:
        task = TaskDB(
            task_id=task_id or _new_task_id(),
            tenant_id=str(tenant_id),
            workspace_id=str(workspace_id),
            actor_id=str(actor_id),
            trace_id=str(trace_id),
            status="CREATED",
            objective=objective,
            world_state_version=world_state_version,
            budget=budget,
            deadline=deadline,
            requires_approval=requires_approval,
            policy_context=dict(policy_context),
        )
        self._session.add(task)
        await self._session.flush()
        await self._record_transition(task, None, "CREATED", None)
        await self._session.commit()
        return task

    async def transition_task(
        self,
        task: TaskDB,
        *,
        target: TaskStatus,
        actor_id: UUID,
        expected: TaskStatus | None = None,
        reason: str | None = None,
    ) -> TaskDB:
        """Advance the lifecycle; fail closed on illegal or raced transitions."""

        current = cast(TaskStatus, task.status)
        expected_status = expected if expected is not None else current
        if expected_status != current:
            raise TaskStateConflictError(
                f"Task {task.task_id} moved from {expected_status} to {current} before transition."
            )
        assert_transition(current, target)  # raises TaskLifecycleError when illegal
        result = await self._session.execute(
            update(TaskDB)
            .where(TaskDB.task_id == task.task_id, TaskDB.status == current)
            .values(status=target)
        )
        if int(getattr(result, "rowcount", 0)) != 1:
            await self._session.rollback()
            raise TaskStateConflictError(
                f"Task {task.task_id} was concurrently modified; no transition applied."
            )
        await self._record_transition(task, current, target, reason)
        task.status = target
        await self._session.commit()
        return task

    async def _record_transition(
        self,
        task: TaskDB,
        from_status: TaskStatus | None,
        to_status: TaskStatus,
        reason: str | None,
    ) -> None:
        self._session.add(
            TaskTransitionDB(
                task_id=task.task_id,
                from_status=from_status,
                to_status=to_status,
                reason=reason,
                actor_id=task.actor_id,
            )
        )
        await self._session.flush()

    async def list_transitions(self, task: TaskDB) -> list[TaskTransitionDB]:
        result = await self._session.scalars(
            select(TaskTransitionDB)
            .where(TaskTransitionDB.task_id == task.task_id)
            .order_by(TaskTransitionDB.created_at)
        )
        return list(result)

    # ── Intent and plan checkpoints (idempotent) ─────────────────────────────

    async def get_intent(self, task: TaskDB) -> TaskIntentDB | None:
        return cast(
            TaskIntentDB | None,
            await self._session.scalar(
                select(TaskIntentDB).where(TaskIntentDB.task_id == task.task_id)
            ),
        )

    async def save_intent(
        self, task: TaskDB, *, objective: str, intent_payload: dict[str, Any]
    ) -> TaskIntentDB:
        existing = await self.get_intent(task)
        if existing is not None:
            return existing
        record = TaskIntentDB(
            task_id=task.task_id, objective=objective, intent_payload=intent_payload
        )
        self._session.add(record)
        await self._session.commit()
        return record

    async def get_latest_plan(self, task: TaskDB) -> TaskPlanDB | None:
        return cast(
            TaskPlanDB | None,
            await self._session.scalar(
                select(TaskPlanDB)
                .where(TaskPlanDB.task_id == task.task_id)
                .order_by(TaskPlanDB.created_at.desc())
                .limit(1)
            ),
        )

    async def save_plan(
        self, task: TaskDB, *, plan_payload: dict[str, Any], assumptions: list[str]
    ) -> TaskPlanDB:
        record = TaskPlanDB(
            task_id=task.task_id, plan_payload=plan_payload, assumptions=list(assumptions)
        )
        self._session.add(record)
        await self._session.commit()
        return record

    # ── Runs, steps, invocations ────────────────────────────────────────────

    async def get_latest_run(self, task: TaskDB) -> TaskRunDB | None:
        return cast(
            TaskRunDB | None,
            await self._session.scalar(
                select(TaskRunDB)
                .where(TaskRunDB.task_id == task.task_id)
                .order_by(TaskRunDB.run_number.desc())
                .limit(1)
            ),
        )

    async def list_runs(self, task: TaskDB) -> list[TaskRunDB]:
        result = await self._session.scalars(
            select(TaskRunDB)
            .where(TaskRunDB.task_id == task.task_id)
            .order_by(TaskRunDB.run_number)
        )
        return list(result)

    async def create_run(self, task: TaskDB, *, world_state_version: int) -> TaskRunDB:
        latest = await self.get_latest_run(task)
        run = TaskRunDB(
            task_id=task.task_id,
            run_number=(latest.run_number + 1) if latest is not None else 1,
            status="RUNNING",
            world_state_version=world_state_version,
        )
        self._session.add(run)
        await self._session.commit()
        return run

    async def finish_run(
        self, run: TaskRunDB, *, status: str, checkpoint_step: str | None
    ) -> TaskRunDB:
        run.status = status
        run.checkpoint_step = checkpoint_step
        await self._session.commit()
        return run

    async def upsert_step(
        self,
        run: TaskRunDB,
        *,
        step_id: str,
        agent_role: str,
        status: str,
        error: str | None,
        invocation_ids: list[str],
        evidence_refs: list[str],
        outputs: list[dict[str, Any]],
    ) -> TaskStepDB:
        existing = await self._session.scalar(
            select(TaskStepDB).where(TaskStepDB.run_id == run.run_id, TaskStepDB.step_id == step_id)
        )
        if existing is not None:
            return existing
        record = TaskStepDB(
            run_id=run.run_id,
            task_id=run.task_id,
            step_id=step_id,
            agent_role=agent_role,
            status=status,
            error=error,
            invocation_ids=list(invocation_ids),
            evidence_refs=list(evidence_refs),
            outputs=list(outputs),
        )
        self._session.add(record)
        await self._session.commit()
        return record

    async def list_steps(self, run: TaskRunDB) -> list[TaskStepDB]:
        result = await self._session.scalars(
            select(TaskStepDB).where(TaskStepDB.run_id == run.run_id)
        )
        return list(result)

    async def record_invocation(
        self, task: TaskDB, *, run_id: str, step_id: str, result: ToolInvocationResult
    ) -> TaskInvocationDB:
        """Idempotent by invocation id: a retried record never duplicates."""

        existing = await self._session.get(TaskInvocationDB, str(result.invocation_id))
        if existing is not None:
            return existing
        record = TaskInvocationDB(
            invocation_id=str(result.invocation_id),
            task_id=task.task_id,
            run_id=run_id,
            step_id=step_id,
            capability_id=result.capability_id,
            capability_version=result.capability_version,
            status=result.status,
            side_effect=result.side_effect,
            world_state_version=result.world_state_version,
            arguments_sha256=result.provenance.arguments_sha256,
            authorization={
                "allowed": result.authorization.allowed,
                "reason": result.authorization.reason,
                "policy_id": result.authorization.policy_id,
            },
            provenance={
                "invoked_at": result.provenance.invoked_at.isoformat(),
                "actor_id": str(result.provenance.actor_id),
                "tenant_id": str(result.provenance.tenant_id),
                "workspace_id": str(result.provenance.workspace_id),
                "task_id": str(result.provenance.task_id),
                "trace_id": str(result.provenance.trace_id),
                "capability_id": result.provenance.capability_id,
                "capability_version": result.provenance.capability_version,
                "world_state_version": result.provenance.world_state_version,
                "arguments_sha256": result.provenance.arguments_sha256,
            },
            evidence_refs=list(result.evidence_refs),
            result_data=result.data,
            error=result.error,
        )
        self._session.add(record)
        await self._session.commit()
        return record

    async def find_prior_success_invocation(
        self, task: TaskDB, *, step_id: str, capability_id: str, arguments_sha256: str
    ) -> TaskInvocationDB | None:
        """Resume helper: has this exact invocation already succeeded durably?"""

        return cast(
            TaskInvocationDB | None,
            await self._session.scalar(
                select(TaskInvocationDB).where(
                    TaskInvocationDB.task_id == task.task_id,
                    TaskInvocationDB.step_id == step_id,
                    TaskInvocationDB.capability_id == capability_id,
                    TaskInvocationDB.arguments_sha256 == arguments_sha256,
                    TaskInvocationDB.status == "SUCCESS",
                )
            ),
        )

    async def list_invocations(self, task: TaskDB) -> list[TaskInvocationDB]:
        result = await self._session.scalars(
            select(TaskInvocationDB)
            .where(TaskInvocationDB.task_id == task.task_id)
            .order_by(TaskInvocationDB.created_at)
        )
        return list(result)

    # ── Evidence, proposals, approvals, execution, outcome ───────────────────

    async def record_evidence(
        self,
        task: TaskDB,
        *,
        ref: str,
        source_invocation_id: str | None,
        payload_digest: str | None,
    ) -> TaskEvidenceDB:
        existing = await self._session.scalar(
            select(TaskEvidenceDB).where(
                TaskEvidenceDB.task_id == task.task_id, TaskEvidenceDB.ref == ref
            )
        )
        if existing is not None:
            return existing
        record = TaskEvidenceDB(
            task_id=task.task_id,
            ref=ref,
            source_invocation_id=source_invocation_id,
            payload_digest=payload_digest,
        )
        self._session.add(record)
        await self._session.commit()
        return record

    async def list_evidence(self, task: TaskDB) -> list[TaskEvidenceDB]:
        result = await self._session.scalars(
            select(TaskEvidenceDB)
            .where(TaskEvidenceDB.task_id == task.task_id)
            .order_by(TaskEvidenceDB.created_at)
        )
        return list(result)

    async def list_proposals(self, task: TaskDB) -> list[TaskProposalDB]:
        result = await self._session.scalars(
            select(TaskProposalDB)
            .where(TaskProposalDB.task_id == task.task_id)
            .order_by(TaskProposalDB.created_at)
        )
        return list(result)

    async def save_proposals(
        self, task: TaskDB, *, proposals: tuple[AgentProposal, ...]
    ) -> list[TaskProposalDB]:
        if await self.list_proposals(task):
            return await self.list_proposals(task)
        records: list[TaskProposalDB] = []
        for proposal in proposals:
            record = TaskProposalDB(
                task_id=task.task_id,
                agent_id=proposal.agent_id,
                agent_role=proposal.agent_role,
                statement=proposal.statement,
                actions=[dict(action) for action in proposal.actions],
                evidence_refs=list(proposal.evidence_refs),
                confidence=proposal.confidence,
                assumptions=list(proposal.assumptions),
            )
            self._session.add(record)
            records.append(record)
        await self._session.commit()
        return records

    async def append_approval(
        self,
        task: TaskDB,
        *,
        decision: str,
        approver_id: UUID | None,
        reason: str | None,
    ) -> TaskApprovalDB:
        record = TaskApprovalDB(
            task_id=task.task_id,
            decision=decision,
            approver_id=str(approver_id) if approver_id else None,
            reason=reason,
        )
        self._session.add(record)
        await self._session.commit()
        return record

    async def latest_approval(self, task: TaskDB) -> TaskApprovalDB | None:
        return cast(
            TaskApprovalDB | None,
            await self._session.scalar(
                select(TaskApprovalDB)
                .where(TaskApprovalDB.task_id == task.task_id)
                .order_by(TaskApprovalDB.created_at.desc())
                .limit(1)
            ),
        )

    async def list_approvals(self, task: TaskDB) -> list[TaskApprovalDB]:
        result = await self._session.scalars(
            select(TaskApprovalDB)
            .where(TaskApprovalDB.task_id == task.task_id)
            .order_by(TaskApprovalDB.created_at)
        )
        return list(result)

    async def set_terminal_reasons(
        self,
        task: TaskDB,
        *,
        blocked_reason: str | None = None,
        failure_reason: str | None = None,
    ) -> None:
        if blocked_reason is not None:
            task.blocked_reason = blocked_reason
        if failure_reason is not None:
            task.failure_reason = failure_reason
        await self._session.commit()

    async def get_execution(self, task: TaskDB) -> TaskExecutionDB | None:
        return cast(
            TaskExecutionDB | None,
            await self._session.scalar(
                select(TaskExecutionDB).where(TaskExecutionDB.task_id == task.task_id)
            ),
        )

    async def start_execution(self, task: TaskDB, *, idempotency_key: str) -> TaskExecutionDB:
        existing = await self.get_execution(task)
        if existing is not None:
            return existing
        record = TaskExecutionDB(
            task_id=task.task_id, status="RUNNING", idempotency_key=idempotency_key
        )
        self._session.add(record)
        await self._session.commit()
        return record

    async def finish_execution(
        self, execution: TaskExecutionDB, *, status: str, failure_reason: str | None = None
    ) -> TaskExecutionDB:
        execution.status = status
        execution.failure_reason = failure_reason
        await self._session.commit()
        return execution

    async def save_outcome(
        self,
        task: TaskDB,
        *,
        status: str,
        recommendation: str | None,
        result_payload: dict[str, Any],
    ) -> TaskOutcomeDB:
        existing = await self._session.scalar(
            select(TaskOutcomeDB).where(TaskOutcomeDB.task_id == task.task_id)
        )
        if existing is not None:
            return existing
        record = TaskOutcomeDB(
            task_id=task.task_id,
            status=status,
            recommendation=recommendation,
            result_payload=result_payload,
        )
        self._session.add(record)
        await self._session.commit()
        return record

    async def get_outcome(self, task: TaskDB) -> TaskOutcomeDB | None:
        return cast(
            TaskOutcomeDB | None,
            await self._session.scalar(
                select(TaskOutcomeDB).where(TaskOutcomeDB.task_id == task.task_id)
            ),
        )
