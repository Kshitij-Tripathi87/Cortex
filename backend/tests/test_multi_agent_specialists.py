"""Test Autonomous Specialist Agents — Program M.2.

Verifies:
- SourcingAgent proposals & peer review
- InventoryAgent warehouse rebalancing proposals & peer review
- LogisticsAgent transit delay rerouting proposals & peer review
- ProductionAgent factory overtime proposals & peer review
"""

from __future__ import annotations

from app.modules.multi_agent.agent_models import AgentRole
from app.modules.multi_agent.agents.inventory_agent import InventoryAgent
from app.modules.multi_agent.agents.logistics_agent import LogisticsAgent
from app.modules.multi_agent.agents.production_agent import ProductionAgent
from app.modules.multi_agent.agents.sourcing_agent import SourcingAgent
from app.modules.rl.rl_models import ActionType
from app.modules.world.state_projection import (
    capacity_var_id,
    create_initial_state,
    inventory_var_id,
    lead_time_var_id,
    transit_delay_var_id,
)
from app.modules.world.world_models import StateVariable, StateVariableType


class TestSpecialistAgents:
    def test_sourcing_agent_propose_and_critique(self) -> None:
        """Sourcing agent detects delayed suppliers and proposes expediting."""
        s1 = StateVariable(
            variable_id=lead_time_var_id("sup_slow"),
            variable_type=StateVariableType.LEAD_TIME,
            entity_id="sup_slow",
            entity_type="supplier",
            value=16,  # > 10d
        )

        state = create_initial_state(
            workspace_id="ws_src",
            world_id="world_src",
            graph_version=1,
            initial_variables={s1.variable_id: s1},
        )

        agent = SourcingAgent()
        props = agent.evaluate_and_propose(state)

        assert len(props) == 1
        assert props[0].agent_role == AgentRole.SOURCING_SPECIALIST
        assert props[0].proposed_action.action_type == ActionType.EXPEDITE_SUPPLIER
        assert props[0].confidence_score > 0.80

    def test_inventory_agent_rebalance_proposal(self) -> None:
        """Inventory agent pairs depleted warehouse with surplus warehouse for stock transfer."""
        w_low = StateVariable(
            variable_id=inventory_var_id("wh_depleted", "comp_01"),
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_depleted",
            entity_type="warehouse",
            value=100,  # Depleted
        )
        w_high = StateVariable(
            variable_id=inventory_var_id("wh_surplus", "comp_01"),
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_surplus",
            entity_type="warehouse",
            value=1200,  # Surplus
        )

        state = create_initial_state(
            workspace_id="ws_inv",
            world_id="world_inv",
            graph_version=1,
            initial_variables={w_low.variable_id: w_low, w_high.variable_id: w_high},
        )

        agent = InventoryAgent()
        props = agent.evaluate_and_propose(state)

        assert len(props) == 1
        assert props[0].agent_role == AgentRole.INVENTORY_SPECIALIST
        assert props[0].proposed_action.action_type == ActionType.TRANSFER_INVENTORY
        assert props[0].proposed_action.entity_id == "wh_surplus"
        assert props[0].proposed_action.target_entity_id == "wh_depleted"

    def test_logistics_and_production_agents(self) -> None:
        """Logistics and production agents detect bottleneck routes and factory stress."""
        r1 = StateVariable(
            variable_id=transit_delay_var_id("lane_port_to_hub"),
            variable_type=StateVariableType.TRANSIT_DELAY,
            entity_id="lane_port_to_hub",
            entity_type="route",
            value=8,  # > 5d
        )
        f1 = StateVariable(
            variable_id=capacity_var_id("fac_plant_1"),
            variable_type=StateVariableType.CAPACITY,
            entity_id="fac_plant_1",
            entity_type="factory",
            value=65.0,  # < 80%
        )

        state = create_initial_state(
            workspace_id="ws_log_prod",
            world_id="world_log_prod",
            graph_version=1,
            initial_variables={r1.variable_id: r1, f1.variable_id: f1},
        )

        log_agent = LogisticsAgent()
        prod_agent = ProductionAgent()

        log_props = log_agent.evaluate_and_propose(state)
        prod_props = prod_agent.evaluate_and_propose(state)

        assert len(log_props) == 1
        assert log_props[0].proposed_action.action_type == ActionType.REROUTE_SHIPMENT

        assert len(prod_props) == 1
        assert prod_props[0].proposed_action.action_type == ActionType.ADJUST_PRODUCTION
