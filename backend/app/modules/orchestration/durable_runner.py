"""Durable task runner: drives MAF-3 orchestration through durable checkpoints.

The runner composes the MAF-3 components (planner, executor, synthesizer,
tool gateway) with durable wrappers so that:

* every gateway invocation is persisted to PostgreSQL as it happens
  (DurableTraceWriter);
* a worker restart resumes from the last committed checkpoint and never
  re-executes a capability that already succeeded for the same
  (task, step, capability, arguments) digest (DurableCapabilityExecutor);
* the approval boundary is durable: EXECUTING is reachable only after an
  APPROVED record exists, and the re-invocation of consequential steps sets
  ``execution_approved`` only then.

Redis is not consulted anywhere in this module; transport is the caller's
concern.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .capability_registry import NexusCapabilityRegistry
from .contracts import AgentContext, CapabilityDescriptor, TaskContext, TaskPlan, TaskResult
from .executor import NexusTaskExecutor, StepOutcome
from .planner import NexusTaskPlanner
from .synthesis import DeterministicTaskSynthesizer
from .task_intent import TaskIntent
from .task_runtime_models import TaskDB
from .task_runtime_repository import TaskNotFound, TaskRuntimeRepository
from .task_runtime_service import NexusTaskRuntime, TaskScope
from .tool_gateway import (
    NexusToolGateway,
    ToolGateway,
    ToolInvocationResult,
)

_WRITE_SIDE_EFFECTS = frozenset({"WRITE_REVERSIBLE", "WRITE_CONSEQUENTIAL"})


class DurableCapabilityExecutor:
    """Gateway executor wrapper: deduplicates consequential work on resume.

    Before invoking the wrapped executor, the wrapper checks for a prior
    SUCCESS invocation with the same (task, step, capability, arguments
    digest). A found record replays its stored result without re-executing
    the capability, so a restarted worker never repeats consequential work.
    """

    def __init__(
        self,
        *,
        inner: Any,
        session_factory: async_sessionmaker[AsyncSession],
        task_id: str,
        run_id: str,
        step_id: str,
    ) -> None:
        self._inner = inner
        self._session_factory = session_factory
        self._task_id = task_id
        self._run_id = run_id
        self._step_id = step_id

    async def execute(
        self,
        *,
        capability: CapabilityDescriptor,
        arguments: dict[str, Any],
        context: AgentContext,
    ) -> dict[str, Any]:
        digest = _arguments_digest(arguments)
        async with self._session_factory() as session:
            repo = TaskRuntimeRepository(session=session)
            task = await repo.get_task(
                self._task_id,
                tenant_id=context.tenant_id,
                workspace_id=context.workspace_id,
            )
            prior = await repo.find_prior_success_invocation(
                task,
                step_id=self._step_id,
                capability_id=capability.capability_id,
                arguments_sha256=digest,
            )
            if prior is not None and prior.result_data is not None:
                replayed: dict[str, Any] = dict(prior.result_data)
                replayed["evidence_refs"] = tuple(prior.evidence_refs)
                return replayed
        return cast(
            dict[str, Any],
            await self._inner.execute(capability=capability, arguments=arguments, context=context),
        )


class DurableTraceWriter:
    """Gateway trace writer that persists every invocation to PostgreSQL."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        task_id: str,
        run_id: str,
        step_id: str,
    ) -> None:
        self._session_factory = session_factory
        self._task_id = task_id
        self._run_id = run_id
        self._step_id = step_id

    async def record_tool_invocation(self, *, result: ToolInvocationResult) -> None:
        async with self._session_factory() as session:
            repo = TaskRuntimeRepository(session=session)
            task = await repo.get_task(
                self._task_id,
                tenant_id=result.provenance.tenant_id,
                workspace_id=result.provenance.workspace_id,
            )
            await repo.record_invocation(
                task, run_id=self._run_id, step_id=self._step_id, result=result
            )


