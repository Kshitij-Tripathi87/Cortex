"""Test Deep RL Research & Robustness — Program L Validation Gate.

Verifies:
- RL Policy performance retention under 3x severe distribution shift
- Zero safety boundary violations under non-stationary shock sequences
"""

from __future__ import annotations

from app.modules.rl.policy import DQNMitigationPolicy
from app.modules.rl.rl_validation import RLResearchValidator
from app.modules.world.state_projection import (
    capacity_var_id,
    create_initial_state,
    inventory_var_id,
    lead_time_var_id,
)
from app.modules.world.world_models import StateVariable, StateVariableType


class TestRLDeepResearch:
    def test_rl_policy_distribution_shift_robustness(self) -> None:
        """RL policy outperforms heuristic baseline under 3x severe disruption shifts."""
        s1 = StateVariable(
            variable_id=lead_time_var_id("sup_1"),
            variable_type=StateVariableType.LEAD_TIME,
            entity_id="sup_1",
            entity_type="supplier",
            value=8,
        )
        w1 = StateVariable(
            variable_id=inventory_var_id("wh_1", "comp_01"),
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_1",
            entity_type="warehouse",
            value=600,
        )
        f1 = StateVariable(
            variable_id=capacity_var_id("fac_1"),
            variable_type=StateVariableType.CAPACITY,
            entity_id="fac_1",
            entity_type="factory",
            value=100.0,
        )

        state = create_initial_state(
            workspace_id="ws_rl_research",
            world_id="world_rl_research",
            graph_version=1,
            initial_variables={s1.variable_id: s1, w1.variable_id: w1, f1.variable_id: f1},
        )

        policy = DQNMitigationPolicy()
        validator = RLResearchValidator()

        result = validator.test_distribution_shift(
            nominal_world_state=state,
            policy=policy,
            severity_multiplier=3.0,
        )

        assert result.severity_multiplier == 3.0
        assert result.safety_violations == 0
        assert result.is_robust_under_shift is True
        assert result.rl_cumulative_reward >= result.baseline_cumulative_reward
