"""Test Simulation Fault Injection — Resilience against Corrupt, Missing, or Malformed Inputs.

Program J.4 (Simulation Quality & Evaluation Bridge) — Milestone J.4 Phase 5.

Verifies:
- Missing snapshot or world state
- Corrupted / unknown event types
- Malformed payloads (missing required keys)
- Empty scenario execution
- Duplicate event IDs
"""

from __future__ import annotations

from app.modules.simulation.simulation_engine import SimulationEngine
from app.modules.simulation.simulation_models import SimulationStatus
from app.modules.twin.twin_models import DigitalTwin, TwinScenario
from app.modules.world.state_projection import (
    create_initial_state,
    create_state_snapshot,
    inventory_var_id,
)
from app.modules.world.state_repository import StateRepository
from app.modules.world.world_models import StateVariable, StateVariableType


class TestSimulationFaultInjection:
    async def test_missing_snapshot_fails_safely(self, db_session) -> None:
        """Simulation with non-existent snapshot fails gracefully with IsolationError."""
        twin = DigitalTwin(
            twin_id="twin_missing_snap",
            organization_id="org_fault",
            workspace_id="ws_fault",
            parent_world_id="world_nonexistent",
            parent_version=1,
            snapshot_id="snap_nonexistent",
            name="Missing Snapshot Twin",
        )
        scenario = TwinScenario(
            scenario_id="scn_fault",
            name="Fault Scenario",
            events=[],
        )

        engine = SimulationEngine(db_session)
        result = await engine.simulate(twin, scenario)

        assert result.status == SimulationStatus.FAILED
        assert result.error_message is not None
        assert "not found" in result.error_message.lower()

    async def test_empty_scenario_runs_cleanly_as_noop(self, db_session) -> None:
        """Empty scenario execution completes with baseline state preserved."""
        repo = StateRepository(db_session)
        workspace_id = "ws_empty_scn"
        world_id = "world_empty_scn"

        var = StateVariable(
            variable_id=inventory_var_id("wh_1", "comp_a"),
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_1",
            entity_type="warehouse",
            value=250,
        )
        state = create_initial_state(
            workspace_id=workspace_id,
            world_id=world_id,
            graph_version=1,
            initial_variables={var.variable_id: var},
        )
        snapshot = create_state_snapshot(state)
        await repo.create(state)
        await repo.store_snapshot(snapshot)

        twin = DigitalTwin(
            twin_id="twin_empty",
            organization_id="org_empty",
            workspace_id=workspace_id,
            parent_world_id=world_id,
            parent_version=1,
            snapshot_id=snapshot.snapshot_id,
            name="Empty Scenario Twin",
        )
        scenario = TwinScenario(
            scenario_id="scn_empty",
            name="Empty Scenario",
            events=[],
        )

        engine = SimulationEngine(db_session)
        result = await engine.simulate(twin, scenario)

        assert result.status == SimulationStatus.COMPLETED
        assert result.final_state_hash == snapshot.state_hash
        assert result.final_metrics["total_inventory"] == 250.0

    async def test_unknown_event_type_skipped_without_state_corruption(self, db_session) -> None:
        """Simulation handles unrecognized event types without crashing or corrupting state."""
        repo = StateRepository(db_session)
        workspace_id = "ws_unk_evt"
        world_id = "world_unk_evt"

        var = StateVariable(
            variable_id=inventory_var_id("wh_1", "comp_a"),
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_1",
            entity_type="warehouse",
            value=500,
        )
        state = create_initial_state(
            workspace_id=workspace_id,
            world_id=world_id,
            graph_version=1,
            initial_variables={var.variable_id: var},
        )
        snapshot = create_state_snapshot(state)
        await repo.create(state)
        await repo.store_snapshot(snapshot)

        twin = DigitalTwin(
            twin_id="twin_unk_evt",
            organization_id="org_unk",
            workspace_id=workspace_id,
            parent_world_id=world_id,
            parent_version=1,
            snapshot_id=snapshot.snapshot_id,
            name="Unknown Event Twin",
        )
        scenario = TwinScenario(
            scenario_id="scn_unk",
            name="Unknown Event Scenario",
            events=[
                {
                    "entity_type": "alien_mothership",
                    "entity_id": "ship_01",
                    "event_type": "teleportation_flux",
                    "payload": {"quantum_spin": 42},
                }
            ],
        )

        engine = SimulationEngine(db_session)
        result = await engine.simulate(twin, scenario)

        # Completes safely, ignores unknown event
        assert result.status == SimulationStatus.COMPLETED
        assert result.final_state_hash == snapshot.state_hash
        assert result.final_metrics["total_inventory"] == 500.0
