"""Logistics Specialist Agent.

Program M.2 (Functional Logistics Specialist):
Monitors transportation routes, freight carrier schedules, and transit delay risks.
Proposes freight rerouting and transit mode switching.
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


class LogisticsAgent(SpecialistAgent):
    """Domain specialist responsible for transportation routes and carrier execution."""

    def __init__(self, name: str = "Logistics Specialist"):
        super().__init__(role=AgentRole.LOGISTICS_SPECIALIST, name=name)

    def evaluate_and_propose(self, world_state: WorldState) -> list[AgentProposal]:
        """Identify delayed routes and formulate rerouting proposals."""
        proposals = []

        routes = [
            v
            for v in world_state.variables.values()
            if v.variable_type == StateVariableType.TRANSIT_DELAY
        ]

        for r in routes:
            delay = float(r.raw_value)
            if delay > 5.0:
                prop_id = str(uuid7())
                action = MitigationAction(
                    action_type=ActionType.REROUTE_SHIPMENT,
                    entity_id=r.entity_id,
                    target_entity_id="air_freight_express",
                    cost_usd=3200.0,
                    rationale=f"Reroute shipment on {r.entity_id} to Air Freight Express bypassing bottleneck.",
                )
                proposals.append(
                    AgentProposal(
                        proposal_id=prop_id,
                        agent_role=self.role,
                        agent_name=self.name,
                        proposed_action=action,
                        estimated_cost_usd=3200.0,
                        estimated_revenue_protected_usd=28000.0,
                        confidence_score=0.85,
                        domain_rationale=f"Transit delay on {r.entity_id} is {delay:.1f}d. Air rerouting recovers 4 days.",
                        supporting_evidence=[f"transit_delay={delay}d", "threshold=5d"],
                    )
                )

        return proposals

    def critique_proposal(
        self,
        proposal: AgentProposal,
        world_state: WorldState,
    ) -> AgentCritique:
        """Critique proposals through carrier capacity and transit feasibility."""
        critique_id = str(uuid7())

        if proposal.proposed_action.action_type == ActionType.TRANSFER_INVENTORY:
            return AgentCritique(
                critique_id=critique_id,
                target_proposal_id=proposal.proposal_id,
                reviewer_role=self.role,
                supports_proposal=True,
                feasibility_score=0.92,
                critique_rationale="Inter-warehouse truckload capacity is available for transfer dispatch.",
            )

        return AgentCritique(
            critique_id=critique_id,
            target_proposal_id=proposal.proposal_id,
            reviewer_role=self.role,
            supports_proposal=True,
            feasibility_score=0.88,
            critique_rationale="Logistics lanes support proposed operational movement.",
        )
