"""Test Agent Grounding & Hallucination Defense — Program P.5.

Verifies:
- Verification of grounded agent proposals against real WorldState entities
- Detection and rejection of hallucinated entities or unsupported claims
"""

from __future__ import annotations

from app.modules.multi_agent.agent_models import AgentProposal, AgentRole
from app.modules.production_validation.agent_grounding import AgentGroundingAuditor
from app.modules.rl.rl_models import ActionType, MitigationAction
from app.modules.world.state_projection import (
    create_initial_state,
    inventory_var_id,
    lead_time_var_id,
)
from app.modules.world.world_models import StateVariable, StateVariableType


class TestAgentGroundingAudit:
    def test_grounded_vs_hallucinated_proposal_audit(self) -> None:
        """Grounded proposal passes while hallucinated entity fails audit."""
        s1 = StateVariable(
            variable_id=lead_time_var_id("sup_real_01"),
            variable_type=StateVariableType.LEAD_TIME,
            entity_id="sup_real_01",
            entity_type="supplier",
            value=10,
        )
        w1 = StateVariable(
            variable_id=inventory_var_id("wh_real_01", "comp_01"),
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_real_01",
            entity_type="warehouse",
            value=500,
        )

        world_state = create_initial_state(
            workspace_id="ws_grounding",
            world_id="world_grounding",
            graph_version=1,
            initial_variables={s1.variable_id: s1, w1.variable_id: w1},
        )

        auditor = AgentGroundingAuditor()

        # 1. Grounded proposal
        grounded_prop = AgentProposal(
            proposal_id="prop_grounded",
            agent_role=AgentRole.SOURCING_SPECIALIST,
            agent_name="Sourcing Agent",
            proposed_action=MitigationAction(
                ActionType.EXPEDITE_SUPPLIER, "sup_real_01", cost_usd=3000.0
            ),
            domain_rationale="Lead time increased by 3 days.",
            estimated_cost_usd=3000.0,
            estimated_revenue_protected_usd=35000.0,
            confidence_score=0.92,
            supporting_evidence=["Historical lead time baseline was 7 days."],
        )

        res_grounded = auditor.audit_proposal(grounded_prop, world_state)
        assert res_grounded.audit_passed is True
        assert res_grounded.unverified_or_hallucinated_claims == 0
        assert res_grounded.grounding_rate_pct == 100.0

        # 2. Hallucinated proposal referencing fictitious supplier
        hallucinated_prop = AgentProposal(
            proposal_id="prop_hallucinated",
            agent_role=AgentRole.SOURCING_SPECIALIST,
            agent_name="Sourcing Agent",
            proposed_action=MitigationAction(
                ActionType.EXPEDITE_SUPPLIER, "sup_fake_invented", cost_usd=3000.0
            ),
            domain_rationale="Invented phantom supplier proposal.",
            estimated_cost_usd=3000.0,
            estimated_revenue_protected_usd=35000.0,
            confidence_score=0.92,
            supporting_evidence=[],
        )

        res_hallucinated = auditor.audit_proposal(hallucinated_prop, world_state)
        assert res_hallucinated.audit_passed is False
        assert res_hallucinated.unverified_or_hallucinated_claims >= 1
