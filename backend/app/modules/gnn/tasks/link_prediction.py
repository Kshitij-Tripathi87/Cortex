"""Hidden Dependency & Latent Link Prediction Task Engine.

Program K.5 (Hidden Dependency & Latent Vulnerability Detection):
Discovers unrecorded, indirect dependencies such as shared tier-2 suppliers,
geographical co-location risks, and latent correlation clusters.
"""

from __future__ import annotations

import math

from app.modules.gnn.gnn_models import (
    EdgeType,
    EmbeddingBundle,
    HeteroGraphData,
    HiddenDependencyReport,
    PredictedHiddenDependency,
)
from app.modules.gnn.math_utils import dot, random_matrix, vec_mat_mul


class HiddenDependencyDetector:
    """Discovers latent dependencies and hidden single-point-of-failure clusters."""

    def __init__(self, confidence_threshold: float = 0.50, seed: int = 42):
        self.confidence_threshold = confidence_threshold
        # Bilinear projection matrix for link scoring
        self.W_link = random_matrix(32, 32, seed=seed, std=0.1)

    def detect_hidden_dependencies(
        self,
        graph_data: HeteroGraphData,
        embeddings: EmbeddingBundle,
        max_discoveries: int = 15,
    ) -> HiddenDependencyReport:
        """Detect latent dependencies between entities with no direct recorded edge."""
        existing_edges = set()
        for e in graph_data.edges:
            existing_edges.add((e.source_id, e.target_id))
            existing_edges.add((e.target_id, e.source_id))

        node_ids = sorted(graph_data.nodes.keys())
        discoveries = []
        clusters = []

        # Find 2-hop shared neighbors
        neighbors_map: dict[str, set[str]] = {nid: set() for nid in node_ids}
        for e in graph_data.edges:
            neighbors_map[e.source_id].add(e.target_id)
            neighbors_map[e.target_id].add(e.source_id)

        dim = embeddings.dim
        W = [row[:dim] for row in self.W_link[:dim]]

        for i in range(len(node_ids)):
            nid_u = node_ids[i]
            if nid_u not in embeddings.embeddings:
                continue
            z_u = embeddings.embeddings[nid_u].vector

            for j in range(i + 1, len(node_ids)):
                nid_v = node_ids[j]
                if nid_v not in embeddings.embeddings:
                    continue

                if (nid_u, nid_v) in existing_edges:
                    continue

                z_v = embeddings.embeddings[nid_v].vector

                # Bilinear link score: sigmoid(z_u^T W z_v)
                z_u_W = vec_mat_mul(z_u, W)
                raw_score = dot(z_u_W, z_v)
                cos_sim = dot(z_u, z_v)
                logit = -raw_score - 2.0 * cos_sim
                confidence = 1.0 / (1.0 + math.exp(max(-50.0, min(50.0, logit))))

                shared_neighbors = neighbors_map[nid_u] & neighbors_map[nid_v]

                if confidence >= self.confidence_threshold or len(shared_neighbors) >= 1:
                    u_node = graph_data.nodes[nid_u]
                    v_node = graph_data.nodes[nid_v]

                    if len(shared_neighbors) >= 1:
                        dep_nature = "shared_upstream_supplier_or_hub"
                        evidence = f"Both entities share {len(shared_neighbors)} upstream operational connections."
                        risk = "high"
                    else:
                        dep_nature = "latent_topological_cluster"
                        evidence = f"High GNN structural correlation score ({confidence:.2f}) indicates hidden dependency."
                        risk = "medium"

                    discoveries.append(
                        PredictedHiddenDependency(
                            source_node_id=u_node.entity_id,
                            target_node_id=v_node.entity_id,
                            predicted_edge_type=EdgeType.DEPENDS_ON,
                            confidence=confidence,
                            dependency_nature=dep_nature,
                            evidence_rationale=evidence,
                            risk_impact=risk,
                        )
                    )

        discoveries.sort(key=lambda d: d.confidence, reverse=True)

        if discoveries:
            primary_cluster = [discoveries[0].source_node_id, discoveries[0].target_node_id]
            clusters.append(primary_cluster)

        return HiddenDependencyReport(
            workspace_id=graph_data.workspace_id,
            world_id=graph_data.world_id,
            discovered_dependencies=discoveries[:max_discoveries],
            high_risk_correlation_clusters=clusters,
            model_version=embeddings.model_version,
        )
