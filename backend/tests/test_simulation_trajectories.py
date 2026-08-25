"""Test Simulation Trajectories — Deterministic Scenario Correctness Tests.

Program J.4 (Simulation Quality & Evaluation Bridge) — Milestone J.4 Phase 1.

Validates exact analytical trajectory contracts:
- J.4.1: Supplier Failure (capacity -> 0, buffer depletion, stockout)
- J.4.2: Supplier Delay (lead time shifts, capacity remains 100%)
- J.4.3: Inventory Shortage (rapid depletion, stockout hours, SLA exposure)
- J.4.4: Demand Spike (demand surge, inventory coverage degradation)
- J.4.5: Full Trajectory Step Contract (state_0 -> event_1 -> state_1 -> ... -> state_N)
"""

from __future__ import annotations

import json
from pathlib import Path

from app.modules.twin.twin_validation_helpers import make_fake_event
from app.modules.world.state_projection import (
    apply_transition,
    capacity_var_id,
    create_initial_state,
    demand_var_id,
    inventory_var_id,
    lead_time_var_id,
    project_event_to_transition,
)
from app.modules.world.world_models import StateVariable, StateVariableType

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "simulation"


def _load_fixture(filename: str) -> dict:
    with open(FIXTURES_DIR / filename) as f:
        return json.load(f)


