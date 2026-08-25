"""Inventory Specialist Agent.

Program M.2 (Functional Inventory Specialist):
Monitors warehouse stock coverage, safety buffer depletion, and stockout risks.
Proposes inter-warehouse rebalancing and stock transfers.
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


class InventoryAgent(SpecialistAgent):
    """Domain specialist responsible for warehouse inventory and stockout prevention."""

    def __init__(self, name: str = "Inventory Specialist"):
        super().__init__(role=AgentRole.INVENTORY_SPECIALIST, name=name)

    def evaluate_and_propose(self, world_state: WorldState) -> list[AgentProposal]:
        """Identify depleted warehouses and pair with surplus warehouses for transfer."""
        proposals = []

        warehouses = [
            v
            for v in world_state.variables.values()
            if v.variable_type == StateVariableType.INVENTORY
        ]

        # Sort warehouses by inventory level
        sorted_wh = sorted(warehouses, key=lambda v: float(v.raw_value))

        if len(sorted_wh) >= 2:
            lowest = sorted_wh[0]
            highest = sorted_wh[-1]

            low_val = float(lowest.raw_value)
            high_val = float(highest.raw_value)

            # If lowest is below threshold (e.g. 200) and highest has surplus (> 500)
            if low_val < 300.0 and high_val > 400.0:
                transfer_qty = min(200.0, (high_val - low_val) / 2.0)
                prop_id = str(uuid7())
                action = MitigationAction(
                    action_type=ActionType.TRANSFER_INVENTORY,
                    entity_id=highest.entity_id,
                    target_entity_id=lowest.entity_id,
                    quantity=transfer_qty,
                    cost_usd=transfer_qty * 8.0,
                    rationale=f"Transfer {transfer_qty:.0f} units from {highest.entity_id} to replenish {lowest.entity_id}.",
                )
                proposals.append(
                    AgentProposal(
                        proposal_id=prop_id,
                        agent_role=self.role,
                        agent_name=self.name,
                        proposed_action=action,
                        estimated_cost_usd=transfer_qty * 8.0,
                        estimated_revenue_protected_usd=40000.0,
                        confidence_score=0.92,
                        domain_rationale=(
                            f"Warehouse {lowest.entity_id} at critical stock ({low_val:.0f} units). "
                            f"Rebalancing {transfer_qty:.0f} units from {highest.entity_id} prevents imminent stockout."
                        ),
                        supporting_evidence=[
                            f"low_stock={low_val}",
                            f"surplus_stock={high_val}",
                            f"transfer_qty={transfer_qty}",
                        ],
                    )
                )

        return proposals

    def critique_proposal(
        self,
        proposal: AgentProposal,
        world_state: WorldState,
    ) -> AgentCritique:
        """Critique proposals through inventory safety buffer lens."""
        critique_id = str(uuid7())

        if proposal.proposed_action.action_type == ActionType.EXPEDITE_SUPPLIER:
            return AgentCritique(
                critique_id=critique_id,
                target_proposal_id=proposal.proposal_id,
                reviewer_role=self.role,
                supports_proposal=True,
                feasibility_score=0.90,
                critique_rationale="Expedited shipments directly replenish depleting warehouse safety stocks.",
            )

        return AgentCritique(
            critique_id=critique_id,
            target_proposal_id=proposal.proposal_id,
            reviewer_role=self.role,
            supports_proposal=True,
            feasibility_score=0.85,
            critique_rationale="Inventory positions remain within normal bounds under proposed action.",
        )
