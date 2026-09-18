"""Deterministic execution of Nexus task plans through the tool gateway.

Steps run sequentially in plan order unless the plan declares dependencies,
in which case independent steps run concurrently and dependents wait for all
prerequisites. Every capability invocation is routed through the injected
ToolGateway; the executor holds no repository, database, HTTP, or filesystem
access of its own.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Literal

from .contracts import (
    AgentContext,
    CapabilityDescriptor,
    TaskContext,
    TaskPlan,
    TaskPlanStep,
    TaskResult,
)
from .tool_gateway import ToolGateway


@dataclass(frozen=True)
class StepOutcome:
    """Recorded outcome of one plan step after gateway enforcement."""

    step_id: str
    status: str
    error: str | None
    invocation_ids: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    outputs: tuple[dict[str, Any], ...] = ()


class NexusTaskExecutor:
    """Execute a TaskPlan against a frozen TaskContext via the tool gateway."""

    def __init__(self, *, gateway: ToolGateway) -> None:
        self._gateway = gateway

    async def execute(self, *, plan: TaskPlan, context: TaskContext) -> TaskResult:
        result, _ = await self.execute_with_outcomes(plan=plan, context=context)
        return result

    async def execute_with_outcomes(
        self, *, plan: TaskPlan, context: TaskContext
    ) -> tuple[TaskResult, dict[str, StepOutcome]]:
        """Execute the plan and expose per-step outcomes for synthesis."""
        capabilities = {capability.capability_id: capability for capability in context.capabilities}
        agent_context = AgentContext(
            workspace_id=context.workspace_id,
            tenant_id=context.tenant_id,
            task_id=context.task_id,
            trace_id=context.trace_id,
            actor_id=context.actor_id,
            world_state_version=context.world_state_version,
            entity_ids=context.selected_entities,
            evidence_refs=context.evidence_refs,
            allowed_capabilities=tuple(capabilities),
            policy_context=dict(context.policy_context),
            budget=context.budget,
            deadline=context.deadline,
        )
        arguments_by_step = self._step_arguments(context, plan)

        outcomes: dict[str, StepOutcome] = {}
        for level in self._execution_levels(plan.steps):
            results = await asyncio.gather(
                *(
                    self._run_step(step, capabilities, arguments_by_step, agent_context, outcomes)
                    for step in level
                )
            )
            for outcome in results:
                outcomes[outcome.step_id] = outcome

        return self._result(plan, context, outcomes), outcomes

    async def _run_step(
        self,
        step: TaskPlanStep,
        capabilities: dict[str, CapabilityDescriptor],
        arguments_by_step: dict[str, dict[str, Any]],
        agent_context: AgentContext,
        completed: dict[str, StepOutcome],
    ) -> StepOutcome:
        for prerequisite in step.dependencies:
            outcome = completed.get(prerequisite)
            if outcome is None or outcome.status != "SUCCESS":
                return StepOutcome(step.step_id, "SKIPPED", "DEPENDENCY_FAILED", (), ())

        arguments = arguments_by_step.get(step.step_id, {})
        invocation_ids: list[str] = []
        evidence: list[str] = []
        collected_outputs: list[dict[str, Any]] = []
        for capability_id in step.required_capabilities:
            capability = capabilities.get(capability_id)
            if capability is None:
                return StepOutcome(
                    step.step_id, "FAILED", "CAPABILITY_NOT_FOUND", tuple(invocation_ids), ()
                )
            try:
                result = await self._gateway.invoke(
                    capability=capability, arguments=arguments, context=agent_context
                )
            except TypeError:
                return StepOutcome(
                    step.step_id, "FAILED", "INVALID_STEP_ARGUMENTS", tuple(invocation_ids), ()
                )
            invocation_ids.append(str(result.invocation_id))
            if result.status != "SUCCESS":
                return StepOutcome(
                    step.step_id, result.status, result.error, tuple(invocation_ids), ()
                )
            evidence.extend(result.evidence_refs)
            if result.data is not None:
                collected_outputs.append(result.data)
        return StepOutcome(
            step.step_id,
            "SUCCESS",
            None,
            tuple(invocation_ids),
            tuple(evidence),
            tuple(collected_outputs),
        )

    @staticmethod
    def _step_arguments(context: TaskContext, plan: TaskPlan) -> dict[str, dict[str, Any]]:
        raw = context.constraints.get("step_arguments")
        if raw is None:
            return {}
        if not isinstance(raw, dict):
            raise ValueError(
                "constraints['step_arguments'] must be a mapping of step id to arguments."
            )
        known = {step.step_id for step in plan.steps}
        arguments: dict[str, dict[str, Any]] = {}
        for step_id, value in raw.items():
            if step_id not in known:
                raise ValueError(f"step_arguments references unknown step: {step_id!r}")
            if not isinstance(value, dict):
                raise ValueError(f"step_arguments for {step_id!r} must be a dictionary.")
            arguments[step_id] = value
        return arguments

    @staticmethod
    def _execution_levels(steps: tuple[TaskPlanStep, ...]) -> list[tuple[TaskPlanStep, ...]]:
        remaining = {step.step_id: set(step.dependencies) for step in steps}
        levels: list[tuple[TaskPlanStep, ...]] = []
        done: set[str] = set()
        while remaining:
            ready = tuple(
                step
                for step in steps
                if step.step_id in remaining and remaining[step.step_id] <= done
            )
            if not ready:
                raise ValueError("Plan dependencies contain a cycle.")
            levels.append(ready)
            for step in ready:
                remaining.pop(step.step_id)
                done.add(step.step_id)
        return levels

    @staticmethod
    def _result(
        plan: TaskPlan, context: TaskContext, outcomes: dict[str, StepOutcome]
    ) -> TaskResult:
        ordered = [outcomes[step.step_id] for step in plan.steps]
        evidence: list[str] = []
        for outcome in ordered:
            for ref in outcome.evidence_refs:
                if ref not in evidence:
                    evidence.append(ref)

        statuses = [outcome.status for outcome in ordered]
        status: Literal["COMPLETED", "BLOCKED", "FAILED", "AWAITING_APPROVAL"]
        if any(outcome.error == "APPROVAL_REQUIRED" for outcome in ordered):
            status = "AWAITING_APPROVAL"
        elif "BLOCKED" in statuses:
            status = "BLOCKED"
        elif "FAILED" in statuses or "SKIPPED" in statuses:
            status = "FAILED"
        else:
            status = "COMPLETED"

        return TaskResult(
            task_id=context.task_id,
            status=status,
            recommendation=None,
            evidence_refs=tuple(evidence),
            trace_id=context.trace_id,
            metadata={
                "steps": {
                    step.step_id: {
                        "status": outcomes[step.step_id].status,
                        "error": outcomes[step.step_id].error,
                        "invocation_ids": list(outcomes[step.step_id].invocation_ids),
                    }
                    for step in plan.steps
                }
            },
        )