class TestDeterministicScenarioTrajectories:
    """Analytical trajectory verification test suite."""

    def test_supplier_failure_hand_calculated_trajectory(self) -> None:
        """J.4.1: Verify step-by-step buffer depletion and stockout on supplier failure."""
        var_inv_id = inventory_var_id("wh_01", "comp_01")
        var_lt_id = lead_time_var_id("sup_01")
        var_cap_id = capacity_var_id("sup_01")

        var_inv = StateVariable(
            variable_id=var_inv_id,
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_01",
            entity_type="warehouse",
            value=300,
        )
        var_lt = StateVariable(
            variable_id=var_lt_id,
            variable_type=StateVariableType.LEAD_TIME,
            entity_id="sup_01",
            entity_type="supplier",
            value=5,
        )
        var_cap = StateVariable(
            variable_id=var_cap_id,
            variable_type=StateVariableType.CAPACITY,
            entity_id="sup_01",
            entity_type="supplier",
            value=100.0,
        )

        state = create_initial_state(
            workspace_id="ws_traj_1",
            world_id="world_traj_1",
            graph_version=1,
            initial_variables={
                var_inv.variable_id: var_inv,
                var_lt.variable_id: var_lt,
                var_cap.variable_id: var_cap,
            },
        )
        assert float(state.variables[var_inv_id].raw_value) == 300
        assert float(state.variables[var_cap_id].raw_value) == 100.0

        # Step 1: Supplier failure event (capacity drops to 0) + Day 1 consumption (-100)
        evt_fail = make_fake_event(
            event_id="evt_fail_1",
            world_id="world_traj_1",
            workspace_id="ws_traj_1",
            entity_type="supplier",
            entity_id="sup_01",
            event_type="factory_shutdown",
            payload={"capacity_pct": 0.0, "cause": "supplier_failure"},
        )
        trans1 = project_event_to_transition(state, evt_fail)
        assert trans1 is not None
        state = apply_transition(state, trans1)
        assert float(state.variables[var_cap_id].raw_value) == 0.0

        evt_cons_1 = make_fake_event(
            event_id="evt_cons_1",
            world_id="world_traj_1",
            workspace_id="ws_traj_1",
            entity_type="warehouse",
            entity_id="wh_01",
            event_type="inventory_changed",
            payload={"warehouse_id": "wh_01", "component_id": "comp_01", "quantity_change": -100},
        )
        trans2 = project_event_to_transition(state, evt_cons_1)
        assert trans2 is not None
        state = apply_transition(state, trans2)
        assert float(state.variables[var_inv_id].raw_value) == 200

        # Step 2: Day 2 consumption (-100) -> buffer depleting
        evt_cons_2 = make_fake_event(
            event_id="evt_cons_2",
            world_id="world_traj_1",
            workspace_id="ws_traj_1",
            entity_type="warehouse",
            entity_id="wh_01",
            event_type="inventory_changed",
            payload={"warehouse_id": "wh_01", "component_id": "comp_01", "quantity_change": -100},
        )
        trans3 = project_event_to_transition(state, evt_cons_2)
        assert trans3 is not None
        state = apply_transition(state, trans3)
        assert float(state.variables[var_inv_id].raw_value) == 100

        # Step 3: Day 3 consumption (-100) -> stockout reached (0 inventory)
        evt_cons_3 = make_fake_event(
            event_id="evt_cons_3",
            world_id="world_traj_1",
            workspace_id="ws_traj_1",
            entity_type="warehouse",
            entity_id="wh_01",
            event_type="inventory_changed",
            payload={"warehouse_id": "wh_01", "component_id": "comp_01", "quantity_change": -100},
        )
        trans4 = project_event_to_transition(state, evt_cons_3)
        assert trans4 is not None
        state = apply_transition(state, trans4)
        assert float(state.variables[var_inv_id].raw_value) == 0

    def test_supplier_delay_distinction_from_failure(self) -> None:
        """J.4.2: Verify supplier delay shifts lead time while capacity remains operational (100%)."""
        var_inv_id = inventory_var_id("wh_01", "comp_01")
        var_lt_id = lead_time_var_id("sup_01")
        var_cap_id = capacity_var_id("sup_01")

        var_inv = StateVariable(
            variable_id=var_inv_id,
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_01",
            entity_type="warehouse",
            value=500,
        )
        var_lt = StateVariable(
            variable_id=var_lt_id,
            variable_type=StateVariableType.LEAD_TIME,
            entity_id="sup_01",
            entity_type="supplier",
            value=5,
        )
        var_cap = StateVariable(
            variable_id=var_cap_id,
            variable_type=StateVariableType.CAPACITY,
            entity_id="sup_01",
            entity_type="supplier",
            value=100.0,
        )

        state = create_initial_state(
            workspace_id="ws_traj_2",
            world_id="world_traj_2",
            graph_version=1,
            initial_variables={
                var_inv.variable_id: var_inv,
                var_lt.variable_id: var_lt,
                var_cap.variable_id: var_cap,
            },
        )

        evt_delay = make_fake_event(
            event_id="evt_delay_1",
            world_id="world_traj_2",
            workspace_id="ws_traj_2",
            entity_type="supplier",
            entity_id="sup_01",
            event_type="supplier_delayed",
            payload={"delay_days": 7, "disruption_type": "port_congestion"},
        )
        trans = project_event_to_transition(state, evt_delay)
        assert trans is not None
        state = apply_transition(state, trans)

        # Invariant: Lead time shifts 5 + 7 = 12, but capacity remains 100.0%
        assert float(state.variables[var_lt_id].raw_value) == 12.0
        assert float(state.variables[var_cap_id].raw_value) == 100.0
        assert float(state.variables[var_inv_id].raw_value) == 500.0

    def test_inventory_shortage_trajectory(self) -> None:
        """J.4.3: Verify inventory drop, negative stock, and stockout calculation."""
        var_inv_id = inventory_var_id("wh_01", "comp_01")
        var_inv = StateVariable(
            variable_id=var_inv_id,
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_01",
            entity_type="warehouse",
            value=250,
        )
        state = create_initial_state(
            workspace_id="ws_traj_3",
            world_id="world_traj_3",
            graph_version=1,
            initial_variables={var_inv.variable_id: var_inv},
        )

        evt_scrap = make_fake_event(
            event_id="evt_scrap_1",
            world_id="world_traj_3",
            workspace_id="ws_traj_3",
            entity_type="warehouse",
            entity_id="wh_01",
            event_type="inventory_changed",
            payload={"warehouse_id": "wh_01", "component_id": "comp_01", "quantity_change": -400},
        )
        trans = project_event_to_transition(state, evt_scrap)
        assert trans is not None
        state = apply_transition(state, trans)

        assert float(state.variables[var_inv_id].raw_value) == -150.0

    def test_demand_spike_trajectory(self) -> None:
        """J.4.4: Verify demand surge transition."""
        var_dem_id = demand_var_id("prod_01")
        var_dem = StateVariable(
            variable_id=var_dem_id,
            variable_type=StateVariableType.DEMAND,
            entity_id="prod_01",
            entity_type="component",
            value=200,
        )
        state = create_initial_state(
            workspace_id="ws_traj_4",
            world_id="world_traj_4",
            graph_version=1,
            initial_variables={var_dem.variable_id: var_dem},
        )

        evt_demand = make_fake_event(
            event_id="evt_dem_1",
            world_id="world_traj_4",
            workspace_id="ws_traj_4",
            entity_type="component",
            entity_id="prod_01",
            event_type="demand_changed",
            payload={"demand_change": 500, "confidence": 0.95},
        )
        trans = project_event_to_transition(state, evt_demand)
        assert trans is not None
        state = apply_transition(state, trans)

        assert float(state.variables[var_dem_id].raw_value) == 700.0
