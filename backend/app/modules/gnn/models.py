"""Supply Chain Graph Neural Network Backbone Architecture.

Program K.2 (Graph Neural Network Backbone):
- Multi-layer Heterogeneous Graph Attention Network (HeteroGAT)
- Produces normalized dense node embeddings capturing multi-hop supply chain context
"""

from __future__ import annotations

from app.modules.gnn.gnn_models import (
    EmbeddingBundle,
    HeteroGraphData,
    NodeEmbedding,
)
from app.modules.gnn.layers import GraphAttentionLayer
from app.modules.gnn.math_utils import normalize

GNN_MODEL_VERSION = "cortex-gnn-v1.0"


class SupplyChainGNN:
    """Multi-layer Graph Neural Network for Supply Chain Operational Graphs."""

    def __init__(
        self,
        in_features: int = 10,
        hidden_dim: int = 64,
        embedding_dim: int = 32,
        num_layers: int = 2,
        num_heads: int = 4,
        seed: int = 42,
        version: str = GNN_MODEL_VERSION,
    ):
        self.in_features = in_features
        self.hidden_dim = hidden_dim
        self.embedding_dim = embedding_dim
        self.num_layers = num_layers
        self.version = version

        self.layers: list[GraphAttentionLayer] = []

        # Layer 1: in_features -> hidden_dim
        self.layers.append(
            GraphAttentionLayer(
                in_features=in_features,
                out_features=hidden_dim,
                num_heads=num_heads,
                seed=seed,
            )
        )

        # Intermediate layers
        for layer_idx in range(1, num_layers - 1):
            self.layers.append(
                GraphAttentionLayer(
                    in_features=hidden_dim,
                    out_features=hidden_dim,
                    num_heads=num_heads,
                    seed=seed + layer_idx,
                )
            )

        # Final Embedding Layer: hidden_dim -> embedding_dim
        self.layers.append(
            GraphAttentionLayer(
                in_features=hidden_dim,
                out_features=embedding_dim,
                num_heads=num_heads,
                seed=seed + 99,
            )
        )

    def encode(self, graph_data: HeteroGraphData) -> EmbeddingBundle:
        """Forward pass over graph to compute all node embeddings."""
        num_nodes = graph_data.num_nodes
        if num_nodes == 0:
            return EmbeddingBundle(
                workspace_id=graph_data.workspace_id,
                world_id=graph_data.world_id,
                version=graph_data.version,
                embeddings={},
                dim=self.embedding_dim,
                model_version=self.version,
            )

        # 1. Construct feature matrix X as list of lists
        sorted_node_ids = [graph_data.idx_to_node[i] for i in range(num_nodes)]
        feature_keys = sorted(graph_data.nodes[sorted_node_ids[0]].features.keys())

        X = []
        for nid in sorted_node_ids:
            node = graph_data.nodes[nid]
            row = [node.features.get(k, 0.0) for k in feature_keys]
            # Pad or truncate to in_features
            if len(row) < self.in_features:
                row.extend([0.0] * (self.in_features - len(row)))
            elif len(row) > self.in_features:
                row = row[: self.in_features]
            X.append(row)

        # 2. Construct bidirectional adjacency list
        adj: dict[int, list[int]] = {i: [] for i in range(num_nodes)}
        for edge in graph_data.edges:
            if (
                edge.source_id in graph_data.node_to_idx
                and edge.target_id in graph_data.node_to_idx
            ):
                src_idx = graph_data.node_to_idx[edge.source_id]
                dst_idx = graph_data.node_to_idx[edge.target_id]
                adj[src_idx].append(dst_idx)
                adj[dst_idx].append(src_idx)

        # 3. Pass through GNN layers
        H = X
        for layer in self.layers:
            H = layer.forward(H, adj)

        # 4. L2 Normalize node embeddings for cosine similarity
        embeddings: dict[str, NodeEmbedding] = {}
        for i, nid in enumerate(sorted_node_ids):
            node = graph_data.nodes[nid]
            norm_vec = normalize(H[i])
            embeddings[nid] = NodeEmbedding(
                node_id=nid,
                node_type=node.node_type,
                vector=norm_vec,
                dim=self.embedding_dim,
                model_version=self.version,
            )

        return EmbeddingBundle(
            workspace_id=graph_data.workspace_id,
            world_id=graph_data.world_id,
            version=graph_data.version,
            embeddings=embeddings,
            dim=self.embedding_dim,
            model_version=self.version,
        )
