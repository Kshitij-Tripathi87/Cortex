"""RL Models — Immutable Contracts for Reinforcement Learning & Policy Optimization.

Program L (Reinforcement Learning & Mitigation Policy Optimization):
- L.1: MDP State & Action Spaces
- L.2: Policy & Value Representations
- L.3: Trajectory & Transition Records
- L.4: Evaluation & Policy Benchmarks
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class ActionType(StrEnum):
    """Mitigation action types in the supply chain MDP."""

    NOOP = "noop"
    EXPEDITE_SUPPLIER = "expedite_supplier"
    TRANSFER_INVENTORY = "transfer_inventory"
    REROUTE_SHIPMENT = "reroute_shipment"
    SWITCH_SUPPLIER = "switch_supplier"
    ADJUST_PRODUCTION = "adjust_production"
    PRIORITIZE_TIER1 = "prioritize_tier1"


@dataclass(frozen=True)
class MitigationAction:
    """Discrete/Parametric action in the MDP action space."""

    action_type: ActionType
    entity_id: str
    quantity: float = 0.0
    target_entity_id: str | None = None
    cost_usd: float = 0.0
    rationale: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_type": self.action_type.value,
            "entity_id": self.entity_id,
            "quantity": self.quantity,
            "target_entity_id": self.target_entity_id,
            "cost_usd": self.cost_usd,
            "rationale": self.rationale,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class EnvStateVector:
    """Numerical state representation of the supply chain network."""

    state_features: list[float]
    total_inventory: float
    avg_capacity_pct: float
    max_lead_time_days: float
    stockout_occurrences: int
    step_number: int
    state_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "state_features": list(self.state_features),
            "total_inventory": self.total_inventory,
            "avg_capacity_pct": self.avg_capacity_pct,
            "max_lead_time_days": self.max_lead_time_days,
            "stockout_occurrences": self.stockout_occurrences,
            "step_number": self.step_number,
            "state_hash": self.state_hash,
        }


@dataclass(frozen=True)
class StepResult:
    """Result of an environment step: (s, a) -> (s', r, done, info)."""

    next_state: EnvStateVector
    reward: float
    done: bool
    kpi_deltas: dict[str, float]
    info: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "next_state": self.next_state.to_dict(),
            "reward": self.reward,
            "done": self.done,
            "kpi_deltas": dict(self.kpi_deltas),
            "info": dict(self.info),
        }


@dataclass(frozen=True)
class TransitionRecord:
    """Single experience transition for replay and policy training."""

    state: EnvStateVector
    action: MitigationAction
    reward: float
    next_state: EnvStateVector
    done: bool
    step: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.to_dict(),
            "action": self.action.to_dict(),
            "reward": self.reward,
            "next_state": self.next_state.to_dict(),
            "done": self.done,
            "step": self.step,
        }


@dataclass(frozen=True)
class TrajectoryRollout:
    """Full episode trajectory under a policy."""

    trajectory_id: str
    policy_name: str
    scenario_id: str
    transitions: list[TransitionRecord]
    cumulative_reward: float
    final_revenue_at_risk_usd: float
    total_cost_usd: float
    steps_executed: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "trajectory_id": self.trajectory_id,
            "policy_name": self.policy_name,
            "scenario_id": self.scenario_id,
            "cumulative_reward": round(self.cumulative_reward, 2),
            "final_revenue_at_risk_usd": round(self.final_revenue_at_risk_usd, 2),
            "total_cost_usd": round(self.total_cost_usd, 2),
            "steps_executed": self.steps_executed,
            "transitions": [t.to_dict() for t in self.transitions],
        }


@dataclass(frozen=True)
class PolicyRecommendation:
    """Optimal mitigation policy recommendation for a given operational state."""

    recommended_action: MitigationAction
    action_q_value: float
    expected_reward: float
    candidate_actions: list[dict[str, Any]]
    policy_version: str
    confidence: float
    safety_validated: bool
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommended_action": self.recommended_action.to_dict(),
            "action_q_value": round(self.action_q_value, 4),
            "expected_reward": round(self.expected_reward, 2),
            "candidate_actions": self.candidate_actions,
            "policy_version": self.policy_version,
            "confidence": round(self.confidence, 4),
            "safety_validated": self.safety_validated,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass(frozen=True)
class RLBenchmarkComparison:
    """Comparative evaluation between RL Policy and Heuristic/Rule Baseline."""

    policy_version: str
    baseline_name: str
    rl_cumulative_reward: float
    baseline_cumulative_reward: float
    reward_lift_pct: float
    rl_revenue_saved_usd: float
    baseline_revenue_saved_usd: float
    passed_production_gate: bool
    episodes_evaluated: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_version": self.policy_version,
            "baseline_name": self.baseline_name,
            "rl_cumulative_reward": round(self.rl_cumulative_reward, 2),
            "baseline_cumulative_reward": round(self.baseline_cumulative_reward, 2),
            "reward_lift_pct": round(self.reward_lift_pct, 2),
            "rl_revenue_saved_usd": round(self.rl_revenue_saved_usd, 2),
            "baseline_revenue_saved_usd": round(self.baseline_revenue_saved_usd, 2),
            "passed_production_gate": self.passed_production_gate,
            "episodes_evaluated": self.episodes_evaluated,
        }
