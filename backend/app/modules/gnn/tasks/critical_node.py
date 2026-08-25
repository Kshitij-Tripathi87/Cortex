"""Critical Node & Bottleneck Prediction Task Engine.

Program K.4 (Critical Node & Single Point of Failure Detection):
Identifies systemic bottleneck entities whose disruption triggers catastrophic
network-wide failure.
"""

from __future__ import annotations

from app.modules.gnn.gnn_models import (
    CriticalNodePrediction,
    CriticalNodeReport,
    EmbeddingBundle,
    HeteroGraphData,
)
from app.modules.gnn.math_utils import norm


class CriticalNodePredictor:
    """Predicts systemic bottleneck nodes and single points of failure (SPOFs)."""

    def __init__(
        self,
        criticality_threshold: float = 0.65,
        default_component_value: float = 25000.0,
    ):
        self.criticality_threshold = criticality_threshold
        self.default_component_value = default_component_value

    def predict_critical_nodes(
        self,
        graph_data: HeteroGraphData,
        embeddings: EmbeddingBundle,
        top_k: int = 10,
    ) -> CriticalNodeReport:
        """Scan network and classify systemic criticality per node."""
        predictions = []

        # Count in and out degree per node
        out_edges: dict[str, list[str]] = {nid: [] for nid in graph_data.nodes}
        in_edges: dict[str, list[str]] = {nid: [] for nid in graph_data.nodes}
        for e in graph_data.edges:
            if e.source_id in out_edges:
                out_edges[e.source_id].append(e.target_id)
            if e.target_id in in_edges:
                in_edges[e.target_id].append(e.source_id)

        spof_count = 0
        max_risk = 0.0

        for nid, node in graph_data.nodes.items():
            # 1. Structural bottleneck signals
            in_deg = len(in_edges[nid])
            pagerank = node.features.get("pagerank", 0.1)
            capacity = node.features.get("capacity_pct", 100.0)

            # 2. Embedding norm and activation magnitude
            emb_vector = embeddings.embeddings.get(nid)
            emb_norm = norm(emb_vector.vector) if emb_vector else 1.0

            # 3. Downstream impact count (breadth-first traversal)
            downstream = self._count_downstream_reach(nid, out_edges)

            # 4. Criticality Score Formula
            reach_ratio = downstream / max(1, graph_data.num_nodes)
            centrality_factor = min(1.0, pagerank * len(graph_data.nodes))
            capacity_stress = max(0.0, (100.0 - capacity) / 100.0)

            raw_score = (0.45 * reach_ratio) + (0.35 * centrality_factor) + (0.20 * capacity_stress)
            criticality_score = float(min(1.0, max(0.0, raw_score * emb_norm)))

            is_critical = criticality_score >= self.criticality_threshold
            is_spof = (downstream >= len(graph_data.nodes) // 3) and (in_deg <= 1)

            if is_spof:
                spof_count += 1
            if criticality_score > max_risk:
                max_risk = criticality_score

            reasons = []
            if is_spof:
                reasons.append(
                    "Single Point of Failure: No redundant supply path for downstream nodes"
                )
            if reach_ratio > 0.4:
                reasons.append(f"High network blast radius: Reaches {downstream} downstream nodes")
            if centrality_factor > 0.7:
                reasons.append("High topological centrality across supply chains")
            if capacity < 80.0:
                reasons.append(f"Operating under capacity stress ({capacity:.0f}%)")

            if not reasons:
                reasons.append("Normal operational profile")

            est_revenue_loss = downstream * self.default_component_value * criticality_score

            predictions.append(
                CriticalNodePrediction(
                    node_id=node.entity_id,
                    node_type=node.node_type,
                    name=node.name,
                    criticality_score=criticality_score,
                    is_critical=is_critical,
                    is_single_point_of_failure=is_spof,
                    affected_downstream_nodes=downstream,
                    estimated_revenue_at_risk_usd=est_revenue_loss,
                    primary_vulnerability_reasons=reasons,
                )
            )

        # Sort descending by criticality score
        predictions.sort(key=lambda p: p.criticality_score, reverse=True)

        return CriticalNodeReport(
            workspace_id=graph_data.workspace_id,
            world_id=graph_data.world_id,
            total_nodes_analyzed=graph_data.num_nodes,
            critical_nodes=predictions[:top_k],
            spof_count=spof_count,
            max_network_risk_score=max_risk,
            model_version=embeddings.model_version,
        )

    def _count_downstream_reach(self, start_nid: str, out_edges: dict[str, list[str]]) -> int:
        """Count unique reachable downstream entities via BFS."""
        visited = set()
        queue = [start_nid]
        while queue:
            curr = queue.pop(0)
            for neighbor in out_edges.get(curr, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
        return len(visited)
