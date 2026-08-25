"""Test Multi-Agent Adversarial & Conflict Stress — Program M Validation Gate.

Verifies:
- Conflict resolution when specialist agents have opposing priorities
- Deadlock avoidance and consensus convergence
- Pareto-efficiency of synthesized plans
"""

from __future__ import annotations

from app.modules.multi_agent.agent_validation import MultiAgentResearchValidator
from app.modules.world.state_projection import (
    capacity_var_id,
    create_initial_state,
    inventory_var_id,
    lead_time_var_id,
    transit_delay_var_id,
)
from app.modules.world.world_models import StateVariable, StateVariableType


class TestMultiAgentAdversarial:
    def test_multi_agent_adversarial_conflict_resolution(self) -> None:
        """Executive coordinator resolves conflicting proposals into a Pareto-efficient plan."""
        # Extreme conflicting scenario:
        # Supplier delayed (Sourcing wants expedite)
        # Route congested (Logistics wants air freight)
        # Warehouse depleted (Inventory wants transfer)
        # Factory throttled (Production wants overtime)
        s1 = StateVariable(
            variable_id=lead_time_var_id("sup_crit"),
            variable_type=StateVariableType.LEAD_TIME,
            entity_id="sup_crit",
            entity_type="supplier",
            value=18,
        )
        r1 = StateVariable(
            variable_id=transit_delay_var_id("lane_choke"),
            variable_type=StateVariableType.TRANSIT_DELAY,
            entity_id="lane_choke",
            entity_type="route",
            value=9,
        )
        w1 = StateVariable(
            variable_id=inventory_var_id("wh_east", "comp_01"),
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_east",
            entity_type="warehouse",
            value=50,
        )
        w2 = StateVariable(
            variable_id=inventory_var_id("wh_west", "comp_01"),
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_west",
            entity_type="warehouse",
            value=900,
        )
        f1 = StateVariable(
            variable_id=capacity_var_id("fac_1"),
            variable_type=StateVariableType.CAPACITY,
            entity_id="fac_1",
            entity_type="factory",
            value=60.0,
        )

        state = create_initial_state(
            workspace_id="ws_adv",
            world_id="world_adv",
            graph_version=1,
            initial_variables={
                s1.variable_id: s1,
                r1.variable_id: r1,
                w1.variable_id: w1,
                w2.variable_id: w2,
                f1.variable_id: f1,
            },
        )

        validator = MultiAgentResearchValidator()
        result = validator.test_adversarial_conflict_resolution(
            adversarial_state=state,
            scenario_description="Multi-Domain Resource Contention",
        )

        assert result.deadlock_detected is False
        assert result.num_proposals >= 3
        assert result.consensus_score >= 0.70
        assert result.pareto_efficiency_score > 0.0
        assert len(result.trade_offs_resolved) > 0
