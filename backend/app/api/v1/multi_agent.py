"""Multi-Agent API v1 — Autonomous Specialist Agents & Consensus Endpoints.

Program M (Multi-Agent Coordination & Autonomous Specialist Agents):
- POST /multi-agent/deliberate — Run multi-round deliberation to produce a consensus mitigation plan
- GET /multi-agent/agents — List active specialist agents and functional domains
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database import get_db
from app.infrastructure.security import AuthContext, get_current_user, require_workspace_access
from app.modules.multi_agent.agent_service import MultiAgentService
from app.modules.world.state_repository import StateRepository

router = APIRouter()
logger = logging.getLogger(__name__)


class DeliberateRequest(BaseModel):
    workspace_id: str
    world_id: str
    version: int = 1


@router.post("/deliberate")
async def deliberate_plan(
    req: DeliberateRequest,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Run 3-round specialist deliberation to generate a consensus mitigation plan."""
    require_workspace_access(req.workspace_id, auth)

    repo = StateRepository(db)
    world_state = await repo.get(req.world_id, req.workspace_id, req.version)
    if not world_state or world_state.workspace_id != req.workspace_id:
        raise HTTPException(status_code=404, detail="World state not found")

    service = MultiAgentService()
    plan = service.coordinate_mitigation(world_state)
    return plan.to_dict()


@router.get("/agents")
async def list_agents(
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """List available autonomous specialist agents and functional domains."""
    service = MultiAgentService()
    agents = service.list_active_agents()
    return {"agents": agents, "count": len(agents)}
