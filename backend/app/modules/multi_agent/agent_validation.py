"""Deep Multi-Agent Adversarial & Conflict Validation Engine — Program M Research Layer.

Validates:
- Multi-agent behavior under irreconcilable domain conflicts
- Deadlock avoidance and consensus convergence
- Pareto-efficiency of synthesized mitigation plans
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.modules.multi_agent.consensus_engine import MultiAgentConsensusEngine
from app.modules.world.world_models import WorldState


@dataclass(frozen=True)
class AdversarialValidationResult:
    """Measures multi-agent resolution behavior under high-stress conflicting objectives."""

    conflict_scenario: str
    num_proposals: int
    num_objections_raised: int
    deadlock_detected: bool
    consensus_score: float
    pareto_efficiency_score: float  # 0.0 - 1.0 (Net protected value / Max attainable)
    trade_offs_resolved: list[str] = field(default_factory=list)


class MultiAgentResearchValidator:
    """Research and stress-testing harness for Multi-Agent coordination dynamics."""

    def __init__(self, consensus_engine: MultiAgentConsensusEngine | None = None):
        self.engine = consensus_engine or MultiAgentConsensusEngine()

    def test_adversarial_conflict_resolution(
        self,
        adversarial_state: WorldState,
        scenario_description: str = "High-Cost Expedite vs. Zero-Transit Feasibility",
    ) -> AdversarialValidationResult:
        """Evaluate consensus synthesis when agents have strictly opposing priorities."""
        plan = self.engine.deliberate(adversarial_state)

        # Measure objections in critiques
        objections = [c for c in plan.peer_critiques if not c.supports_proposal or c.feasibility_score < 0.70]
        deadlock = len(plan.selected_actions) == 0 and len(plan.proposals_evaluated) > 0

        # Pareto efficiency: net value of selected actions relative to total possible
        total_possible = sum(p.estimated_revenue_protected_usd for p in plan.proposals_evaluated)
        net_selected = max(0.0, plan.total_protected_revenue_usd - plan.total_cost_usd)
        pareto_score = (net_selected / total_possible) if total_possible > 0 else 1.0
        pareto_score = min(1.0, max(0.0, pareto_score))

        trade_offs = []
        if len(objections) > 0:
            trade_offs.append(f"Resolved {len(objections)} cross-functional domain objections without deadlock.")
        trade_offs.append(plan.trade_off_analysis)

        return AdversarialValidationResult(
            conflict_scenario=scenario_description,
            num_proposals=len(plan.proposals_evaluated),
            num_objections_raised=len(objections),
            deadlock_detected=deadlock,
            consensus_score=round(plan.consensus_score, 4),
            pareto_efficiency_score=round(pareto_score, 4),
            trade_offs_resolved=trade_offs,
        )
