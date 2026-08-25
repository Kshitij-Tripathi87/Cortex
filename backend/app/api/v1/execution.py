"""Execution API v1 — Supervised Execution & Closed-Loop Operations.

Program N (Supervised Execution & Closed-Loop Operations):
- POST /execution/plan — Create and validate an ActionPlan
- POST /execution/simulate-gate — Dry-run plan through Digital Twin sandbox
- POST /execution/decision-card — Retrieve human review decision brief
- POST /execution/decide — Record operator decision
- POST /execution/dispatch — Dispatch approved plan to external enterprise adapter
- POST /execution/close-loop — Record actual outcome in decision memory
- GET /execution/memory — Query decision memory records
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.ids import uuid7
from app.infrastructure.database import get_db
from app.infrastructure.security import AuthContext, get_current_user, require_workspace_access
from app.modules.execution.execution_models import (
    ActionPlan,
    OperatorDecision,
    PlanStatus,
)
from app.modules.execution.execution_service import ExecutionService
from app.modules.rl.rl_models import ActionType, MitigationAction
from app.modules.world.state_repository import StateRepository

router = APIRouter()
logger = logging.getLogger(__name__)

_execution_service = ExecutionService()


# ─────────────────────────────────────────────────────────────────────────────
# Request / Response Schemas
# ─────────────────────────────────────────────────────────────────────────────


class CreatePlanRequest(BaseModel):
    workspace_id: str
    world_id: str
    action_type: ActionType
    entity_id: str
    quantity: float = 0.0
    target_entity_id: str | None = None
    cost_usd: float = 0.0
    objective: str
    version: int = 1


class PlanActionRequest(BaseModel):
    workspace_id: str
    world_id: str
    plan: dict[str, Any]
    version: int = 1


class OperatorDecisionRequest(BaseModel):
    workspace_id: str
    world_id: str
    plan: dict[str, Any]
    decision: OperatorDecision
    modifications: dict[str, Any] | None = None


class DispatchPlanRequest(BaseModel):
    workspace_id: str
    plan: dict[str, Any]
    idempotency_key: str | None = None


class CloseLoopRequest(BaseModel):
    workspace_id: str
    world_id: str
    plan: dict[str, Any]
    operator_decision: OperatorDecision
    actual_outcome_revenue_saved_usd: float | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/plan")
async def create_plan(
    req: CreatePlanRequest,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Create an ActionPlan and validate it against policy rules."""
    require_workspace_access(req.workspace_id, auth)

    repo = StateRepository(db)
    world_state = await repo.get(req.world_id, req.workspace_id, req.version)
    if not world_state or world_state.workspace_id != req.workspace_id:
        raise HTTPException(status_code=404, detail="World state not found")

    action = MitigationAction(
        action_type=req.action_type,
        entity_id=req.entity_id,
        quantity=req.quantity,
        target_entity_id=req.target_entity_id,
        cost_usd=req.cost_usd,
    )

    plan = _execution_service.create_plan_from_action(
        workspace_id=req.workspace_id,
        world_id=req.world_id,
        action=action,
        objective=req.objective,
        world_state=world_state,
        operator_role=auth.roles[0] if auth.roles else "operator",
    )
    return plan.to_dict()


