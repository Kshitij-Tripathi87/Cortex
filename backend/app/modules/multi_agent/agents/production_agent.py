"""Production Specialist Agent.

Program M.2 (Functional Production Specialist):
Monitors manufacturing plant capacity, line downtime, and production schedule bottlenecks.
Proposes manufacturing schedule rebalancing and overtime shifts.
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


class ProductionAgent(SpecialistAgent):
    """Domain specialist responsible for factory capacity and plant floor throughput."""

    def __init__(self, name: str = "Production Specialist"):
        super().__init__(role=AgentRole.PRODUCTION_SPECIALIST, name=name)

    def evaluate_and_propose(self, world_state: WorldState) -> list[AgentProposal]:
        """Identify degraded factories and propose schedule / capacity adjustments."""
        proposals = []

        factories = [
            v
            for v in world_state.variables.values()
            if v.variable_type == StateVariableType.CAPACITY
        ]

        for f in factories:
            cap = float(f.raw_value)
            if cap < 80.0:  # Capacity constraint or partial shutdown
                prop_id = str(uuid7())
                action = MitigationAction(
                    action_type=ActionType.ADJUST_PRODUCTION,
                    entity_id=f.entity_id,
                    quantity=cap,
                    cost_usd=2500.0,
                    rationale=f"Authorize weekend overtime shift at {f.entity_id} to restore 100% capacity.",
                )
                proposals.append(
                    AgentProposal(
                        proposal_id=prop_id,
                        agent_role=self.role,
                        agent_name=self.name,
                        proposed_action=action,
                        estimated_cost_usd=2500.0,
                        estimated_revenue_protected_usd=30000.0,
                        confidence_score=0.90,
                        domain_rationale=f"Plant {f.entity_id} capacity operating at {cap:.0f}%. Overtime shift eliminates backlogs.",
                        supporting_evidence=[f"capacity={cap}%", "nominal=100%"],
                    )
                )

        return proposals

    def critique_proposal(
        self,
        proposal: AgentProposal,
        world_state: WorldState,
    ) -> AgentCritique:
        """Critique proposals through manufacturing throughput and raw material availability."""
        critique_id = str(uuid7())

        if proposal.proposed_action.action_type == ActionType.EXPEDITE_SUPPLIER:
            return AgentCritique(
                critique_id=critique_id,
                target_proposal_id=proposal.proposal_id,
                reviewer_role=self.role,
                supports_proposal=True,
                feasibility_score=0.95,
                critique_rationale="Accelerating component delivery prevents factory downtime and assembly idling.",
            )

        return AgentCritique(
            critique_id=critique_id,
            target_proposal_id=proposal.proposal_id,
            reviewer_role=self.role,
            supports_proposal=True,
            feasibility_score=0.85,
            critique_rationale="Manufacturing floor can absorb the operational parameters of this action.",
        )
