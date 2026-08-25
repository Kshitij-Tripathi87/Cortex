"""Test Counterfactual Consistency — Bounded Causal Footprint Invariant.

Program J.4 (Simulation Quality & Evaluation Bridge) — Milestone J.4 Phase 1 & 3.

Verifies:
- Counterfactual Branching: Twin A (Disruption baseline) vs Twin B (Disruption + Mitigation)
- Expected Changes: Only targeted mitigation variables change
- Forbidden Changes: Unrelated suppliers, factories, demands, and workspaces have ZERO modifications
- Bounded Causal Footprint: Mathematical verification of isolation
"""

from __future__ import annotations

from app.modules.evaluation.simulation_evaluation import SimulationEvaluationHarness
from app.modules.twin.twin_validation_helpers import make_fake_event
from app.modules.world.state_projection import (
    apply_transition,
    capacity_var_id,
    create_initial_state,
    demand_var_id,
    inventory_var_id,
    project_event_to_transition,
    supplier_health_var_id,
)
from app.modules.world.world_models import StateVariable, StateVariableType


class TestCounterfactualConsistency:
    def test_counterfactual_mitigation_bounded_causal_footprint(self) -> None:
        """Twin A (raw disruption) vs Twin B (disruption + inventory transfer) changes ONLY expected variables."""
        wh_1_inv_id = inventory_var_id("wh_east", "comp_alpha")
        wh_2_inv_id = inventory_var_id("wh_west", "comp_alpha")
        sup_health_id = supplier_health_var_id("sup_unrelated")
        fac_cap_id = capacity_var_id("fac_central")
        cust_dem_id = demand_var_id("prod_omega")

        wh_1_inv = StateVariable(
            variable_id=wh_1_inv_id,
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_east",
            entity_type="warehouse",
            value=50,
        )
        wh_2_inv = StateVariable(
            variable_id=wh_2_inv_id,
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_west",
            entity_type="warehouse",
            value=500,
        )
        sup_health = StateVariable(
            variable_id=sup_health_id,
            variable_type=StateVariableType.SUPPLIER_HEALTH,
            entity_id="sup_unrelated",
            entity_type="supplier",
            value=0.98,
        )
        fac_cap = StateVariable(
            variable_id=fac_cap_id,
            variable_type=StateVariableType.CAPACITY,
            entity_id="fac_central",
            entity_type="factory",
            value=100.0,
        )
        cust_dem = StateVariable(
            variable_id=cust_dem_id,
            variable_type=StateVariableType.DEMAND,
            entity_id="prod_omega",
            entity_type="component",
            value=250,
        )

        base_state = create_initial_state(
            workspace_id="ws_cf_test",
            world_id="world_cf_test",
            graph_version=1,
            initial_variables={
                wh_1_inv.variable_id: wh_1_inv,
                wh_2_inv.variable_id: wh_2_inv,
                sup_health.variable_id: sup_health,
                fac_cap.variable_id: fac_cap,
                cust_dem.variable_id: cust_dem,
            },
        )

        # 2. Simulate Twin A: Supplier disruption strikes wh_east consumption without mitigation
        twin_a_state = base_state
        evt_draw = make_fake_event(
            event_id="evt_draw_a",
            world_id="world_cf_test",
            workspace_id="ws_cf_test",
            entity_type="warehouse",
            entity_id="wh_east",
            event_type="inventory_changed",
            payload={
                "warehouse_id": "wh_east",
                "component_id": "comp_alpha",
                "quantity_change": -100,
            },
        )
        tr_a = project_event_to_transition(twin_a_state, evt_draw)
        assert tr_a is not None
        twin_a_state = apply_transition(twin_a_state, tr_a)
        assert float(twin_a_state.variables[wh_1_inv.variable_id].raw_value) == -50.0  # Stockout

        # 3. Simulate Twin B: Disruption strikes wh_east + Mitigation: transfer 150 from wh_west to wh_east
        twin_b_state = base_state
        # Apply same shock
        tr_b_shock = project_event_to_transition(twin_b_state, evt_draw)
        assert tr_b_shock is not None
        twin_b_state = apply_transition(twin_b_state, tr_b_shock)

        # Apply mitigation: transfer -150 from wh_west and +150 to wh_east
        evt_transfer_source = make_fake_event(
            event_id="evt_trf_src",
            world_id="world_cf_test",
            workspace_id="ws_cf_test",
            entity_type="warehouse",
            entity_id="wh_west",
            event_type="inventory_changed",
            payload={
                "warehouse_id": "wh_west",
                "component_id": "comp_alpha",
                "quantity_change": -150,
            },
        )
        tr_src = project_event_to_transition(twin_b_state, evt_transfer_source)
        assert tr_src is not None
        twin_b_state = apply_transition(twin_b_state, tr_src)

        evt_transfer_dest = make_fake_event(
            event_id="evt_trf_dst",
            world_id="world_cf_test",
            workspace_id="ws_cf_test",
            entity_type="warehouse",
            entity_id="wh_east",
            event_type="inventory_changed",
            payload={
                "warehouse_id": "wh_east",
                "component_id": "comp_alpha",
                "quantity_change": 150,
            },
        )
        tr_dst = project_event_to_transition(twin_b_state, evt_transfer_dest)
        assert tr_dst is not None
        twin_b_state = apply_transition(twin_b_state, tr_dst)

        assert (
            float(twin_b_state.variables[wh_1_inv.variable_id].raw_value) == 100.0
        )  # Stockout prevented!
        assert (
            float(twin_b_state.variables[wh_2_inv.variable_id].raw_value) == 350.0
        )  # West reduced

        # 4. Evaluate counterfactual consistency via evaluation harness
        harness = SimulationEvaluationHarness()
        cf_report = harness.verify_counterfactual_consistency(
            baseline_state=base_state,
            disruption_state=twin_a_state,
            mitigation_state=twin_b_state,
            expected_modified_prefixes=[
                "inventory.warehouse.comp_alpha.wh_east",
                "inventory.warehouse.comp_alpha.wh_west",
            ],
            forbidden_modified_prefixes=[
                "supplier_health.",
                "capacity.",
                "demand.",
            ],
        )

        assert cf_report["consistent"] is True
        assert cf_report["consistency_score"] == 1.0
        assert len(cf_report["forbidden_violations"]) == 0
        assert len(cf_report["expected_modifications"]) == 2

        # Verify completely untouched invariants
        assert (
            twin_b_state.variables[sup_health.variable_id].raw_value
            == base_state.variables[sup_health.variable_id].raw_value
        )
        assert (
            twin_b_state.variables[fac_cap.variable_id].raw_value
            == base_state.variables[fac_cap.variable_id].raw_value
        )
        assert (
            twin_b_state.variables[cust_dem.variable_id].raw_value
            == base_state.variables[cust_dem.variable_id].raw_value
        )