@router.post("/simulate-gate")
async def simulate_gate(
    req: PlanActionRequest,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Dry-run plan in an isolated digital twin sandbox."""
    require_workspace_access(req.workspace_id, auth)

    repo = StateRepository(db)
    world_state = await repo.get(req.world_id, req.workspace_id, req.version)
    if not world_state or world_state.workspace_id != req.workspace_id:
        raise HTTPException(status_code=404, detail="World state not found")

    # Reconstruct ActionPlan
    p_dict = req.plan
    action_dict = p_dict["action"]
    action = MitigationAction(
        action_type=ActionType(action_dict["action_type"]),
        entity_id=action_dict["entity_id"],
        quantity=action_dict["quantity"],
        target_entity_id=action_dict.get("target_entity_id"),
        cost_usd=action_dict["cost_usd"],
    )
    plan = ActionPlan(
        plan_id=p_dict["plan_id"],
        workspace_id=p_dict["workspace_id"],
        world_id=p_dict["world_id"],
        objective=p_dict["objective"],
        action=action,
        target_system=p_dict["target_system"],
        expected_cost_usd=p_dict["expected_cost_usd"],
        expected_benefit_usd=p_dict["expected_benefit_usd"],
        expected_risk_score=p_dict["expected_risk_score"],
        affected_entities=p_dict["affected_entities"],
        prerequisites=p_dict["prerequisites"],
        policy_version=p_dict["policy_version"],
        simulation_id=p_dict.get("simulation_id"),
        status=PlanStatus(p_dict["status"]),
    )

    updated_plan, gate_res = _execution_service.run_simulation_gate(plan, world_state)
    return {"plan": updated_plan.to_dict(), "simulation_result": gate_res.to_dict()}


@router.post("/decision-card")
async def get_decision_card(
    req: PlanActionRequest,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Retrieve the human-in-the-loop decision card."""
    require_workspace_access(req.workspace_id, auth)

    repo = StateRepository(db)
    world_state = await repo.get(req.world_id, req.workspace_id, req.version)
    if not world_state or world_state.workspace_id != req.workspace_id:
        raise HTTPException(status_code=404, detail="World state not found")

    p_dict = req.plan
    action_dict = p_dict["action"]
    action = MitigationAction(
        action_type=ActionType(action_dict["action_type"]),
        entity_id=action_dict["entity_id"],
        quantity=action_dict["quantity"],
        target_entity_id=action_dict.get("target_entity_id"),
        cost_usd=action_dict["cost_usd"],
    )
    plan = ActionPlan(
        plan_id=p_dict["plan_id"],
        workspace_id=p_dict["workspace_id"],
        world_id=p_dict["world_id"],
        objective=p_dict["objective"],
        action=action,
        target_system=p_dict["target_system"],
        expected_cost_usd=p_dict["expected_cost_usd"],
        expected_benefit_usd=p_dict["expected_benefit_usd"],
        expected_risk_score=p_dict["expected_risk_score"],
        affected_entities=p_dict["affected_entities"],
        prerequisites=p_dict["prerequisites"],
        policy_version=p_dict["policy_version"],
        simulation_id=p_dict.get("simulation_id"),
        status=PlanStatus(p_dict["status"]),
    )

    card = _execution_service.get_decision_card(plan, world_state)
    return card.to_dict()


@router.post("/decide")
async def submit_operator_decision(
    req: OperatorDecisionRequest,
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Record human review decision on the plan."""
    require_workspace_access(req.workspace_id, auth)

    p_dict = req.plan
    action_dict = p_dict["action"]
    action = MitigationAction(
        action_type=ActionType(action_dict["action_type"]),
        entity_id=action_dict["entity_id"],
        quantity=action_dict["quantity"],
        target_entity_id=action_dict.get("target_entity_id"),
        cost_usd=action_dict["cost_usd"],
    )
    plan = ActionPlan(
        plan_id=p_dict["plan_id"],
        workspace_id=p_dict["workspace_id"],
        world_id=p_dict["world_id"],
        objective=p_dict["objective"],
        action=action,
        target_system=p_dict["target_system"],
        expected_cost_usd=p_dict["expected_cost_usd"],
        expected_benefit_usd=p_dict["expected_benefit_usd"],
        expected_risk_score=p_dict["expected_risk_score"],
        affected_entities=p_dict["affected_entities"],
        prerequisites=p_dict["prerequisites"],
        policy_version=p_dict["policy_version"],
        simulation_id=p_dict.get("simulation_id"),
        status=PlanStatus(p_dict["status"]),
    )

    updated = _execution_service.record_operator_decision(
        plan=plan,
        decision=req.decision,
        operator_id=auth.user_id,
        modifications=req.modifications,
    )
    return updated.to_dict()


@router.post("/dispatch")
async def dispatch_plan(
    req: DispatchPlanRequest,
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Dispatch an approved ActionPlan to the external enterprise adapter."""
    require_workspace_access(req.workspace_id, auth)

    p_dict = req.plan
    action_dict = p_dict["action"]
    action = MitigationAction(
        action_type=ActionType(action_dict["action_type"]),
        entity_id=action_dict["entity_id"],
        quantity=action_dict["quantity"],
        target_entity_id=action_dict.get("target_entity_id"),
        cost_usd=action_dict["cost_usd"],
    )
    plan = ActionPlan(
        plan_id=p_dict["plan_id"],
        workspace_id=p_dict["workspace_id"],
        world_id=p_dict["world_id"],
        objective=p_dict["objective"],
        action=action,
        target_system=p_dict["target_system"],
        expected_cost_usd=p_dict["expected_cost_usd"],
        expected_benefit_usd=p_dict["expected_benefit_usd"],
        expected_risk_score=p_dict["expected_risk_score"],
        affected_entities=p_dict["affected_entities"],
        prerequisites=p_dict["prerequisites"],
        policy_version=p_dict["policy_version"],
        simulation_id=p_dict.get("simulation_id"),
        status=PlanStatus(p_dict["status"]),
    )

    idem_key = req.idempotency_key or f"idem_{uuid7()}"
    exec_res = _execution_service.execute_plan(plan, idempotency_key=idem_key)
    return exec_res.to_dict()


@router.post("/close-loop")
async def close_loop(
    req: CloseLoopRequest,
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Record executed decision and actual outcome in Decision Memory."""
    require_workspace_access(req.workspace_id, auth)

    p_dict = req.plan
    action_dict = p_dict["action"]
    action = MitigationAction(
        action_type=ActionType(action_dict["action_type"]),
        entity_id=action_dict["entity_id"],
        quantity=action_dict["quantity"],
        target_entity_id=action_dict.get("target_entity_id"),
        cost_usd=action_dict["cost_usd"],
    )
    plan = ActionPlan(
        plan_id=p_dict["plan_id"],
        workspace_id=p_dict["workspace_id"],
        world_id=p_dict["world_id"],
        objective=p_dict["objective"],
        action=action,
        target_system=p_dict["target_system"],
        expected_cost_usd=p_dict["expected_cost_usd"],
        expected_benefit_usd=p_dict["expected_benefit_usd"],
        expected_risk_score=p_dict["expected_risk_score"],
        affected_entities=p_dict["affected_entities"],
        prerequisites=p_dict["prerequisites"],
        policy_version=p_dict["policy_version"],
        simulation_id=p_dict.get("simulation_id"),
        status=PlanStatus(p_dict["status"]),
    )

    memory_record = _execution_service.close_decision_loop(
        workspace_id=req.workspace_id,
        world_id=req.world_id,
        plan=plan,
        operator_decision=req.operator_decision,
        operator_id=auth.user_id,
        actual_outcome_revenue_saved_usd=req.actual_outcome_revenue_saved_usd,
    )
    return memory_record.to_dict()


@router.get("/memory")
async def list_decision_memory(
    workspace_id: str = Query(...),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Query all decision memory records and calibration analytics."""
    require_workspace_access(workspace_id, auth)

    records = _execution_service.memory_store.list_records(workspace_id)
    analytics = _execution_service.memory_store.get_calibration_analytics(workspace_id)

    return {
        "workspace_id": workspace_id,
        "records": [r.to_dict() for r in records],
        "analytics": analytics,
    }
