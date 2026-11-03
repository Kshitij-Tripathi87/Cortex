"""Durable task lifecycle for the Nexus orchestration runtime.

Every state is explicit: failure, blocking, and skipping are recorded states,
never silence. Transitions are guarded by a fixed map so a crashed or buggy
worker can never invent an illegal path (for example PROPOSED -> EXECUTING
without a human approval record).
"""

from __future__ import annotations

from typing import Literal

TaskStatus = Literal[
    "CREATED",
    "INTENT_RESOLVED",
    "PLANNED",
    "RUNNING",
    "PROPOSED",
    "AWAITING_APPROVAL",
    "APPROVED",
    "EXECUTING",
    "COMPLETED",
    "REJECTED",
    "FAILED",
    "BLOCKED",
]

TERMINAL_STATUSES: frozenset[TaskStatus] = frozenset({"COMPLETED", "REJECTED", "FAILED", "BLOCKED"})

TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    "CREATED": frozenset({"INTENT_RESOLVED", "FAILED", "BLOCKED"}),
    "INTENT_RESOLVED": frozenset({"PLANNED", "FAILED", "BLOCKED"}),
    "PLANNED": frozenset({"RUNNING", "FAILED", "BLOCKED"}),
    "RUNNING": frozenset({"PROPOSED", "FAILED", "BLOCKED"}),
    "PROPOSED": frozenset({"AWAITING_APPROVAL", "COMPLETED", "FAILED", "BLOCKED"}),
    "AWAITING_APPROVAL": frozenset({"APPROVED", "REJECTED", "FAILED", "BLOCKED"}),
    "APPROVED": frozenset({"EXECUTING", "FAILED", "BLOCKED"}),
    "EXECUTING": frozenset({"COMPLETED", "FAILED", "BLOCKED"}),
    "COMPLETED": frozenset(),
    "REJECTED": frozenset(),
    "FAILED": frozenset(),
    "BLOCKED": frozenset(),
}


class TaskLifecycleError(ValueError):
    """Raised when a lifecycle transition is not allowed."""


def assert_transition(current: TaskStatus, target: TaskStatus) -> None:
    """Validate one durable transition; raise instead of inventing states."""

    if current == target:
        return
    if target not in TRANSITIONS.get(current, frozenset()):
        raise TaskLifecycleError(f"Illegal task lifecycle transition: {current} -> {target}")
