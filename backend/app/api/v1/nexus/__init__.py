"""Nexus Decision Intelligence API — Stable /v1/* Surface.

Stable API surface for the Nexus operational decision system:

  /v1/world                  - world state metadata (version, counts)
  /v1/entities               - CRUD + query against the world model
  /v1/graph                  - traversal / blast radius
  /v1/signals                - operational signal triage
  /v1/risks                  - computed risk registry (CRITICAL/HIGH/MEDIUM/LOW)
  /v1/forecasts              - probabilistic demand forecasts
  /v1/calibration            - forecast vs reality calibration
  /v1/decisions              - decision records + analogous retrieval
  /v1/governance             - decision lifecycle state machine (Phase G)
  /v1/scenarios              - Digital Twin scenario / counterfactual studio
  /v1/vanessa                - grounded natural-language interface
  /v1/realtime               - world-state change event stream

Every endpoint enforces:
  - authentication (JWT bearer or header identity)
  - workspace authorization
  - request_id + correlation_id for tracing
  - structured error envelopes
  - OpenAPI contract tests

Architecture: Ontology (WorldModel) → Risk Engine → Scenario Studio →
    → Decision Lifecycle → Approval → Execution → Outcome → Memory → Evidence
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.common.ids import uuid7
from app.infrastructure.security import (
    AuthContext,
    get_current_user,
    require_workspace_access,
)
from app.modules.nexus_spine.demand import get_demand_engine, get_truth_loop
from app.modules.nexus_spine.memory import (
    DecisionRecord,
    get_decision_memory,
)
from app.modules.nexus_spine.ontology import (
    Entity,
    EntityKind,
    EntityQuery,
    get_world_model,
)
from app.modules.nexus_spine.ontology.core_types import (
    EntityDomain,
    domain_of,
)
from app.modules.nexus_spine.governance import (
    ALLOWED_TRANSITIONS,
    DecisionLifecycle,
    DecisionLifecycleManager,
    DecisionPhase,
    get_decision_lifecycle_manager,
    validate_world_state_consistent,
)
from app.modules.nexus_spine.vanessa import (
    VanessaAnswer,
    VanessaOrchestrator,
    VanessaQuery,
    get_vanessa,
)

router = APIRouter()


# ──────────────────────────────────────────────────────────────────────────────
# Common envelope
# ──────────────────────────────────────────────────────────────────────────────


class ApiEnvelope(BaseModel):
    """Every response wraps its payload in this envelope so we can carry
    request_id + correlation_id + timestamp alongside the actual data."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    correlation_id: str | None = None
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    data: dict[str, Any]


def _envelope(request: Request, data: dict[str, Any], correlation_id: str | None = None) -> ApiEnvelope:
    request_id = getattr(request.state, "request_id", None) or uuid7()
    return ApiEnvelope(
        request_id=request_id,
        correlation_id=correlation_id,
        data=data,
    )


# ──────────────────────────────────────────────────────────────────────────────
# /v1/world
# ──────────────────────────────────────────────────────────────────────────────


