"""Microsoft Agent Framework adapter for the Nexus orchestration boundary.

The adapter intentionally contains no business-domain persistence or
authorization. Those concerns remain in Nexus services and are supplied
through TaskContext and capability-backed tools.
"""

from __future__ import annotations

from ..contracts import TaskContext, TaskPlan, TaskResult
from ..executor import NexusTaskExecutor
from ..planner import NexusTaskPlanner
from ..tool_gateway import ToolGateway
from .base import FrameworkOrchestrator


class AgentFrameworkOrchestrator(FrameworkOrchestrator):
    """Framework-backed orchestration implementation.

    The MAF-2 workflow path is deterministic and framework-independent: the
    Nexus task planner compiles the frozen TaskContext into a bounded plan and
    the Nexus task executor runs it through the tool gateway. Microsoft Agent
    Framework is imported only inside execution methods once the
    provider-backed planner agent and workflow runtime are mounted, so the
    Nexus contract and non-framework tests remain importable without loading
    an LLM provider at module import time.
    """

    def __init__(self, *, gateway: ToolGateway) -> None:
        self._planner = NexusTaskPlanner()
        self._executor = NexusTaskExecutor(gateway=gateway)

    async def plan(self, context: TaskContext) -> TaskPlan:
        """Create the bounded plan via the Nexus task planner."""
        return await self._planner.plan(context)

    async def run_task(self, context: TaskContext) -> TaskResult:
        """Plan and execute the task with every capability call gated."""
        try:
            plan = await self._planner.plan(context)
        except ValueError as exc:
            return TaskResult(
                task_id=context.task_id,
                status="BLOCKED",
                trace_id=context.trace_id,
                metadata={"planning_error": str(exc)},
            )
        return await self._executor.execute(plan=plan, context=context)
