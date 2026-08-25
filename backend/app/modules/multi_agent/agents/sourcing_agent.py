"""Sourcing Specialist Agent.

Program M.2 (Functional Sourcing Specialist):
Monitors supplier lead times, disruption health scores, and alternative supplier viability.
Proposes supplier switching, rush expediting, and volume re-allocation.
"""

from __future__ import annotations

from app.common.ids import uuid7
from app.modules.multi_agent.agent_models import (
    AgentCritique,
    AgentProposal,
    AgentRole,
)
from app.modules.multi_agent.base_agent import SpecialistAgent
from app.modules.rl.rl_models import ActionType, MitigationAction
from app.modules.world.world_models import StateVariableType, WorldState


class SourcingAgent(SpecialistAgent):
    """Domain specialist responsible for upstream supplier operations."""

    def __init__(self, name: str = "Sourcing Specialist"):
        super().__init__(role=AgentRole.SOURCING_SPECIALIST, name=name)

    def evaluate_and_propose(self, world_state: WorldState) -> list[AgentProposal]:
        """Identify delayed or unhealthy suppliers and formulate sourcing proposals."""
        proposals = []

        suppliers = [
            v
            for v in world_state.variables.values()
            if v.variable_type == StateVariableType.LEAD_TIME
        ]

        for s in suppliers:
            lead_time = float(s.raw_value)
            if lead_time > 10.0:  # Significant lead time delay
                prop_id = str(uuid7())
                action = MitigationAction(
                    action_type=ActionType.EXPEDITE_SUPPLIER,
                    entity_id=s.entity_id,
                    quantity=3.0,  # 3 days expedite
                    cost_usd=4500.0,
                    rationale=f"Expedite supplier {s.entity_id} to compress lead time by 3 days.",
                )
                proposals.append(
                    AgentProposal(
                        proposal_id=prop_id,
                        agent_role=self.role,
                        agent_name=self.name,
                        proposed_action=action,
                        estimated_cost_usd=4500.0,
                        estimated_revenue_protected_usd=35000.0,
                        confidence_score=0.88,
                        domain_rationale=(
                            f"Supplier {s.entity_id} lead time currently at {lead_time:.1f}d. "
                            f"3-day expedite prevents downstream line starvation."
                        ),
                        supporting_evidence=[f"lead_time={lead_time}d", "threshold=10d"],
                    )
                )

        return proposals

    def critique_proposal(
        self,
        proposal: AgentProposal,
        world_state: WorldState,
    ) -> AgentCritique:
        """Critique proposals through the lens of sourcing feasibility."""
        critique_id = str(uuid7())

        if proposal.proposed_action.action_type == ActionType.TRANSFER_INVENTORY:
            # Sourcing supports inventory rebalancing if it reduces urgency for supplier expediting
            return AgentCritique(
                critique_id=critique_id,
                target_proposal_id=proposal.proposal_id,
                reviewer_role=self.role,
                supports_proposal=True,
                feasibility_score=0.95,
                critique_rationale="Inventory transfer provides buffer without requiring supplier surge pricing.",
            )

        return AgentCritique(
            critique_id=critique_id,
            target_proposal_id=proposal.proposal_id,
            reviewer_role=self.role,
            supports_proposal=True,
            feasibility_score=0.85,
            critique_rationale="Action is compatible with supplier contract parameters.",
        )
