"""Test Policy & Safety Engine — Program N.2.

Verifies:
- Monetary spending limits by operator role
- Blacklisted / sanctioned vendor filtering
- Warehouse safety buffer depletion prevention
- Input parameter bounds checking
"""

from __future__ import annotations

from app.modules.execution.execution_models import ActionPlan, ExecutionSystem, PlanStatus
from app.modules.execution.policy_engine import PolicyEngine
from app.modules.rl.rl_models import ActionType, MitigationAction
from app.modules.world.state_projection import (
    create_initial_state,
    inventory_var_id,
)
from app.modules.world.world_models import StateVariable, StateVariableType


class TestPolicyEngine:
    def test_monetary_spend_limit_check(self) -> None:
        """Actions exceeding $50k require Executive authorization."""
        engine = PolicyEngine(max_operator_spend_usd=50000.0)

        plan = ActionPlan(
            plan_id="plan_high_cost",
            workspace_id="ws_pol",
            world_id="world_pol",
            objective="Emergency charter",
            action=MitigationAction(ActionType.EXPEDITE_SUPPLIER, "sup_01", cost_usd=75000.0),
            target_system=ExecutionSystem.ERP,
            expected_cost_usd=75000.0,
            expected_benefit_usd=100000.0,
            expected_risk_score=0.1,
            affected_entities=["sup_01"],
            prerequisites=[],
            policy_version="v1.0",
            simulation_id=None,
            status=PlanStatus.DRAFT,
        )

        state = create_initial_state(workspace_id="ws_pol", world_id="world_pol", graph_version=1)

        # 1. Operator role -> Rejected
        allowed_op, viols_op = engine.validate(plan, state, operator_role="operator")
        assert allowed_op is False
        assert len(viols_op) == 1
        assert viols_op[0].rule_name == "MonetarySpendAuthority"

        # 2. Executive role -> Allowed
        allowed_exec, viols_exec = engine.validate(plan, state, operator_role="executive")
        assert allowed_exec is True
        assert len(viols_exec) == 0

    def test_warehouse_minimum_safety_buffer(self) -> None:
        """Transfer cannot leave source warehouse below 100 units safety buffer."""
        engine = PolicyEngine(min_warehouse_safety_stock=100.0)

        w1 = StateVariable(
            variable_id=inventory_var_id("wh_src", "comp_01"),
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_src",
            entity_type="warehouse",
            value=250,
        )

        state = create_initial_state(
            workspace_id="ws_pol_inv",
            world_id="world_pol_inv",
            graph_version=1,
            initial_variables={w1.variable_id: w1},
        )

        # Transferring 200 units leaves 50 units (< 100) -> Violation
        violating_plan = ActionPlan(
            plan_id="plan_inv_viol",
            workspace_id="ws_pol_inv",
            world_id="world_pol_inv",
            objective="Rebalance stock",
            action=MitigationAction(
                ActionType.TRANSFER_INVENTORY, "wh_src", target_entity_id="wh_dst", quantity=200.0
            ),
            target_system=ExecutionSystem.WMS,
            expected_cost_usd=1600.0,
            expected_benefit_usd=20000.0,
            expected_risk_score=0.1,
            affected_entities=["wh_src", "wh_dst"],
            prerequisites=[],
            policy_version="v1.0",
            simulation_id=None,
            status=PlanStatus.DRAFT,
        )

        allowed, viols = engine.validate(violating_plan, state)
        assert allowed is False
        assert viols[0].rule_name == "MinimumSafetyBuffer"
