"""Microsoft Agent Framework adapter for the Nexus orchestration boundary.

The adapter intentionally contains no business-domain persistence or authorization.
Those concerns remain in Nexus services and are supplied through TaskContext and
capability-backed tools.
"""

from __future__ import annotations

from .base import FrameworkOrchestrator
from ..contracts import TaskContext, TaskPlan, TaskResult


class AgentFrameworkOrchestrator(FrameworkOrchestrator):
    """Framework-backed orchestration implementation.

    Agent Framework is imported only inside the execution methods so the Nexus
    contract and non-framework unit tests remain importable without loading an
    LLM provider at module import time.
    """

    async def plan(self, context: TaskContext) -> TaskPlan:
        # Planning is intentionally delegated to Nexus's task-planning service
        # in the first integration slice. The framework adapter will host the
        # planner agent once provider configuration and structured-output
        # contracts are wired into staging.
        raise NotImplementedError("Agent Framework planner integration is MAF-2")

    async def run_task(self, context: TaskContext) -> TaskResult:
        # Execution remains blocked until the task planner, capability registry,
        # and Nexus tool gateway are wired. This prevents a framework agent from
        # reaching synthetic tools or bypassing Nexus authorization.
        raise NotImplementedError("Agent Framework execution integration is MAF-2")
