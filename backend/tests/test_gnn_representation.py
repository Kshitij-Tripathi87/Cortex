"""Test GNN Graph Representation & Extraction — Program K.1.

Verifies:
- Heterogeneous graph extraction from WorldState
- Operational and topological feature encoding
- PageRank and degree centrality calculation
- HeteroGraphData invariant integrity
"""

from __future__ import annotations

from app.modules.gnn.gnn_models import NodeType
from app.modules.gnn.graph_representation import GraphExtractor
from app.modules.world.state_projection import (
    capacity_var_id,
    create_initial_state,
    demand_var_id,
    inventory_var_id,
    lead_time_var_id,
    supplier_health_var_id,
)
from app.modules.world.world_models import StateVariable, StateVariableType


class TestGraphRepresentation:
    def test_extract_heterogeneous_graph_from_world_state(self) -> None:
        """Extract multi-tier supply chain graph from WorldState variables."""
        # 1. Setup multi-node world state
        s1 = StateVariable(
            variable_id=lead_time_var_id("sup_alpha"),
            variable_type=StateVariableType.LEAD_TIME,
            entity_id="sup_alpha",
            entity_type="supplier",
            value=7,
        )
        s1_health = StateVariable(
            variable_id=supplier_health_var_id("sup_alpha"),
            variable_type=StateVariableType.SUPPLIER_HEALTH,
            entity_id="sup_alpha",
            entity_type="supplier",
            value=0.95,
        )
        f1 = StateVariable(
            variable_id=capacity_var_id("fac_bravo"),
            variable_type=StateVariableType.CAPACITY,
            entity_id="fac_bravo",
            entity_type="factory",
            value=90.0,
        )
        w1 = StateVariable(
            variable_id=inventory_var_id("wh_charlie", "comp_1"),
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_charlie",
            entity_type="warehouse",
            value=1200,
        )
        c1 = StateVariable(
            variable_id=demand_var_id("cust_delta"),
            variable_type=StateVariableType.DEMAND,
            entity_id="cust_delta",
            entity_type="customer",
            value=450,
        )

        state = create_initial_state(
            workspace_id="ws_gnn_rep",
            world_id="world_gnn_rep",
            graph_version=1,
            initial_variables={
                s1.variable_id: s1,
                s1_health.variable_id: s1_health,
                f1.variable_id: f1,
                w1.variable_id: w1,
                c1.variable_id: c1,
            },
        )

        # 2. Extract graph
        extractor = GraphExtractor()
        graph_data = extractor.extract_from_world_state(state)

        # Assertions
        assert graph_data.workspace_id == "ws_gnn_rep"
        assert graph_data.world_id == "world_gnn_rep"
        assert graph_data.num_nodes >= 4
        assert len(graph_data.edges) >= 3

        # Verify node types
        node_types = {n.node_type for n in graph_data.nodes.values()}
        assert NodeType.SUPPLIER in node_types
        assert NodeType.FACTORY in node_types
        assert NodeType.WAREHOUSE in node_types
        assert NodeType.CUSTOMER in node_types

        # Verify structural features
        for node in graph_data.nodes.values():
            assert "pagerank" in node.features
            assert "degree_centrality" in node.features
            assert node.features["pagerank"] > 0.0
