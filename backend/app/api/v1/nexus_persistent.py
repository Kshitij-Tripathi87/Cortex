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
  - risks      : record (upsert) / list / get / triage-status (v0.8.5-B3)
  - signals    : canonical detection-on-read over PG state (v0.8.5-B3)
  - scenarios  : create / list / get / simulate-against-snapshot (v0.8.5-B3)
  - evidence   : append nodes+edges / read decision DAG (v0.8.5-B3)
  - approvals  : approver identity trail written by advance() (v0.8.5-B3, B8)

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

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.ids import uuid7
from app.config import get_settings
from app.infrastructure.database import get_db, get_session_factory
from app.infrastructure.outbox_publisher import (
    commit_and_notify,
    current_outbox_publisher,
    get_backlog_stats,
)
from app.infrastructure.realtime_bus import sse_stream
from app.infrastructure.security import AuthContext, get_current_user, require_workspace_access
from app.modules.nexus_spine.governance.lifecycle import DecisionPhase
from app.modules.nexus_spine.ontology.entities import Entity
from app.modules.nexus_spine.p0_migration import (
    AuthoritativeDecisionMemory,
    AuthoritativeDecisionService,
    AuthoritativeTruthLoop,
    DuplicateModelVersionError,
    InvalidModelTransitionError,
    InvalidTransitionError,
    ModelNotFoundError,
    NexusRole,
    PermissionDenied,
    Principal,
    PromotionGateConfig,
    PromotionGateFailedError,
    RegistryConflictError,
    RegistryValidationError,
    StaleWorldStateError,
    VanessaPipeline,
    get_authoritative_decision_memory,
    get_authoritative_decision_service,
    get_authoritative_inference_engine,
    get_authoritative_model_registry,
    get_authoritative_registry_service,
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
        await commit_and_notify(session)
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
            actor_role=p.role.value,
            reason=body.reason,
            metadata=body.metadata,
            current_world_state_version=body.expected_world_state_version,
            current_world_state_hash=body.expected_world_state_hash,
        )
        # Apply chosen_option at APPROVED time if supplied
        if target == DecisionPhase.APPROVED and body.chosen_option:
            # record chosen_option via advance metadata (stored in transition)
            pass
        await commit_and_notify(session)
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
                actor_role=p.role.value,
                reason="executed via API",
            )
        await commit_and_notify(session)
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
        await commit_and_notify(session)
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
    await commit_and_notify(session)
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
    await commit_and_notify(session)
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
    await commit_and_notify(session)
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
# /models & /inference — Governed Model Registry & Real ML Inference (v0.8.4)
# ─────────────────────────────────────────────────────────────────────


class ModelRegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    model_type: str = Field(min_length=1)  # forecast|risk|gnn|rl|eta|sla
    description: str = ""
    training_dataset: str | None = None
    feature_schema: dict[str, Any] = Field(default_factory=dict)
    world_state_version: int | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    calibration: dict[str, Any] = Field(default_factory=dict)
    gnn_config: dict[str, Any] | None = None
    rl_config: dict[str, Any] | None = None
    promotion_gates: dict[str, Any] | None = None


class ModelEvaluateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metrics: dict[str, Any]
    shadow_metrics: dict[str, Any] | None = None
    calibration: dict[str, Any] | None = None
    target_status: str = "shadow"


class ModelPromoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skip_gate_validation: bool = False
    custom_gates: dict[str, Any] | None = None


class ModelRollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1)
    fallback_model_id: str | None = None


class DemandInferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sku: str = Field(min_length=1)
    features: dict[str, Any] = Field(default_factory=dict)
    horizon_days: int = Field(default=14, ge=1, le=90)
    world_state_version: int = Field(default=1, ge=0)
    supplier_id: str | None = None
    region: str | None = None
    product_family: str | None = None


class RiskInferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_id: str = Field(min_length=1)
    features: dict[str, Any] = Field(default_factory=dict)
    world_state_version: int = Field(default=1, ge=0)


