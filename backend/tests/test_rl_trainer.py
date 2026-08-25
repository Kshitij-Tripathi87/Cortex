"""Test RL Trainer & Rollout Collector — Program L.3.

Verifies:
- Full episode rollout trajectory collection
- Comparative evaluation between RL Policy and Heuristic Baseline
- Production gate verification
"""

from __future__ import annotations

from app.modules.rl.environment import SupplyChainEnv
from app.modules.rl.policy import DQNMitigationPolicy
from app.modules.rl.trainer import RLPolicyTrainer, RolloutCollector
from app.modules.world.state_projection import (
    create_initial_state,
    inventory_var_id,
    lead_time_var_id,
)
from app.modules.world.world_models import StateVariable, StateVariableType


class TestRLTrainer:
    def test_rollout_collection_episode(self) -> None:
        """Rollout collector runs a multi-step episode recording all transitions."""
        w1 = StateVariable(
            variable_id=inventory_var_id("wh_1", "comp_01"),
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_1",
            entity_type="warehouse",
            value=600,
        )
        s1 = StateVariable(
            variable_id=lead_time_var_id("sup_1"),
            variable_type=StateVariableType.LEAD_TIME,
            entity_id="sup_1",
            entity_type="supplier",
            value=10,
        )

        state = create_initial_state(
            workspace_id="ws_rollout",
            world_id="world_rollout",
            graph_version=1,
            initial_variables={w1.variable_id: w1, s1.variable_id: s1},
        )

        env = SupplyChainEnv(initial_world_state=state, max_steps=4)
        policy = DQNMitigationPolicy()
        collector = RolloutCollector()

        rollout = collector.collect_trajectory(env, policy, policy_name="test_dqn")

        assert rollout.steps_executed == 4
        assert len(rollout.transitions) == 4
        assert rollout.policy_name == "test_dqn"

    def test_evaluate_policy_against_baseline(self) -> None:
        """RL policy trainer benchmarks policy vs. deterministic heuristic."""
        w1 = StateVariable(
            variable_id=inventory_var_id("wh_1", "comp_01"),
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_1",
            entity_type="warehouse",
            value=400,
        )
        s1 = StateVariable(
            variable_id=lead_time_var_id("sup_1"),
            variable_type=StateVariableType.LEAD_TIME,
            entity_id="sup_1",
            entity_type="supplier",
            value=12,
        )

        state = create_initial_state(
            workspace_id="ws_trainer",
            world_id="world_trainer",
            graph_version=1,
            initial_variables={w1.variable_id: w1, s1.variable_id: s1},
        )

        policy = DQNMitigationPolicy()
        trainer = RLPolicyTrainer()

        comparison = trainer.evaluate_policy_against_baseline(
            world_state=state,
            rl_policy=policy,
            episodes=2,
        )

        assert comparison.policy_version == policy.version
        assert comparison.episodes_evaluated == 2
        assert "reward_lift_pct" in comparison.to_dict()
