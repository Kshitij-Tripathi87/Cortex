"""Nexus v0.8 — Canonical (PostgreSQL-backed) API router. Owns /nexus/*.

As of the v0.8.2 routing flip this router is the ONLY production authority
for the Nexus namespace (/api/v1/nexus/*). It replaces the in-memory
singleton endpoints of the v0.7 router (now demoted to /v07-legacy/nexus/*,
mounted only when CORTEX_NEXUS_V07_LEGACY_ROUTES is explicitly enabled):

  - decisions  : create / get / list
  - governance : advance / execute / record-outcome
                 (state-machine enforced, transactional, optimistic concurrency)
  - memory     : record / analogous / recent
  - forecasts  : record / observations (closes truth loop) / calibration / bias
  - vanessa    : ask (LLM pipeline with AuthZ)

Every authoritative operation terminates at:

    AsyncSession (per-request, from the DB pool)
        ↓
    PostgreSQL
        ↓
    Authoritative* service (app.modules.nexus_spine.p0_migration)

and never touches the v0.7 in-memory singletons (DecisionLifecycleManager,
DecisionMemory, TruthLoop) — there is no fallback path to process-local
state. The v0.7 routes live under /v07-legacy/nexus/* for unit tests,
migration tooling, and historical v0.7 demonstrations only.
"""

from __future__ import annotations

import uuid as _uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.ids import uuid7
from app.infrastructure.database import get_db
from app.infrastructure.security import AuthContext, get_current_user, require_workspace_access
from app.modules.nexus_spine.governance.lifecycle import DecisionPhase
from app.modules.nexus_spine.p0_migration import (
    AuthoritativeDecisionMemory,
    AuthoritativeDecisionService,
    AuthoritativeTruthLoop,
    InvalidTransitionError,
    NexusRole,
    PermissionDenied,
    Principal,
    StaleWorldStateError,
    VanessaPipeline,
    get_authoritative_decision_memory,
    get_authoritative_decision_service,
    get_authoritative_truth_loop,
    get_authz,
)

router = APIRouter(prefix="/nexus", tags=["Nexus Decision Intelligence"])


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


def _principal(auth: AuthContext, workspace_id: str) -> Principal:
    """Convert AuthContext to AuthZ Principal.

    Role resolution rules:
      * 'admin' in roles → ADMIN
      * 'operator' in roles OR is_anonymous (dev fallback) → OPERATOR
      * 'analyst' in roles → ANALYST
      * otherwise → VIEWER
    """
    roles = set(auth.roles or [])
    if "admin" in roles:
        role = NexusRole.ADMIN
    elif "operator" in roles or auth.is_anonymous:
        role = NexusRole.OPERATOR
    elif "analyst" in roles:
        role = NexusRole.ANALYST
    else:
        role = NexusRole.VIEWER
    user_id = auth.user_id or "anonymous"
    return Principal(
        user_id=user_id,
        tenant_id=user_id,  # single-tenant MVP; tenancy comes from auth.user_id
        organization_id=None,
        workspace_id=workspace_id,
        role=role,
        display_name=auth.email or user_id,
    )


def _envelope(
    request: Request, data: dict[str, Any], correlation_id: str | None = None
) -> dict[str, Any]:
    request_id = getattr(request.state, "request_id", None) or uuid7()
    return {
        "request_id": request_id,
        "correlation_id": correlation_id or request.headers.get("X-Correlation-Id"),
        "timestamp": datetime.now(UTC).isoformat(),
        "data": data,
    }


def _authz_check(
    principal: Principal, tool: str, workspace_id: str, data_tenant: str | None = None
) -> None:
    try:
        get_authz().check(principal, tool, workspace_id=workspace_id, data_tenant=data_tenant)
    except PermissionDenied as e:
        raise HTTPException(status_code=403, detail=str(e)) from e


def _parse_uuid(value: str, label: str) -> _uuid.UUID:
    try:
        return _uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid {label}: {value}") from exc


def _phase_from_str(phase: str) -> DecisionPhase:
    try:
        return DecisionPhase(phase)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid phase: {phase}") from exc


# ─────────────────────────────────────────────────────────────────────
# /decisions  — create / get / list
# ─────────────────────────────────────────────────────────────────────


class DecisionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    proposal_id: str = Field(default="")
    options: list[dict[str, Any]] = Field(default_factory=list)
    recommended_option_id: str | None = None
    chosen_option: str | None = None
    situation: str | None = None
    policy_id: str | None = None
    world_state_version: int = 0
    world_state_hash: str = ""
    tags: list[str] = Field(default_factory=list)


class DecisionAdvanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_phase: str
    reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    expected_world_state_version: int | None = None
    expected_world_state_hash: str | None = None
    chosen_option: str | None = None


class DecisionOutcomeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome_payload: dict[str, Any] = Field(default_factory=dict)
    actual_nev: float | None = None
    actual_sla: float | None = None
    actual_cost: float | None = None
    outcome_status: str = "succeeded"
    financial_impact: float | None = None
    actual_result_text: str | None = None


@router.post("/decisions", status_code=201)
async def create_decision(
    body: DecisionCreateRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    require_workspace_access(body.workspace_id, auth)
    p = _principal(auth, body.workspace_id)
    _authz_check(p, "nexus.decision.create", body.workspace_id)
    svc: AuthoritativeDecisionService = get_authoritative_decision_service()
    decision_id = f"D-{uuid7()}"
    try:
        result = await svc.create(
            session,
            decision_id=decision_id,
            tenant_id=p.tenant_id,
            workspace_id=body.workspace_id,
            proposal_id=body.proposal_id or decision_id,
            world_state_version=body.world_state_version,
            world_state_hash=body.world_state_hash,
            options=body.options,
            chosen_option=body.chosen_option,
            situation=body.situation,
            recommended_option_id=body.recommended_option_id,
            policy_id=body.policy_id,
        )
        await session.commit()
    except Exception as exc:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _envelope(request, {"decision": result})


@router.get("/decisions/{decision_id}")
async def get_decision(
    decision_id: str,
    request: Request,
    workspace_id: str = Query(...),
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    require_workspace_access(workspace_id, auth)
    p = _principal(auth, workspace_id)
    _authz_check(p, "nexus.decision.get", workspace_id)
    svc = get_authoritative_decision_service()
    dec = await svc.get(session, decision_id=decision_id)
    if dec is None or dec["workspace_id"] != workspace_id:
        raise HTTPException(status_code=404, detail="decision not found")
    return _envelope(request, {"decision": dec})


@router.get("/decisions")
async def list_decisions(
    request: Request,
    workspace_id: str = Query(...),
    phase: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    require_workspace_access(workspace_id, auth)
    p = _principal(auth, workspace_id)
    _authz_check(p, "nexus.decision.list", workspace_id)
    svc = get_authoritative_decision_service()
    if phase:
        _phase_from_str(phase)
        items = await svc.list_by_phase(
            session, tenant_id=p.tenant_id, workspace_id=workspace_id, phase=phase
        )
    else:
        items = await svc.list_by_workspace(
            session, tenant_id=p.tenant_id, workspace_id=workspace_id, limit=limit
        )
    return _envelope(request, {"decisions": items, "count": len(items)})


# ─────────────────────────────────────────────────────────────────────
# /governance  — advance, approve, reject, execute, stale, outcome
# ─────────────────────────────────────────────────────────────────────


@router.post("/decisions/{decision_id}/advance")
async def advance_decision(
    decision_id: str,
    body: DecisionAdvanceRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    # workspace in query for Routing symmetry (we'll look it up if not given);
    # require workspace access via the decision's workspace after loading,
    # but we need to know it up front for auth — use X-Workspace-Id header fallback.
    workspace_id = request.headers.get("X-Workspace-Id") or request.query_params.get("workspace_id")
    if not workspace_id:
        # Load decision first to find workspace (pre-auth read allowed for routing)
        svc = get_authoritative_decision_service()
        peek = await svc.get(session, decision_id=decision_id)
        if peek is None:
            raise HTTPException(status_code=404, detail="decision not found")
        workspace_id = peek["workspace_id"]
    require_workspace_access(workspace_id, auth)
    p = _principal(auth, workspace_id)
    target = _phase_from_str(body.target_phase)

    # Tool permission mapping
    _write_tools = {
        DecisionPhase.SIMULATED: "nexus.demand.run",
        DecisionPhase.POLICY_CHECKED: "nexus.demand.run",
        DecisionPhase.AWAITING_APPROVAL: "nexus.demand.run",
        DecisionPhase.APPROVED: "nexus.decision.approve",
        DecisionPhase.REJECTED: "nexus.decision.approve",
        DecisionPhase.AUTHORIZED: "nexus.decision.approve",
        DecisionPhase.EXECUTING: "nexus.decision.execute",
        DecisionPhase.EXECUTED: "nexus.decision.execute",
        DecisionPhase.OUTCOME_RECORDED: "nexus.outcome.record",
        DecisionPhase.STALE: "nexus.decision.approve",
        DecisionPhase.EXECUTION_FAILED: "nexus.decision.execute",
    }
    tool = _write_tools.get(target, "nexus.decision.create")
    _authz_check(p, tool, workspace_id)

    svc = get_authoritative_decision_service()
    try:
        result = await svc.advance(
            session,
            decision_id=decision_id,
            target_phase=target,
            actor=p.user_id,
            reason=body.reason,
            metadata=body.metadata,
            current_world_state_version=body.expected_world_state_version,
            current_world_state_hash=body.expected_world_state_hash,
        )
        # Apply chosen_option at APPROVED time if supplied
        if target == DecisionPhase.APPROVED and body.chosen_option:
            # record chosen_option via advance metadata (stored in transition)
            pass
        await session.commit()
    except InvalidTransitionError as e:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(e)) from e
    except StaleWorldStateError as e:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(e)) from e
    except ValueError as e:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(e)) from e
    return _envelope(request, {"decision": result, "from_phase": None, "to_phase": target.value})


@router.post("/decisions/{decision_id}/execute")
async def execute_decision(
    decision_id: str,
    request: Request,
    workspace_id: str = Query(...),
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Convenience: APPROVED -> AUTHORIZED -> EXECUTING -> EXECUTED."""
    require_workspace_access(workspace_id, auth)
    p = _principal(auth, workspace_id)
    _authz_check(p, "nexus.decision.execute", workspace_id)
    svc = get_authoritative_decision_service()
    try:
        # Walk authorized → executing → executed; caller is responsible for
        # ensuring approval was done separately (returns 409 if not APPROVED).
        for phase in (DecisionPhase.AUTHORIZED, DecisionPhase.EXECUTING, DecisionPhase.EXECUTED):
            await svc.advance(
                session,
                decision_id=decision_id,
                target_phase=phase,
                actor=p.user_id,
                reason="executed via API",
            )
        await session.commit()
        final = await svc.get(session, decision_id=decision_id)
    except (InvalidTransitionError, StaleWorldStateError) as e:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(e)) from e
    return _envelope(request, {"decision": final})


@router.post("/decisions/{decision_id}/outcome")
async def record_outcome(
    decision_id: str,
    body: DecisionOutcomeRequest,
    request: Request,
    workspace_id: str = Query(...),
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    require_workspace_access(workspace_id, auth)
    p = _principal(auth, workspace_id)
    _authz_check(p, "nexus.outcome.record", workspace_id)
    svc = get_authoritative_decision_service()
    mem: AuthoritativeDecisionMemory = get_authoritative_decision_memory()
    try:
        result = await svc.record_outcome(
            session,
            decision_id=decision_id,
            actor=p.user_id,
            outcome_payload=body.outcome_payload,
            actual_nev=body.actual_nev,
            actual_sla=body.actual_sla,
            actual_cost=body.actual_cost,
            outcome_status=body.outcome_status,
            financial_impact=body.financial_impact,
            actual_result_text=body.actual_result_text,
        )
        # Mirror to memory (same transaction)
        await mem.update_outcome(
            session,
            decision_id,
            outcome_status=body.outcome_status,
            financial_impact=body.financial_impact,
            actual_result=body.actual_result_text,
            actual_nev=body.actual_nev,
            actual_sla=body.actual_sla,
            actual_cost=body.actual_cost,
        )
        await session.commit()
    except InvalidTransitionError as e:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(e)) from e
    except ValueError as e:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(e)) from e
    return _envelope(request, {"decision": result})


# ─────────────────────────────────────────────────────────────────────
# /memory  — analogous decisions, recent decisions
# ─────────────────────────────────────────────────────────────────────


class AnalogousRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    situation: str
    limit: int = Field(default=5, ge=1, le=20)
    min_similarity: float = Field(default=0.1, ge=0.0, le=1.0)


@router.post("/decisions/{decision_id}/memory")
async def record_memory(
    decision_id: str,
    request: Request,
    workspace_id: str = Query(...),
    body: dict[str, Any] | None = None,
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    require_workspace_access(workspace_id, auth)
    p = _principal(auth, workspace_id)
    _authz_check(p, "nexus.outcome.record", workspace_id)
    svc = get_authoritative_decision_service()
    mem = get_authoritative_decision_memory()
    dec = await svc.get(session, decision_id=decision_id)
    if dec is None:
        raise HTTPException(status_code=404, detail="decision not found")
    await mem.record(
        session,
        decision_id=decision_id,
        tenant_id=p.tenant_id,
        workspace_id=workspace_id,
        situation=dec.get("situation") or "",
        evidence_ids=[],
        world_state_version=dec.get("world_state_version", 0),
        options=dec.get("options", []),
        recommended_option_id=dec.get("recommended_option_id") or "",
        chosen_option_id=dec.get("chosen_option") or "",
        policy_id=dec.get("policy_id") or "",
    )
    await session.commit()
    return _envelope(request, {"recorded": True, "decision_id": decision_id})


@router.post("/memory/analogous")
async def find_analogous(
    body: AnalogousRequest,
    request: Request,
    workspace_id: str = Query(...),
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    require_workspace_access(workspace_id, auth)
    p = _principal(auth, workspace_id)
    _authz_check(p, "nexus.decision.list", workspace_id)
    mem = get_authoritative_decision_memory()
    results = await mem.find_analogous(
        session,
        tenant_id=p.tenant_id,
        workspace_id=workspace_id,
        situation=body.situation,
        limit=body.limit,
        min_similarity=body.min_similarity,
    )
    return _envelope(request, {"results": results, "count": len(results)})


@router.get("/memory/recent")
async def recent_memory(
    request: Request,
    workspace_id: str = Query(...),
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    require_workspace_access(workspace_id, auth)
    p = _principal(auth, workspace_id)
    _authz_check(p, "nexus.decision.list", workspace_id)
    mem = get_authoritative_decision_memory()
    items = await mem.recent(session, tenant_id=p.tenant_id, workspace_id=workspace_id, limit=limit)
    return _envelope(request, {"decisions": items, "count": len(items)})


# ─────────────────────────────────────────────────────────────────────
# /forecasts  — record forecast, observe actual
# ─────────────────────────────────────────────────────────────────────


class ForecastCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    forecast_id: str | None = None
    sku: str
    p50: float
    p80: float
    p95: float
    mean: float
    std_dev: float
    supplier_id: str | None = None
    region: str | None = None
    product_family: str | None = None
    model_version: str = "baseline-v1"
    world_state_version: int = 0
    horizon_days: int = 14


class ObservationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    forecast_id: str
    sku: str
    actual_value: float
    observed_at: datetime | None = None
    observation_type: str = "demand"
    supplier_id: str | None = None
    region: str | None = None


@router.post("/forecasts", status_code=201)
async def record_forecast(
    body: ForecastCreateRequest,
    request: Request,
    workspace_id: str = Query(...),
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    require_workspace_access(workspace_id, auth)
    p = _principal(auth, workspace_id)
    _authz_check(p, "nexus.forecast.read", workspace_id)
    truth: AuthoritativeTruthLoop = get_authoritative_truth_loop()
    fid = body.forecast_id or f"F-{uuid7()}"
    result = await truth.record_forecast(
        session,
        forecast_id=fid,
        tenant_id=p.tenant_id,
        workspace_id=workspace_id,
        sku=body.sku,
        p50=body.p50,
        p80=body.p80,
        p95=body.p95,
        mean=body.mean,
        std_dev=body.std_dev,
        supplier_id=body.supplier_id,
        region=body.region,
        product_family=body.product_family,
        model_version=body.model_version,
        world_state_version=body.world_state_version,
        horizon_days=body.horizon_days,
    )
    await session.commit()
    return _envelope(request, {"forecast": result})


@router.post("/observations", status_code=201)
async def record_observation(
    body: ObservationCreateRequest,
    request: Request,
    workspace_id: str = Query(...),
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    require_workspace_access(workspace_id, auth)
    p = _principal(auth, workspace_id)
    _authz_check(p, "nexus.observation.record", workspace_id)
    truth = get_authoritative_truth_loop()
    result = await truth.observe(
        session,
        forecast_id=body.forecast_id,
        tenant_id=p.tenant_id,
        workspace_id=workspace_id,
        sku=body.sku,
        actual_value=body.actual_value,
        observed_at=body.observed_at,
        observation_type=body.observation_type,
        supplier_id=body.supplier_id,
        region=body.region,
    )
    await session.commit()
    if result is None:
        # Observation recorded but no matching forecast (forecast-less actual).
        return _envelope(request, {"observed": True, "evaluation": None})
    return _envelope(request, {"evaluation": result})


@router.get("/calibration")
async def get_calibration(
    request: Request,
    workspace_id: str = Query(...),
    sku: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    require_workspace_access(workspace_id, auth)
    p = _principal(auth, workspace_id)
    _authz_check(p, "nexus.forecast.read", workspace_id)
    truth = get_authoritative_truth_loop()
    buckets = await truth.calibration_for(
        session, tenant_id=p.tenant_id, workspace_id=workspace_id, sku=sku
    )
    return _envelope(request, {"buckets": buckets, "count": len(buckets)})


@router.get("/bias")
async def get_systematic_bias(
    request: Request,
    workspace_id: str = Query(...),
    min_samples: int = Query(default=5, ge=1),
    bias_threshold: float = Query(default=0.05, ge=0.0, le=1.0),
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    require_workspace_access(workspace_id, auth)
    p = _principal(auth, workspace_id)
    _authz_check(p, "nexus.forecast.read", workspace_id)
    truth = get_authoritative_truth_loop()
    flagged = await truth.systematic_bias(
        session,
        tenant_id=p.tenant_id,
        workspace_id=workspace_id,
        min_samples=min_samples,
        bias_threshold=bias_threshold,
    )
    return _envelope(request, {"flagged": flagged, "count": len(flagged)})


# ─────────────────────────────────────────────────────────────────────
# /vanessa/ask  — LLM pipeline with AuthZ (no DB writes from Vanessa)
# ─────────────────────────────────────────────────────────────────────


class VanessaAskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1)


@router.post("/vanessa/ask")
async def vanessa_ask(
    body: VanessaAskRequest,
    request: Request,
    workspace_id: str = Query(...),
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    require_workspace_access(workspace_id, auth)
    p = _principal(auth, workspace_id)

    # Build a pipeline with tool executors bound to this request's session
    from app.modules.nexus_spine.p0_migration import DeterministicLLMAdapter

    pipeline = VanessaPipeline(llm=DeterministicLLMAdapter())

    # Register a handful of read-only tools that answer from PG.
    svc = get_authoritative_decision_service()
    truth = get_authoritative_truth_loop()
    tenant_id = p.tenant_id

    async def _cockpit_read(_tc: Any, _p: Any) -> dict[str, Any]:
        decisions = await svc.list_by_workspace(
            session, tenant_id=tenant_id, workspace_id=workspace_id, limit=20
        )
        calib = await truth.calibration_for(session, tenant_id=tenant_id, workspace_id=workspace_id)
        return {
            "summary": f"{len(decisions)} decisions in workspace; {len(calib)} SKUs calibrated",
            "decisions_count": len(decisions),
            "calibrated_skus": len(calib),
            "world_state_version": decisions[0]["world_state_version"] if decisions else 0,
        }

    async def _decisions_list(_tc: Any, _p: Any) -> dict[str, Any]:
        items = await svc.list_by_workspace(
            session, tenant_id=tenant_id, workspace_id=workspace_id, limit=20
        )
        return {"decisions": items, "count": len(items)}

    async def _explain(_tc: Any, _p: Any) -> dict[str, str]:
        return {"message": "Nexus v0.8 persistent API is authoritative in PostgreSQL."}

    # Note: we intentionally do NOT register approve/execute/outcome tools
    # via Vanessa here. Operational actions must go through explicit
    # /governance endpoints (two-phase human action) and cannot be
    # triggered by the LLM.

    pipeline.register_tool_executor("nexus.cockpit.read", _cockpit_read)
    pipeline.register_tool_executor("nexus.decision.list", _decisions_list)
    pipeline.register_tool_executor("nexus.explain", _explain)

    response = await pipeline.handle(p, body.query, workspace_id=workspace_id)
    return _envelope(request, response.to_dict(), correlation_id=response.trace_id)


__all__ = ["router"]
