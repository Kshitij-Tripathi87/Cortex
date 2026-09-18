"""Microsoft Agent Framework adapter for the Nexus orchestration boundary.

The adapter intentionally contains no business-domain persistence or
authorization. Those concerns remain in Nexus services and are supplied
through TaskContext and capability-backed tools.
"""

from __future__ import annotations

from dataclasses import replace

from ..capability_registry import (
    AuthorizedCapabilitySet,
    NexusCapabilityRegistry,
)
from ..contracts import TaskContext, TaskPlan, TaskResult
from ..executor import NexusTaskExecutor
from ..planner import NexusTaskPlanner
from ..synthesis import DeterministicTaskSynthesizer, TaskSynthesizer
from ..tool_gateway import ToolGateway
from .base import FrameworkOrchestrator


class AgentFrameworkOrchestrator(FrameworkOrchestrator):
    """Framework-backed orchestration implementation.

    The MAF-3 orchestration shape is: discovery (capability registry) ->
    deterministic planning -> concurrent specialist execution through the
    Nexus tool gateway -> synthesis into grounded proposals. Microsoft Agent
    Framework is imported only inside execution methods once the
    provider-backed planner agent and workflow runtime are mounted, so the
    Nexus contract and non-framework tests remain importable without loading
    an LLM provider at module import time.
    """

    def __init__(
        self,
        *,
        gateway: ToolGateway,
        capability_registry: NexusCapabilityRegistry | None = None,
        synthesizer: TaskSynthesizer | None = None,
    ) -> None:
        self._registry = capability_registry
        # MAF-3 default: specialists are independent and run concurrently.
        self._planner = NexusTaskPlanner(default_execution="concurrent")
        self._executor = NexusTaskExecutor(gateway=gateway)
        self._synthesizer = synthesizer or DeterministicTaskSynthesizer()

    async def plan(self, context: TaskContext) -> TaskPlan:
        """Create the bounded plan via the Nexus task planner."""
        return await self._planner.plan(context)

    async def run_task(self, context: TaskContext) -> TaskResult:
        """Discover, plan, execute through the gateway, and synthesize results."""
        try:
            effective, resolved = await self._resolve_capabilities(context)
            plan = await self._planner.plan(effective)
        except ValueError as exc:
            return TaskResult(
                task_id=context.task_id,
                status="BLOCKED",
                trace_id=context.trace_id,
                metadata={"planning_error": str(exc)},
            )
        result, outcomes = await self._executor.execute_with_outcomes(plan=plan, context=effective)
        proposals = self._synthesizer.synthesize(
            plan=plan, outcomes=outcomes, capabilities=resolved
        )
        return replace(result, proposals=proposals)

    async def _resolve_capabilities(
        self, context: TaskContext
    ) -> tuple[TaskContext, AuthorizedCapabilitySet | None]:
        """Discovery: resolve the workspace-authorized capability set.

        Without a registry the task executes with the capabilities already
        frozen into the context (MAF-2-era behavior). With a registry, context
        capabilities not authorized for the workspace fail closed, and an empty
        context capability list is replaced by the full authorized set.
        """
        if self._registry is None:
            return context, None
        authorized = await self._registry.resolve_for_workspace(
            tenant_id=context.tenant_id,
            workspace_id=context.workspace_id,
            actor_id=context.actor_id,
            task_intent=context.intent,
        )
        if not context.capabilities:
            return replace(context, capabilities=authorized.descriptors), authorized
        authorized_ids = {descriptor.capability_id for descriptor in authorized.descriptors}
        effective = tuple(
            capability
            for capability in context.capabilities
            if capability.capability_id in authorized_ids
        )
        if len(effective) != len(context.capabilities):
            unauthorized = tuple(
                capability_id
                for capability_id in (
                    capability.capability_id for capability in context.capabilities
                )
                if capability_id not in authorized_ids
            )
            raise ValueError(
                "Task context requests capabilities the workspace has not authorized: "
                + ", ".join(unauthorized)
            )
        return replace(context, capabilities=effective), authorized
