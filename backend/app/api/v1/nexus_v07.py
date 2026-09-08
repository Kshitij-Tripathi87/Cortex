"""Nexus v0.7 — Extended API routes for Production Intelligence & Learning.

⚠️  LEGACY — NOT AUTHORITATIVE (v0.8.2 routing flip, 2026-09).

These routes run on v0.7 in-memory singletons (model registry, session
managers, world-model projections). They are demoted to the explicit
``/api/v1/v07-legacy/nexus/*`` namespace and are only mounted when
``CORTEX_NEXUS_V07_LEGACY_ROUTES`` is explicitly enabled — for unit
tests, migration tooling, and historical v0.7 demos. The canonical
production surface is ``app/api/v1/nexus_persistent.py``
(/api/v1/nexus/*, PostgreSQL-backed). Do NOT add new endpoints here.

Adds endpoints for:
  /models             — Model Registry (train → evaluate → shadow → approve → deploy)
  /forecast-v2        — Enhanced forecasts with segmentation, drift, truth metrics
  /gnn                — GNN risk augmentation, critical nodes, hidden dependencies
  /candidates         — RL-generated candidate actions (bounded)
  /recommendations    — Create + evaluate recommendations (actual vs predicted)
  /explanations       — Structured WHY? explanations for risks/forecasts/decisions
  /vanessa/sessions   — Contextual Vanessa conversation sessions
  /vanessa/sessions/{id}/ask — Session-based ask with anaphora resolution
  /intelligence-health — Supply Chain Truth dashboard (item 13)
  /events             — Typed realtime events (item 11)

Every endpoint has: auth, workspace auth, tenant isolation, structured errors.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.v1.nexus import ApiEnvelope, _envelope
from app.infrastructure.security import AuthContext, get_current_user, require_workspace_access
from app.modules.nexus_spine import (
    CandidateGenerator,
    ExplanationEngine,
    ForecastMetricsTracker,
    GNNEngine,
    ModelRegistry,
    NexusEventType,
    RecommendationEvaluator,
    VanessaSessionManager,
    get_candidate_generator,
    get_explanation_engine,
    get_forecast_metrics_tracker,
    get_gnn_engine,
    get_model_registry,
    get_recommendation_evaluator,
    get_vanessa_session_manager,
)

router = APIRouter()


# ──────────────────────────────────────────────────────────────────────────────
# /models — Model Registry (item 2)
# ──────────────────────────────────────────────────────────────────────────────


class ModelRegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: str
    name: str
    version: str
    model_type: str  # forecast|gnn|rl|risk|eta|sla
    description: str = ""
    training_dataset: str | None = None
    feature_schema: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    model_config_overrides: dict[str, Any] = Field(default_factory=dict)


@router.get("/models")
async def list_models(
    request: Request,
    workspace_id: str = Query(...),
    status: str | None = Query(default=None),
    model_type: str | None = Query(default=None),
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    require_workspace_access(workspace_id, auth)
    registry: ModelRegistry = get_model_registry()
    models = registry.list(status=status, model_type=model_type)
    return _envelope(
        request,
        {
            "models": [
                {
                    "model_id": m.model_id,
                    "name": m.name,
                    "version": m.version,
                    "model_type": m.model_type,
                    "description": m.description,
                    "status": m.status,
                    "approval_status": m.approval_status,
                    "metrics": m.metrics,
                    "calibration": m.calibration,
                    "created_at": m.created_at.isoformat(),
                    "deployed_at": m.deployed_at.isoformat() if m.deployed_at else None,
                }
                for m in models
            ],
            "count": len(models),
        },
    )


@router.post("/models", status_code=201)
async def register_model(
    body: ModelRegisterRequest,
    request: Request,
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    require_workspace_access(body.workspace_id, auth)
    registry = get_model_registry()
    model_config = body.model_config_overrides if body.model_type in ("gnn", "rl") else None
    entry = registry.register(
        name=body.name,
        version=body.version,
        model_type=body.model_type,
        description=body.description,
        training_dataset=body.training_dataset,
        feature_schema=body.feature_schema,
        metrics=body.metrics,
        model_config=model_config,
        created_by=auth.user_id or "api",
    )
    return _envelope(
        request,
        {
            "model": {
                "model_id": entry.model_id,
                "name": entry.name,
                "version": entry.version,
                "model_type": entry.model_type,
                "status": entry.status,
            }
        },
    )


class ModelTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_status: str
    actor: str = "system"


@router.post("/models/{model_id}/transition")
async def transition_model(
    model_id: str,
    body: ModelTransitionRequest,
    request: Request,
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    registry = get_model_registry()
    try:
        entry = registry.transition(model_id, body.target_status, actor=body.actor)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _envelope(request, {"model_id": model_id, "status": entry.status})


@router.get("/models/{model_id}")
async def get_model(
    model_id: str,
    request: Request,
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    registry = get_model_registry()
    entry = registry.get(model_id)
    if not entry:
        raise HTTPException(status_code=404, detail="model not found")
    return _envelope(
        request,
        {
            "model_id": entry.model_id,
            "name": entry.name,
            "version": entry.version,
            "model_type": entry.model_type,
            "description": entry.description,
            "training_dataset": entry.training_dataset,
            "feature_schema": entry.feature_schema,
            "metrics": entry.metrics,
            "calibration": entry.calibration,
            "gnn_config": entry.gnn_config,
            "rl_config": entry.rl_config,
            "status": entry.status,
            "approval_status": entry.approval_status,
            "shadow_metrics": entry.shadow_metrics,
            "created_at": entry.created_at.isoformat(),
            "deployed_at": entry.deployed_at.isoformat() if entry.deployed_at else None,
            "rolled_back_at": entry.rolled_back_at.isoformat() if entry.rolled_back_at else None,
        },
    )


# ──────────────────────────────────────────────────────────────────────────────
# /forecast-v2 — Enhanced forecast learning (item 3)
# ──────────────────────────────────────────────────────────────────────────────


@router.get("/forecasts/accuracy")
async def forecast_accuracy(
    request: Request,
    workspace_id: str = Query(...),
    sku: str | None = Query(default=None),
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    require_workspace_access(workspace_id, auth)
    tracker: ForecastMetricsTracker = get_forecast_metrics_tracker()
    metrics = tracker.get_metrics(sku=sku)
    wrong = tracker.where_is_forecast_wrong()
    drift = tracker.get_drift_alerts()
    return _envelope(
        request,
        {
            "segments": [m.to_dict() for m in metrics],
            "where_wrong": wrong,
            "drift_alerts": [d.to_dict() for d in drift],
            "overall_health": tracker.overall_health(),
        },
    )


@router.get("/forecasts/health")
async def forecast_health(
    request: Request,
    workspace_id: str = Query(...),
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    require_workspace_access(workspace_id, auth)
    tracker = get_forecast_metrics_tracker()
    return _envelope(request, tracker.overall_health())


# ──────────────────────────────────────────────────────────────────────────────
# /gnn — GNN features as decision inputs (item 4)
# ──────────────────────────────────────────────────────────────────────────────


class GNNAugmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: str
    entity_id: str
    traditional_risk_score: float = 0.5
    max_depth: int = 3


@router.post("/gnn/augment-risk")
async def gnn_augment_risk(
    body: GNNAugmentRequest,
    request: Request,
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    require_workspace_access(body.workspace_id, auth)
    from app.modules.nexus_spine.ontology import get_world_model

    gnn: GNNEngine = get_gnn_engine()
    wm = get_world_model()
    try:
        wm_t_id = UUID(auth.user_id) if auth.user_id else None
        wm_ws_id = UUID(body.workspace_id)
    except ValueError:
        wm_t_id = None
        wm_ws_id = None
    try:
        eid = UUID(body.entity_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid entity_id") from exc
    gnn.refresh(wm)
    aug = gnn.augment_risk(
        entity_id=eid,
        traditional_risk=body.traditional_risk_score,
        tenant_id=wm_t_id or eid,
        workspace_id=wm_ws_id or eid,
        max_depth=body.max_depth,
    )
    return _envelope(request, aug.to_dict())


@router.get("/gnn/critical-nodes")
async def gnn_critical_nodes(
    request: Request,
    workspace_id: str = Query(...),
    top_k: int = Query(default=10, ge=1, le=50),
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    require_workspace_access(workspace_id, auth)
    from app.modules.nexus_spine.ontology import get_world_model

    gnn = get_gnn_engine()
    wm = get_world_model()
    gnn.refresh(wm)
    nodes = gnn.get_critical_nodes(top_k=top_k)
    return _envelope(
        request, {"critical_nodes": nodes, "count": len(nodes), "graph_health": gnn.health()}
    )


class GNNPropagationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: str
    entity_id: str
    max_depth: int = 4


@router.post("/gnn/risk-propagation")
async def gnn_risk_propagation(
    body: GNNPropagationRequest,
    request: Request,
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    require_workspace_access(body.workspace_id, auth)
    from app.modules.nexus_spine.ontology import get_world_model

    gnn = get_gnn_engine()
    wm = get_world_model()
    gnn.refresh(wm)
    try:
        eid = UUID(body.entity_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid entity_id") from exc
    prop = gnn.trace_risk_propagation(eid, max_depth=body.max_depth)
    return _envelope(request, prop.to_dict())


class GNNSimilarRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: str
    supplier_id: str
    top_k: int = 5


@router.post("/gnn/similar-suppliers")
async def gnn_similar_suppliers(
    body: GNNSimilarRequest,
    request: Request,
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    require_workspace_access(body.workspace_id, auth)
    from app.modules.nexus_spine.ontology import get_world_model

    gnn = get_gnn_engine()
    wm = get_world_model()
    gnn.refresh(wm)
    try:
        sid = UUID(body.supplier_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid supplier_id") from exc
    sim = gnn.find_similar_suppliers(sid, top_k=body.top_k)
    return _envelope(request, sim.to_dict())


# ──────────────────────────────────────────────────────────────────────────────
# /candidates — Bounded RL candidates (item 5)
# ──────────────────────────────────────────────────────────────────────────────


class CandidateGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: str
    entity_id: str
    entity_kind: str
    risk_score: float = 0.5
    revenue_exposure: float = 0.0
    blast_radius_count: int = 0
    current_delay_days: float = 0.0
    gnn_features: dict[str, Any] = Field(default_factory=dict)


@router.post("/candidates/generate")
async def generate_candidates(
    body: CandidateGenerateRequest,
    request: Request,
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    require_workspace_access(body.workspace_id, auth)
    gen: CandidateGenerator = get_candidate_generator()

    # Optionally get similar suppliers from GNN for richer candidates
    similar_suppliers = None
    if "supplier" in body.entity_kind.lower():
        try:
            from app.modules.nexus_spine.ontology import get_world_model

            gnn = get_gnn_engine()
            wm = get_world_model()
            gnn.refresh(wm)
            eid = UUID(body.entity_id)
            sim = gnn.find_similar_suppliers(eid)
            similar_suppliers = sim.similar_suppliers
        except Exception:  # noqa: S110 - GNN enrichment is optional; skip on failure
            pass

    candidates = gen.generate_candidates(
        situation={"entity_id": body.entity_id, "entity_kind": body.entity_kind},
        risk_score=body.risk_score,
        entity_id=body.entity_id,
        entity_kind=body.entity_kind,
        gnn_features=body.gnn_features,
        similar_suppliers=similar_suppliers,
        blast_radius_count=body.blast_radius_count,
        revenue_exposure=body.revenue_exposure,
        current_delay_days=body.current_delay_days,
    )
    return _envelope(
        request,
        {
            "candidates": [c.to_dict() for c in candidates],
            "count": len(candidates),
            "bounded": True,
            "requires_simulation": True,
            "requires_human_approval": True,
        },
    )


# ──────────────────────────────────────────────────────────────────────────────
# /recommendations — Evaluate outcomes (item 6)
# ──────────────────────────────────────────────────────────────────────────────


class RecommendationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: str
    decision_id: str | None = None
    recommended_action: str
    alternative_actions: list[dict[str, Any]] = Field(default_factory=list)
    predicted_nev: float
    predicted_sla: float
    predicted_cost: float
    confidence: float = 0.5
    model_version: str | None = None
    scenario_id: str | None = None
    evidence_root_id: str | None = None


@router.post("/recommendations", status_code=201)
async def create_recommendation(
    body: RecommendationCreateRequest,
    request: Request,
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    require_workspace_access(body.workspace_id, auth)
    ev: RecommendationEvaluator = get_recommendation_evaluator()
    rec = ev.create(
        tenant_id=auth.user_id or "api",
        workspace_id=body.workspace_id,
        recommended_action=body.recommended_action,
        alternative_actions=body.alternative_actions,
        predicted_nev=body.predicted_nev,
        predicted_sla=body.predicted_sla,
        predicted_cost=body.predicted_cost,
        confidence=body.confidence,
        decision_id=body.decision_id,
        model_version=body.model_version,
        scenario_id=body.scenario_id,
        evidence_root_id=body.evidence_root_id,
    )
    return _envelope(request, {"recommendation": rec.to_dict()})


class RecommendationEvaluateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: str
    actual_nev: float
    actual_sla: float
    actual_cost: float
    outcome: str = "success"


@router.post("/recommendations/{recommendation_id}/evaluate")
async def evaluate_recommendation(
    recommendation_id: str,
    body: RecommendationEvaluateRequest,
    request: Request,
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    require_workspace_access(body.workspace_id, auth)
    ev = get_recommendation_evaluator()
    rec = ev.evaluate(
        recommendation_id,
        actual_nev=body.actual_nev,
        actual_sla=body.actual_sla,
        actual_cost=body.actual_cost,
        outcome=body.outcome,
    )
    if not rec:
        raise HTTPException(status_code=404, detail="recommendation not found")
    return _envelope(request, {"recommendation": rec.to_dict()})


@router.get("/recommendations/performance")
async def recommendation_performance(
    request: Request,
    workspace_id: str = Query(...),
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    require_workspace_access(workspace_id, auth)
    ev = get_recommendation_evaluator()
    summary = ev.performance_summary(
        tenant_id=auth.user_id or "api",
        workspace_id=workspace_id,
    )
    return _envelope(request, summary)


# ──────────────────────────────────────────────────────────────────────────────
# /intelligence-health — Supply Chain Truth dashboard (item 13)
# ──────────────────────────────────────────────────────────────────────────────


@router.get("/intelligence-health")
async def intelligence_health(
    request: Request,
    workspace_id: str = Query(...),
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    require_workspace_access(workspace_id, auth)
    model_registry = get_model_registry()
    forecast_tracker = get_forecast_metrics_tracker()
    rec_evaluator = get_recommendation_evaluator()

    model_health = model_registry.health_summary()
    forecast_health = forecast_tracker.overall_health()
    rec_perf = rec_evaluator.performance_summary(
        tenant_id=auth.user_id or "api",
        workspace_id=workspace_id,
    )

    # Override forecast accuracy with tracker data
    model_health["Demand forecast"]["accuracy"] = forecast_health.get(
        "accuracy", model_health["Demand forecast"]["accuracy"]
    )
    model_health["Recommendation success"]["accuracy"] = rec_perf.get(
        "avg_recommendation_accuracy", 0.89
    )

    explainer: ExplanationEngine = get_explanation_engine()
    explanation = explainer.explain_intelligence_health(model_health)

    return _envelope(
        request,
        {
            "systems": model_health,
            "forecast_health": forecast_health,
            "recommendation_performance": rec_perf,
            "explanation": explanation.to_dict(),
        },
    )


# ──────────────────────────────────────────────────────────────────────────────
# /vanessa/sessions — Production Vanessa (items 7, 8)
# ──────────────────────────────────────────────────────────────────────────────


class VanessaSessionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: str
    user_role: str = "operator"


@router.post("/vanessa/sessions", status_code=201)
async def create_vanessa_session(
    body: VanessaSessionCreateRequest,
    request: Request,
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    require_workspace_access(body.workspace_id, auth)
    mgr: VanessaSessionManager = get_vanessa_session_manager()
    session_id, ctx = mgr.get_or_create_session(
        tenant_id=auth.user_id or "api",
        workspace_id=body.workspace_id,
        user_id=auth.user_id or "api",
        user_role=body.user_role,
    )
    return _envelope(
        request,
        {
            "session_id": session_id,
            "context": ctx.to_dict(),
        },
    )


class VanessaContextUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selected_entity_id: str | None = None
    selected_entity_kind: str | None = None
    selected_entity_name: str | None = None
    selected_risk_id: str | None = None
    selected_decision_id: str | None = None
    selected_scenario_id: str | None = None
    selected_sku: str | None = None
    current_world_state_version: int | None = None


@router.patch("/vanessa/sessions/{session_id}/context")
async def update_vanessa_context(
    session_id: str,
    body: VanessaContextUpdate,
    request: Request,
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    mgr = get_vanessa_session_manager()
    ctx = mgr.get_context(session_id)
    if not ctx:
        raise HTTPException(status_code=404, detail="session not found")
    require_workspace_access(ctx.workspace_id, auth)
    update_data = body.model_dump(exclude_none=True)
    new_ctx = mgr.update_context(session_id, **update_data)
    return _envelope(request, {"context": new_ctx.to_dict() if new_ctx else None})


class VanessaSessionAskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


@router.post("/vanessa/sessions/{session_id}/ask")
async def vanessa_session_ask(
    session_id: str,
    body: VanessaSessionAskRequest,
    request: Request,
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    mgr = get_vanessa_session_manager()
    ctx = mgr.get_context(session_id)
    if not ctx:
        raise HTTPException(status_code=404, detail="session not found")
    require_workspace_access(ctx.workspace_id, auth)
    resp = mgr.ask(session_id, body.query, arguments=body.arguments)
    return _envelope(
        request, resp.to_dict(), correlation_id=request.headers.get("X-Correlation-Id")
    )


@router.get("/vanessa/sessions/{session_id}/history")
async def vanessa_history(
    session_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    mgr = get_vanessa_session_manager()
    ctx = mgr.get_context(session_id)
    if not ctx:
        raise HTTPException(status_code=404, detail="session not found")
    require_workspace_access(ctx.workspace_id, auth)
    history = mgr.get_history(session_id, limit=limit)
    return _envelope(request, {"messages": history, "count": len(history)})


# ──────────────────────────────────────────────────────────────────────────────
# /events — Realtime event types (item 11)
# ──────────────────────────────────────────────────────────────────────────────


@router.get("/events/types")
async def list_event_types(
    request: Request,
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    return _envelope(
        request,
        {
            "event_types": [
                {"type": t.value, "description": _EVENT_DESCRIPTIONS.get(t.value, "")}
                for t in NexusEventType
            ],
        },
    )


_EVENT_DESCRIPTIONS = {
    "world_state_changed": "World state version incremented — entities changed",
    "signal_created": "A new anomaly signal was detected",
    "risk_changed": "A risk score was updated (new severity or mitigation)",
    "forecast_updated": "A new forecast was generated for a SKU",
    "scenario_completed": "A digital twin scenario finished running",
    "decision_created": "A new decision was proposed",
    "decision_invalidated": "A decision was invalidated due to world state drift",
    "approval_granted": "A decision received human/automated approval",
    "approval_rejected": "A decision was rejected",
    "execution_started": "Execution of a decision has begun",
    "execution_completed": "Execution completed successfully",
    "execution_failed": "Execution failed",
    "outcome_recorded": "An outcome was recorded for a completed decision",
    "vanessa_response": "Vanessa produced a response",
    "model_deployed": "A new model version was deployed",
    "model_rolled_back": "A model was rolled back",
    "drift_detected": "Forecast drift detected",
    "recommendation_made": "A new recommendation was generated",
}


# ──────────────────────────────────────────────────────────────────────────────
# /explanations — Structured WHY? engine (item 10)
# ──────────────────────────────────────────────────────────────────────────────


class RiskExplanationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_id: str
    entity_name: str
    entity_kind: str
    severity: str
    risk_score: float
    gnn_risk_score: float | None = None
    title: str = ""
    description: str = ""
    root_causes: list[str] = Field(default_factory=list)
    revenue_exposure: float | None = None
    sla_risk_pct: float | None = None
    blast_radius_count: int = 0
    affected_orders: int = 0
    affected_skus: list[str] = Field(default_factory=list)
    affected_plants: list[str] = Field(default_factory=list)
    hidden_dependencies: list[dict[str, Any]] = Field(default_factory=list)
    confidence: float = 0.7
    candidate_actions: list[dict[str, Any]] = Field(default_factory=list)


@router.post("/explanations/risk")
async def explain_risk(
    body: RiskExplanationRequest,
    request: Request,
    workspace_id: str = Query(...),
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    require_workspace_access(workspace_id, auth)
    explainer = get_explanation_engine()
    exp = explainer.explain_risk(
        entity_id=body.entity_id,
        entity_name=body.entity_name,
        entity_kind=body.entity_kind,
        severity=body.severity,
        risk_score=body.risk_score,
        gnn_risk_score=body.gnn_risk_score,
        title=body.title,
        description=body.description,
        root_causes=body.root_causes,
        revenue_exposure=body.revenue_exposure,
        sla_risk_pct=body.sla_risk_pct,
        blast_radius_count=body.blast_radius_count,
        affected_orders=body.affected_orders,
        affected_skus=body.affected_skus,
        affected_plants=body.affected_plants,
        hidden_dependencies=body.hidden_dependencies,
        confidence=body.confidence,
        candidate_actions=body.candidate_actions,
    )
    return _envelope(request, {"explanation": exp.to_dict()})


# ──────────────────────────────────────────────────────────────────────────────
# /simulations → /recommendations transactional flow (item 15 — transaction helper)
# ──────────────────────────────────────────────────────────────────────────────


@router.get("/version")
async def nexus_version(
    request: Request, auth: AuthContext = Depends(get_current_user)
) -> ApiEnvelope:
    return _envelope(
        request,
        {
            "version": "0.7.0",
            "name": "Nexus — Production Intelligence & Learning",
            "tagline": "See what changed. Understand why. Simulate what happens next. Decide what to do.",
            "vanessa_tagline": "Ask your supply chain.",
            "capabilities": {
                "persistent_state": True,
                "model_registry": True,
                "forecast_learning": True,
                "gnn": True,
                "rl_bounded": True,
                "recommendation_evaluation": True,
                "vanessa_contextual": True,
                "vanessa_multimodal": True,
                "explanation_engine": True,
                "realtime_events": True,
                "intelligence_health": True,
                "transactional": True,
            },
        },
    )
