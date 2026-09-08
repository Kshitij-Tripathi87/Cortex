"""World State API v1 — Create, query, replay, rollback, diff, and validate world states.

Program J (World State & Digital Twin) — Milestone J.2.8 World State REST APIs.

Endpoints:
- POST /world/state — Initialize genesis world state
- GET /world/state — Query current or historical world state
- GET /world/history — Query version lineage history
- POST /world/event — Submit domain event through transactional write pipeline
- GET /world/diff — Semantic diff comparison across two state versions
- POST /world/replay — Time-travel state reconstruction (snapshot checkpoint + delta projection)
- POST /world/rollback — Append-only rollback restoring historical variables as new version
- POST /world/validate — Validate state integrity and invariant rules
- GET /world/events — Query raw event log
- POST /world/verify — Verify cryptographic event chain hash integrity

Security:
- Every endpoint resolves a principal via get_current_user
- Workspace access enforced via require_workspace_access
- Multi-tenant isolation guaranteed
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.ids import uuid7
from app.infrastructure.database import get_db
from app.infrastructure.security import AuthContext, get_current_user, require_workspace_access
from app.modules.events.event_models import (
    CapacityChanged,
    DemandChanged,
    FactoryShutdown,
    InventoryChanged,
    OrderCancelled,
    OrderPlaced,
    PriceChanged,
    RouteDisruption,
    ShipmentDelayed,
    SupplierDelayed,
    SupplierHealthChanged,
    WorldEvent,
    WorldEventType,
)
from app.modules.events.event_store import EventStore
from app.modules.world.state_history import (
    StateDiffEngine,
    compare_states,
)
from app.modules.world.state_repository import StateRepository
from app.modules.world.world_models import (
    StateVariable,
    StateVariableType,
    WorldState,
)
from app.modules.world.world_service import WorldStateService
from app.modules.world.world_validation import WorldValidator

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# Request/Response Models
# ─────────────────────────────────────────────────────────────────────────────


class CreateWorldStateRequest(BaseModel):
    workspace_id: str
    world_id: str
    graph_version: int = 1
    initial_variables: dict[str, dict[str, Any]] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class StateVariableResponse(BaseModel):
    variable_id: str
    variable_type: str
    entity_id: str
    entity_type: str
    value: Any
    unit: str | None = None


class WorldStateResponse(BaseModel):
    world_id: str
    workspace_id: str
    version: int
    graph_version: int
    variables: list[StateVariableResponse]
    state_hash: str
    created_at: datetime
    metadata: dict[str, Any]


class SubmitEventRequest(BaseModel):
    workspace_id: str
    world_id: str
    entity_type: str
    entity_id: str
    event_type: str
    payload: dict[str, Any]
    idempotency_key: str | None = None
    caused_by_event_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SubmitEventResponse(BaseModel):
    event_id: str
    version_id: str
    version: int
    is_snapshot_created: bool
    is_duplicate: bool
    state: WorldStateResponse


# Backward compatibility aliases
AppendEventRequest = SubmitEventRequest
AppendEventResponse = SubmitEventResponse


class StateDiffResponse(BaseModel):
    from_version: int
    to_version: int
    variables_added: list[str]
    variables_removed: list[str]
    variables_changed: list[str]
    summary: dict[str, Any]


class ReplayRequest(BaseModel):
    workspace_id: str
    world_id: str
    target_version: int | None = None


class ReplayResponse(BaseModel):
    world_id: str
    version: int
    variables: list[StateVariableResponse]
    state_hash: str
    reconstruction_method: str
    transitions_replayed: int
    snapshot_used: str | None = None


class RollbackRequest(BaseModel):
    workspace_id: str
    world_id: str
    target_version: int
    reason: str


class RollbackResponse(BaseModel):
    new_version: int
    rolled_back_from_version: int
    rolled_back_to_version: int
    events_appended: int
    state: WorldStateResponse


class ValidateStateRequest(BaseModel):
    workspace_id: str
    world_id: str
    version: int | None = None
    expected_hash: str | None = None


class ValidationIssueResponse(BaseModel):
    issue_id: str
    severity: str
    rule: str
    message: str
    affected_variables: list[str]
    metadata: dict[str, Any]


class ValidationResponse(BaseModel):
    world_id: str
    version: int
    is_valid: bool
    rules_checked: int
    issues: list[ValidationIssueResponse]
    validated_at: str


# ─────────────────────────────────────────────────────────────────────────────
# Factory helper to construct domain WorldEvent from API payload
# ─────────────────────────────────────────────────────────────────────────────


def _build_domain_event(body: SubmitEventRequest) -> WorldEvent:
    event_id = str(uuid7())
    etype = body.event_type
    p = body.payload

    if etype == WorldEventType.INVENTORY_CHANGED.value:
        return InventoryChanged(
            event_id=event_id,
            world_id=body.world_id,
            workspace_id=body.workspace_id,
            entity_type=body.entity_type,
            entity_id=body.entity_id,
            warehouse_id=p["warehouse_id"],
            component_id=p["component_id"],
            quantity_change=int(p["quantity_change"]),
            reason=p.get("reason", "api_submission"),
            caused_by_event_id=body.caused_by_event_id,
            metadata=body.metadata,
        )
    elif etype == WorldEventType.SUPPLIER_DELAYED.value:
        return SupplierDelayed(
            event_id=event_id,
            world_id=body.world_id,
            workspace_id=body.workspace_id,
            entity_type=body.entity_type,
            entity_id=body.entity_id,
            delay_days=int(p["delay_days"]),
            disruption_type=p.get("disruption_type", "delay"),
            caused_by_event_id=body.caused_by_event_id,
            metadata=body.metadata,
        )
    elif etype == WorldEventType.SUPPLIER_HEALTH_CHANGED.value:
        return SupplierHealthChanged(
            event_id=event_id,
            world_id=body.world_id,
            workspace_id=body.workspace_id,
            entity_type=body.entity_type,
            entity_id=body.entity_id,
            health_score=float(p["health_score"]),
            previous_score=float(p["previous_score"]) if "previous_score" in p else None,
            caused_by_event_id=body.caused_by_event_id,
            metadata=body.metadata,
        )
    elif etype == WorldEventType.ORDER_PLACED.value:
        return OrderPlaced(
            event_id=event_id,
            world_id=body.world_id,
            workspace_id=body.workspace_id,
            entity_type=body.entity_type,
            entity_id=body.entity_id,
            warehouse_id=p["warehouse_id"],
            component_id=p["component_id"],
            quantity=int(p["quantity"]),
            customer_id=p.get("customer_id"),
            priority=p.get("priority", "standard"),
            caused_by_event_id=body.caused_by_event_id,
            metadata=body.metadata,
        )
    elif etype == WorldEventType.ORDER_CANCELLED.value:
        return OrderCancelled(
            event_id=event_id,
            world_id=body.world_id,
            workspace_id=body.workspace_id,
            entity_type=body.entity_type,
            entity_id=body.entity_id,
            warehouse_id=p["warehouse_id"],
            component_id=p["component_id"],
            quantity=int(p["quantity"]),
            order_id=p["order_id"],
            reason=p.get("reason", "cancelled"),
            caused_by_event_id=body.caused_by_event_id,
            metadata=body.metadata,
        )
    elif etype == WorldEventType.CAPACITY_CHANGED.value:
        return CapacityChanged(
            event_id=event_id,
            world_id=body.world_id,
            workspace_id=body.workspace_id,
            entity_type=body.entity_type,
            entity_id=body.entity_id,
            capacity_pct=float(p["capacity_pct"]),
            reason=p.get("reason", "manual"),
            caused_by_event_id=body.caused_by_event_id,
            metadata=body.metadata,
        )
    elif etype == WorldEventType.FACTORY_SHUTDOWN.value:
        return FactoryShutdown(
            event_id=event_id,
            world_id=body.world_id,
            workspace_id=body.workspace_id,
            entity_type=body.entity_type,
            entity_id=body.entity_id,
            capacity_pct=float(p.get("capacity_pct", 0.0)),
            estimated_recovery_days=int(p["estimated_recovery_days"])
            if "estimated_recovery_days" in p
            else None,
            cause=p.get("cause", "emergency"),
            caused_by_event_id=body.caused_by_event_id,
            metadata=body.metadata,
        )
    elif etype == WorldEventType.ROUTE_DISRUPTION.value:
        return RouteDisruption(
            event_id=event_id,
            world_id=body.world_id,
            workspace_id=body.workspace_id,
            entity_type=body.entity_type,
            entity_id=body.entity_id,
            delay_days=int(p["delay_days"]),
            disruption_type=p.get("disruption_type", "blockage"),
            caused_by_event_id=body.caused_by_event_id,
            metadata=body.metadata,
        )
    elif etype == WorldEventType.SHIPMENT_DELAYED.value:
        return ShipmentDelayed(
            event_id=event_id,
            world_id=body.world_id,
            workspace_id=body.workspace_id,
            entity_type=body.entity_type,
            entity_id=body.entity_id,
            delay_days=int(p["delay_days"]),
            shipment_id=p["shipment_id"],
            cause=p.get("cause", "customs"),
            caused_by_event_id=body.caused_by_event_id,
            metadata=body.metadata,
        )
    elif etype == WorldEventType.DEMAND_CHANGED.value:
        return DemandChanged(
            event_id=event_id,
            world_id=body.world_id,
            workspace_id=body.workspace_id,
            entity_type=body.entity_type,
            entity_id=body.entity_id,
            demand_change=int(p["demand_change"]),
            confidence=float(p.get("confidence", 1.0)),
            source=p.get("source", "forecast"),
            caused_by_event_id=body.caused_by_event_id,
            metadata=body.metadata,
        )
    elif etype == WorldEventType.PRICE_CHANGED.value:
        return PriceChanged(
            event_id=event_id,
            world_id=body.world_id,
            workspace_id=body.workspace_id,
            entity_type=body.entity_type,
            entity_id=body.entity_id,
            new_price=float(p["new_price"]),
            previous_price=float(p["previous_price"]) if "previous_price" in p else None,
            currency=p.get("currency", "USD"),
            caused_by_event_id=body.caused_by_event_id,
            metadata=body.metadata,
        )
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported event_type '{etype}'. Must be one of registered domain event types.",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/world/state", response_model=WorldStateResponse, status_code=201)
async def create_world_state(
    body: CreateWorldStateRequest,
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorldStateResponse:
    """Create genesis world state (version 1) for a workspace."""
    require_workspace_access(body.workspace_id, auth)

    initial_vars = {}
    for var_id, vdata in body.initial_variables.items():
        initial_vars[var_id] = StateVariable(
            variable_id=var_id,
            variable_type=StateVariableType(vdata["variable_type"]),
            entity_id=vdata["entity_id"],
            entity_type=vdata["entity_type"],
            value=vdata["value"],
            unit=vdata.get("unit"),
            metadata=vdata.get("metadata", {}),
        )

    service = WorldStateService(StateRepository(db))
    try:
        state = await service.initialize_world(
            workspace_id=body.workspace_id,
            world_id=body.world_id,
            graph_version=body.graph_version,
            initial_variables=initial_vars,
            metadata=body.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return _state_to_response(state)


@router.get("/world/state", response_model=WorldStateResponse)
async def get_world_state(
    workspace_id: str = Query(...),
    world_id: str = Query(...),
    version: int | None = Query(None, description="Specific version; defaults to latest"),
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorldStateResponse:
    """Get the current (or specific version of) world state."""
    require_workspace_access(workspace_id, auth)

    repo = StateRepository(db)
    if version is not None:
        state = await repo.get(world_id, workspace_id, version=version)
    else:
        state = await repo.get_latest(workspace_id, world_id)

    if not state:
        raise HTTPException(status_code=404, detail="World state not found")

    return _state_to_response(state)


@router.get("/world/history")
async def get_world_history(
    workspace_id: str = Query(...),
    world_id: str = Query(...),
    limit: int = Query(100, ge=1, le=1000),
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get the history of world state versions."""
    require_workspace_access(workspace_id, auth)

    repo = StateRepository(db)
    versions = await repo.get_versions(world_id, workspace_id)
    versions.sort(key=lambda v: v.version, reverse=True)
    return {
        "workspace_id": workspace_id,
        "world_id": world_id,
        "version_count": len(versions),
        "versions": [
            {
                "version_id": v.version_id,
                "version": v.version,
                "graph_version": v.graph_version,
                "state_hash": v.state_hash,
                "event_id": v.event_id,
                "parent_version_id": v.parent_version_id,
                "source": v.source,
                "created_at": v.created_at.isoformat(),
            }
            for v in versions[:limit]
        ],
    }