def _arguments_digest(arguments: dict[str, Any]) -> str:
    """Stable digest matching the gateway's provenance digest."""

    import json
    from hashlib import sha256

    payload = json.dumps(arguments, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(payload.encode("utf-8")).hexdigest()


class DurableTaskRunner:
    """Drives one task lifecycle: submit, resume, approval, execution, outcome."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        capability_registry: NexusCapabilityRegistry,
        capability_executor: Any,
        authorizer: Any,
        schema_validator: Any,
    ) -> None:
        self._session_factory = session_factory
        self._capability_registry = capability_registry
        self._capability_executor = capability_executor
        self._authorizer = authorizer
        self._schema_validator = schema_validator
        self._runtime = NexusTaskRuntime(session_factory=session_factory)
        self._planner = NexusTaskPlanner(default_execution="concurrent")
        self._synthesizer = DeterministicTaskSynthesizer()

    # ── Submit: create + intent checkpoint ──────────────────────────────────

    async def submit(self, *, context: TaskContext) -> str:
        requires_approval = context.intent.requires_consequential_governance
        task_id = await self._runtime.create_task(
            scope=TaskScope(tenant_id=context.tenant_id, workspace_id=context.workspace_id),
            actor_id=context.actor_id,
            trace_id=context.trace_id,
            objective=context.objective,
            world_state_version=context.world_state_version,
            requires_approval=requires_approval,
            policy_context=dict(context.policy_context),
            budget=context.budget,
            deadline=context.deadline,
        )
        await self._runtime.resolve_intent(task_id, scope=_scope_of(context), intent=context.intent)
        return task_id

    # ── Resume: drive from the last committed checkpoint ─────────────────────

    async def resume(self, task_id: str, *, scope: TaskScope) -> str:
        """Drive the task until it waits for a human or reaches a terminal state.

        Returns the current TaskStatus. Safe to call repeatedly and after any
        number of restarts: every phase is committed before the next begins.
        """
        while True:
            status = await self._runtime.get_status(task_id, scope=scope)
            if status in ("CREATED",):
                await self._runtime.block_task(
                    task_id,
                    scope=scope,
                    reason="Intent was never resolved before the worker stopped.",
                )
                continue
            if status == "INTENT_RESOLVED":
                await self._plan_phase(task_id, scope=scope)
                continue
            if status == "PLANNED":
                await self._runtime.start_run(task_id, scope=scope)
                continue
            if status == "RUNNING":
                await self._run_phase(task_id, scope=scope)
                continue
            if status == "PROPOSED":
                await self._propose_decision_phase(task_id, scope=scope)
                continue
            if status == "AWAITING_APPROVAL":
                return "AWAITING_APPROVAL"
            if status == "APPROVED":
                await self._execution_phase(task_id, scope=scope)
                continue
            return status

    # ── Phases ────────────────────────────────────────────────────────────────

    async def _plan_phase(self, task_id: str, *, scope: TaskScope) -> None:
        context = await self._rebuild_context(task_id, scope=scope)
        try:
            plan = await self._planner.plan(context)
        except ValueError as exc:
            await self._runtime.block_task(task_id, scope=scope, reason=str(exc))
            return
        await self._runtime.checkpoint_plan(task_id, scope=scope, plan=plan)

    async def _run_phase(self, task_id: str, *, scope: TaskScope) -> None:
        context = await self._rebuild_context(task_id, scope=scope)
        plan = await self._runtime.get_plan(task_id, scope=scope)
        if plan is None:
            await self._runtime.block_task(
                task_id, scope=scope, reason="No durable plan at RUNNING."
            )
            return
        run_id = await self._runtime.start_run(task_id, scope=scope)

        result, outcomes = await self._execute_with_durability(
            plan=plan, context=context, task_id=task_id, run_id=run_id
        )
        await self._persist_step_records(task_id, scope=scope, plan=plan, outcomes=outcomes)
        proposals = self._synthesizer.synthesize(
            plan=plan,
            outcomes=outcomes,
            capabilities=None,
        )
        await self._runtime.record_proposals(task_id, scope=scope, proposals=proposals)
        await self._record_evidence(task_id, scope=scope, outcomes=outcomes)
        await self._runtime.mark_proposed(task_id, scope=scope)

        # Explicit terminal/error handling: silence is never a valid state.
        if result.status == "AWAITING_APPROVAL":
            await self._runtime.request_approval(
                task_id,
                scope=scope,
                reason="Gateway blocked a consequential write pending approval.",
            )
        elif result.status == "BLOCKED":
            reason = self._first_step_error(outcomes) or "Run was blocked by governance."
            await self._runtime.block_task(task_id, scope=scope, reason=reason)
        elif result.status == "FAILED":
            reason = self._first_step_error(outcomes) or "Run failed during execution."
            await self._runtime.fail_task(task_id, scope=scope, reason=reason)

    @staticmethod
    def _first_step_error(outcomes: dict[str, StepOutcome]) -> str | None:
        for outcome in outcomes.values():
            if outcome.status in ("BLOCKED", "FAILED"):
                return outcome.error
        return None

    async def _propose_decision_phase(self, task_id: str, *, scope: TaskScope) -> None:
        """PROPOSED: request approval or complete directly (never EXECUTING).

        The gateway's own APPROVAL_REQUIRED blocks are the authoritative
        signal that consequential governance is needed, in addition to the
        intent risk class captured at submit time.
        """

        task = await self._runtime.get_task(task_id, scope=scope)
        needs_approval = task.requires_approval or await self._gateway_requires_approval(
            task_id, scope=scope
        )
        if needs_approval:
            await self._runtime.request_approval(
                task_id, scope=scope, reason="Task plan requires consequential governance."
            )
            return
        outcome_payload = {
            "reason": "No consequential capabilities in plan; execution not required.",
            "proposals_recorded": True,
        }
        await self._runtime.complete_task(
            task_id,
            scope=scope,
            recommendation=None,
            result_payload=outcome_payload,
        )

    async def _execution_phase(self, task_id: str, *, scope: TaskScope) -> None:
        """APPROVED -> EXECUTING: re-run consequential steps with approval set.

        Only reached through a durable APPROVED record. The rebuilt context
        carries ``execution_approved`` so the gateway allows the consequential
        write exactly once (the durable invocation store deduplicates retries).
        """

        await self._runtime.start_execution(task_id, scope=scope)
        context = await self._rebuild_context(task_id, scope=scope, execution_approved=True)
        plan = await self._runtime.get_plan(task_id, scope=scope)
        if plan is None:
            await self._runtime.finish_execution(
                task_id, scope=scope, success=False, failure_reason="No durable plan at EXECUTING."
            )
            return
        run_id = await self._runtime.get_run_id(task_id, scope=scope)
        capabilities = {capability.capability_id: capability for capability in context.capabilities}
        executed: list[str] = []
        try:
            for step in plan.steps:
                for capability_id in step.required_capabilities:
                    capability = capabilities.get(capability_id)
                    if capability is None or capability.side_effect not in _WRITE_SIDE_EFFECTS:
                        continue
                    await self._invoke_through_gateway(
                        context=context,
                        capability=capability,
                        step_id=step.step_id,
                        task_id=task_id,
                        run_id=run_id,
                    )
                    executed.append(step.step_id)
        except Exception as exc:  # noqa: BLE001 - the runner must record failures explicitly.
            await self._runtime.finish_execution(
                task_id, scope=scope, success=False, failure_reason=str(exc)
            )
            return
        await self._runtime.finish_execution(
            task_id,
            scope=scope,
            success=True,
        )

    # ── Durable helpers ───────────────────────────────────────────────────────

    async def _gateway_requires_approval(self, task_id: str, *, scope: TaskScope) -> bool:
        """Durable governance truth: did the gateway block a consequential write?"""

        async with self._session_factory() as session:
            repo = TaskRuntimeRepository(session=session)
            task = await repo.get_task(
                task_id, tenant_id=scope.tenant_id, workspace_id=scope.workspace_id
            )
            for record in await repo.list_invocations(task):
                if record.status == "BLOCKED" and record.error == "APPROVAL_REQUIRED":
                    return True
        return False

    async def _rebuild_context(
        self, task_id: str, *, scope: TaskScope, execution_approved: bool = False
    ) -> TaskContext:
        task = await self._runtime.get_task(task_id, scope=scope)
        intent = await self._durable_intent(task)
        authorized = await self._capability_registry.resolve_for_workspace(
            tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id,
            actor_id=UUID(task.actor_id),
            task_intent=intent,
        )
        policy_context = dict(task.policy_context)
        if execution_approved:
            policy_context["execution_approved"] = True
        return TaskContext(
            task_id=UUID(task.task_id),
            workspace_id=scope.workspace_id,
            tenant_id=scope.tenant_id,
            trace_id=UUID(task.trace_id),
            actor_id=UUID(task.actor_id),
            intent=intent,
            objective=task.objective,
            constraints={},
            world_state_version=task.world_state_version,
            capabilities=authorized.descriptors,
            policy_context=policy_context,
            budget=task.budget,
            deadline=task.deadline,
        )

    async def _durable_intent(self, task: TaskDB) -> TaskIntent:
        async with self._session_factory() as session:
            repo = TaskRuntimeRepository(session=session)
            record = await repo.get_intent(task)
            if record is None:
                raise TaskNotFound(f"Task {task.task_id} has no durable intent.")
            return TaskIntent.model_validate(record.intent_payload)

    def _gateway_factory(self, task_id: str, run_id: str) -> Callable[[str], ToolGateway]:
        def factory(step_id: str) -> ToolGateway:
            return NexusToolGateway(
                authorizer=self._authorizer,
                executor=DurableCapabilityExecutor(
                    inner=self._capability_executor,
                    session_factory=self._session_factory,
                    task_id=task_id,
                    run_id=run_id,
                    step_id=step_id,
                ),
                schema_validator=self._schema_validator,
                trace_writer=DurableTraceWriter(
                    session_factory=self._session_factory,
                    task_id=task_id,
                    run_id=run_id,
                    step_id=step_id,
                ),
            )

        return factory

    async def _execute_with_durability(
        self,
        *,
        plan: TaskPlan,
        context: TaskContext,
        task_id: str,
        run_id: str,
    ) -> tuple[TaskResult, dict[str, StepOutcome]]:
        executor = NexusTaskExecutor(
            gateway=self._gateway_factory(task_id, run_id)(plan.steps[0].step_id)
        )
        return await executor.execute_with_outcomes(
            plan=plan,
            context=context,
            gateway_factory=self._gateway_factory(task_id, run_id),
        )

    async def _invoke_through_gateway(
        self,
        *,
        context: TaskContext,
        capability: CapabilityDescriptor,
        step_id: str,
        task_id: str,
        run_id: str,
    ) -> ToolInvocationResult:
        gateway = self._gateway_factory(task_id, run_id)(step_id)
        arguments = self._step_arguments_for(context, step_id)
        return await gateway.invoke(
            capability=capability, arguments=arguments, context=self._agent_context(context)
        )

    @staticmethod
    def _agent_context(context: TaskContext) -> AgentContext:
        return AgentContext(
            workspace_id=context.workspace_id,
            tenant_id=context.tenant_id,
            task_id=context.task_id,
            trace_id=context.trace_id,
            actor_id=context.actor_id,
            world_state_version=context.world_state_version,
            entity_ids=context.selected_entities,
            evidence_refs=context.evidence_refs,
            allowed_capabilities=tuple(
                capability.capability_id for capability in context.capabilities
            ),
            policy_context=dict(context.policy_context),
            budget=context.budget,
            deadline=context.deadline,
        )

    @staticmethod
    def _step_arguments_for(context: TaskContext, step_id: str) -> dict[str, Any]:
        raw = context.constraints.get("step_arguments")
        if isinstance(raw, dict) and isinstance(raw.get(step_id), dict):
            return dict(raw[step_id])
        return {}

    async def _persist_step_records(
        self,
        task_id: str,
        *,
        scope: TaskScope,
        plan: TaskPlan,
        outcomes: dict[str, StepOutcome],
    ) -> None:
        run_id = await self._runtime.get_run_id(task_id, scope=scope)
        for step in plan.steps:
            outcome = outcomes[step.step_id]
            await self._runtime.record_step(
                task_id,
                scope=scope,
                run_id=run_id,
                step_id=step.step_id,
                agent_role=step.agent_role,
                status=outcome.status,
                error=outcome.error,
                invocation_ids=list(outcome.invocation_ids),
                evidence_refs=list(outcome.evidence_refs),
                outputs=[dict(output) for output in outcome.outputs],
            )

    async def _record_evidence(
        self, task_id: str, *, scope: TaskScope, outcomes: dict[str, StepOutcome]
    ) -> None:
        for outcome in outcomes.values():
            for invocation_id, ref in zip(
                outcome.invocation_ids, outcome.evidence_refs, strict=False
            ):
                await self._runtime.record_evidence(
                    task_id,
                    scope=scope,
                    ref=ref,
                    source_invocation_id=invocation_id,
                    payload_digest=None,
                )


def _scope_of(context: TaskContext) -> TaskScope:
    return TaskScope(tenant_id=context.tenant_id, workspace_id=context.workspace_id)
