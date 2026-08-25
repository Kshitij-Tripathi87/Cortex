"""DEFERRED -- Workflow & Orchestration Core

Status: FROZEN (ADR-0007)
Phase: 2+
Reason: Excluded from MVP wedge per cortex-mvp-execution-plan.md section 7.2
Action: Do not import into production paths.

Last touched: 2026-08-01

Workflow metrics — Prometheus-compatible workflow operation metrics.

Exposes counters and gauges for workflow engine health.
"""

from __future__ import annotations

from app.deferred.workflow_engine.workflow_models import WorkflowStatus


class WorkflowMetrics:
    """In-process metrics collector for workflow operations.

    Phase 1 uses Python-level counters.  Phase 2+ can transition to
    Prometheus client library counters (Counter, Gauge, Histogram).
    """

    def __init__(self) -> None:
        self._started: dict[str, int] = {}
        self._completed: dict[str, int] = {}
        self._failed: dict[str, int] = {}
        self._stage_completed: dict[str, int] = {}
        self._stage_failed: dict[str, int] = {}
        self._stage_retried: dict[str, int] = {}

    def record_start(self, workflow_name: str) -> None:
        self._started[workflow_name] = self._started.get(workflow_name, 0) + 1

    def record_completion(self, workflow_name: str, status: WorkflowStatus) -> None:
        if status == WorkflowStatus.COMPLETED:
            self._completed[workflow_name] = self._completed.get(workflow_name, 0) + 1
        elif status in {WorkflowStatus.FAILED, WorkflowStatus.CANCELLED}:
            self._failed[workflow_name] = self._failed.get(workflow_name, 0) + 1

    def record_stage_completed(self, stage_name: str) -> None:
        self._stage_completed[stage_name] = self._stage_completed.get(stage_name, 0) + 1

    def record_stage_failed(self, stage_name: str) -> None:
        self._stage_failed[stage_name] = self._stage_failed.get(stage_name, 0) + 1

    def record_stage_retried(self, stage_name: str) -> None:
        self._stage_retried[stage_name] = self._stage_retried.get(stage_name, 0) + 1

    def summary(self) -> dict:
        return {
            "started": dict(self._started),
            "completed": dict(self._completed),
            "failed": dict(self._failed),
            "stages": {
                "completed": dict(self._stage_completed),
                "failed": dict(self._stage_failed),
                "retried": dict(self._stage_retried),
            },
        }


metrics = WorkflowMetrics()
