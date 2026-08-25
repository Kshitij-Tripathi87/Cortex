"""Test Multi-Agent Consensus & Deliberation Engine — Program M.3.

Verifies:
- 3-round multi-agent deliberation cycle
- Conflict resolution and cross-specialist peer review
- CoordinatedMitigationPlan synthesis and consensus scoring
"""

from __future__ import annotations

from app.modules.multi_agent.consensus_engine import MultiAgentConsensusEngine
from app.modules.world.state_projection import (
    capacity_var_id,
    create_initial_state,
    inventory_var_id,
    lead_time_var_id,
)
from app.modules.world.world_models import StateVariable, StateVariableType


class TestMultiAgentConsensus:
    def test_full_3_round_consensus_deliberation(self) -> None:
        """Full deliberation across all specialist agents produces a unified consensus plan."""
        s1 = StateVariable(
            variable_id=lead_time_var_id("sup_01"),
            variable_type=StateVariableType.LEAD_TIME,
            entity_id="sup_01",
            entity_type="supplier",
            value=15,  # Needs expedite
        )
        w_low = StateVariable(
            variable_id=inventory_var_id("wh_east", "comp_01"),
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_east",
            entity_type="warehouse",
            value=80,  # Needs replenishment
        )
        w_high = StateVariable(
            variable_id=inventory_var_id("wh_west", "comp_01"),
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_west",
            entity_type="warehouse",
            value=950,  # Surplus
        )
        f1 = StateVariable(
            variable_id=capacity_var_id("fac_01"),
            variable_type=StateVariableType.CAPACITY,
            entity_id="fac_01",
            entity_type="factory",
            value=70.0,  # Needs overtime
        )

        state = create_initial_state(
            workspace_id="ws_consensus",
            world_id="world_consensus",
            graph_version=1,
            initial_variables={
                s1.variable_id: s1,
                w_low.variable_id: w_low,
                w_high.variable_id: w_high,
                f1.variable_id: f1,
            },
        )

        engine = MultiAgentConsensusEngine()
        plan = engine.deliberate(state)

        assert plan.workspace_id == "ws_consensus"
        assert len(plan.proposals_evaluated) >= 3
        assert len(plan.peer_critiques) >= 6
        assert len(plan.selected_actions) >= 1
        assert plan.consensus_score >= 0.70
        assert plan.total_protected_revenue_usd > 0
        assert len(plan.coordination_summary) > 0
        assert len(plan.trade_off_analysis) > 0
