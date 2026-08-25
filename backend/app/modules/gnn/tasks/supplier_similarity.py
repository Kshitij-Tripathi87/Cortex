"""Supplier Similarity & Alternative Sourcing Task Engine.

Program K.3 (Supplier Similarity & Alternative Sourcing):
Ranks viable alternative suppliers when a primary supplier experiences disruption,
combining learned topological embeddings with operational constraints.
"""

from __future__ import annotations

from app.modules.gnn.gnn_models import (
    EmbeddingBundle,
    HeteroGraphData,
    NodeEmbedding,
    NodeType,
    SourcingFactorScores,
    SupplierSimilarityCandidate,
    SupplierSimilarityReport,
)
from app.modules.gnn.math_utils import dot


class SupplierSimilarityEngine:
    """Computes transparent, multi-factor alternative sourcing recommendations."""

    def __init__(
        self,
        weight_embedding: float = 0.40,
        weight_lead_time: float = 0.20,
        weight_capacity: float = 0.20,
        weight_risk: float = 0.20,
    ):
        self.w_emb = weight_embedding
        self.w_lt = weight_lead_time
        self.w_cap = weight_capacity
        self.w_risk = weight_risk

    def find_alternatives(
        self,
        target_supplier_id: str,
        graph_data: HeteroGraphData,
        embeddings: EmbeddingBundle,
        top_k: int = 5,
        min_health_threshold: float = 0.40,
    ) -> SupplierSimilarityReport:
        """Find and rank alternative suppliers for a disrupted target supplier."""
        # Find target node
        target_node = None
        target_nid = None
        for nid, node in graph_data.nodes.items():
            if node.entity_id == target_supplier_id or node.node_id == target_supplier_id:
                target_node = node
                target_nid = nid
                break

        if not target_node or not target_nid or target_nid not in embeddings.embeddings:
            # Return empty report if target not found
            return SupplierSimilarityReport(
                target_supplier_id=target_supplier_id,
                target_supplier_name=target_supplier_id,
                candidates=[],
                model_version=embeddings.model_version,
            )

        target_vec = embeddings.embeddings[target_nid].vector
        target_lt = target_node.features.get("lead_time_days", 7.0)

        # Collect candidate suppliers
        candidates = []
        for nid, node in graph_data.nodes.items():
            if node.node_type != NodeType.SUPPLIER or nid == target_nid:
                continue

            cand_emb = embeddings.embeddings.get(
                nid,
                NodeEmbedding(nid, NodeType.SUPPLIER, [0.0] * embeddings.dim, embeddings.dim, ""),
            )
            cand_vec = cand_emb.vector

            # 1. Cosine similarity between embeddings (unit norm)
            emb_sim = dot(target_vec, cand_vec)
            emb_sim = max(0.0, min(1.0, (emb_sim + 1.0) / 2.0))

            # 2. Lead time compatibility
            cand_lt = node.features.get("lead_time_days", 7.0)
            lt_diff = abs(cand_lt - target_lt)
            lt_score = 1.0 / (1.0 + (lt_diff / 7.0))

            # 3. Capacity readiness
            cand_cap = node.features.get("capacity_pct", 100.0)
            cap_score = min(1.0, max(0.0, cand_cap / 100.0))

            # 4. Risk / health score match
            cand_health = node.features.get("supplier_health", 1.0)
            if cand_health < min_health_threshold:
                continue

            health_score = min(1.0, max(0.0, cand_health))

            factors = SourcingFactorScores(
                structural_embedding_similarity=emb_sim,
                lead_time_compatibility=lt_score,
                capacity_readiness=cap_score,
                risk_profile_match=health_score,
                product_overlap_score=0.85,
            )

            # Overall composite match score
            total_score = (
                self.w_emb * factors.structural_embedding_similarity
                + self.w_lt * factors.lead_time_compatibility
                + self.w_cap * factors.capacity_readiness
                + self.w_risk * factors.risk_profile_match
            )

            rationale = (
                f"High structural topological similarity ({factors.structural_embedding_similarity:.2f}) "
                f"with {cand_cap:.0f}% operational capacity and {cand_lt:.1f}d lead time."
            )

            candidates.append(
                SupplierSimilarityCandidate(
                    candidate_supplier_id=node.entity_id,
                    candidate_name=node.name,
                    overall_match_score=total_score,
                    rank=0,
                    factor_scores=factors,
                    estimated_lead_time_days=cand_lt,
                    health_score=cand_health,
                    capacity_pct=cand_cap,
                    shared_components=[],
                    recommendation_rationale=rationale,
                )
            )

        # Sort descending by match score
        candidates.sort(key=lambda c: c.overall_match_score, reverse=True)

        # Assign ranks
        ranked_candidates = []
        for rank_idx, cand in enumerate(candidates[:top_k], start=1):
            ranked_candidates.append(
                SupplierSimilarityCandidate(
                    candidate_supplier_id=cand.candidate_supplier_id,
                    candidate_name=cand.candidate_name,
                    overall_match_score=cand.overall_match_score,
                    rank=rank_idx,
                    factor_scores=cand.factor_scores,
                    estimated_lead_time_days=cand.estimated_lead_time_days,
                    health_score=cand.health_score,
                    capacity_pct=cand.capacity_pct,
                    shared_components=cand.shared_components,
                    recommendation_rationale=cand.recommendation_rationale,
                )
            )

        return SupplierSimilarityReport(
            target_supplier_id=target_node.entity_id,
            target_supplier_name=target_node.name,
            candidates=ranked_candidates,
            model_version=embeddings.model_version,
        )
