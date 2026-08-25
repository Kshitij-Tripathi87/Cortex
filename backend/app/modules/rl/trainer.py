"""RL Policy Trainer & Trajectory Rollout Engine.

Program L.3 (Experience Rollout & Policy Benchmarking):
- Multi-step episode rollouts
- Policy vs. Baseline comparative evaluation
- Performance lift computation & production gate enforcement
"""

from __future__ import annotations

from app.common.ids import uuid7
from app.modules.rl.environment import SupplyChainEnv
from app.modules.rl.policy import (
    BasePolicy,
    DQNMitigationPolicy,
    RuleBasedBaselinePolicy,
)
from app.modules.rl.rl_models import (
    RLBenchmarkComparison,
    TrajectoryRollout,
    TransitionRecord,
)
from app.modules.world.world_models import WorldState


class RolloutCollector:
    """Collects multi-step trajectories in the SupplyChainEnv under a policy."""

    def collect_trajectory(
        self,
        env: SupplyChainEnv,
        policy: BasePolicy,
        policy_name: str = "policy",
    ) -> TrajectoryRollout:
        """Run an episode in env using policy until done."""
        traj_id = str(uuid7())
        transitions: list[TransitionRecord] = []

        curr_state = env.reset()
        cum_reward = 0.0
        total_cost = 0.0
        done = False
        steps = 0

        while not done:
            legal_actions = env.get_legal_actions()
            action = policy.select_action(curr_state, legal_actions)
            total_cost += action.cost_usd

            step_res = env.step(action)
            cum_reward += step_res.reward
            steps += 1

            transitions.append(
                TransitionRecord(
                    state=curr_state,
                    action=action,
                    reward=step_res.reward,
                    next_state=step_res.next_state,
                    done=step_res.done,
                    step=steps,
                )
            )

            curr_state = step_res.next_state
            done = step_res.done

        return TrajectoryRollout(
            trajectory_id=traj_id,
            policy_name=policy_name,
            scenario_id=env.base_state.world_id,
            transitions=transitions,
            cumulative_reward=cum_reward,
            final_revenue_at_risk_usd=curr_state.stockout_occurrences * 10000.0,
            total_cost_usd=total_cost,
            steps_executed=steps,
        )


class RLPolicyTrainer:
    """Trains and benchmarks RL policies against baseline heuristics."""

    def __init__(
        self,
        collector: RolloutCollector | None = None,
        baseline_policy: BasePolicy | None = None,
    ):
        self.collector = collector or RolloutCollector()
        self.baseline_policy = baseline_policy or RuleBasedBaselinePolicy()

    def evaluate_policy_against_baseline(
        self,
        world_state: WorldState,
        rl_policy: DQNMitigationPolicy,
        episodes: int = 3,
    ) -> RLBenchmarkComparison:
        """Benchmark RL policy rollouts against deterministic heuristic baseline."""
        rl_rewards = []
        base_rewards = []
        rl_costs = []
        base_costs = []

        for _ep in range(episodes):
            env_rl = SupplyChainEnv(initial_world_state=world_state, max_steps=6)
            env_base = SupplyChainEnv(initial_world_state=world_state, max_steps=6)

            rl_rollout = self.collector.collect_trajectory(
                env_rl, rl_policy, policy_name=rl_policy.version
            )
            base_rollout = self.collector.collect_trajectory(
                env_base, self.baseline_policy, policy_name="heuristic_baseline"
            )

            rl_rewards.append(rl_rollout.cumulative_reward)
            base_rewards.append(base_rollout.cumulative_reward)
            rl_costs.append(rl_rollout.total_cost_usd)
            base_costs.append(base_rollout.total_cost_usd)

        avg_rl_reward = sum(rl_rewards) / len(rl_rewards)
        avg_base_reward = sum(base_rewards) / len(base_rewards)

        # Reward lift %: (RL - Base) / abs(Base)
        reward_lift = ((avg_rl_reward - avg_base_reward) / max(1e-4, abs(avg_base_reward))) * 100.0

        # Estimated revenue savings ($)
        rl_saved = max(0.0, 50000.0 - (sum(rl_costs) / len(rl_costs)))
        base_saved = max(0.0, 30000.0 - (sum(base_costs) / len(base_costs)))

        passed_gate = avg_rl_reward >= avg_base_reward

        return RLBenchmarkComparison(
            policy_version=rl_policy.version,
            baseline_name="deterministic_rule_based_heuristic",
            rl_cumulative_reward=avg_rl_reward,
            baseline_cumulative_reward=avg_base_reward,
            reward_lift_pct=reward_lift,
            rl_revenue_saved_usd=rl_saved,
            baseline_revenue_saved_usd=base_saved,
            passed_production_gate=passed_gate,
            episodes_evaluated=episodes,
        )
