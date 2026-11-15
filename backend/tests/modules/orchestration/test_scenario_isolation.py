"""Scenario-1 acceptance tests — isolated scenarios over production World State.

Flow under test:

    Initialize production World State -> run scenario from the same
    snapshot the task runtime uses -> parameter changes -> simulation
        -> outcome

The key invariant — scenario mutation must never write to production World
State — is asserted at the database level: row counts, versions, events, and
variable values for the production world_id are compared before and after.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.events.event_models import DemandChanged, InventoryChanged
from app.modules.orchestration.scenario import ScenarioIsolationError, ScenarioService
from app.modules.world.state_repository import StateRepository, WorldStateDB, WorldStateEventDB
from app.modules.world.world_models import StateVariable, StateVariableType
from app.modules.world.world_service import WorldStateService

TENANT = uuid4()
WORKSPACE = uuid4()
WORLD_ID = "wh-prod-main"
INVENTORY_VAR = "inventory.warehouse.comp_042.wh_001"
DEMAND_VAR = "demand.component.comp_042"


async def make_db(tmp_path: str):
    from sqlalchemy import MetaData

    from app.infrastructure.database import Base
    from app.modules.world import state_repository  # noqa: F401

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}", echo=False)
    metadata = MetaData()
    for table in Base.metadata.sorted_tables:
        if table.name.startswith("world_"):
            table.to_metadata(metadata)
    for table in metadata.tables.values():
        table.schema = None
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await init_world(factory, WORLD_ID, inventory_qty=500, demand_qty=25)
    return factory


async def init_world(factory, world_id: str, *, inventory_qty: int, demand_qty: int) -> None:
    async with factory() as session:
        service = WorldStateService(repository=StateRepository(db=session))
        await service.initialize_world(
            workspace_id=str(WORKSPACE),
            world_id=world_id,
            initial_variables={
                INVENTORY_VAR: StateVariable.from_raw_value(
                    INVENTORY_VAR,
                    StateVariableType.INVENTORY,
                    "comp_042",
                    "warehouse",
                    inventory_qty,
                    unit="units",
                ),
                DEMAND_VAR: StateVariable.from_raw_value(
                    DEMAND_VAR,
                    StateVariableType.DEMAND,
                    "comp_042",
                    "component",
                    demand_qty,
                    unit="units/day",
                ),
            },
        )


async def production_snapshot(factory) -> dict[str, Any]:
    """Database-level snapshot of every production world record."""

    async with factory() as session:
        repo = StateRepository(db=session)
        states = (
            (await session.execute(select(WorldStateDB).where(WorldStateDB.world_id == WORLD_ID)))
            .scalars()
            .all()
        )
        events = (
            (
                await session.execute(
                    select(WorldStateEventDB).where(WorldStateEventDB.world_id == WORLD_ID)
                )
            )
            .scalars()
            .all()
        )
        latest = await repo.get_latest(world_id=WORLD_ID, workspace_id=str(WORKSPACE))
        assert latest is not None
        return {
            "state_rows": len(states),
            "event_rows": len(events),
            "version": latest.version,
            "variables": {
                variable_id: variable.raw_value
                for variable_id, variable in latest.variables.items()
            },
        }


def demand_event(change: int) -> DemandChanged:
    return DemandChanged(
        event_id=str(uuid4()),
        world_id="deliberately-wrong-production-target",
        workspace_id=str(WORKSPACE),
        entity_type="component",
        entity_id="comp_042",
        demand_change=change,
    )


def inventory_event(change: int) -> InventoryChanged:
    return InventoryChanged(
        event_id=str(uuid4()),
        world_id="deliberately-wrong-production-target",
        workspace_id=str(WORKSPACE),
        entity_type="warehouse",
        entity_id="wh_001",
        warehouse_id="wh_001",
        component_id="comp_042",
        quantity_change=change,
        reason="scenario",
    )


@pytest.mark.asyncio
async def test_scenario_consumes_the_same_world_state_snapshot_as_the_task_runtime(tmp_path):
    factory = await make_db(str(tmp_path / "t.sqlite3"))
    service = ScenarioService(session_factory=factory)

    outcome = await service.run_scenario(
        workspace_id=str(WORKSPACE),
        world_id=WORLD_ID,
        baseline_version=1,
        parameter_events=[demand_event(50)],
    )

    # The baseline is the exact production version the task runtime reads.
    assert outcome.baseline_world_id == WORLD_ID
    assert outcome.baseline_version == 1
    assert outcome.scenario_version == 2
    # The parameter change applied on top of the baseline values.
    assert outcome.deltas == {DEMAND_VAR: 50}
    assert outcome.state.get_variable(DEMAND_VAR).raw_value == 75


@pytest.mark.asyncio
async def test_scenario_mutation_never_writes_production_world_state_db_level(tmp_path):
    factory = await make_db(str(tmp_path / "t.sqlite3"))
    before = await production_snapshot(factory)
    assert before["event_rows"] == 0

    service = ScenarioService(session_factory=factory)
    outcome = await service.run_scenario(
        workspace_id=str(WORKSPACE),
        world_id=WORLD_ID,
        baseline_version=1,
        parameter_events=[inventory_event(-200), demand_event(50)],
    )

    after = await production_snapshot(factory)

    # Database-level invariant: the production world is byte-for-byte
    # unchanged — same row counts, same version, same values, no new events.
    assert after["state_rows"] == before["state_rows"]
    assert after["event_rows"] == before["event_rows"]
    assert after["version"] == before["version"]
    assert after["variables"] == before["variables"]

    # The scenario's events live only under the isolated scenario world id —
    # even though both parameter events were mis-specified against production.
    async with factory() as session:
        scenario_events = (
            (
                await session.execute(
                    select(WorldStateEventDB).where(
                        WorldStateEventDB.world_id == outcome.scenario_world_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(scenario_events) == 2
        assert {event.event_type for event in scenario_events} == {
            "inventory_changed",
            "demand_change",
        }
        production_events = (
            (
                await session.execute(
                    select(WorldStateEventDB).where(WorldStateEventDB.world_id == WORLD_ID)
                )
            )
            .scalars()
            .all()
        )
        assert len(production_events) == 0


@pytest.mark.asyncio
async def test_scenario_world_lineage_records_parent_snapshot(tmp_path):
    factory = await make_db(str(tmp_path / "t.sqlite3"))
    service = ScenarioService(session_factory=factory)
    outcome = await service.run_scenario(
        workspace_id=str(WORKSPACE),
        world_id=WORLD_ID,
        baseline_version=1,
        parameter_events=[demand_event(10)],
    )

    async with factory() as session:
        repo = StateRepository(db=session)
        metadata = await repo.get_metadata(outcome.scenario_world_id, str(WORKSPACE))
        assert metadata is not None
        assert metadata.source == "simulation"
        assert metadata.parent_world_id == WORLD_ID
        assert metadata.parent_version == 1
        assert "scenario" in metadata.tags

        state = await repo.get_latest(
            world_id=outcome.scenario_world_id, workspace_id=str(WORKSPACE)
        )
        assert state is not None
        assert state.metadata["parent_world_id"] == WORLD_ID
        assert state.metadata["parent_version"] == 1


@pytest.mark.asyncio
async def test_scenario_is_deterministic_across_runs(tmp_path):
    factory = await make_db(str(tmp_path / "t.sqlite3"))
    service = ScenarioService(session_factory=factory)

    first = await service.run_scenario(
        workspace_id=str(WORKSPACE),
        world_id=WORLD_ID,
        baseline_version=1,
        parameter_events=[inventory_event(-100), demand_event(25)],
    )
    second = await service.run_scenario(
        workspace_id=str(WORKSPACE),
        world_id=WORLD_ID,
        baseline_version=1,
        parameter_events=[inventory_event(-100), demand_event(25)],
    )

    assert first.deltas == second.deltas
    assert first.variables_changed == second.variables_changed
    assert first.scenario_version == second.scenario_version
    assert first.applied_event_ids != second.applied_event_ids  # distinct worlds

    # Both runs left production untouched.
    snapshot = await production_snapshot(factory)
    assert snapshot["version"] == 1
    assert snapshot["variables"] == {INVENTORY_VAR: 500, DEMAND_VAR: 25}


@pytest.mark.asyncio
async def test_scenario_from_missing_baseline_fails_closed(tmp_path):
    factory = await make_db(str(tmp_path / "t.sqlite3"))
    service = ScenarioService(session_factory=factory)

    with pytest.raises(ScenarioIsolationError, match="no version 99"):
        await service.run_scenario(
            workspace_id=str(WORKSPACE),
            world_id=WORLD_ID,
            baseline_version=99,
            parameter_events=[demand_event(10)],
        )


@pytest.mark.asyncio
async def test_scenario_isolation_violation_is_raised_explicitly(tmp_path):
    factory = await make_db(str(tmp_path / "t.sqlite3"))
    production_service = WorldStateService(repository=StateRepository(db=factory()))
    service = ScenarioService(
        session_factory=factory, world_service_factory=lambda: production_service
    )
    original_submit = production_service.submit_event

    # Simulate a regression that bypasses the structural redirect: parameter
    # events leak back to the production world id. The runner's
    # post-simulation version verification must catch the drift.
    async def leaking_submit(event, *, idempotency_key=None, create_snapshot_if_interval=True):
        production_event = replace(event, world_id=WORLD_ID)
        return await original_submit(
            production_event,
            idempotency_key=idempotency_key,
            create_snapshot_if_interval=create_snapshot_if_interval,
        )

    production_service.submit_event = leaking_submit  # type: ignore[method-assign]

    with pytest.raises(ScenarioIsolationError, match="production World State"):
        await service.run_scenario(
            workspace_id=str(WORKSPACE),
            world_id=WORLD_ID,
            baseline_version=1,
            parameter_events=[demand_event(50)],
        )
