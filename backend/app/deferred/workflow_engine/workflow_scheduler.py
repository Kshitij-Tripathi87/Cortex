"""DEFERRED -- Workflow & Orchestration Core

Status: FROZEN (ADR-0007)
Phase: 2+
Reason: Excluded from MVP wedge per cortex-mvp-execution-plan.md section 7.2
Action: Do not import into production paths.

Last touched: 2026-08-01

Workflow scheduler — recurring workflow triggers.

Provides cron-like scheduling for recurring workflows (e.g., weekly
model training, daily integrity checks).  Uses asyncio for simplicity
in Phase 1; can be replaced with ARQ or APScheduler later.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger("cortex.workflow.scheduler")

ScheduledTask = Callable[[], Awaitable[None]]


class WorkflowScheduler:
    """Simple recurring task scheduler for workflow triggers."""

    def __init__(self) -> None:
        self._tasks: list[ScheduledTask] = []
        self._running = False
        self._loop: asyncio.Task | None = None

    def register(self, task: ScheduledTask) -> None:
        self._tasks.append(task)

    async def start(self, interval_seconds: int = 60) -> None:
        self._running = True
        self._loop = asyncio.create_task(self._run_loop(interval_seconds))

    async def stop(self) -> None:
        self._running = False
        if self._loop:
            self._loop.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._loop

    async def _run_loop(self, interval_seconds: int) -> None:
        while self._running:
            for task in self._tasks:
                try:
                    await task()
                except Exception:
                    logger.exception("Scheduled task failed")
            await asyncio.sleep(interval_seconds)

    async def schedule_cleanup(self) -> None:
        """Recurring task: clean up completed workflow state after TTL."""
        pass

    async def schedule_retry_stalled(self) -> None:
        """Recurring task: retry workflows stuck in RUNNING for too long."""
        pass


scheduler = WorkflowScheduler()
