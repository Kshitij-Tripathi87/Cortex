"""Test Simulation Gate — Program N.3.

Verifies:
- Digital Twin sandbox pre-execution dry-run
- Net financial benefit assertion
- Downstream stockout threshold validation
"""

from __future__ import annotations

from app.modules.execution.execution_models import ActionPlan, ExecutionSystem, PlanStatus
from app.modules.execution.simulation_gate import SimulationGate
from app.modules.rl.rl_models import ActionType, MitigationAction
from app.modules.world.state_projection import (
    create_initial_state,
    inventory_var_id,
    lead_time_var_id,
)
from app.modules.world.world_models import StateVariable, StateVariableType


class TestSimulationGate:
    def test_simulation_gate_dry_run_pass(self) -> None:
        """Simulation gate verifies positive net benefit in isolated sandbox."""
        w1 = StateVariable(
            variable_id=inventory_var_id("wh_1", "comp_01"),
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_1",
            entity_type="warehouse",
            value=800,
        )
        s1 = StateVariable(
            variable_id=lead_time_var_id("sup_1"),
            variable_type=StateVariableType.LEAD_TIME,
            entity_id="sup_1",
            entity_type="supplier",
            value=12,
        )

        state = create_initial_state(
            workspace_id="ws_gate",
            world_id="world_gate",
            graph_version=1,
            initial_variables={w1.variable_id: w1, s1.variable_id: s1},
        )

        plan = ActionPlan(
            plan_id="plan_gate_01",
            workspace_id="ws_gate",
            world_id="world_gate",
            objective="Expedite critical component",
            action=MitigationAction(
                ActionType.EXPEDITE_SUPPLIER, "sup_1", quantity=3.0, cost_usd=4500.0
            ),
            target_system=ExecutionSystem.PROCUREMENT,
            expected_cost_usd=4500.0,
            expected_benefit_usd=30000.0,
            expected_risk_score=0.1,
            affected_entities=["sup_1"],
            prerequisites=[],
            policy_version="v1.0",
            simulation_id=None,
            status=PlanStatus.SIMULATION_PENDING,
        )

        gate = SimulationGate()
        result = gate.verify_plan(plan, state)

        assert result.plan_id == "plan_gate_01"
        assert result.simulation_passed is True
        assert result.simulated_net_benefit_usd == 25500.0
        assert "PASS" in result.validation_log
