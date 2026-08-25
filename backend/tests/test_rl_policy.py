"""Test RL Policy & Value Networks — Program L.2.

Verifies:
- DQN Q-value scoring and action selection
- Deterministic heuristic baseline policy
- Policy recommendation generation with safety constraints
"""

from __future__ import annotations

from app.modules.rl.environment import SupplyChainEnv
from app.modules.rl.policy import DQNMitigationPolicy, RuleBasedBaselinePolicy
from app.modules.rl.rl_models import ActionType, MitigationAction
from app.modules.world.state_projection import (
    create_initial_state,
    inventory_var_id,
    lead_time_var_id,
)
from app.modules.world.world_models import StateVariable, StateVariableType


class TestRLPolicy:
    def test_dqn_policy_action_selection(self) -> None:
        """DQN selects action that optimizes Q-value scoring."""
        policy = DQNMitigationPolicy()

        w1 = StateVariable(
            variable_id=inventory_var_id("wh_1", "comp_01"),
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_1",
            entity_type="warehouse",
            value=100,
        )
        s1 = StateVariable(
            variable_id=lead_time_var_id("sup_1"),
            variable_type=StateVariableType.LEAD_TIME,
            entity_id="sup_1",
            entity_type="supplier",
            value=12,
        )

        state = create_initial_state(
            workspace_id="ws_policy",
            world_id="world_policy",
            graph_version=1,
            initial_variables={w1.variable_id: w1, s1.variable_id: s1},
        )

        env = SupplyChainEnv(initial_world_state=state)
        rec = policy.recommend_action(env)

        assert rec.recommended_action is not None
        assert rec.confidence > 0.80
        assert rec.safety_validated is True
        assert len(rec.candidate_actions) > 0

    def test_rule_based_baseline_policy_heuristic(self) -> None:
        """Baseline heuristic prioritizes stockout mitigation and delay expedites."""
        baseline = RuleBasedBaselinePolicy()

        w1 = StateVariable(
            variable_id=inventory_var_id("wh_0", "comp_01"),
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_0",
            entity_type="warehouse",
            value=0,  # Stockout
        )

        state = create_initial_state(
            workspace_id="ws_base",
            world_id="world_base",
            graph_version=1,
            initial_variables={w1.variable_id: w1},
        )

        env = SupplyChainEnv(initial_world_state=state)
        state_vec = env._extract_state_vector()

        legal_acts = [
            MitigationAction(ActionType.NOOP, "system"),
            MitigationAction(
                ActionType.TRANSFER_INVENTORY, "wh_surplus", target_entity_id="wh_0", quantity=100
            ),
        ]

        action = baseline.select_action(state_vec, legal_acts)
        assert action.action_type == ActionType.TRANSFER_INVENTORY
