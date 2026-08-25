"""DEFERRED -- Workflow & Orchestration Core

Status: FROZEN (ADR-0007)
Phase: 2+
Reason: Excluded from MVP wedge per cortex-mvp-execution-plan.md section 7.2
Action: Do not import into production paths.

Last touched: 2026-08-01

Workflow & Orchestration Core — deterministic workflow engine for Cortex.

The workflow engine coordinates existing domain services (Evidence, Graph,
Signals, Scenarios, Recommendations, Decisions) through declarative DAG-based
workflow templates.  It does NOT replace those services—it orchestrates them.

Programs
--------
 - Runtime            – workflow service, engine, executor, scheduler
 - APIs               – REST endpoints for workflow lifecycle
 - Persistence        – PostgreSQL workflow_runs, step_runs, artifacts
 - Eventing           – domain events for workflow stage transitions

All unit-level behavior is tested via the `tests/` suite.

"""

from app.deferred.workflow_engine.workflow_engine import WorkflowEngine
from app.deferred.workflow_engine.workflow_models import (
    GateApproval,
    StageDefinition,
    StageInstance,
    StageStatus,
    WorkflowDefinition,
    WorkflowInstance,
    WorkflowStatus,
)
from app.deferred.workflow_engine.workflow_registry import WorkflowRegistry
from app.deferred.workflow_engine.workflow_service import WorkflowService

__all__ = [
    "WorkflowEngine",
    "WorkflowRegistry",
    "WorkflowService",
    "WorkflowDefinition",
    "StageDefinition",
    "WorkflowInstance",
    "StageInstance",
    "GateApproval",
    "WorkflowStatus",
    "StageStatus",
]
