"""GNN API v1 — Graph Neural Networks & Graph Intelligence Endpoints.

Program K (Graph Intelligence & Graph Neural Networks):
- POST /gnn/embeddings — Compute dense node embeddings for a world state
- POST /gnn/similar-suppliers — Multi-factor alternative supplier recommendation
- POST /gnn/critical-nodes — Single points of failure and systemic bottleneck detection
- POST /gnn/hidden-dependencies — Latent dependency discovery
- POST /gnn/risk-propagation — Cascading disruption forecasting
- POST /gnn/benchmark — Compare GNN performance against deterministic baselines
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database import get_db
from app.infrastructure.security import AuthContext, get_current_user, require_workspace_access
from app.modules.gnn.gnn_models import GNNTaskType
from app.modules.gnn.gnn_service import GNNService
from app.modules.world.state_repository import StateRepository

router = APIRouter()
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Request / Response Schemas
# ─────────────────────────────────────────────────────────────────────────────


class GNNEvaluationRequest(BaseModel):
    workspace_id: str
    world_id: str
    version: int = 1


class SupplierSimilarityRequest(BaseModel):
    workspace_id: str
    world_id: str
    target_supplier_id: str
    version: int = 1
    top_k: int = Field(default=5, ge=1, le=20)


class CriticalNodesRequest(BaseModel):
    workspace_id: str
    world_id: str
    version: int = 1
    top_k: int = Field(default=10, ge=1, le=50)


class HiddenDependenciesRequest(BaseModel):
    workspace_id: str
    world_id: str
    version: int = 1
    max_discoveries: int = Field(default=15, ge=1, le=50)


class RiskPropagationRequest(BaseModel):
    workspace_id: str
    world_id: str
    epicenter_entity_id: str
    version: int = 1
    horizon_ticks: int = Field(default=7, ge=1, le=30)
    initial_severity_pct: float = Field(default=100.0, ge=0.0, le=100.0)


class GNNBenchmarkRequest(BaseModel):
    workspace_id: str
    world_id: str
    task_type: GNNTaskType
    target_entity_id: str | None = None
    version: int = 1


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/embeddings")
async def compute_embeddings(
    req: GNNEvaluationRequest,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Compute dense GNN node embeddings for a world state."""
    require_workspace_access(req.workspace_id, auth)

    repo = StateRepository(db)
    world_state = await repo.get(req.world_id, req.workspace_id, req.version)
    if not world_state or world_state.workspace_id != req.workspace_id:
        raise HTTPException(status_code=404, detail="World state not found")

    service = GNNService()
    bundle = service.compute_embeddings(world_state)
    return bundle.to_dict()


@router.post("/similar-suppliers")
async def find_similar_suppliers(
    req: SupplierSimilarityRequest,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Find and rank alternative suppliers with multi-factor transparency."""
    require_workspace_access(req.workspace_id, auth)

    repo = StateRepository(db)
    world_state = await repo.get(req.world_id, req.workspace_id, req.version)
    if not world_state or world_state.workspace_id != req.workspace_id:
        raise HTTPException(status_code=404, detail="World state not found")

    service = GNNService()
    report = service.find_alternative_suppliers(
        world_state=world_state,
        target_supplier_id=req.target_supplier_id,
        top_k=req.top_k,
    )
    return report.to_dict()


@router.post("/critical-nodes")
async def predict_critical_nodes(
    req: CriticalNodesRequest,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Identify single points of failure and systemic bottleneck entities."""
    require_workspace_access(req.workspace_id, auth)

    repo = StateRepository(db)
    world_state = await repo.get(req.world_id, req.workspace_id, req.version)
    if not world_state or world_state.workspace_id != req.workspace_id:
        raise HTTPException(status_code=404, detail="World state not found")

    service = GNNService()
    report = service.predict_critical_nodes(world_state=world_state, top_k=req.top_k)
    return report.to_dict()


@router.post("/hidden-dependencies")
async def detect_hidden_dependencies(
    req: HiddenDependenciesRequest,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Discover unrecorded dependencies and shared vulnerability clusters."""
    require_workspace_access(req.workspace_id, auth)

    repo = StateRepository(db)
    world_state = await repo.get(req.world_id, req.workspace_id, req.version)
    if not world_state or world_state.workspace_id != req.workspace_id:
        raise HTTPException(status_code=404, detail="World state not found")

    service = GNNService()
    report = service.detect_hidden_dependencies(
        world_state=world_state,
        max_discoveries=req.max_discoveries,
    )
    return report.to_dict()


@router.post("/risk-propagation")
async def forecast_risk_propagation(
    req: RiskPropagationRequest,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Forecast cascading disruption propagation across multi-tier networks."""
    require_workspace_access(req.workspace_id, auth)

    repo = StateRepository(db)
    world_state = await repo.get(req.world_id, req.workspace_id, req.version)
    if not world_state or world_state.workspace_id != req.workspace_id:
        raise HTTPException(status_code=404, detail="World state not found")

    service = GNNService()
    report = service.forecast_risk_propagation(
        world_state=world_state,
        epicenter_entity_id=req.epicenter_entity_id,
        horizon_ticks=req.horizon_ticks,
        initial_severity_pct=req.initial_severity_pct,
    )
    return report.to_dict()


@router.post("/benchmark")
async def benchmark_gnn(
    req: GNNBenchmarkRequest,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Benchmark GNN against deterministic algorithms with statistical significance testing."""
    require_workspace_access(req.workspace_id, auth)

    repo = StateRepository(db)
    world_state = await repo.get(req.world_id, req.workspace_id, req.version)
    if not world_state or world_state.workspace_id != req.workspace_id:
        raise HTTPException(status_code=404, detail="World state not found")

    service = GNNService()
    comparison = service.benchmark_gnn_against_baseline(
        world_state=world_state,
        task_type=req.task_type,
        target_entity_id=req.target_entity_id,
    )
    return comparison.to_dict()
