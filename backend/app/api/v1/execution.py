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
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.ids import uuid7
from app.infrastructure.database import get_db
from app.infrastructure.security import AuthContext, get_current_user, require_workspace_access
from app.modules.execution.execution_models import (
    ActionPlan,
    ExecutionSystem,
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
# The plan a caller sends back
# ─────────────────────────────────────────────────────────────────────────────
#
# These routes are stateless: the caller receives a plan from POST /plan and
# sends it back on each later step. The body is therefore untrusted input and
# is validated here, in one place, before any of it is used. A malformed plan
# used to raise KeyError/ValueError inside the handler and surface as a 500.
#
# The request field stays ``plan: dict`` so the published API contract does
# not change; unknown keys (``violations``, ``created_at`` ...) are ignored.
#
# Known limitation, deliberately not hidden: because the plan lives with the
# caller, its ``status`` is whatever the caller sends. The adapters behind
# ``/dispatch`` are simulations (nothing leaves this server). Before a real
# enterprise adapter is connected, plans must be stored server-side and
# ``/dispatch`` must take a plan id, not a plan body.


class _ActionBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    action_type: ActionType
    entity_id: str = Field(min_length=1, max_length=255)
    quantity: float = 0.0
    target_entity_id: str | None = Field(default=None, max_length=255)
    cost_usd: float = 0.0


class _PlanBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    plan_id: str = Field(min_length=1, max_length=255)
    workspace_id: str = Field(min_length=1, max_length=255)
    world_id: str = Field(min_length=1, max_length=255)
    objective: str = Field(max_length=4000)
    action: _ActionBody
    target_system: ExecutionSystem
    expected_cost_usd: float
    expected_benefit_usd: float
    expected_risk_score: float
    affected_entities: list[str] = Field(max_length=1000)
    prerequisites: list[str] = Field(max_length=1000)
    policy_version: str = Field(max_length=255)
    simulation_id: str | None = Field(default=None, max_length=255)
    status: PlanStatus


def _plan_from_body(
    body: dict[str, Any], *, workspace_id: str, world_id: str | None = None
) -> ActionPlan:
    """Validate the plan a caller sent and rebuild the ``ActionPlan``.

    Raises:
        HTTPException(422): the plan is malformed, or names a workspace or
            world other than the one this request is for.
    """
    try:
        parsed = _PlanBody.model_validate(body)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=[
                {
                    "loc": ["body", "plan", *error["loc"]],
                    "msg": error["msg"],
                    "type": error["type"],
                }
                for error in exc.errors(include_url=False, include_input=False)
            ],
        ) from None
    # The caller was authorised for ``workspace_id``. A plan that names a
    # different workspace must not be run or recorded under this one.
    if parsed.workspace_id != workspace_id:
        raise HTTPException(
            status_code=422,
            detail="The plan belongs to a different workspace than this request",
        )
    if world_id is not None and parsed.world_id != world_id:
        raise HTTPException(
            status_code=422,
            detail="The plan belongs to a different world than this request",
        )
    return ActionPlan(
        plan_id=parsed.plan_id,
        workspace_id=parsed.workspace_id,
        world_id=parsed.world_id,
        objective=parsed.objective,
        action=MitigationAction(
            action_type=parsed.action.action_type,
            entity_id=parsed.action.entity_id,
            quantity=parsed.action.quantity,
            target_entity_id=parsed.action.target_entity_id,
            cost_usd=parsed.action.cost_usd,
        ),
        target_system=parsed.target_system,
        expected_cost_usd=parsed.expected_cost_usd,
        expected_benefit_usd=parsed.expected_benefit_usd,
        expected_risk_score=parsed.expected_risk_score,
        affected_entities=list(parsed.affected_entities),
        prerequisites=list(parsed.prerequisites),
        policy_version=parsed.policy_version,
        simulation_id=parsed.simulation_id,
        status=parsed.status,
    )


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

    plan = _plan_from_body(req.plan, workspace_id=req.workspace_id, world_id=req.world_id)

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

    plan = _plan_from_body(req.plan, workspace_id=req.workspace_id, world_id=req.world_id)

    card = _execution_service.get_decision_card(plan, world_state)
    return card.to_dict()


@router.post("/decide")
async def submit_operator_decision(
    req: OperatorDecisionRequest,
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Record human review decision on the plan."""
    require_workspace_access(req.workspace_id, auth)

    plan = _plan_from_body(req.plan, workspace_id=req.workspace_id, world_id=req.world_id)

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

    plan = _plan_from_body(req.plan, workspace_id=req.workspace_id)

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

    plan = _plan_from_body(req.plan, workspace_id=req.workspace_id, world_id=req.world_id)

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
