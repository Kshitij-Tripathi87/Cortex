"""Test RL Supply Chain Environment — Program L.1.

Verifies:
- MDP State space vector extraction
- Action execution and state transition application
- Financial / operational reward calculation
- Legal action discovery
"""

from __future__ import annotations

from app.modules.rl.environment import SupplyChainEnv
from app.modules.rl.rl_models import ActionType, MitigationAction
from app.modules.world.state_projection import (
    create_initial_state,
    inventory_var_id,
    lead_time_var_id,
)
from app.modules.world.world_models import StateVariable, StateVariableType


class TestRLEnvironment:
    def test_environment_reset_and_state_vector(self) -> None:
        """Environment reset produces proper feature vector and summary statistics."""
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
            value=7,
        )

        state = create_initial_state(
            workspace_id="ws_rl_env",
            world_id="world_rl_env",
            graph_version=1,
            initial_variables={w1.variable_id: w1, s1.variable_id: s1},
        )

        env = SupplyChainEnv(initial_world_state=state, max_steps=5)
        vec = env.reset()

        assert vec.total_inventory == 800.0
        assert vec.max_lead_time_days == 7.0
        assert vec.step_number == 0
        assert len(vec.state_features) >= 2

    def test_step_action_execution_and_reward(self) -> None:
        """Applying an expedite action modifies supplier state and yields step result."""
        w1 = StateVariable(
            variable_id=inventory_var_id("wh_1", "comp_01"),
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_1",
            entity_type="warehouse",
            value=500,
        )
        s1 = StateVariable(
            variable_id=lead_time_var_id("sup_1"),
            variable_type=StateVariableType.LEAD_TIME,
            entity_id="sup_1",
            entity_type="supplier",
            value=14,
        )

        state = create_initial_state(
            workspace_id="ws_rl_step",
            world_id="world_rl_step",
            graph_version=1,
            initial_variables={w1.variable_id: w1, s1.variable_id: s1},
        )

        env = SupplyChainEnv(initial_world_state=state, max_steps=3)
        env.reset()

        action = MitigationAction(
            action_type=ActionType.EXPEDITE_SUPPLIER,
            entity_id="sup_1",
            quantity=3.0,
            cost_usd=4500.0,
        )

        step_res = env.step(action)

        assert step_res.done is False
        assert step_res.next_state.step_number == 1
        assert "revenue_at_risk_delta" in step_res.kpi_deltas
        assert step_res.kpi_deltas["action_cost_usd"] == 4500.0

    def test_legal_action_discovery(self) -> None:
        """Environment discovers candidate inventory transfers and supplier expedites."""
        w1 = StateVariable(
            variable_id=inventory_var_id("wh_alpha", "comp_01"),
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_alpha",
            entity_type="warehouse",
            value=1000,
        )
        w2 = StateVariable(
            variable_id=inventory_var_id("wh_beta", "comp_01"),
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_beta",
            entity_type="warehouse",
            value=50,
        )
        s1 = StateVariable(
            variable_id=lead_time_var_id("sup_gamma"),
            variable_type=StateVariableType.LEAD_TIME,
            entity_id="sup_gamma",
            entity_type="supplier",
            value=10,
        )

        state = create_initial_state(
            workspace_id="ws_rl_actions",
            world_id="world_rl_actions",
            graph_version=1,
            initial_variables={w1.variable_id: w1, w2.variable_id: w2, s1.variable_id: s1},
        )

        env = SupplyChainEnv(initial_world_state=state)
        actions = env.get_legal_actions()

        action_types = {a.action_type for a in actions}
        assert ActionType.NOOP in action_types
        assert ActionType.TRANSFER_INVENTORY in action_types
        assert ActionType.EXPEDITE_SUPPLIER in action_types
