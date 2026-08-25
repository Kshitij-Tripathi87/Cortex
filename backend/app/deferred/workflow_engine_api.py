"""DEFERRED -- Workflow & Orchestration Core

Status: FROZEN (ADR-0007)
Phase: 2+
Reason: Excluded from MVP wedge per cortex-mvp-execution-plan.md section 7.2
Action: Do not import into production paths.

Last touched: 2026-08-01

Workflow API v1 — REST endpoints for workflow lifecycle."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.deferred.workflow_engine.workflow_engine import WorkflowEngine
from app.deferred.workflow_engine.workflow_models import WorkflowInstance
from app.deferred.workflow_engine.workflow_registry import WorkflowRegistry
from app.deferred.workflow_engine.workflow_service import WorkflowService
from app.infrastructure.database import get_db

router = APIRouter()

engine = WorkflowEngine()
registry = WorkflowRegistry()


class StartWorkflowRequest(BaseModel):
    workflow_name: str = Field(..., min_length=1, max_length=128)
    workspace_id: str = Field(..., min_length=1, max_length=36)
    triggered_by: str | None = None
    version: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class WorkflowStatusResponse(BaseModel):
    instance_id: str
    workflow_name: str
    workspace_id: str
    version: str
    status: str
    triggered_by: str | None
    stage_count: int
    stages: list[dict[str, Any]]
    started_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class WorkflowListResponse(BaseModel):
    instances: list[WorkflowStatusResponse]
    total: int


class GateApprovalRequest(BaseModel):
    stage_instance_id: str
    approved_by: str = Field(..., min_length=1)
    decision: str = Field(default="approved", pattern="^(approved|rejected)$")
    rationale: str | None = None


class WorkflowTemplateResponse(BaseModel):
    name: str
    version: str
    stage_count: int
    stages: list[dict[str, Any]]


@router.post("/workflow/start", response_model=WorkflowStatusResponse)
async def start_workflow(
    body: StartWorkflowRequest,
    db: AsyncSession = Depends(get_db),
) -> WorkflowStatusResponse:
    """Start a new workflow instance."""
    svc = _get_service(db)
    try:
        instance = await svc.start(
            db,
            workflow_name=body.workflow_name,
            workspace_id=body.workspace_id,
            triggered_by=body.triggered_by,
            version=body.version,
            params=body.params,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return _instance_to_response(instance)


@router.get("/workflow/{instance_id}", response_model=WorkflowStatusResponse)
async def get_workflow(
    instance_id: str,
    db: AsyncSession = Depends(get_db),
) -> WorkflowStatusResponse:
    """Get the current status of a workflow instance."""
    svc = _get_service(db)
    instance = await svc.get_instance(db, instance_id)
    if instance is None:
        raise HTTPException(status_code=404, detail="Workflow instance not found")
    return _instance_to_response(instance)


@router.post("/workflow/{instance_id}/cancel", response_model=WorkflowStatusResponse)
async def cancel_workflow(
    instance_id: str,
    db: AsyncSession = Depends(get_db),
) -> WorkflowStatusResponse:
    """Cancel a running workflow instance."""
    svc = _get_service(db)
    try:
        instance = await svc.cancel(db, instance_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _instance_to_response(instance)


@router.post("/workflow/{instance_id}/retry", response_model=WorkflowStatusResponse)
async def retry_workflow(
    instance_id: str,
    db: AsyncSession = Depends(get_db),
) -> WorkflowStatusResponse:
    """Retry a failed workflow instance (creates a new one from the same input)."""
    svc = _get_service(db)
    try:
        instance = await svc.retry(db, instance_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _instance_to_response(instance)


@router.post("/workflow/{instance_id}/resume", response_model=WorkflowStatusResponse)
async def resume_workflow(
    instance_id: str,
    db: AsyncSession = Depends(get_db),
) -> WorkflowStatusResponse:
    """Resume a workflow that is awaiting approval."""
    svc = _get_service(db)
    try:
        instance = await svc.resume(db, instance_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _instance_to_response(instance)


@router.post("/workflow/{instance_id}/approve", response_model=WorkflowStatusResponse)
async def approve_gate(
    instance_id: str,
    body: GateApprovalRequest,
    db: AsyncSession = Depends(get_db),
) -> WorkflowStatusResponse:
    """Approve or reject a gate stage in a workflow."""
    svc = _get_service(db)
    try:
        instance = await svc.approve_gate(
            db,
            instance_id,
            body.stage_instance_id,
            body.approved_by,
            body.rationale,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _instance_to_response(instance)


@router.get("/workflow/{instance_id}/timeline", response_model=list[dict[str, Any]])
async def get_timeline(
    instance_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Get the step-by-step timeline of a workflow instance."""
    svc = _get_service(db)
    instance = await svc.get_instance(db, instance_id)
    if instance is None:
        raise HTTPException(status_code=404, detail="Workflow instance not found")

    timeline: list[dict[str, Any]] = []
    for stage in instance.stages:
        timeline.append(
            {
                "stage_id": stage.stage_id,
                "name": stage.name,
                "agent": stage.agent,
                "verb": stage.verb,
                "status": stage.status.value,
                "gate": stage.gate,
                "attempt": stage.attempt,
                "last_error": stage.last_error,
                "started_at": stage.started_at.isoformat() if stage.started_at else None,
                "completed_at": stage.completed_at.isoformat() if stage.completed_at else None,
                "depends_on": list(stage.depends_on),
            }
        )
    return timeline


@router.get("/workflow/templates", response_model=list[WorkflowTemplateResponse])
async def list_templates() -> list[WorkflowTemplateResponse]:
    """List all available workflow templates."""
    templates = registry.list_templates()
    result: list[WorkflowTemplateResponse] = []
    for t in templates:
        definition = registry.get(t["name"], t["version"])
        if definition:
            result.append(
                WorkflowTemplateResponse(
                    name=definition.name,
                    version=definition.version,
                    stage_count=len(definition.stages),
                    stages=[
                        {
                            "stage_id": s.stage_id,
                            "name": s.name,
                            "agent": s.agent,
                            "verb": s.verb,
                            "depends_on": list(s.depends_on),
                            "gate": s.gate,
                        }
                        for s in definition.stages
                    ],
                )
            )
    return result


def _instance_to_response(instance: WorkflowInstance) -> WorkflowStatusResponse:
    return WorkflowStatusResponse(
        instance_id=instance.instance_id,
        workflow_name=instance.workflow_name,
        workspace_id=instance.workspace_id,
        version=instance.version,
        status=instance.status.value,
        triggered_by=instance.triggered_by,
        stage_count=len(instance.stages),
        stages=[
            {
                "stage_instance_id": s.stage_instance_id,
                "stage_id": s.stage_id,
                "name": s.name,
                "agent": s.agent,
                "verb": s.verb,
                "status": s.status.value,
                "gate": s.gate,
                "attempt": s.attempt,
                "last_error": s.last_error,
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "completed_at": s.completed_at.isoformat() if s.completed_at else None,
                "depends_on": list(s.depends_on),
            }
            for s in instance.stages
        ],
        started_at=instance.started_at,
        updated_at=instance.updated_at,
        completed_at=instance.completed_at,
    )


def _get_service(db: AsyncSession) -> WorkflowService:
    return WorkflowService(registry, engine)
