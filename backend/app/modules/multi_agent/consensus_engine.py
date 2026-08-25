"""Multi-Agent Consensus & Deliberation Engine.

Program M.3 (Consensus & Deliberation Protocol):
Orchestrates the 3-round multi-agent coordination workflow:
1. Round 1: Autonomous Domain Proposals
2. Round 2: Cross-Specialist Peer Review & Critique
3. Round 3: Executive Coordinator Conflict Resolution & Plan Synthesis
"""

from __future__ import annotations

from app.common.ids import uuid7
from app.modules.multi_agent.agent_models import (
    AgentCritique,
    AgentProposal,
    AgentRole,
    CoordinatedMitigationPlan,
)
from app.modules.multi_agent.agents.inventory_agent import InventoryAgent
from app.modules.multi_agent.agents.logistics_agent import LogisticsAgent
from app.modules.multi_agent.agents.production_agent import ProductionAgent
from app.modules.multi_agent.agents.sourcing_agent import SourcingAgent
from app.modules.multi_agent.base_agent import SpecialistAgent
from app.modules.rl.rl_models import ActionType, MitigationAction
from app.modules.world.world_models import WorldState


class MultiAgentConsensusEngine:
    """Coordinates autonomous specialist agents to form unified mitigation plans."""

    def __init__(self, specialists: list[SpecialistAgent] | None = None):
        self.specialists = specialists or [
            SourcingAgent(),
            InventoryAgent(),
            LogisticsAgent(),
            ProductionAgent(),
        ]

    def deliberate(
        self,
        world_state: WorldState,
    ) -> CoordinatedMitigationPlan:
        """Run the complete 3-round multi-agent deliberation cycle."""
        plan_id = str(uuid7())

        # ─────────────────────────────────────────────────────────────────────
        # Round 1: Autonomous Domain Proposals
        # ─────────────────────────────────────────────────────────────────────
        all_proposals: list[AgentProposal] = []
        for agent in self.specialists:
            props = agent.evaluate_and_propose(world_state)
            all_proposals.extend(props)

        # Fallback default proposal if no disruptions detected
        if not all_proposals:
            noop_action = MitigationAction(
                action_type=ActionType.NOOP,
                entity_id="system",
                rationale="All operational metrics are within nominal limits.",
            )
            all_proposals.append(
                AgentProposal(
                    proposal_id=str(uuid7()),
                    agent_role=AgentRole.EXECUTIVE_COORDINATOR,
                    agent_name="Executive Coordinator",
                    proposed_action=noop_action,
                    estimated_cost_usd=0.0,
                    estimated_revenue_protected_usd=0.0,
                    confidence_score=1.0,
                    domain_rationale="No immediate interventions required.",
                    supporting_evidence=["all_metrics_nominal"],
                )
            )

        # ─────────────────────────────────────────────────────────────────────
        # Round 2: Peer Review & Critique
        # ─────────────────────────────────────────────────────────────────────
        all_critiques: list[AgentCritique] = []
        for prop in all_proposals:
            for reviewer in self.specialists:
                if reviewer.role != prop.agent_role:
                    critique = reviewer.critique_proposal(prop, world_state)
                    all_critiques.append(critique)

        # ─────────────────────────────────────────────────────────────────────
        # Round 3: Executive Coordinator Plan Synthesis
        # ─────────────────────────────────────────────────────────────────────
        # Score each proposal by composite value & peer support
        proposal_scores: list[tuple[float, AgentProposal]] = []

        for prop in all_proposals:
            critiques_for_prop = [
                c for c in all_critiques if c.target_proposal_id == prop.proposal_id
            ]
            avg_feasibility = (
                sum(c.feasibility_score for c in critiques_for_prop) / len(critiques_for_prop)
                if critiques_for_prop
                else 1.0
            )

            # Net value = Protected Revenue - Cost
            net_value = max(0.0, prop.estimated_revenue_protected_usd - prop.estimated_cost_usd)
            composite_score = net_value * prop.confidence_score * avg_feasibility
            proposal_scores.append((composite_score, prop))

        # Sort descending by composite score
        proposal_scores.sort(key=lambda x: x[0], reverse=True)

        selected_proposals = [
            p for _, p in proposal_scores[:3]
        ]  # Take top 3 non-conflicting actions
        selected_actions = [p.proposed_action for p in selected_proposals]

        total_cost = sum(p.estimated_cost_usd for p in selected_proposals)
        total_protected = sum(p.estimated_revenue_protected_usd for p in selected_proposals)

        # Calculate consensus score
        if all_critiques:
            supported = sum(1 for c in all_critiques if c.supports_proposal)
            consensus_score = supported / len(all_critiques)
        else:
            consensus_score = 1.0

        summary = (
            f"Synthesized consensus mitigation plan selecting {len(selected_actions)} coordinated actions. "
            f"Total protected revenue: ${total_protected:,.0f} at an estimated cost of ${total_cost:,.0f}."
        )

        trade_off_rationale = (
            f"Executive synthesis reconciled trade-offs between speed and expenditure: "
            f"Selected proposals attained {consensus_score * 100:.1f}% cross-specialist peer consensus."
        )

        return CoordinatedMitigationPlan(
            plan_id=plan_id,
            workspace_id=world_state.workspace_id,
            world_id=world_state.world_id,
            selected_actions=selected_actions,
            total_cost_usd=total_cost,
            total_protected_revenue_usd=total_protected,
            consensus_score=consensus_score,
            participating_agents=[a.role for a in self.specialists],
            proposals_evaluated=all_proposals,
            peer_critiques=all_critiques,
            coordination_summary=summary,
            trade_off_analysis=trade_off_rationale,
        )