@router.get("/world")
async def get_world_state(
    request: Request,
    workspace_id: str = Query(...),
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    require_workspace_access(workspace_id, auth)
    wm = get_world_model()
    tenant_id = auth.user_id or uuid7()
    try:
        ws_uuid = UUID(workspace_id)
        t_uuid = UUID(str(tenant_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid workspace_id")
    return _envelope(
        request,
        {
            "world_state_version": wm.world_state_version,
            "entity_counts": {
                kind.value: wm.count(t_uuid, ws_uuid, kind)
                for kind in EntityKind
            },
            "tenant_id": str(t_uuid),
            "workspace_id": workspace_id,
        },
    )


# ──────────────────────────────────────────────────────────────────────────────
# /v1/entities
# ──────────────────────────────────────────────────────────────────────────────


class EntityUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    natural_key: str
    name: str
    description: str = ""
    kind: str
    state: dict[str, Any] = Field(default_factory=dict)
    source: str = "api"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    tags: list[str] = Field(default_factory=list)


class EntityResponse(BaseModel):
    entity_id: str
    kind: str
    natural_key: str
    name: str
    description: str
    state: dict[str, Any]
    confidence: float
    tenant_id: str
    workspace_id: str
    updated_at: str
    provenance_steps: int


def _entity_to_response(e: Entity) -> EntityResponse:
    return EntityResponse(
        entity_id=str(e.entity_id),
        kind=e.kind.value,
        natural_key=e.natural_key,
        name=e.name,
        description=e.description,
        state=dict(e.state),
        confidence=e.confidence,
        tenant_id=str(e.tenant_id),
        workspace_id=str(e.workspace_id),
        updated_at=e.updated_at.isoformat(),
        provenance_steps=len(e.provenance),
    )


@router.post("/entities", status_code=201)
async def upsert_entity(
    body: EntityUpsertRequest,
    request: Request,
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    require_workspace_access(body.workspace_id, auth)
    try:
        ws_uuid = UUID(body.workspace_id)
        kind = EntityKind(body.kind)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid input: {exc}")
    try:
        t_uuid = UUID(auth.user_id) if auth.user_id else uuid7()
    except ValueError:
        t_uuid = uuid7()

    entity = Entity(
        tenant_id=t_uuid,
        workspace_id=ws_uuid,
        kind=kind,
        natural_key=body.natural_key,
        name=body.name,
        description=body.description,
        source=body.source,
        confidence=body.confidence,
        state=body.state,
        tags=body.tags,
    )
    saved, world_state_version = get_world_model().upsert(entity, actor=auth.user_id or "api")
    return _envelope(
        request,
        {"entity": _entity_to_response(saved).model_dump(), "world_state_version": world_state_version},
    )


@router.get("/entities")
async def query_entities(
    request: Request,
    workspace_id: str = Query(...),
    kinds: list[str] | None = Query(default=None),
    domain: str | None = Query(default=None),
    text_search: str | None = Query(default=None),
    min_confidence: float = Query(default=0.0, ge=0.0, le=1.0),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    require_workspace_access(workspace_id, auth)
    try:
        ws_uuid = UUID(workspace_id)
        t_uuid = UUID(auth.user_id) if auth.user_id else uuid7()
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid workspace_id")

    kind_enums = None
    if kinds:
        try:
            kind_enums = [EntityKind(k) for k in kinds]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"invalid kinds: {exc}")
    domain_enum = None
    if domain:
        try:
            domain_enum = EntityDomain(domain)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"invalid domain: {exc}")

    page = get_world_model().query(
        EntityQuery(
            tenant_id=t_uuid,
            workspace_id=ws_uuid,
            kinds=kind_enums,
            domain=domain_enum,
            text_search=text_search,
            min_confidence=min_confidence,
            limit=limit,
            offset=offset,
        )
    )
    return _envelope(
        request,
        {
            "items": [_entity_to_response(e).model_dump() for e in page.items],
            "total": page.total,
            "limit": page.limit,
            "offset": page.offset,
            "has_more": page.has_more,
        },
    )


@router.get("/entities/{entity_id}")
async def get_entity(
    entity_id: str,
    request: Request,
    workspace_id: str = Query(...),
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    require_workspace_access(workspace_id, auth)
    try:
        ws_uuid = UUID(workspace_id)
        t_uuid = UUID(auth.user_id) if auth.user_id else uuid7()
        e_uuid = UUID(entity_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid identifier")
    entity = get_world_model().get(t_uuid, ws_uuid, e_uuid)
    if entity is None:
        raise HTTPException(status_code=404, detail="entity not found")
    return _envelope(request, {"entity": _entity_to_response(entity).model_dump()})


# ──────────────────────────────────────────────────────────────────────────────
# /v1/graph
# ──────────────────────────────────────────────────────────────────────────────


class BlastRadiusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    seed_entity_id: str
    max_depth: int = Field(default=4, ge=1, le=6)


@router.post("/graph/blast-radius")
async def blast_radius(
    body: BlastRadiusRequest,
    request: Request,
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    require_workspace_access(body.workspace_id, auth)
    from app.modules.nexus_spine.vanessa.builtin_tools import GetBlastRadiusTool
    try:
        ws_uuid = UUID(body.workspace_id)
        t_uuid = UUID(auth.user_id) if auth.user_id else uuid7()
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid workspace_id")
    from app.modules.nexus_spine.vanessa.tools import ToolCall

    tool = GetBlastRadiusTool()
    call = ToolCall(
        tool_name=tool.name,
        arguments={
            "seed_entity_id": body.seed_entity_id,
            "max_depth": body.max_depth,
        },
        requester_role="analyst",
        requester_id=auth.user_id or "api",
        tenant_id=t_uuid,
        workspace_id=ws_uuid,
    )
    result = tool.invoke(call)
    if not result.ok:
        raise HTTPException(status_code=400, detail=result.error)
    return _envelope(request, result.payload, correlation_id=request.headers.get("X-Correlation-Id"))


class TraverseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    seed_entity_id: str
    max_depth: int = Field(default=3, ge=1, le=6)


@router.post("/graph/traverse")
async def traverse_graph(
    body: TraverseRequest,
    request: Request,
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    require_workspace_access(body.workspace_id, auth)
    from app.modules.nexus_spine.vanessa.builtin_tools import TraverseGraphTool
    try:
        ws_uuid = UUID(body.workspace_id)
        t_uuid = UUID(auth.user_id) if auth.user_id else uuid7()
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid workspace_id")
    from app.modules.nexus_spine.vanessa.tools import ToolCall

    tool = TraverseGraphTool()
    call = ToolCall(
        tool_name=tool.name,
        arguments={
            "seed_entity_id": body.seed_entity_id,
            "max_depth": body.max_depth,
        },
        requester_role="viewer",
        requester_id=auth.user_id or "api",
        tenant_id=t_uuid,
        workspace_id=ws_uuid,
    )
    result = tool.invoke(call)
    if not result.ok:
        raise HTTPException(status_code=400, detail=result.error)
    return _envelope(request, result.payload)


# ──────────────────────────────────────────────────────────────────────────────
# /v1/signals
# ──────────────────────────────────────────────────────────────────────────────


@router.get("/signals")
async def list_signals(
    request: Request,
    workspace_id: str = Query(...),
    entity_id: str | None = Query(default=None),
    min_severity: float = Query(default=0.0, ge=0.0, le=1.0),
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    require_workspace_access(workspace_id, auth)
    from app.modules.nexus_spine.vanessa.builtin_tools import GetSignalTool
    try:
        ws_uuid = UUID(workspace_id)
        t_uuid = UUID(auth.user_id) if auth.user_id else uuid7()
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid workspace_id")
    from app.modules.nexus_spine.vanessa.tools import ToolCall

    tool = GetSignalTool()
    call = ToolCall(
        tool_name=tool.name,
        arguments={"entity_id": entity_id, "min_severity": min_severity},
        requester_role="viewer",
        requester_id=auth.user_id or "api",
        tenant_id=t_uuid,
        workspace_id=ws_uuid,
    )
    result = tool.invoke(call)
    if not result.ok:
        raise HTTPException(status_code=400, detail=result.error)
    return _envelope(request, result.payload)


# ──────────────────────────────────────────────────────────────────────────────
# /v1/risks
# ──────────────────────────────────────────────────────────────────────────────


@router.get("/risks/suppliers")
async def supplier_risk(
    request: Request,
    workspace_id: str = Query(...),
    min_risk: float = Query(default=0.0, ge=0.0, le=1.0),
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    require_workspace_access(workspace_id, auth)
    from app.modules.nexus_spine.vanessa.builtin_tools import GetSupplierRiskTool
    try:
        ws_uuid = UUID(workspace_id)
        t_uuid = UUID(auth.user_id) if auth.user_id else uuid7()
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid workspace_id")
    from app.modules.nexus_spine.vanessa.tools import ToolCall

    tool = GetSupplierRiskTool()
    call = ToolCall(
        tool_name=tool.name,
        arguments={"min_risk": min_risk},
        requester_role="viewer",
        requester_id=auth.user_id or "api",
        tenant_id=t_uuid,
        workspace_id=ws_uuid,
    )
    result = tool.invoke(call)
    if not result.ok:
        raise HTTPException(status_code=400, detail=result.error)
    return _envelope(request, result.payload)


@router.get("/risks/orders-at-risk")
async def orders_at_risk(
    request: Request,
    workspace_id: str = Query(...),
    min_revenue: float = Query(default=0.0, ge=0.0),
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    require_workspace_access(workspace_id, auth)
    from app.modules.nexus_spine.vanessa.builtin_tools import GetOrdersAtRiskTool
    try:
        ws_uuid = UUID(workspace_id)
        t_uuid = UUID(auth.user_id) if auth.user_id else uuid7()
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid workspace_id")
    from app.modules.nexus_spine.vanessa.tools import ToolCall

    tool = GetOrdersAtRiskTool()
    call = ToolCall(
        tool_name=tool.name,
        arguments={"min_revenue": min_revenue},
        requester_role="viewer",
        requester_id=auth.user_id or "api",
        tenant_id=t_uuid,
        workspace_id=ws_uuid,
    )
    result = tool.invoke(call)
    if not result.ok:
        raise HTTPException(status_code=400, detail=result.error)
    return _envelope(request, result.payload)


# ──────────────────────────────────────────────────────────────────────────────
# /v1/forecasts
# ──────────────────────────────────────────────────────────────────────────────


class ForecastRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    sku: str
    horizon_days: int = Field(default=14, ge=1, le=365)


@router.post("/forecasts")
async def produce_forecast(
    body: ForecastRequest,
    request: Request,
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    require_workspace_access(body.workspace_id, auth)
    from app.modules.nexus_spine.vanessa.builtin_tools import GetForecastTool
    try:
        ws_uuid = UUID(body.workspace_id)
        t_uuid = UUID(auth.user_id) if auth.user_id else uuid7()
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid workspace_id")
    from app.modules.nexus_spine.vanessa.tools import ToolCall

    tool = GetForecastTool()
    call = ToolCall(
        tool_name=tool.name,
        arguments={"sku": body.sku, "horizon_days": body.horizon_days},
        requester_role="viewer",
        requester_id=auth.user_id or "api",
        tenant_id=t_uuid,
        workspace_id=ws_uuid,
    )
    result = tool.invoke(call)
    if not result.ok:
        raise HTTPException(status_code=400, detail=result.error)
    return _envelope(request, result.payload)


class ForecastActualRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    forecast_id: str
    sku: str
    horizon_days: int = Field(default=14, ge=1)
    observed_at: datetime
    actual_quantity: float


@router.post("/forecasts/observe")
async def observe_forecast(
    body: ForecastActualRequest,
    request: Request,
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    """Record an actual demand observation against a forecast.

    Closes the truth loop — returns the evaluation (absolute error,
    percentage error, P80/P95 coverage) and updates calibration statistics.
    """
    require_workspace_access(body.workspace_id, auth)
    from app.modules.nexus_spine.demand import ForecastActual

    evaluation = get_truth_loop().observe(
        ForecastActual(
            forecast_id=body.forecast_id,
            sku=body.sku,
            horizon_days=body.horizon_days,
            observed_at=body.observed_at,
            actual_quantity=body.actual_quantity,
        )
    )
    if evaluation is None:
        raise HTTPException(status_code=404, detail="no matching forecast recorded")
    return _envelope(
        request,
        {
            "forecast_id": evaluation.forecast_id,
            "sku": evaluation.sku,
            "predicted_p50": evaluation.predicted_p50,
            "actual": evaluation.actual,
            "absolute_error": evaluation.absolute_error,
            "percentage_error": evaluation.percentage_error,
            "bias": evaluation.bias,
            "is_within_p80": evaluation.is_within_p80,
            "is_within_p95": evaluation.is_within_p95,
        },
    )


@router.get("/calibration/{sku}")
async def get_calibration(
    sku: str,
    request: Request,
    workspace_id: str = Query(...),
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    require_workspace_access(workspace_id, auth)
    from app.modules.nexus_spine.vanessa.builtin_tools import CompareForecastActualTool
    try:
        ws_uuid = UUID(workspace_id)
        t_uuid = UUID(auth.user_id) if auth.user_id else uuid7()
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid workspace_id")
    from app.modules.nexus_spine.vanessa.tools import ToolCall

    tool = CompareForecastActualTool()
    call = ToolCall(
        tool_name=tool.name,
        arguments={"sku": sku, "min_samples": 1},
        requester_role="analyst",
        requester_id=auth.user_id or "api",
        tenant_id=t_uuid,
        workspace_id=ws_uuid,
    )
    result = tool.invoke(call)
    if not result.ok:
        raise HTTPException(status_code=400, detail=result.error)
    return _envelope(request, result.payload)


# ──────────────────────────────────────────────────────────────────────────────
# /v1/decisions
# ──────────────────────────────────────────────────────────────────────────────


class DecisionRecordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    decision_id: str
    situation: str
    evidence_ids: list[str] = Field(default_factory=list)
    world_state_version: int
    options: list[dict[str, Any]]
    recommended_option_id: str
    chosen_option_id: str
    policy_id: str
    approval_id: str | None = None
    tags: list[str] = Field(default_factory=list)


@router.post("/decisions", status_code=201)
async def record_decision(
    body: DecisionRecordRequest,
    request: Request,
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    require_workspace_access(body.workspace_id, auth)
    record = DecisionRecord(
        decision_id=body.decision_id,
        tenant_id=auth.user_id or "api",
        workspace_id=body.workspace_id,
        situation=body.situation,
        evidence_ids=body.evidence_ids,
        world_state_version=body.world_state_version,
        options=body.options,
        recommended_option_id=body.recommended_option_id,
        chosen_option_id=body.chosen_option_id,
        policy_id=body.policy_id,
        approval_id=body.approval_id,
        executed_at=datetime.now(UTC),
        tags=body.tags,
    )
    get_decision_memory().record(record)

    # Also create the governance lifecycle for governance tracking
    from app.modules.nexus_spine.governance import (
        DecisionLifecycle,
        get_decision_lifecycle_manager,
    )
    from app.modules.nexus_spine.ontology.repository import canonical_state_hash

    wm = get_world_model()
    entities_for_hash = [
        {"entity_id": str(e.entity_id), "state": dict(e.state)}
        for e in wm.iter_entities(
            tenant_id=UUID(auth.user_id) if auth.user_id else uuid7(),
            workspace_id=UUID(body.workspace_id),
        )
    ]
    world_state_hash = canonical_state_hash({"entities": entities_for_hash})

    manager = get_decision_lifecycle_manager()
    lifecycle = DecisionLifecycle(
        decision_id=body.decision_id,
        tenant_id=auth.user_id or "api",
        workspace_id=body.workspace_id,
        world_state_version=body.world_state_version,
        world_state_hash=world_state_hash,
        proposal_id=body.decision_id,
        options=body.options,
        chosen_option=body.chosen_option_id,
    )
    manager.put(lifecycle)
    data = record.to_dict()
    data["governance"] = {
        "lifecycle_id": lifecycle.decision_id,
        "phase": lifecycle.phase,
    }
    return _envelope(request, {"decision": data})


class DecisionOutcomeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    decision_id: str
    outcome_status: str | None = None
    financial_impact: float | None = None
    actual_result: str | None = None
    human_feedback: str | None = None


class DecisionOutcomeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    decision_id: str
    outcome_status: str | None = None
    financial_impact: float | None = None
    actual_result: str | None = None
    human_feedback: str | None = None


@router.patch("/decisions/{decision_id}/outcome")
async def update_decision_outcome(
    decision_id: str,
    body: DecisionOutcomeUpdate,
    request: Request,
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    require_workspace_access(body.workspace_id, auth)
    updated = get_decision_memory().update_outcome(
        decision_id,
        outcome_status=body.outcome_status,
        financial_impact=body.financial_impact,
        actual_result=body.actual_result,
        human_feedback=body.human_feedback,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="decision not found")
    return _envelope(request, {"decision": updated.to_dict()})


class AnalogousDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    situation: str
    limit: int = Field(default=5, ge=1, le=20)


@router.post("/decisions/analogous")
async def find_analogous_decisions(
    body: AnalogousDecisionRequest,
    request: Request,
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    require_workspace_access(body.workspace_id, auth)
    from app.modules.nexus_spine.vanessa.builtin_tools import FindAnalogousDecisionsTool
    try:
        ws_uuid = UUID(body.workspace_id)
        t_uuid = UUID(auth.user_id) if auth.user_id else uuid7()
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid workspace_id")
    from app.modules.nexus_spine.vanessa.tools import ToolCall

    tool = FindAnalogousDecisionsTool()
    call = ToolCall(
        tool_name=tool.name,
        arguments={"situation": body.situation, "limit": body.limit},
        requester_role="analyst",
        requester_id=auth.user_id or "api",
        tenant_id=t_uuid,
        workspace_id=ws_uuid,
    )
    result = tool.invoke(call)
    if not result.ok:
        raise HTTPException(status_code=400, detail=result.error)
    return _envelope(request, result.payload)


# ──────────────────────────────────────────────────────────────────────────────
# /v1/vanessa
# ──────────────────────────────────────────────────────────────────────────────


class VanessaAskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    query: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


@router.post("/vanessa/ask")
async def vanessa_ask(
    body: VanessaAskRequest,
    request: Request,
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    require_workspace_access(body.workspace_id, auth)
    try:
        ws_uuid = UUID(body.workspace_id)
        t_uuid = UUID(auth.user_id) if auth.user_id else uuid7()
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid workspace_id")
    query = VanessaQuery(
        query=body.query,
        requester_id=auth.user_id or "api",
        requester_role="analyst",
        tenant_id=t_uuid,
        workspace_id=ws_uuid,
        arguments=body.arguments,
    )
    answer = get_vanessa().ask(query)
    return _envelope(request, answer.to_dict(), correlation_id=request.headers.get("X-Correlation-Id"))


@router.get("/vanessa/tools")
async def list_vanessa_tools(
    request: Request,
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    tools = get_vanessa().registry.list_tools()
    return _envelope(request, {"tools": tools, "count": len(tools)})


# ──────────────────────────────────────────────────────────────────────────────
# /v1/risks/computed  — Phase C
# ──────────────────────────────────────────────────────────────────────────────


@router.get("/risks")
async def list_computed_risks(
    request: Request,
    workspace_id: str = Query(...),
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    """Compute the risk registry from live world state (Phase C).
    
    Aggregates signals, blast radius, and exposure into ranked
    RiskAssessments. Every response is deterministic given identical world
    state.
    """
    require_workspace_access(workspace_id, auth)
    from app.modules.nexus_spine.risk import get_risk_engine
    try:
        ws_uuid = UUID(workspace_id)
        t_uuid = UUID(auth.user_id) if auth.user_id else uuid7()
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid workspace_id")
    risks = get_risk_engine().compute(t_uuid, ws_uuid)
    return _envelope(
        request,
        {
            "risks": [r.to_dict() for r in risks],
            "count": len(risks),
            "computed_at": datetime.now(UTC).isoformat(),
        },
    )


# ──────────────────────────────────────────────────────────────────────────────
# /v1/scenarios  — Phase D (Digital Twin)
# ──────────────────────────────────────────────────────────────────────────────


class ScenarioMutationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str
    target_entity_id: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class ScenarioRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: str
    name: str = "Unnamed scenario"
    description: str = ""
    mutations: list[ScenarioMutationModel] = Field(default_factory=list)


class ScenarioCompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: str
    baseline: ScenarioRunRequest
    candidates: list[ScenarioRunRequest] = Field(default_factory=list)


@router.post("/scenarios/run")
async def run_scenario(
    body: ScenarioRunRequest,
    request: Request,
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    """Execute a scenario in the Digital Twin."""
    require_workspace_access(body.workspace_id, auth)
    try:
        ws_uuid = UUID(body.workspace_id)
        t_uuid = UUID(auth.user_id) if auth.user_id else uuid7()
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid workspace_id")

    from app.modules.nexus_spine.scenarios import (
        MutationKind,
        ScenarioDefinition,
        ScenarioMutation,
        get_scenario_studio,
    )

    mutations: list[ScenarioMutation] = []
    for m in body.mutations:
        try:
            mutations.append(
                ScenarioMutation(
                    kind=MutationKind(m.kind),
                    target_entity_id=UUID(m.target_entity_id),
                    parameters=m.parameters,
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"invalid mutation: {exc}") from exc

    scenario = ScenarioDefinition(
        name=body.name,
        description=body.description,
        workspace_id=str(ws_uuid),
        tenant_id=str(t_uuid),
        mutations=mutations,
    )
    result = get_scenario_studio().run(scenario)
    return _envelope(request, result.to_dict())


@router.post("/scenarios/compare")
async def compare_scenarios(
    body: ScenarioCompareRequest,
    request: Request,
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    """Run a baseline + candidate scenarios and return side-by-side metrics."""
    require_workspace_access(body.workspace_id, auth)
    try:
        ws_uuid = UUID(body.workspace_id)
        t_uuid = UUID(auth.user_id) if auth.user_id else uuid7()
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid workspace_id")

    from app.modules.nexus_spine.scenarios import (
        MutationKind,
        ScenarioDefinition,
        ScenarioMutation,
        get_scenario_studio,
    )

    def _to_definition(req: ScenarioRunRequest) -> ScenarioDefinition:
        mutations: list[ScenarioMutation] = []
        for m in req.mutations:
            mutations.append(
                ScenarioMutation(
                    kind=MutationKind(m.kind),
                    target_entity_id=UUID(m.target_entity_id),
                    parameters=m.parameters,
                )
            )
        return ScenarioDefinition(
            name=req.name,
            description=req.description,
            workspace_id=str(ws_uuid),
            tenant_id=str(t_uuid),
            mutations=mutations,
        )

    baseline_def = _to_definition(body.baseline)
    candidate_defs = [_to_definition(c) for c in body.candidates]
    studio = get_scenario_studio()
    comparison = studio.compare(baseline_def, candidate_defs)
    return _envelope(request, comparison)



# ──────────────────────────────────────────────────────────────────────────────
# /v1/governance — Phase G: Governed Operations
# ──────────────────────────────────────────────────────────────────────────────


class GovernanceAdvanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision_id: str
    target_phase: str
    actor_id: str = "system"
    reason: str = ""


class ApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actor_id: str = "operator"


class RejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actor_id: str = "operator"
    reason: str = ""


@router.post("/governance/decisions/{decision_id}/advance")
async def advance_decision(
    decision_id: str,
    body: GovernanceAdvanceRequest,
    request: Request,
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    """Advance a decision through its lifecycle state machine.

    Validates that the requested transition is legal per ALLOWED_TRANSITIONS
    and records the transition with full provenance.
    """
    manager = get_decision_lifecycle_manager()
    lifecycle = manager.get(decision_id)
    if lifecycle is None:
        raise HTTPException(status_code=404, detail="decision not found")

    try:
        target = DecisionPhase(body.target_phase)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"invalid target_phase: {body.target_phase}")

    try:
        transition = lifecycle.advance(target, actor=body.actor_id, reason=body.reason)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _envelope(
        request,
        {
            "decision_id": decision_id,
            "from_phase": transition.from_phase.value,
            "to_phase": transition.to_phase.value,
            "status": "success",
        },
    )


@router.post("/governance/decisions/{decision_id}/approve")
async def approve_decision(
    decision_id: str,
    body: ApproveRequest,
    request: Request,
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    """Approve a decision. Valid from AWAITING_APPROVAL or earlier pre-approval phases."""
    manager = get_decision_lifecycle_manager()
    lc = manager.get(decision_id)
    if lc is None:
        raise HTTPException(status_code=404, detail="decision not found")

    valid_for_approval = {DecisionPhase.AWAITING_APPROVAL, DecisionPhase.SIMULATED, DecisionPhase.POLICY_CHECKED}
    if lc.phase not in valid_for_approval:
        raise HTTPException(status_code=409, detail=f"Cannot approve in phase {lc.phase.value}")

    lc.advance(DecisionPhase.APPROVED, actor=body.actor_id)
    return _envelope(request, {"decision_id": decision_id, "phase": "approved"})


@router.post("/governance/decisions/{decision_id}/reject")
async def reject_decision(
    decision_id: str,
    body: RejectRequest,
    request: Request,
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    """Reject a decision. Terminal — no further transitions allowed."""
    manager = get_decision_lifecycle_manager()
    lc = manager.get(decision_id)
    if lc is None:
        raise HTTPException(status_code=404, detail="decision not found")

    lc.advance(DecisionPhase.REJECTED, actor=body.actor_id, reason=body.reason)
    return _envelope(
        request,
        {"decision_id": decision_id, "phase": "rejected", "reason": body.reason},
    )


@router.post("/governance/decisions/{decision_id}/mark-stale")
async def mark_decision_stale(
    decision_id: str,
    request: Request,
    reason: str = "World state drifted",
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    """Mark a decision as stale when the world state has moved beneath it."""
    manager = get_decision_lifecycle_manager()
    lc = manager.get(decision_id)
    if lc is None:
        raise HTTPException(status_code=404, detail="decision not found")

    lc.mark_stale(actor="system", reason=reason)
    return _envelope(request, {"decision_id": decision_id, "phase": "stale", "reason": reason})


@router.get("/governance/decisions/{decision_id}")
async def get_lifecycle_detail(
    decision_id: str,
    request: Request,
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    """Get a decision's full lifecycle with all transitions."""
    manager = get_decision_lifecycle_manager()
    lc = manager.get(decision_id)
    if lc is None:
        raise HTTPException(status_code=404, detail="decision not found")
    return _envelope(request, lc.to_dict())


@router.get("/governance/decisions/{decision_id}/audit-trail")
async def get_decision_audit_trail(
    decision_id: str,
    request: Request,
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    """Get full transition history for a decision (for compliance/proof-of-change)."""
    manager = get_decision_lifecycle_manager()
    lc = manager.get(decision_id)
    if lc is None:
        raise HTTPException(status_code=404, detail="decision not found")

    transitions = [
        {
            "transition_id": t.transition_id,
            "from_phase": t.from_phase.value,
            "to_phase": t.to_phase.value,
            "actor": t.actor,
            "timestamp": t.timestamp.isoformat(),
            "metadata": t.metadata,
        }
        for t in lc.transitions
    ]
    return _envelope(
        request,
        {
            "decision_id": decision_id,
            "current_phase": lc.phase.value,
            "transitions": transitions,
            "count": len(transitions),
        },
    )


@router.get("/governance/decisions/{decision_id}/state-machine")
async def get_state_machine(
    decision_id: str,
    request: Request,
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    """Return the allowed transitions from the current decision phase."""
    manager = get_decision_lifecycle_manager()
    lc = manager.get(decision_id)
    if lc is None:
        raise HTTPException(status_code=404, detail="decision not found")

    allowed = sorted(t.value for t in ALLOWED_TRANSITIONS[lc.phase])
    return _envelope(
        request,
        {
            "decision_id": decision_id,
            "current_phase": lc.phase.value,
            "allowed_transitions": allowed,
            "is_terminal": lc.is_terminal(),
        },
    )


@router.get("/realtime/events")
async def recent_events(
    request: Request,
    workspace_id: str = Query(...),
    limit: int = Query(default=100, ge=1, le=1000),
    auth: AuthContext = Depends(get_current_user),
) -> ApiEnvelope:
    """Return the most recent world-state change events.

    Backed by the in-memory event log of the WorldModelRepository. A
    streaming variant (SSE) is added in Phase N (Realtime fabric).
    """
    require_workspace_access(workspace_id, auth)
    wm = get_world_model()
    events = wm.events[-limit:]
    return _envelope(request, {"events": events, "count": len(events)})
