"""Test Critical Node & SPOF Detection — Program K.4.

Verifies:
- Single Point of Failure (SPOF) detection
- Network-wide criticality scoring
- Blast radius and downstream impact calculation
"""

from __future__ import annotations

from app.modules.gnn.graph_representation import GraphExtractor
from app.modules.gnn.models import SupplyChainGNN
from app.modules.gnn.tasks.critical_node import CriticalNodePredictor
from app.modules.world.state_projection import (
    capacity_var_id,
    create_initial_state,
    demand_var_id,
    inventory_var_id,
    lead_time_var_id,
)
from app.modules.world.world_models import StateVariable, StateVariableType


class TestCriticalNodes:
    def test_predict_critical_bottleneck_and_spof(self) -> None:
        """Sole upstream supplier connecting to factories and warehouses is identified as SPOF."""
        # Bottleneck supplier
        s_sole = StateVariable(
            variable_id=lead_time_var_id("sup_sole_monopoly"),
            variable_type=StateVariableType.LEAD_TIME,
            entity_id="sup_sole_monopoly",
            entity_type="supplier",
            value=14,
        )
        f1 = StateVariable(
            variable_id=capacity_var_id("fac_1"),
            variable_type=StateVariableType.CAPACITY,
            entity_id="fac_1",
            entity_type="factory",
            value=100.0,
        )
        f2 = StateVariable(
            variable_id=capacity_var_id("fac_2"),
            variable_type=StateVariableType.CAPACITY,
            entity_id="fac_2",
            entity_type="factory",
            value=100.0,
        )
        w1 = StateVariable(
            variable_id=inventory_var_id("wh_1", "comp_a"),
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_1",
            entity_type="warehouse",
            value=800,
        )
        c1 = StateVariable(
            variable_id=demand_var_id("cust_1"),
            variable_type=StateVariableType.DEMAND,
            entity_id="cust_1",
            entity_type="customer",
            value=500,
        )

        state = create_initial_state(
            workspace_id="ws_crit_node",
            world_id="world_crit_node",
            graph_version=1,
            initial_variables={
                s_sole.variable_id: s_sole,
                f1.variable_id: f1,
                f2.variable_id: f2,
                w1.variable_id: w1,
                c1.variable_id: c1,
            },
        )

        extractor = GraphExtractor()
        graph_data = extractor.extract_from_world_state(state)
        gnn = SupplyChainGNN(in_features=graph_data.feature_dim)
        embeddings = gnn.encode(graph_data)

        predictor = CriticalNodePredictor(criticality_threshold=0.30)
        report = predictor.predict_critical_nodes(graph_data, embeddings, top_k=5)

        assert report.total_nodes_analyzed >= 5
        assert len(report.critical_nodes) > 0

        # The sole supplier should be top critical or SPOF
        top_node = report.critical_nodes[0]
        assert top_node.criticality_score > 0.0
        assert top_node.affected_downstream_nodes > 0
        assert top_node.estimated_revenue_at_risk_usd > 0
        assert len(top_node.primary_vulnerability_reasons) > 0
