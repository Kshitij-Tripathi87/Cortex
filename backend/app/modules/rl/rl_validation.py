"""Deep RL Policy Research & Robustness Validation Engine — Program L Research Layer.

Validates:
- Policy performance under non-stationary distribution shifts
- Extreme shock robustness (2x - 4x disruption severity)
- Safety boundary violation rates and constraint satisfaction
"""

from __future__ import annotations

import copy
from dataclasses import dataclass

from app.modules.rl.environment import SupplyChainEnv
from app.modules.rl.policy import DQNMitigationPolicy, RuleBasedBaselinePolicy
from app.modules.rl.rl_models import ActionType
from app.modules.rl.trainer import RolloutCollector
from app.modules.world.world_models import StateVariable, StateVariableType, WorldState


@dataclass(frozen=True)
class DistributionShiftResult:
    """Measures policy degradation when disruption severity shifts out of training distribution."""

    severity_multiplier: float
    rl_cumulative_reward: float
    baseline_cumulative_reward: float
    performance_retention_pct: float  # How much reward is retained vs nominal
    safety_violations: int
    is_robust_under_shift: bool


class RLResearchValidator:
    """Research and robustness validation suite for Reinforcement Learning mitigation policies."""

    def __init__(
        self,
        collector: RolloutCollector | None = None,
        baseline_policy: RuleBasedBaselinePolicy | None = None,
    ):
        self.collector = collector or RolloutCollector()
        self.baseline_policy = baseline_policy or RuleBasedBaselinePolicy()

    def test_distribution_shift(
        self,
        nominal_world_state: WorldState,
        policy: DQNMitigationPolicy,
        severity_multiplier: float = 3.0,
    ) -> DistributionShiftResult:
        """Subject the policy to a 3x severe disruption environment."""
        # 1. Create extreme shock world state
        shifted_vars = {}
        for var_id, var in nominal_world_state.variables.items():
            val = float(var.raw_value)
            if var.variable_type == StateVariableType.LEAD_TIME:
                val = val * severity_multiplier
            elif var.variable_type == StateVariableType.INVENTORY:
                val = max(0.0, val / severity_multiplier)
            elif var.variable_type == StateVariableType.CAPACITY:
                val = max(10.0, val / severity_multiplier)

            new_var = StateVariable(
                variable_id=var.variable_id,
                variable_type=var.variable_type,
                entity_id=var.entity_id,
                entity_type=var.entity_type,
                value=val,
            )
            shifted_vars[var_id] = new_var

        shifted_state = copy.deepcopy(nominal_world_state)
        # Update variables dict on shifted_state
        object.__setattr__(shifted_state, "variables", shifted_vars)

        # 2. Run nominal vs shifted rollouts
        env_nominal = SupplyChainEnv(nominal_world_state, max_steps=5)
        env_shifted_rl = SupplyChainEnv(shifted_state, max_steps=5)
        env_shifted_base = SupplyChainEnv(shifted_state, max_steps=5)

        nominal_rollout = self.collector.collect_trajectory(env_nominal, policy)
        shifted_rl_rollout = self.collector.collect_trajectory(env_shifted_rl, policy)
        shifted_base_rollout = self.collector.collect_trajectory(
            env_shifted_base, self.baseline_policy
        )

        # 3. Check for safety violations
        safety_violations = 0
        for tr in shifted_rl_rollout.transitions:
            # Check for unreasonable action cost
            if tr.action.cost_usd > 75000.0:
                safety_violations += 1
            # Check for illegal transfer from zero-inventory warehouse
            if (
                tr.action.action_type == ActionType.TRANSFER_INVENTORY
                and tr.state.total_inventory <= 0
            ):
                safety_violations += 1

        retention = (
            (shifted_rl_rollout.cumulative_reward / max(1e-4, nominal_rollout.cumulative_reward))
            * 100.0
            if nominal_rollout.cumulative_reward != 0
            else 100.0
        )

        is_robust = (
            shifted_rl_rollout.cumulative_reward >= shifted_base_rollout.cumulative_reward
        ) and (safety_violations == 0)

        return DistributionShiftResult(
            severity_multiplier=severity_multiplier,
            rl_cumulative_reward=round(shifted_rl_rollout.cumulative_reward, 2),
            baseline_cumulative_reward=round(shifted_base_rollout.cumulative_reward, 2),
            performance_retention_pct=round(retention, 2),
            safety_violations=safety_violations,
            is_robust_under_shift=is_robust,
        )
