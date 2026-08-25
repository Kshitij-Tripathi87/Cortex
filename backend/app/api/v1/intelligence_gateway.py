"""Intelligence Gateway API — Single AI Boundary for GNN, RL, Ranking, and Forecasting.

Endpoints:
- POST /api/v1/ai/infer — Run intelligence task with deterministic fallback
- GET /api/v1/ai/models — List registered models and active deployments
- POST /api/v1/ai/models/{id}/promote — Promote model to active production stage
- POST /api/v1/ai/models/{id}/rollback — Rollback model deployment
- GET /api/v1/ai/baselines — List deterministic fallback baselines
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.common.ids import uuid7
from app.infrastructure.security import get_current_user
from app.modules.identity.models import UserPrincipal
from app.modules.intelligence.gateway import (
    IntelligenceGateway,
    IntelligenceRequest,
    IntelligenceTask,
)
from app.modules.intelligence.model_registry import ModelRegistry

router = APIRouter(prefix="/ai", tags=["Intelligence Gateway"])

_gateway = IntelligenceGateway()
_model_registry = ModelRegistry()


class InferenceApiRequest(BaseModel):
    task: str = Field(description="Task type (e.g. SUPPLIER_SIMILARITY, CRITICAL_NODE_DETECTION, RISK_PROPAGATION, POLICY_OPTIMIZATION)")
    input_data: dict[str, Any] = Field(default_factory=dict)
    world_state_version: int = Field(default=1)
    model_version: str | None = None
    enable_shadow: bool = False
    fallback_to_deterministic: bool = True


@router.post("/infer")
async def execute_inference(
    req: InferenceApiRequest,
    principal: UserPrincipal = Depends(get_current_user),
    x_workspace_id: str = Header(default="default_workspace"),
    x_correlation_id: str | None = Header(default=None),
) -> dict[str, Any]:
    """Execute AI model inference via the unified gateway with safety fallback."""
    try:
        task_enum = IntelligenceTask[req.task.upper()]
    except KeyError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid task '{req.task}'. Valid tasks: {[t.name for t in IntelligenceTask]}",
        )

    corr_id = x_correlation_id or str(uuid7())
    req_obj = IntelligenceRequest(
        request_id=str(uuid7()),
        task=task_enum,
        tenant_id=getattr(principal, "tenant_id", None) or "default_tenant",
        workspace_id=x_workspace_id,
        correlation_id=corr_id,
        world_state_version=req.world_state_version,
        input_data=req.input_data,
        model_version=req.model_version,
        enable_shadow=req.enable_shadow,
        fallback_to_deterministic=req.fallback_to_deterministic,
    )

    response = await _gateway.infer(req_obj)
    return {
        "request_id": response.request_id,
        "task": response.task.name,
        "status": response.status.name,
        "model_id": response.model_id,
        "model_version": response.model_version,
        "output": response.output,
        "confidence": response.confidence,
        "calibration_score": response.calibration_score,
        "evidence_refs": response.evidence_refs,
        "duration_ms": response.duration_ms,
        "shadow_comparison": response.shadow_comparison,
        "warnings": response.warnings,
    }


@router.get("/models")
async def list_models(
    principal: UserPrincipal = Depends(get_current_user),
) -> dict[str, Any]:
    """List registered AI models, validation scores, and deployment targets."""
    models = _model_registry.list_models(org_id="default_org")
    return {
        "models": [
            {
                "model_id": m.model_id,
                "model_type": m.model_type.name,
                "version": m.version,
                "status": m.status.name,
                "artifact_uri": m.artifact_uri,
                "registered_at": m.registered_at.isoformat(),
            }
            for m in models
        ]
    }


@router.post("/models/{model_id}/promote")
async def promote_model(
    model_id: str,
    principal: UserPrincipal = Depends(get_current_user),
) -> dict[str, Any]:
    """Promote a validated shadow model to active production serving."""
    try:
        deployment = _model_registry.promote(model_id)
        return {
            "deployment_id": deployment.deployment_id,
            "model_id": deployment.model_id,
            "status": deployment.status.name,
            "deployed_at": deployment.deployed_at.isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/models/{model_id}/rollback")
async def rollback_model(
    model_id: str,
    principal: UserPrincipal = Depends(get_current_user),
) -> dict[str, Any]:
    """Rollback an active deployment to the previous stable release."""
    try:
        deployment = _model_registry.rollback(model_id)
        return {
            "deployment_id": deployment.deployment_id,
            "model_id": deployment.model_id,
            "status": deployment.status.name,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/baselines")
async def list_baselines() -> dict[str, Any]:
    """List registered deterministic baselines used for high-availability fallbacks."""
    return {
        "baselines": [
            {
                "task": "SUPPLIER_SIMILARITY",
                "method": "Normalized euclidean attribute matching & tier compatibility",
                "guarantee": "Deterministic 100% availability",
            },
            {
                "task": "CRITICAL_NODE_DETECTION",
                "method": "Graph betweenness & degree centrality ranking",
                "guarantee": "Deterministic 100% availability",
            },
            {
                "task": "RISK_PROPAGATION",
                "method": "Multi-hop BFS topological reachability and attenuation",
                "guarantee": "Deterministic 100% availability",
            },
            {
                "task": "POLICY_OPTIMIZATION",
                "method": "Greedy cost-minimization rule-based heuristic",
                "guarantee": "Deterministic 100% availability",
            },
        ]
    }
