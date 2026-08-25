"""Test GNN Backbone & Layer Architecture — Program K.2.

Verifies:
- Multi-Head Graph Attention Layer computation
- Residual connections and layer normalization
- SupplyChainGNN forward pass and embedding bundle extraction
"""

from __future__ import annotations

import math
import random

from app.modules.gnn.graph_representation import GraphExtractor
from app.modules.gnn.layers import GraphAttentionLayer
from app.modules.gnn.math_utils import norm
from app.modules.gnn.models import SupplyChainGNN
from app.modules.world.state_projection import (
    capacity_var_id,
    create_initial_state,
    inventory_var_id,
    lead_time_var_id,
)
from app.modules.world.world_models import StateVariable, StateVariableType


class TestGNNBackbone:
    def test_graph_attention_layer_forward(self) -> None:
        """GraphAttentionLayer applies multi-head message passing with residuals."""
        num_nodes = 5
        in_dim = 8
        out_dim = 16
        num_heads = 4

        layer = GraphAttentionLayer(
            in_features=in_dim,
            out_features=out_dim,
            num_heads=num_heads,
            residual=True,
            seed=123,
        )

        rng = random.Random(42)
        X = [[rng.gauss(0, 1) for _ in range(in_dim)] for _ in range(num_nodes)]
        adj = {0: [1, 2], 1: [0, 3], 2: [0], 3: [1, 4], 4: [3]}

        out = layer.forward(X, adj)

        assert len(out) == num_nodes
        assert len(out[0]) == out_dim

        # Check layer normalization (mean ~ 0, std ~ 1 per node)
        for i in range(num_nodes):
            m = sum(out[i]) / out_dim
            v = sum((x - m) ** 2 for x in out[i]) / out_dim
            assert abs(m) < 1e-3
            assert abs(math.sqrt(v) - 1.0) < 1e-2

    def test_supply_chain_gnn_encode_pipeline(self) -> None:
        """SupplyChainGNN encodes graph into normalized NodeEmbedding bundle."""
        v1 = StateVariable(
            variable_id=lead_time_var_id("sup_1"),
            variable_type=StateVariableType.LEAD_TIME,
            entity_id="sup_1",
            entity_type="supplier",
            value=10,
        )
        v2 = StateVariable(
            variable_id=capacity_var_id("fac_1"),
            variable_type=StateVariableType.CAPACITY,
            entity_id="fac_1",
            entity_type="factory",
            value=85.0,
        )
        v3 = StateVariable(
            variable_id=inventory_var_id("wh_1", "comp_a"),
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_1",
            entity_type="warehouse",
            value=500,
        )

        state = create_initial_state(
            workspace_id="ws_gnn_backbone",
            world_id="world_gnn_backbone",
            graph_version=1,
            initial_variables={v1.variable_id: v1, v2.variable_id: v2, v3.variable_id: v3},
        )

        extractor = GraphExtractor()
        graph_data = extractor.extract_from_world_state(state)

        gnn = SupplyChainGNN(in_features=graph_data.feature_dim, hidden_dim=32, embedding_dim=16)
        bundle = gnn.encode(graph_data)

        assert bundle.workspace_id == "ws_gnn_backbone"
        assert bundle.num_embeddings == graph_data.num_nodes
        assert bundle.dim == 16

        for emb in bundle.embeddings.values():
            assert len(emb.vector) == 16
            # Unit norm verification
            n = norm(emb.vector)
            assert abs(n - 1.0) < 1e-4
