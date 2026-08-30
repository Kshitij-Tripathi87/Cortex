"""Digital Twin API v1 — Create, run, fork, query, archive, destroy twins.

Program J (World State & Digital Twin) — J.3.1 Twin Lifecycle REST APIs.

Endpoints:
- POST /twin/create — Create an isolated twin from a world snapshot
- POST /twin/run — Run a scenario against a twin in isolated memory
- POST /twin/fork — Branch an existing twin into a counterfactual branch
- GET /twin/list — List all twins for a workspace
- GET /twin/{twin_id} — Get twin metadata (lineage included)
- GET /twin/{twin_id}/results — Get run results for a twin
- POST /twin/{twin_id}/archive — Archive a twin (soft lifecycle transition)
- DELETE /twin/{twin_id} — Destroy a twin permanently (twin namespace only)
- POST /twin/scenario — Instantiate a scenario from a registered template
- GET /twin/scenarios — List available scenario templates

Security:
- Every endpoint resolves a principal via get_current_user
- Workspace access enforced via require_workspace_access(workspace_id, auth)
- Multi-tenant isolation and complete memory sandbox isolation

J.3.1 invariants:
- Response `lineage` fields are immutable once returned (frozen at creation).
- Runs are deterministic: same (snapshot, scenario, seed) → same final hash.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database import get_db
from app.infrastructure.security import AuthContext, get_current_user, require_workspace_access
from app.modules.simulation.scenario_registry import get_scenario_registry
from app.modules.twin.twin_isolation import IsolationError
from app.modules.twin.twin_models import (
    DigitalTwin,
    ScenarioType,
    TwinScenario,
    TwinStatus,
)
from app.modules.twin.twin_service import TwinService

router = APIRouter()
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Request/Response Models
# ─────────────────────────────────────────────────────────────────────────────


class CreateTwinRequest(BaseModel):
    organization_id: str | None = None
    workspace_id: str
    world_id: str
    snapshot_id: str
    name: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)


class TwinResponse(BaseModel):
    twin_id: str
    organization_id: str
    workspace_id: str
    parent_world_id: str
    parent_version: int
    snapshot_id: str
    fork_of_twin_id: str | None
    fork_from_run_id: str | None
    name: str
    status: str
    description: str
    tags: list[str]
    lineage_hash: str
    created_at: str
    created_by: str | None


class RunScenarioRequest(BaseModel):
    workspace_id: str
    twin_id: str
    scenario_id: str | None = None
    custom_scenario: TwinScenario | None = None
    inject_events: list[dict[str, Any]] = Field(default_factory=list)
    # Deterministic run control: same (snapshot, scenario, seed) → same result.
    seed: int = 0


class RunResultResponse(BaseModel):
    run_id: str
    twin_id: str
    scenario_id: str
    final_state_hash: str
    final_version: int
    events_processed: int
    metrics: dict[str, float]
    comparison: dict[str, Any] | None
    timeline: list[dict[str, Any]]
    seed: int = 0


class ForkTwinRequest(BaseModel):
    workspace_id: str
    source_twin_id: str
    name: str
    description: str = ""


class CreateScenarioRequest(BaseModel):
    template_id: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class ScenarioResponse(BaseModel):
    scenario_id: str
    name: str
    description: str
    scenario_type: str
    events: list[dict[str, Any]]


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/twin/create", response_model=TwinResponse, status_code=201)
async def create_twin(
    body: CreateTwinRequest,
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TwinResponse:
    """Create a new digital twin from a snapshot."""
    require_workspace_access(body.workspace_id, auth)

    service = TwinService(db)
    try:
        twin = await service.clone(
            workspace_id=body.workspace_id,
            world_id=body.world_id,
            snapshot_id=body.snapshot_id,
            name=body.name,
            description=body.description,
            created_by=auth.user_id if hasattr(auth, "user_id") else None,
            tags=body.tags,
            organization_id=body.organization_id,
        )
    except IsolationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _twin_to_response(twin)


@router.get("/twin/list")
async def list_twins(
    workspace_id: str = Query(...),
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List all digital twins in a workspace."""
    require_workspace_access(workspace_id, auth)

    service = TwinService(db)
    twins = await service.list_twins(workspace_id)
    return {
        "workspace_id": workspace_id,
        "twin_count": len(twins),
        "twins": [_twin_to_response(t) for t in twins],
    }


