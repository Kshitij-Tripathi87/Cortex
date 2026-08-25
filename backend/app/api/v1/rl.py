"""RL API v1 — Reinforcement Learning & Mitigation Policy Optimization Endpoints.

Program L (Reinforcement Learning & Policy Optimization):
- POST /rl/recommend-action — Generate optimal policy recommendation
- POST /rl/rollout — Run multi-step trajectory rollout in sandbox
- POST /rl/benchmark — Benchmark RL policy against deterministic baseline
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database import get_db
from app.infrastructure.security import AuthContext, get_current_user, require_workspace_access
from app.modules.rl.rl_service import RLService
from app.modules.world.state_repository import StateRepository

router = APIRouter()
logger = logging.getLogger(__name__)


class RLActionRequest(BaseModel):
    workspace_id: str
    world_id: str
    version: int = 1


class RLRolloutRequest(BaseModel):
    workspace_id: str
    world_id: str
    version: int = 1
    max_steps: int = Field(default=10, ge=1, le=50)


class RLBenchmarkRequest(BaseModel):
    workspace_id: str
    world_id: str
    version: int = 1
    episodes: int = Field(default=3, ge=1, le=20)


@router.post("/recommend-action")
async def recommend_action(
    req: RLActionRequest,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Recommend the optimal mitigation action for the given world state."""
    require_workspace_access(req.workspace_id, auth)

    repo = StateRepository(db)
    world_state = await repo.get(req.world_id, req.workspace_id, req.version)
    if not world_state or world_state.workspace_id != req.workspace_id:
        raise HTTPException(status_code=404, detail="World state not found")

    service = RLService()
    rec = service.recommend_mitigation_action(world_state)
    return rec.to_dict()


@router.post("/rollout")
async def run_rollout(
    req: RLRolloutRequest,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Execute a multi-step trajectory rollout in sandbox environment."""
    require_workspace_access(req.workspace_id, auth)

    repo = StateRepository(db)
    world_state = await repo.get(req.world_id, req.workspace_id, req.version)
    if not world_state or world_state.workspace_id != req.workspace_id:
        raise HTTPException(status_code=404, detail="World state not found")

    service = RLService()
    rollout = service.run_trajectory_rollout(world_state, max_steps=req.max_steps)
    return rollout.to_dict()


@router.post("/benchmark")
async def benchmark_policy(
    req: RLBenchmarkRequest,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Benchmark RL policy performance against deterministic baseline heuristic."""
    require_workspace_access(req.workspace_id, auth)

    repo = StateRepository(db)
    world_state = await repo.get(req.world_id, req.workspace_id, req.version)
    if not world_state or world_state.workspace_id != req.workspace_id:
        raise HTTPException(status_code=404, detail="World state not found")

    service = RLService()
    comparison = service.benchmark_against_baseline(world_state, episodes=req.episodes)
    return comparison.to_dict()
