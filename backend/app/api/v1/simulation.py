"""Simulation API v1 — Run simulations and retrieve results.

Endpoints:
- POST /simulation/run — Run a simulation
- GET /simulation/result/{simulation_id} — Get simulation result
- POST /simulation/batch — Run multiple simulations
- GET /simulation/scenarios — List available scenarios

Security:
- Every endpoint resolves a principal via get_current_user
- Workspace access enforced via require_workspace_access
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database import get_db
from app.infrastructure.security import AuthContext, get_current_user, require_workspace_access
from app.modules.simulation.scenario_registry import get_scenario_registry
from app.modules.simulation.simulation_engine import SimulationEngine
from app.modules.simulation.simulation_models import (
    SimulationConfig,
    TickGranularity,
)
from app.modules.twin.twin_models import DigitalTwin, TwinScenario, TwinStatus

router = APIRouter()
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Request/Response Models
# ─────────────────────────────────────────────────────────────────────────────


class SimulationConfigRequest(BaseModel):
    tick_granularity: TickGranularity = TickGranularity.DAY
    max_ticks: int = 30
    include_recovery: bool = True
    recovery_ticks: int = 7
    random_seed: int | None = None


class RunSimulationRequest(BaseModel):
    workspace_id: str
    twin_id: str
    scenario_id: str
    config: SimulationConfigRequest | None = None


class SimulationTickResponse(BaseModel):
    tick_id: str
    tick_number: int
    simulated_time: str
    state_hash: str
    metrics: dict[str, float]
    event_count: int


class SimulationResultResponse(BaseModel):
    simulation_id: str
    twin_id: str
    scenario_id: str
    status: str
    ticks_executed: int
    final_state_hash: str
    final_version: int
    timeline: list[SimulationTickResponse]
    final_metrics: dict[str, float]
    baseline_metrics: dict[str, float]
    impact: dict[str, Any] | None
    started_at: str | None
    completed_at: str | None
    duration_ms: float | None


class BatchSimulationRequest(BaseModel):
    workspace_id: str
    twin_id: str
    scenario_ids: list[str]
    config: SimulationConfigRequest | None = None


class BatchSimulationResponse(BaseModel):
    workspace_id: str
    scenario_count: int
    results: list[SimulationResultResponse]


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/simulation/run", response_model=SimulationResultResponse)
async def run_simulation(
    body: RunSimulationRequest,
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SimulationResultResponse:
    """Run a simulation against a digital twin."""
    require_workspace_access(body.workspace_id, auth)

    # Get scenario
    registry = get_scenario_registry()
    scenario = None
    for template in registry.list_all():
        try:
            candidate = template.factory(scenario_id=body.scenario_id, **template.optional_params)
            if candidate.scenario_id == body.scenario_id:
                scenario = candidate
                break
        except Exception as exc:  # noqa: BLE001 - factory may raise for any bad template
            logger.warning("Scenario factory failed for %s: %s", body.scenario_id, exc)
            continue
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")

    # Build config
    config = None
    if body.config:
        config = SimulationConfig(
            config_id="runtime-config",
            tick_granularity=body.config.tick_granularity,
            max_ticks=body.config.max_ticks,
            include_recovery=body.config.include_recovery,
            recovery_ticks=body.config.recovery_ticks,
            random_seed=body.config.random_seed,
        )

    # Load twin from the database, or fall back to a runtime stub twin.
    from app.modules.twin.twin_repository import TwinRepository

    twin = await TwinRepository(db).get_twin(body.twin_id)
    if not twin:
        twin = DigitalTwin(
            twin_id=body.twin_id,
            organization_id=body.workspace_id,
            workspace_id=body.workspace_id,
            parent_world_id=body.twin_id,
            parent_version=1,
            snapshot_id="placeholder",
            name="Runtime Twin",
            status=TwinStatus.READY,
        )

    engine = SimulationEngine(db)
    result = await engine.simulate(twin, scenario, config)

    return _result_to_response(result)


@router.post("/simulation/batch", response_model=BatchSimulationResponse)
async def run_batch_simulations(
    body: BatchSimulationRequest,
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BatchSimulationResponse:
    """Run multiple simulations against a twin."""
    require_workspace_access(body.workspace_id, auth)

    registry = get_scenario_registry()
    scenarios: list[TwinScenario] = []
    for sid in body.scenario_ids:
        found = None
        for template in registry.list_all():
            try:
                candidate = template.factory(scenario_id=sid, **template.optional_params)
                if candidate.scenario_id == sid:
                    found = candidate
                    break
            except Exception as exc:  # noqa: BLE001 - factory may raise for any bad template
                logger.warning("Scenario factory failed for %s: %s", sid, exc)
                continue
        if not found:
            raise HTTPException(status_code=404, detail=f"Scenario {sid} not found")
        scenarios.append(found)

    config = None
    if body.config:
        config = SimulationConfig(
            config_id="runtime-config",
            tick_granularity=body.config.tick_granularity,
            max_ticks=body.config.max_ticks,
        )

    from app.modules.twin.twin_repository import TwinRepository

    twin = await TwinRepository(db).get_twin(body.twin_id)
    if not twin:
        twin = DigitalTwin(
            twin_id=body.twin_id,
            organization_id=body.workspace_id,
            workspace_id=body.workspace_id,
            parent_world_id=body.twin_id,
            parent_version=1,
            snapshot_id="placeholder",
            name="Runtime Twin",
            status=TwinStatus.READY,
        )

    engine = SimulationEngine(db)
    results = await engine.simulate_batch(twin, scenarios, config)

    return BatchSimulationResponse(
        workspace_id=body.workspace_id,
        scenario_count=len(results),
        results=[_result_to_response(r) for r in results],
    )


@router.get("/simulation/result/{simulation_id}")
async def get_simulation_result(
    simulation_id: str,
    workspace_id: str = Query(...),
    auth: AuthContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get a simulation result by ID."""
    require_workspace_access(workspace_id, auth)
    # In production, this would look up from persistence
    raise HTTPException(status_code=501, detail="Requires simulation persistence layer")


@router.get("/simulation/scenarios")
async def list_scenarios(
    workspace_id: str = Query(...),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """List all available simulation scenarios."""
    require_workspace_access(workspace_id, auth)

    registry = get_scenario_registry()
    templates = registry.list_all()
    return {
        "workspace_id": workspace_id,
        "template_count": len(templates),
        "templates": [t.to_dict() for t in templates],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _result_to_response(result: Any) -> SimulationResultResponse:
    return SimulationResultResponse(
        simulation_id=result.simulation_id,
        twin_id=result.twin_id,
        scenario_id=result.scenario_id,
        status=result.status.value,
        ticks_executed=result.ticks_executed,
        final_state_hash=result.final_state_hash,
        final_version=result.final_version,
        timeline=[
            SimulationTickResponse(
                tick_id=t.tick_id,
                tick_number=t.tick_number,
                simulated_time=t.simulated_time.isoformat(),
                state_hash=t.state_hash,
                metrics=t.metrics,
                event_count=len(t.events),
            )
            for t in result.timeline
        ],
        final_metrics=result.final_metrics,
        baseline_metrics=result.baseline_metrics,
        impact=result.impact.to_dict() if result.impact else None,
        started_at=result.started_at.isoformat() if result.started_at else None,
        completed_at=result.completed_at.isoformat() if result.completed_at else None,
        duration_ms=result.duration_ms,
    )