@router.get("/twin/{twin_id}", response_model=TwinResponse)
async def get_twin_by_id(
    twin_id: str,
    workspace_id: str = Query(...),
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TwinResponse:
    """Get metadata for a specific digital twin."""
    require_workspace_access(workspace_id, auth)

    service = TwinService(db)
    # Workspace-scoped read: a twin in another workspace is invisible here.
    twin = await service.get_twin(twin_id, workspace_id=workspace_id)
    if not twin:
        raise HTTPException(status_code=404, detail=f"Twin {twin_id} not found")

    return _twin_to_response(twin)


@router.post("/twin/run", response_model=RunResultResponse)
async def run_scenario(
    body: RunScenarioRequest,
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RunResultResponse:
    """Execute a scenario against a digital twin in isolated sandbox memory."""
    require_workspace_access(body.workspace_id, auth)

    service = TwinService(db)
    twin = await service.get_twin(body.twin_id, workspace_id=body.workspace_id)
    if not twin:
        raise HTTPException(status_code=404, detail=f"Twin {body.twin_id} not found")

    # Resolve scenario
    if body.scenario_id:
        registry = get_scenario_registry()
        scenario = None
        for template in registry.list_all():
            try:
                scenario = template.factory(
                    scenario_id=body.scenario_id, **template.optional_params
                )
                break
            except Exception as exc:
                logger.warning("Scenario factory failed: %s", exc)
                continue
        if not scenario:
            raise HTTPException(status_code=404, detail="Scenario not found")
    elif body.custom_scenario:
        scenario = body.custom_scenario
    else:
        raise HTTPException(
            status_code=400, detail="Either scenario_id or custom_scenario must be provided"
        )

    try:
        result = await service.run(twin, scenario, seed=body.seed, inject_events=body.inject_events)
    except IsolationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return RunResultResponse(
        run_id=result.run_id,
        twin_id=result.twin_id,
        scenario_id=result.scenario_id,
        final_state_hash=result.final_state_hash,
        final_version=result.final_version,
        events_processed=result.events_processed,
        metrics=result.metrics,
        comparison=result.comparison,
        timeline=result.timeline,
        seed=body.seed,
    )


@router.post("/twin/fork", response_model=TwinResponse, status_code=201)
async def fork_twin(
    body: ForkTwinRequest,
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TwinResponse:
    """Fork an existing twin into a counterfactual branch."""
    require_workspace_access(body.workspace_id, auth)

    service = TwinService(db)
    try:
        fork = await service.fork(
            source_twin_id=body.source_twin_id,
            fork_name=body.name,
            description=body.description,
            created_by=auth.user_id if hasattr(auth, "user_id") else None,
        )
    except IsolationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _twin_to_response(fork)


@router.post("/twin/{twin_id}/archive", response_model=TwinResponse)
async def archive_twin(
    twin_id: str,
    workspace_id: str = Query(...),
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TwinResponse:
    """Archive a digital twin (soft lifecycle transition; remains queryable)."""
    require_workspace_access(workspace_id, auth)

    service = TwinService(db)
    twin = await service.get_twin(twin_id, workspace_id=workspace_id)
    if not twin:
        raise HTTPException(status_code=404, detail=f"Twin {twin_id} not found")
    try:
        archived = await service.archive(twin_id)
    except IsolationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return _twin_to_response(archived)


@router.delete("/twin/{twin_id}", status_code=204)
async def destroy_twin(
    twin_id: str,
    workspace_id: str = Query(...),
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Permanently destroy a digital twin (twin + runs). Production is untouched."""
    require_workspace_access(workspace_id, auth)

    service = TwinService(db)
    destroyed = await service.destroy(twin_id)
    if not destroyed:
        raise HTTPException(status_code=404, detail=f"Twin {twin_id} not found")


@router.post("/twin/scenario", response_model=ScenarioResponse, status_code=201)
async def create_scenario_from_template(
    body: CreateScenarioRequest,
    workspace_id: str = Query(...),
    auth: AuthContext = Depends(get_current_user),
) -> ScenarioResponse:
    """Create a scenario from a registered template."""
    require_workspace_access(workspace_id, auth)

    registry = get_scenario_registry()
    try:
        scenario = registry.instantiate(body.template_id, body.parameters)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return ScenarioResponse(
        scenario_id=scenario.scenario_id,
        name=scenario.name,
        description=scenario.description,
        scenario_type=scenario.scenario_type.value,
        events=scenario.events,
    )


@router.get("/twin/scenarios")
async def list_available_scenarios(
    workspace_id: str = Query(...),
    scenario_type: str | None = Query(None),
    tag: str | None = Query(None),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """List all available scenario templates."""
    require_workspace_access(workspace_id, auth)

    registry = get_scenario_registry()
    if scenario_type:
        templates = registry.list_by_type(ScenarioType(scenario_type))
    elif tag:
        templates = registry.list_by_tag(tag)
    else:
        templates = registry.list_all()

    return {
        "workspace_id": workspace_id,
        "template_count": len(templates),
        "templates": [t.to_dict() for t in templates],
    }


# ─────────────────────────────────────────────────────────────────────────────
# New J.3.1 Endpoints: Lineage, State, Events, Results
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/twin/{twin_id}/lineage")
async def get_twin_lineage(
    twin_id: str,
    workspace_id: str = Query(...),
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get a twin's immutable lineage and verify its integrity."""
    require_workspace_access(workspace_id, auth)

    service = TwinService(db)
    twin = await service.get_twin(twin_id, workspace_id=workspace_id)
    if not twin:
        raise HTTPException(status_code=404, detail=f"Twin {twin_id} not found")

    from app.modules.twin.twin_models import compute_twin_lineage_hash, lineage_intact

    return {
        "twin_id": twin_id,
        "organization_id": twin.organization_id,
        "workspace_id": twin.workspace_id,
        "parent_world_id": twin.parent_world_id,
        "parent_version": twin.parent_version,
        "snapshot_id": twin.snapshot_id,
        "fork_of_twin_id": twin.fork_of_twin_id,
        "fork_from_run_id": twin.fork_from_run_id,
        "created_at": twin.created_at.isoformat(),
        "lineage_hash": twin.lineage_hash,
        "lineage_intact": lineage_intact(twin),
        "computed_hash": compute_twin_lineage_hash(twin),
    }


@router.get("/twin/{twin_id}/state")
async def get_twin_state(
    twin_id: str,
    workspace_id: str = Query(...),
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get a twin's current state (variables, version, hash)."""
    require_workspace_access(workspace_id, auth)

    service = TwinService(db)
    twin = await service.get_twin(twin_id, workspace_id=workspace_id)
    if not twin:
        raise HTTPException(status_code=404, detail=f"Twin {twin_id} not found")

    state = await service.get_current_state(twin)
    return {
        "twin_id": twin_id,
        "world_id": state.world_id,
        "workspace_id": state.workspace_id,
        "version": state.version,
        "variable_count": len(state.variables),
        "state_hash": state.metadata.get("state_hash", ""),
        "variables": {vid: v.to_dict() for vid, v in state.variables.items()},
        "graph_version": state.graph_version,
    }


@router.get("/twin/{twin_id}/events")
async def get_twin_events(
    twin_id: str,
    workspace_id: str = Query(...),
    run_id: str | None = Query(None),
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get a twin's event log (optionally filtered by run)."""
    require_workspace_access(workspace_id, auth)

    service = TwinService(db)
    twin = await service.get_twin(twin_id, workspace_id=workspace_id)
    if not twin:
        raise HTTPException(status_code=404, detail=f"Twin {twin_id} not found")

    runs = await service.repo.get_runs(twin_id, workspace_id)
    if run_id:
        runs = [r for r in runs if r.run_id == run_id]

    all_events = []
    for run in runs:
        for ev in run.injected_events or []:
            all_events.append(ev)

    return {
        "twin_id": twin_id,
        "event_count": len(all_events),
        "events": all_events,
    }


@router.get("/twin/{twin_id}/results")
async def get_twin_results(
    twin_id: str,
    workspace_id: str = Query(...),
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get all scenario run results for a twin."""
    require_workspace_access(workspace_id, auth)

    service = TwinService(db)
    results = await service.get_results(twin_id)
    return {
        "twin_id": twin_id,
        "results_count": len(results),
        "results": [
            {
                "run_id": r.run_id,
                "scenario_id": r.scenario_id,
                "final_state_hash": r.final_state_hash,
                "final_version": r.final_version,
                "events_processed": r.events_processed,
                "metrics": r.metrics,
                "comparison": r.comparison,
                "seed": r.metadata.get("seed", 0),
                "rng_version": r.metadata.get("rng_version"),
                "engine_version": r.metadata.get("engine_version"),
                "simulation_version": r.metadata.get("simulation_version"),
            }
            for r in results
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _twin_to_response(twin: DigitalTwin) -> TwinResponse:
    return TwinResponse(
        twin_id=twin.twin_id,
        organization_id=twin.organization_id,
        workspace_id=twin.workspace_id,
        parent_world_id=twin.parent_world_id,
        parent_version=twin.parent_version,
        snapshot_id=twin.snapshot_id,
        fork_of_twin_id=twin.fork_of_twin_id,
        fork_from_run_id=twin.fork_from_run_id,
        name=twin.name,
        status=twin.status.value if isinstance(twin.status, TwinStatus) else str(twin.status),
        description=twin.description,
        tags=list(twin.tags),
        lineage_hash=twin.lineage_hash,
        created_at=twin.created_at.isoformat(),
        created_by=twin.created_by,
    )
