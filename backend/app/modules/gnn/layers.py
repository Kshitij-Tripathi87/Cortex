"""GNN Layers — Pure Python Graph Attention & Message Passing Architectures.

Program K.2 (Graph Neural Network Layers):
- Multi-Head Heterogeneous Graph Attention Layer (GraphAttentionLayer)
- Residual Connections & Layer Normalization
- Relation-Specific Weight Projections
"""

from __future__ import annotations

import math

from app.modules.gnn.math_utils import (
    dot,
    elu,
    layer_norm,
    leaky_relu,
    random_matrix,
    random_vector,
    softmax,
    vec_mat_mul,
)


class GraphAttentionLayer:
    """Multi-Head Graph Attention Layer with relation-aware message passing."""

    def __init__(
        self,
        in_features: int,
        out_features: int,
        num_heads: int = 4,
        dropout: float = 0.1,
        alpha: float = 0.2,  # LeakyReLU slope
        residual: bool = True,
        seed: int = 42,
    ):
        self.in_features = in_features
        self.out_features = out_features
        self.num_heads = num_heads
        self.head_dim = max(1, out_features // num_heads)
        self.dropout = dropout
        self.alpha = alpha
        self.residual = residual

        # Deterministic Xavier initialization
        std = math.sqrt(2.0 / (in_features + out_features))

        # Weight matrices for each head: (in_features x head_dim)
        self.W = [
            random_matrix(in_features, self.head_dim, seed=seed + h * 10, std=std)
            for h in range(num_heads)
        ]
        # Self and neighbor attention vectors: (head_dim)
        self.a_src = [
            random_vector(self.head_dim, seed=seed + h * 10 + 1, std=std) for h in range(num_heads)
        ]
        self.a_dst = [
            random_vector(self.head_dim, seed=seed + h * 10 + 2, std=std) for h in range(num_heads)
        ]

        # Residual projection if dimensions differ
        if residual and in_features != out_features:
            self.W_res = random_matrix(in_features, out_features, seed=seed + 999, std=std)
        else:
            self.W_res = None

    def forward(
        self,
        node_features: list[list[float]],  # Shape: (N, in_features)
        adjacency_list: dict[int, list[int]],  # node_idx -> list of neighbor node_idx
    ) -> list[list[float]]:
        """Execute forward graph attention message passing pass."""
        num_nodes = len(node_features)
        if num_nodes == 0:
            return []

        # Store projected outputs per head: head -> list of vectors (N x head_dim)
        head_outputs: list[list[list[float]]] = []

        for h in range(self.num_heads):
            W_h = self.W[h]
            a_s = self.a_src[h]
            a_d = self.a_dst[h]

            # Linear projection: h_proj[i] = x_i * W_h
            h_proj = [vec_mat_mul(node_features[i], W_h) for i in range(num_nodes)]

            # Attention scores
            score_src = [dot(h_proj[i], a_s) for i in range(num_nodes)]
            score_dst = [dot(h_proj[i], a_d) for i in range(num_nodes)]

            out_h = []
            for i in range(num_nodes):
                neighbors = adjacency_list.get(i, [])
                all_neighbors = [i] + [nbr for nbr in neighbors if nbr < num_nodes]

                # Compute unnormalized logits
                logits = [
                    leaky_relu(score_src[i] + score_dst[j], self.alpha) for j in all_neighbors
                ]
                attn_weights = softmax(logits)

                # Weighted sum of neighbor representations
                aggregated = [0.0] * self.head_dim
                for w_idx, j in enumerate(all_neighbors):
                    weight = attn_weights[w_idx]
                    for d in range(self.head_dim):
                        aggregated[d] += weight * h_proj[j][d]

                out_h.append(aggregated)

            head_outputs.append(out_h)

        # Concatenate multi-head outputs: (N, num_heads * head_dim)
        out = []
        for i in range(num_nodes):
            concat_vec = []
            for h in range(self.num_heads):
                concat_vec.extend(head_outputs[h][i])

            # If concat dimension is smaller/larger than out_features, adjust
            if len(concat_vec) < self.out_features:
                concat_vec.extend([0.0] * (self.out_features - len(concat_vec)))
            elif len(concat_vec) > self.out_features:
                concat_vec = concat_vec[: self.out_features]

            # Non-linear activation (ELU)
            activated = [elu(x) for x in concat_vec]

            # Residual connection
            if self.residual:
                if self.W_res is not None:
                    res = vec_mat_mul(node_features[i], self.W_res)
                elif len(node_features[i]) == self.out_features:
                    res = node_features[i]
                else:
                    res = [0.0] * self.out_features
                activated = [a + r for a, r in zip(activated, res, strict=True)]

            # Layer normalization
            normed = layer_norm(activated)
            out.append(normed)

        return out