@router.post("/models/register", status_code=201)
async def register_model(
    body: ModelRegisterRequest,
    request: Request,
    workspace_id: str = Query(...),
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    require_workspace_access(workspace_id, auth)
    p = _principal(auth, workspace_id)
    _authz_check(p, "nexus.model.register", workspace_id)
    registry = get_authoritative_model_registry()
    try:
        model = await registry.register_candidate(
            session,
            tenant_id=p.tenant_id,
            workspace_id=workspace_id,
            name=body.name,
            version=body.version,
            model_type=body.model_type,
            description=body.description,
            training_dataset=body.training_dataset,
            feature_schema=body.feature_schema,
            world_state_version=body.world_state_version,
            metrics=body.metrics,
            calibration=body.calibration,
            gnn_config=body.gnn_config,
            rl_config=body.rl_config,
            promotion_gates=body.promotion_gates,
            actor_principal=p,
        )
        await commit_and_notify(session)
    except DuplicateModelVersionError as e:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(e)) from e
    return _envelope(request, {"model": model})


@router.get("/models")
async def list_models(
    request: Request,
    workspace_id: str = Query(...),
    status: str | None = Query(default=None),
    model_type: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    require_workspace_access(workspace_id, auth)
    p = _principal(auth, workspace_id)
    _authz_check(p, "nexus.model.read", workspace_id)
    registry = get_authoritative_model_registry()
    models = await registry.list_models(
        session,
        tenant_id=p.tenant_id,
        workspace_id=workspace_id,
        status=status,
        model_type=model_type,
    )
    return _envelope(request, {"models": models, "count": len(models)})


@router.get("/models/health")
async def get_models_health(
    request: Request,
    workspace_id: str = Query(...),
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    require_workspace_access(workspace_id, auth)
    p = _principal(auth, workspace_id)
    _authz_check(p, "nexus.model.read", workspace_id)
    registry = get_authoritative_model_registry()
    summary = await registry.health_summary(
        session, tenant_id=p.tenant_id, workspace_id=workspace_id
    )
    return _envelope(request, {"health": summary})


@router.get("/models/drift")
async def get_models_drift(
    request: Request,
    workspace_id: str = Query(...),
    model_id: str | None = Query(default=None),
    min_samples: int = Query(default=5, ge=1),
    wape_threshold: float = Query(default=0.15, ge=0.0, le=1.0),
    bias_threshold: float = Query(default=0.08, ge=0.0, le=1.0),
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    require_workspace_access(workspace_id, auth)
    p = _principal(auth, workspace_id)
    _authz_check(p, "nexus.model.read", workspace_id)
    truth = get_authoritative_truth_loop()
    report = await truth.detect_drift(
        session,
        tenant_id=p.tenant_id,
        workspace_id=workspace_id,
        model_id=model_id,
        min_samples=min_samples,
        wape_drift_threshold=wape_threshold,
        bias_threshold=bias_threshold,
    )
    return _envelope(request, {"drift": report})


@router.get("/models/{model_id}")
async def get_model(
    model_id: str,
    request: Request,
    workspace_id: str = Query(...),
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    require_workspace_access(workspace_id, auth)
    p = _principal(auth, workspace_id)
    _authz_check(p, "nexus.model.read", workspace_id)
    registry = get_authoritative_model_registry()
    model = await registry.get_model(session, model_id)
    if not model or model["tenant_id"] != p.tenant_id or model["workspace_id"] != workspace_id:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")
    return _envelope(request, {"model": model})


@router.post("/models/{model_id}/evaluate")
async def evaluate_model(
    model_id: str,
    body: ModelEvaluateRequest,
    request: Request,
    workspace_id: str = Query(...),
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    require_workspace_access(workspace_id, auth)
    p = _principal(auth, workspace_id)
    _authz_check(p, "nexus.model.evaluate", workspace_id)
    registry = get_authoritative_model_registry()
    try:
        model = await registry.evaluate_candidate(
            session,
            model_id=model_id,
            metrics=body.metrics,
            shadow_metrics=body.shadow_metrics,
            calibration=body.calibration,
            target_status=body.target_status,
            actor_principal=p,
        )
        await commit_and_notify(session)
    except ModelNotFoundError as e:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(e)) from e
    except InvalidModelTransitionError as e:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(e)) from e
    return _envelope(request, {"model": model})


@router.post("/models/{model_id}/promote")
async def promote_model(
    model_id: str,
    body: ModelPromoteRequest,
    request: Request,
    workspace_id: str = Query(...),
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    require_workspace_access(workspace_id, auth)
    p = _principal(auth, workspace_id)
    _authz_check(p, "nexus.model.promote", workspace_id)
    registry = get_authoritative_model_registry()
    gates = PromotionGateConfig(**body.custom_gates) if body.custom_gates else None
    try:
        result = await registry.promote_model(
            session,
            model_id=model_id,
            actor_principal=p,
            custom_gates=gates,
            skip_gate_validation=body.skip_gate_validation,
        )
        await commit_and_notify(session)
    except ModelNotFoundError as e:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(e)) from e
    except PromotionGateFailedError as e:
        await session.rollback()
        raise HTTPException(
            status_code=422,
            detail={
                "message": str(e),
                "failures": e.failures,
                "evaluated_metrics": e.evaluated_metrics,
            },
        ) from e
    return _envelope(request, result)


@router.post("/models/{model_id}/rollback")
async def rollback_model(
    model_id: str,
    body: ModelRollbackRequest,
    request: Request,
    workspace_id: str = Query(...),
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    require_workspace_access(workspace_id, auth)
    p = _principal(auth, workspace_id)
    _authz_check(p, "nexus.model.rollback", workspace_id)
    registry = get_authoritative_model_registry()
    try:
        result = await registry.rollback_model(
            session,
            model_id=model_id,
            actor_principal=p,
            reason=body.reason,
            fallback_model_id=body.fallback_model_id,
        )
        await commit_and_notify(session)
    except ModelNotFoundError as e:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(e)) from e
    return _envelope(request, result)


@router.post("/inference/demand", status_code=201)
async def predict_demand(
    body: DemandInferenceRequest,
    request: Request,
    workspace_id: str = Query(...),
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    require_workspace_access(workspace_id, auth)
    p = _principal(auth, workspace_id)
    _authz_check(p, "nexus.inference.run", workspace_id)
    engine = get_authoritative_inference_engine()
    result = await engine.predict_demand(
        session,
        tenant_id=p.tenant_id,
        workspace_id=workspace_id,
        sku=body.sku,
        features=body.features,
        horizon_days=body.horizon_days,
        world_state_version=body.world_state_version,
        supplier_id=body.supplier_id,
        region=body.region,
        product_family=body.product_family,
        actor_principal=p,
    )
    await commit_and_notify(session)
    return _envelope(request, {"prediction": result})


@router.post("/inference/risk", status_code=201)
async def predict_risk(
    body: RiskInferenceRequest,
    request: Request,
    workspace_id: str = Query(...),
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    require_workspace_access(workspace_id, auth)
    p = _principal(auth, workspace_id)
    _authz_check(p, "nexus.inference.run", workspace_id)
    engine = get_authoritative_inference_engine()
    result = await engine.predict_risk(
        session,
        tenant_id=p.tenant_id,
        workspace_id=workspace_id,
        entity_id=body.entity_id,
        features=body.features,
        world_state_version=body.world_state_version,
        actor_principal=p,
    )
    await commit_and_notify(session)
    return _envelope(request, {"prediction": result})


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


# ─────────────────────────────────────────────────────────────────────
# /risks — record / list / get / triage (v0.8.5-B3)
#
# The persisted risk registry. Detectors (risk engine, GNN, humans,
# external systems) record assessments; the registry upserts on the open
# risk for (tenant, workspace, entity).
# ─────────────────────────────────────────────────────────────────────


class RiskRecordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    entity_id: str
    entity_kind: str
    severity: str  # CRITICAL|HIGH|MEDIUM|LOW|WATCH
    title: str
    world_state_version: int
    risk_score: float = 0.0
    gnn_risk_score: float | None = None
    description: str = ""
    blast_radius_count: int = 0
    revenue_exposure: float | None = None
    sla_risk_pct: float | None = None
    root_causes: list[str] = Field(default_factory=list)
    hidden_dependencies: list[str] = Field(default_factory=list)


class RiskStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    status: str  # open|mitigated|closed|stale


@router.post("/risks", status_code=201)
async def record_risk(
    body: RiskRecordRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    require_workspace_access(body.workspace_id, auth)
    p = _principal(auth, body.workspace_id)
    _authz_check(p, "nexus.risk.record", body.workspace_id)
    svc = get_authoritative_registry_service()
    try:
        result = await svc.record_risk(
            session,
            tenant_id=p.tenant_id,
            workspace_id=body.workspace_id,
            entity_id=body.entity_id,
            entity_kind=body.entity_kind,
            severity=body.severity,
            title=body.title,
            world_state_version=body.world_state_version,
            risk_score=body.risk_score,
            gnn_risk_score=body.gnn_risk_score,
            description=body.description,
            blast_radius_count=body.blast_radius_count,
            revenue_exposure=body.revenue_exposure,
            sla_risk_pct=body.sla_risk_pct,
            root_causes=body.root_causes,
            hidden_dependencies=body.hidden_dependencies,
        )
        await commit_and_notify(session)
    except RegistryValidationError as e:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _envelope(request, {"risk": result})


@router.get("/risks")
async def list_risks(
    request: Request,
    workspace_id: str = Query(...),
    min_severity: str | None = Query(None),
    status: str = Query("open", description="open|mitigated|closed|stale|all"),
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    require_workspace_access(workspace_id, auth)
    p = _principal(auth, workspace_id)
    _authz_check(p, "nexus.risk.read", workspace_id)
    svc = get_authoritative_registry_service()
    try:
        risks = await svc.list_risks(
            session,
            tenant_id=p.tenant_id,
            workspace_id=workspace_id,
            min_severity=min_severity,
            status=None if status == "all" else status,
        )
    except RegistryValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _envelope(request, {"risks": risks, "count": len(risks)})


@router.get("/risks/{risk_id}")
async def get_risk(
    risk_id: str,
    request: Request,
    workspace_id: str = Query(...),
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    require_workspace_access(workspace_id, auth)
    p = _principal(auth, workspace_id)
    _authz_check(p, "nexus.risk.read", workspace_id)
    svc = get_authoritative_registry_service()
    try:
        risk = await svc.get_risk(session, risk_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="risk not found") from None
    if risk["workspace_id"] != workspace_id or risk["tenant_id"] != p.tenant_id:
        raise HTTPException(status_code=404, detail="risk not found")
    return _envelope(request, {"risk": risk})


@router.patch("/risks/{risk_id}")
async def triage_risk(
    risk_id: str,
    body: RiskStatusRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    require_workspace_access(body.workspace_id, auth)
    p = _principal(auth, body.workspace_id)
    _authz_check(p, "nexus.risk.triage", body.workspace_id)
    svc = get_authoritative_registry_service()
    try:
        risk = await svc.get_risk(session, risk_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="risk not found") from None
    if risk["workspace_id"] != body.workspace_id or risk["tenant_id"] != p.tenant_id:
        raise HTTPException(status_code=404, detail="risk not found")
    try:
        updated = await svc.set_risk_status(session, risk_id, body.status)
        await commit_and_notify(session)
    except RegistryValidationError as e:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _envelope(request, {"risk": updated})


# ─────────────────────────────────────────────────────────────────────
# /signals — canonical detection-on-read (v0.8.5-B3)
#
# Signals are computed from live PG-backed graph/operational state on every
# read (same SignalEngine construction as GET /graph/signals) — there is no
# persisted signal table by design. Persisted derivatives live in the risk
# registry and the evidence DAG.
# ─────────────────────────────────────────────────────────────────────


@router.get("/signals")
async def list_signals(
    request: Request,
    workspace_id: str = Query(...),
    signal_names: str | None = Query(None, description="Comma-separated signal names"),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    require_workspace_access(workspace_id, auth)
    p = _principal(auth, workspace_id)
    _authz_check(p, "nexus.signal.read", workspace_id)
    from app.modules.graph.cache import create_cache
    from app.modules.graph.context_engine import (
        OperationalStateEngine,
        SqlOperationalStateRepository,
        create_context_cache,
    )
    from app.modules.graph.feature_engine import FeatureEngine
    from app.modules.graph.repository import SqlGraphRepository
    from app.modules.graph.service import GraphService
    from app.modules.graph.signal_engine import SignalEngine

    repo = SqlGraphRepository(session)
    service = GraphService(repo)
    feature_engine = FeatureEngine(service, create_cache())
    context_engine = OperationalStateEngine(
        SqlOperationalStateRepository(session, create_context_cache()),
        context_cache=create_context_cache(),
    )
    signal_engine = SignalEngine(feature_engine, context_engine)

    signals_to_compute = signal_names.split(",") if signal_names else None
    result = await signal_engine.detect_signals(workspace_id, signal_names=signals_to_compute)
    ss = result.snapshot
    signals = [
        {
            "signal_id": sig.signal_id,
            "signal_name": sig.signal_name,
            "signal_version": sig.signal_version,
            "workspace_id": sig.workspace_id,
            "snapshot_version": sig.snapshot_version,
            "snapshot_hash": sig.snapshot_hash,
            "severity": sig.severity.value,
            "confidence": sig.confidence,
            "category": sig.category.value,
            "affected_node_ids": sig.affected_node_ids,
            "affected_entity_types": sig.affected_entity_types,
            "affected_entity_ids": sig.affected_entity_ids,
            "propagation_scope": sig.propagation_scope,
            "feature_evidence": sig.feature_evidence,
            "explanation": sig.explanation,
            "created_at": sig.created_at.isoformat(),
        }
        for sig in ss.signals
        if sig.confidence >= min_confidence
    ]
    return _envelope(
        request,
        {
            "workspace_id": ss.workspace_id,
            "snapshot_version": ss.snapshot_version,
            "snapshot_hash": ss.snapshot_hash,
            "signals": signals,
            "count": len(signals),
            "metadata": ss.metadata,
        },
    )


# ─────────────────────────────────────────────────────────────────────
# /scenarios — create / list / get / simulate (v0.8.5-B3)
# ─────────────────────────────────────────────────────────────────────


class ScenarioCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    name: str
    world_state_version: int
    description: str = ""
    decision_id: str | None = None
    parent_scenario_id: str | None = None
    is_baseline: bool = False
    mutations: list[dict[str, Any]] = Field(default_factory=list)


class ScenarioSimulateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    entities: list[Entity] = Field(default_factory=list)
    world_state_version: int = 0


@router.post("/scenarios", status_code=201)
async def create_scenario(
    body: ScenarioCreateRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    require_workspace_access(body.workspace_id, auth)
    p = _principal(auth, body.workspace_id)
    _authz_check(p, "nexus.scenario.create", body.workspace_id)
    svc = get_authoritative_registry_service()
    try:
        result = await svc.create_scenario(
            session,
            tenant_id=p.tenant_id,
            workspace_id=body.workspace_id,
            name=body.name,
            world_state_version=body.world_state_version,
            description=body.description,
            decision_id=body.decision_id,
            parent_scenario_id=body.parent_scenario_id,
            is_baseline=body.is_baseline,
            mutations=body.mutations,
        )
        await commit_and_notify(session)
    except RegistryValidationError as e:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _envelope(request, {"scenario": result})


@router.get("/scenarios")
async def list_scenarios(
    request: Request,
    workspace_id: str = Query(...),
    decision_id: str | None = Query(None),
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    require_workspace_access(workspace_id, auth)
    p = _principal(auth, workspace_id)
    _authz_check(p, "nexus.scenario.read", workspace_id)
    svc = get_authoritative_registry_service()
    scenarios = await svc.list_scenarios(
        session,
        tenant_id=p.tenant_id,
        workspace_id=workspace_id,
        decision_id=decision_id,
    )
    return _envelope(request, {"scenarios": scenarios, "count": len(scenarios)})


@router.get("/scenarios/{scenario_id}")
async def get_scenario(
    scenario_id: str,
    request: Request,
    workspace_id: str = Query(...),
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    require_workspace_access(workspace_id, auth)
    p = _principal(auth, workspace_id)
    _authz_check(p, "nexus.scenario.read", workspace_id)
    svc = get_authoritative_registry_service()
    try:
        scenario = await svc.get_scenario(session, scenario_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="scenario not found") from None
    if scenario["workspace_id"] != workspace_id or scenario["tenant_id"] != p.tenant_id:
        raise HTTPException(status_code=404, detail="scenario not found")
    return _envelope(request, {"scenario": scenario})


@router.post("/scenarios/{scenario_id}/simulate")
async def simulate_scenario(
    scenario_id: str,
    body: ScenarioSimulateRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Run the stored scenario against the caller-supplied entity snapshot."""
    require_workspace_access(body.workspace_id, auth)
    p = _principal(auth, body.workspace_id)
    _authz_check(p, "nexus.scenario.simulate", body.workspace_id)
    svc = get_authoritative_registry_service()
    try:
        scenario = await svc.get_scenario(session, scenario_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="scenario not found") from None
    if scenario["workspace_id"] != body.workspace_id or scenario["tenant_id"] != p.tenant_id:
        raise HTTPException(status_code=404, detail="scenario not found")
    try:
        outcome = await svc.simulate_scenario(
            session,
            scenario_id,
            body.entities,
            world_state_version=body.world_state_version,
        )
        await commit_and_notify(session)
    except RegistryValidationError as e:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _envelope(request, outcome)


# ─────────────────────────────────────────────────────────────────────
# /decisions/{id}/evidence + /approvals (v0.8.5-B3)
#
# Decision-scoped: the workspace is derived from the decision (same routing
# pattern as advance()). Manual appends emit EVIDENCE_APPENDED; lifecycle
# transitions additionally self-append approval/execution/outcome nodes.
# ─────────────────────────────────────────────────────────────────────


class EvidenceNodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_type: (
        str  # observation|signal|forecast|risk|scenario|decision|approval|execution|outcome|claim
    )
    label: str
    payload: dict[str, Any] = Field(default_factory=dict)
    checksum: str | None = None
    source_entity_id: str | None = None


class EvidenceEdgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_node_id: str
    to_node_id: str
    relation: str  # supports|causes|informs|contradicts|proves|derived_from
    weight: float = 1.0


async def _decision_scope(
    session: AsyncSession, auth: AuthContext, decision_id: str, tool: str
) -> tuple[Principal, dict[str, Any]]:
    """Resolve (principal, decision) for decision-scoped endpoints."""
    svc = get_authoritative_decision_service()
    dec = await svc.get(session, decision_id=decision_id)
    if dec is None:
        raise HTTPException(status_code=404, detail="decision not found")
    require_workspace_access(dec["workspace_id"], auth)
    p = _principal(auth, dec["workspace_id"])
    _authz_check(p, tool, dec["workspace_id"])
    if dec["tenant_id"] != p.tenant_id:
        raise HTTPException(status_code=404, detail="decision not found")
    return p, dec


@router.post("/decisions/{decision_id}/evidence/nodes", status_code=201)
async def append_evidence_node(
    decision_id: str,
    body: EvidenceNodeRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    _p, dec = await _decision_scope(session, auth, decision_id, "nexus.evidence.append")
    svc = get_authoritative_registry_service()
    try:
        node = await svc.append_evidence_node(
            session,
            tenant_id=dec["tenant_id"],
            workspace_id=dec["workspace_id"],
            decision_id=decision_id,
            node_type=body.node_type,
            label=body.label,
            payload=body.payload,
            checksum=body.checksum,
            source_entity_id=body.source_entity_id,
        )
        await commit_and_notify(session)
    except RegistryValidationError as e:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _envelope(request, {"node": node})


@router.post("/decisions/{decision_id}/evidence/edges", status_code=201)
async def append_evidence_edge(
    decision_id: str,
    body: EvidenceEdgeRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    _p, dec = await _decision_scope(session, auth, decision_id, "nexus.evidence.append")
    svc = get_authoritative_registry_service()
    try:
        edge = await svc.append_evidence_edge(
            session,
            tenant_id=dec["tenant_id"],
            workspace_id=dec["workspace_id"],
            decision_id=decision_id,
            from_node_id=body.from_node_id,
            to_node_id=body.to_node_id,
            relation=body.relation,
            weight=body.weight,
        )
        await commit_and_notify(session)
    except RegistryConflictError as e:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(e)) from e
    except RegistryValidationError as e:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(e)) from e
    return _envelope(request, {"edge": edge})


@router.get("/decisions/{decision_id}/evidence")
async def get_evidence_graph(
    decision_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    await _decision_scope(session, auth, decision_id, "nexus.evidence.read")
    svc = get_authoritative_registry_service()
    graph = await svc.get_evidence_graph(session, decision_id)
    graph["node_count"] = len(graph["nodes"])
    graph["edge_count"] = len(graph["edges"])
    return _envelope(request, graph)


@router.get("/decisions/{decision_id}/approvals")
async def list_approvals(
    decision_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    await _decision_scope(session, auth, decision_id, "nexus.approval.read")
    svc = get_authoritative_registry_service()
    approvals = await svc.list_approvals(session, decision_id)
    return _envelope(
        request, {"decision_id": decision_id, "approvals": approvals, "count": len(approvals)}
    )


# ─────────────────────────────────────────────────────────────────────
# /realtime — durable replay, live SSE, relay health (v0.8.5-B4)
#
# The realtime contract (single envelope everywhere — HTTP replay, SSE,
# WebSocket):
#     {event_id, seq, type, entity_type, entity_id, payload,
#      world_state_version, correlation_id, timestamp}
#   * event_id = identity (idempotency key; at-least-once safe)
#   * seq      = per-workspace order (PG-allocated, never reinvented)
#   * world_state_version = authoritative state version for reconciliation
#
# AuthZ boundaries (each enforced independently; 403 never logs out):
#   connect (stream) / subscribe (WS) / replay (events) / resync (snapshot).
# ─────────────────────────────────────────────────────────────────────


def _outbox_row_to_wire(row: Any) -> dict[str, Any]:
    """Render an EventRecordDB row in the canonical realtime envelope."""
    created = getattr(row, "created_at", None)
    return {
        "event_id": row.event_id,
        "seq": row.seq,
        "type": row.event_type,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "payload": row.payload or {},
        "world_state_version": row.world_state_version,
        "correlation_id": row.correlation_id,
        "timestamp": created.isoformat() if created is not None else None,
    }


async def _resolve_stream_identity(
    request: Request,
    token: str | None,
    workspace_id: str,
) -> tuple[AuthContext, str, str]:
    """Resolve (auth, workspace_id, tenant_id) for the SSE handshake.

    Mirrors the WebSocket handshake (``_resolve_ws_identity``): EventSource
    cannot set headers, so a ``?token=`` JWT is accepted. A PRESENTED token
    must verify (fail-closed 401); the workspace is taken from verified
    claims — the query value is never trusted when a token is present.
    Without a token, the standard header/strict identity applies and the
    query workspace must be authorized (403 otherwise — which never
    destroys the caller's session).
    """
    settings = get_settings()
    if token:
        if not settings.jwt_secret:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token verification is not configured",
                headers={"WWW-Authenticate": "Bearer"},
            )
        from app.modules.identity.jwt_auth import verify_token

        try:
            claims = verify_token(token, settings)
        except PermissionError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(exc),
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
        user_id = claims.get("sub")
        verified_ws = claims.get("workspace_id")
        if not isinstance(user_id, str) or not isinstance(verified_ws, str):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has no identity/workspace claims",
                headers={"WWW-Authenticate": "Bearer"},
            )
        roles = claims.get("roles", [])
        # Server decides: the authorized workspace comes from verified
        # claims; the query value is never trusted when a token is present.
        auth = AuthContext(
            user_id=user_id,
            email=str(claims.get("email") or "") or None,
            roles=[str(r) for r in roles] if isinstance(roles, list) else [],
            workspace_ids=[verified_ws],
            is_anonymous=False,
        )
        principal = _principal(auth, verified_ws)
        _authz_check(principal, "nexus.realtime.read", verified_ws)
        return auth, verified_ws, principal.tenant_id

    auth = await get_current_user(request)
    require_workspace_access(workspace_id, auth)
    principal = _principal(auth, workspace_id)
    _authz_check(principal, "nexus.realtime.read", workspace_id)
    return auth, workspace_id, principal.tenant_id


@router.get("/realtime/events")
async def realtime_events(
    request: Request,
    workspace_id: str = Query(...),
    after_seq: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=5000),
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Durable replay: events for a workspace with ``seq > after_seq``.

    Returns the reconciliation envelope ``{events, from_seq, to_seq,
    latest_seq, world_state_version, has_more, resync_required}``. When the
    gap exceeds ``CORTEX_REALTIME_RESYNC_THRESHOLD`` the server refuses the
    page-by-page replay (``resync_required=true``) and the client must take
    an authoritative snapshot instead.
    """
    from app.infrastructure import metrics as _metrics
    from app.modules.nexus_spine.persistence.repositories import get_event_repository

    require_workspace_access(workspace_id, auth)
    principal = _principal(auth, workspace_id)
    _authz_check(principal, "nexus.realtime.read", workspace_id)

    settings = get_settings()
    repo = get_event_repository()
    latest_seq, latest_wsv = await repo.get_head(
        session, tenant_id=principal.tenant_id, workspace_id=workspace_id
    )
    if latest_seq - after_seq > settings.realtime_resync_threshold:
        _metrics.realtime_resync_total.labels(transport="http").inc()
        return _envelope(
            request,
            {
                "events": [],
                "from_seq": after_seq,
                "to_seq": after_seq,
                "latest_seq": latest_seq,
                "world_state_version": latest_wsv,
                "has_more": True,
                "resync_required": True,
            },
        )

    rows = await repo.get_since_seq(
        session,
        workspace_id=workspace_id,
        since_seq=after_seq,
        tenant_id=principal.tenant_id,
        limit=min(limit, settings.realtime_replay_limit),
    )
    events = [_outbox_row_to_wire(r) for r in rows]
    to_seq = events[-1]["seq"] if events else after_seq
    _metrics.realtime_replay_total.labels(transport="http").inc()
    return _envelope(
        request,
        {
            "events": events,
            "from_seq": after_seq,
            "to_seq": to_seq,
            "latest_seq": latest_seq,
            "world_state_version": latest_wsv,
            "has_more": to_seq < latest_seq,
            "resync_required": False,
        },
    )


@router.get("/realtime/stream")
async def realtime_stream(
    request: Request,
    workspace_id: str = Query(...),
    after_seq: int = Query(default=0, ge=0),
    token: str | None = Query(default=None),
) -> StreamingResponse:
    """Live SSE: ``connected`` → durable catch-up → live tail with gap gate.

    Identity resolves BEFORE the first byte: 401/403 surface as JSON, never
    as a 200 stream. Reconnects pass the last confirmed ``after_seq`` and
    receive exactly the missed events before the live tail resumes. A
    ``resync_needed`` frame means the client must replay-or-resnapshot.
    """
    _, authorized_ws, tenant_id = await _resolve_stream_identity(request, token, workspace_id)
    settings = get_settings()
    gen = sse_stream(
        workspace_id=authorized_ws,
        last_seen_seq=after_seq,
        session_factory=get_session_factory(),
        tenant_id=tenant_id,
        heartbeat_s=settings.realtime_sse_heartbeat_s,
        replay_limit=settings.realtime_replay_limit,
    )
    return StreamingResponse(
        gen,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/realtime/health")
async def realtime_health(
    request: Request,
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Operational relay health: API/DB/Redis/Outbox/Worker.

    Aggregate-only (no tenant/workspace data). ``/readyz`` stays the K8s
    traffic gate; this endpoint is the on-call truth for the relay: a dead
    relay with a growing backlog reads BACKLOGGING/DEGRADED here instead of
    hiding behind a green ``/healthz``.
    """
    stats = await get_backlog_stats(session)

    try:
        from app.infrastructure.cache_manager import get_cache_manager

        redis_ok = await get_cache_manager().is_redis_available()
    except Exception:  # noqa: BLE001 — probe failure IS the signal
        redis_ok = False

    pub = current_outbox_publisher()
    if pub is None:
        worker_status, worker_detail = "UNKNOWN", "no publisher in this process"
        heartbeat: dict[str, Any] | None = None
    else:
        heartbeat = pub.heartbeat()
        last = pub.last_sweep_at
        stale_after = max(3.0 * pub.sweep_interval, 5.0)
        if last is not None and last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        age = (datetime.now(UTC) - last).total_seconds() if last else None
        if not pub.running:
            worker_status, worker_detail = "DEGRADED", "publisher stopped"
        elif pub.last_sweep_error:
            worker_status, worker_detail = "DEGRADED", pub.last_sweep_error[:200]
        elif age is not None and age > stale_after:
            worker_status, worker_detail = "DEGRADED", f"last sweep {age:.0f}s ago"
        else:
            worker_status, worker_detail = "HEALTHY", "sweeping"

    pending = stats.pending_count
    oldest_age = stats.oldest_pending_age_s
    # A fleeting row between commit and fast-path delivery is not an outage;
    # a backlog older than a few sweep intervals is.
    if pending == 0 or (oldest_age is not None and oldest_age <= 5.0):
        outbox_status = "HEALTHY"
    else:
        outbox_status = "BACKLOGGING"

    return _envelope(
        request,
        {
            "api": {"status": "HEALTHY"},
            "db": {"status": "HEALTHY"},
            "redis": {
                "status": "HEALTHY" if redis_ok else "DEGRADED",
                "detail": "reachable" if redis_ok else "unreachable",
            },
            "outbox": {
                "status": outbox_status,
                "pending_count": pending,
                "oldest_pending_age_s": oldest_age,
            },
            "worker": {
                "status": worker_status,
                "detail": worker_detail,
                "heartbeat": heartbeat,
            },
        },
    )


__all__ = ["router"]
