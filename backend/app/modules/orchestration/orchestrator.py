"""Framework-independent orchestration contract used by Cortex Nexus."""

from __future__ import annotations

from abc import ABC, abstractmethod

from .contracts import TaskContext, TaskPlan, TaskResult


class NexusOrchestrator(ABC):
    """Stable Nexus boundary around an interchangeable orchestration engine."""

    @abstractmethod
    async def plan(self, context: TaskContext) -> TaskPlan:
        """Create a bounded execution plan from authoritative task context."""
        raise NotImplementedError

    @abstractmethod
    async def run_task(self, context: TaskContext) -> TaskResult:
        """Execute a planned task and return a structured result."""
        raise NotImplementedError
