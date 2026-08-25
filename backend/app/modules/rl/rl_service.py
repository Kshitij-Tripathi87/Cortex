"""RL Service Layer — Orchestrates Reinforcement Learning Policies.

Program L (Reinforcement Learning & Policy Optimization):
Provides service facade for:
- Mitigation Action Recommendation
- Multi-step Trajectory Simulation
- Policy vs. Baseline Benchmarking
"""

from __future__ import annotations

from app.modules.rl.environment import SupplyChainEnv
from app.modules.rl.policy import DQNMitigationPolicy
from app.modules.rl.rl_models import (
    PolicyRecommendation,
    RLBenchmarkComparison,
    TrajectoryRollout,
)
from app.modules.rl.trainer import RLPolicyTrainer, RolloutCollector
from app.modules.world.world_models import WorldState


class RLService:
    """Unified service for Reinforcement Learning policy operations."""

    def __init__(
        self,
        default_policy: DQNMitigationPolicy | None = None,
        trainer: RLPolicyTrainer | None = None,
        collector: RolloutCollector | None = None,
    ):
        self.policy = default_policy or DQNMitigationPolicy()
        self.trainer = trainer or RLPolicyTrainer()
        self.collector = collector or RolloutCollector()

    def recommend_mitigation_action(
        self,
        world_state: WorldState,
    ) -> PolicyRecommendation:
        """Recommend optimal mitigation action using learned policy."""
        env = SupplyChainEnv(initial_world_state=world_state)
        return self.policy.recommend_action(env)

    def run_trajectory_rollout(
        self,
        world_state: WorldState,
        max_steps: int = 10,
    ) -> TrajectoryRollout:
        """Execute full episode rollout under the active policy."""
        env = SupplyChainEnv(initial_world_state=world_state, max_steps=max_steps)
        return self.collector.collect_trajectory(env, self.policy, policy_name=self.policy.version)

    def benchmark_against_baseline(
        self,
        world_state: WorldState,
        episodes: int = 3,
    ) -> RLBenchmarkComparison:
        """Benchmark RL policy against deterministic rule-based heuristic."""
        return self.trainer.evaluate_policy_against_baseline(
            world_state=world_state,
            rl_policy=self.policy,
            episodes=episodes,
        )
