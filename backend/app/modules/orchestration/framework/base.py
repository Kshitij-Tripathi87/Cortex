"""Framework adapter base classes."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..contracts import TaskContext, TaskPlan, TaskResult
from ..orchestrator import NexusOrchestrator


class FrameworkOrchestrator(NexusOrchestrator, ABC):
    """Marker/base class for third-party orchestration implementations."""

    @abstractmethod
    async def plan(self, context: TaskContext) -> TaskPlan:
        raise NotImplementedError

    @abstractmethod
    async def run_task(self, context: TaskContext) -> TaskResult:
        raise NotImplementedError