@router.post("/world/event", response_model=SubmitEventResponse, status_code=201)
async def submit_world_event(
    body: SubmitEventRequest,
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubmitEventResponse:
    """Submit an event to mutate the world state through authoritative pipeline."""
    require_workspace_access(body.workspace_id, auth)

    domain_event = _build_domain_event(body)
    service = WorldStateService(StateRepository(db))

    try:
        result = await service.submit_event(
            domain_event,
            idempotency_key=body.idempotency_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return SubmitEventResponse(
        event_id=result.event_id,
        version_id=result.version_id,
        version=result.version,
        is_snapshot_created=result.is_snapshot_created,
        is_duplicate=result.is_duplicate,
        state=_state_to_response(result.state),
    )


@router.get("/world/diff", response_model=StateDiffResponse)
async def get_state_diff(
    workspace_id: str = Query(...),
    world_id: str = Query(...),
    from_version: int = Query(...),
    to_version: int = Query(...),
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StateDiffResponse:
    """Compare two versions of world state."""
    require_workspace_access(workspace_id, auth)

    repo = StateRepository(db)
    try:
        comparison = await compare_states(repo, world_id, workspace_id, from_version, to_version)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return StateDiffResponse(
        from_version=from_version,
        to_version=to_version,
        variables_added=comparison.variables_added,
        variables_removed=comparison.variables_removed,
        variables_changed=comparison.variables_changed,
        summary=StateDiffEngine().summarize_changes(comparison),
    )


@router.post("/world/replay", response_model=ReplayResponse)
async def replay_world_state(
    body: ReplayRequest,
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReplayResponse:
    """Reconstruct world state at a specific version (time travel)."""
    require_workspace_access(body.workspace_id, auth)

    service = WorldStateService(StateRepository(db))
    if body.target_version is None:
        rep_res = await service.replay_from_genesis(body.world_id, body.workspace_id)
        state = rep_res.state
        method = "full_replay"
        transitions_replayed = rep_res.transitions_applied
        snapshot_used = None
    else:
        tt_res = await service.time_travel(
            body.world_id, body.workspace_id, target_version=body.target_version
        )
        state = tt_res.state
        method = tt_res.reconstruction_method
        transitions_replayed = tt_res.transitions_replayed
        snapshot_used = tt_res.snapshot_used

    return ReplayResponse(
        world_id=body.world_id,
        version=state.version,
        variables=[
            StateVariableResponse(
                variable_id=v.variable_id,
                variable_type=v.variable_type.value,
                entity_id=v.entity_id,
                entity_type=v.entity_type,
                value=v.raw_value,
                unit=v.unit,
            )
            for v in state.variables.values()
        ],
        state_hash=state.metadata.get("state_hash", ""),
        reconstruction_method=method,
        transitions_replayed=transitions_replayed,
        snapshot_used=snapshot_used,
    )


@router.post("/world/rollback", response_model=RollbackResponse)
async def rollback_world_state(
    body: RollbackRequest,
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RollbackResponse:
    """Perform an append-only rollback restoring historical variables as a new version."""
    require_workspace_access(body.workspace_id, auth)

    service = WorldStateService(StateRepository(db))
    try:
        result = await service.rollback_world(
            workspace_id=body.workspace_id,
            world_id=body.world_id,
            target_version=body.target_version,
            reason=body.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return RollbackResponse(
        new_version=result.new_state.version,
        rolled_back_from_version=result.rolled_back_from_version,
        rolled_back_to_version=result.rolled_back_to_version,
        events_appended=result.events_appended,
        state=_state_to_response(result.new_state),
    )


@router.post("/world/validate", response_model=ValidationResponse)
async def validate_world_state(
    body: ValidateStateRequest,
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ValidationResponse:
    """Validate world state against all structural, domain, and security rules."""
    require_workspace_access(body.workspace_id, auth)

    repo = StateRepository(db)
    if body.version is not None:
        state = await repo.get(body.world_id, body.workspace_id, version=body.version)
    else:
        state = await repo.get_latest(body.workspace_id, body.world_id)

    if not state:
        raise HTTPException(status_code=404, detail="World state not found")

    validator = WorldValidator()
    result = validator.validate(state, expected_hash=body.expected_hash)

    return ValidationResponse(
        world_id=state.world_id,
        version=state.version,
        is_valid=result.is_valid,
        rules_checked=result.rules_checked,
        issues=[
            ValidationIssueResponse(
                issue_id=i.issue_id,
                severity=i.severity.value,
                rule=i.rule,
                message=i.message,
                affected_variables=i.affected_variables,
                metadata=i.metadata,
            )
            for i in result.issues
        ],
        validated_at=result.validated_at.isoformat(),
    )


@router.get("/world/events")
async def get_world_events(
    workspace_id: str = Query(...),
    world_id: str = Query(...),
    entity_type: str | None = Query(None),
    event_type: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get the event log for a world."""
    require_workspace_access(workspace_id, auth)

    store = EventStore(db)
    records = await store.list_events(
        world_id=world_id,
        entity_type=entity_type,
        event_type=event_type,
        limit=limit,
    )
    return {
        "world_id": world_id,
        "event_count": len(records),
        "events": [
            {
                "event_id": r.event.event_id,
                "entity_type": r.event.entity_type,
                "entity_id": r.event.entity_id,
                "event_type": r.event.event_type.value,
                "payload": r.payload,
                "occurred_at": r.event.occurred_at.isoformat(),
                "sequence": r.sequence,
                "event_hash": r.event_hash,
            }
            for r in records
        ],
    }


@router.post("/world/verify")
async def verify_world_event_chain(
    workspace_id: str = Query(...),
    world_id: str = Query(...),
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Verify the integrity of a world's event chain."""
    require_workspace_access(workspace_id, auth)

    store = EventStore(db)
    result = await store.verify(world_id)

    return {
        "world_id": world_id,
        "is_valid": result.is_valid,
        "total_events": result.total_events,
        "verified_events": result.verified_events,
        "first_invalid_event_id": result.first_invalid_event_id,
        "error_message": result.error_message,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _state_to_response(state: WorldState) -> WorldStateResponse:
    return WorldStateResponse(
        world_id=state.world_id,
        workspace_id=state.workspace_id,
        version=state.version,
        graph_version=state.graph_version,
        variables=[
            StateVariableResponse(
                variable_id=v.variable_id,
                variable_type=v.variable_type.value,
                entity_id=v.entity_id,
                entity_type=v.entity_type,
                value=v.raw_value,
                unit=v.unit,
            )
            for v in state.variables.values()
        ],
        state_hash=state.metadata.get("state_hash", ""),
        created_at=state.created_at,
        metadata=dict(state.metadata),
    )
