"""Nexus GNN Engine — production graph intelligence for decision features.

Rather than running a full PyG model inline (which would add heavy deps),
this engine implements deterministic graph algorithms that produce
GNN-style features:

  - Node centrality (Pagerank-like) for critical-node detection
  - Betweenness for bottleneck detection
  - Multi-hop reachability for hidden dependency discovery
  - Risk propagation along weighted edges
  - Supplier similarity via shared-customer / shared-product Jaccard

These features are injected into risk scores and decisions so that the
operator sees GNN outputs alongside traditional risk metrics — e.g.:

    Supplier S-142
    Traditional risk score: 0.71
    GNN risk score:         0.88
    Hidden dependency:
      S-142 → subcontractor X → port P-07
    Impact: +12 additional downstream orders
"""

from __future__ import annotations

import math
import threading
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class HiddenDependency:
    """A multi-hop chain the traditional risk engine would miss."""

    source_entity_id: str
    path: list[str]
    path_relation_types: list[str]
    target_entity_id: str
    risk_contribution: float  # how much this hidden chain adds to risk
    downstream_order_count: int
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_entity_id": self.source_entity_id,
            "path": self.path,
            "path_relation_types": self.path_relation_types,
            "target_entity_id": self.target_entity_id,
            "risk_contribution": round(self.risk_contribution, 4),
            "downstream_order_count": self.downstream_order_count,
            "description": self.description,
        }


@dataclass
class RiskPropagationPath:
    """How risk propagates from a failing node through the graph."""

    origin_entity_id: str
    affected_entities: list[dict[str, Any]]
    propagation_depth: int
    total_blast_radius: int
    revenue_at_risk: float
    pagerank_decay: list[float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "origin_entity_id": self.origin_entity_id,
            "affected_entities": self.affected_entities,
            "propagation_depth": self.propagation_depth,
            "total_blast_radius": self.total_blast_radius,
            "revenue_at_risk": round(self.revenue_at_risk, 2),
            "pagerank_decay": [round(p, 4) for p in self.pagerank_decay],
        }


@dataclass
class SupplierSimilarity:
    """Similar suppliers for alternative sourcing recommendations."""

    supplier_id: str
    similar_suppliers: list[
        dict[str, Any]
    ]  # [{supplier_id, similarity_score, shared_skus, shared_regions}]

    def to_dict(self) -> dict[str, Any]:
        return {
            "supplier_id": self.supplier_id,
            "similar_suppliers": [
                {
                    "supplier_id": s["supplier_id"],
                    "similarity_score": round(s["similarity_score"], 4),
                    "shared_skus": s["shared_skus"],
                    "shared_regions": s["shared_regions"],
                    "can_absorb_pct": round(s.get("can_absorb_pct", 0), 4),
                }
                for s in self.similar_suppliers
            ],
        }


@dataclass
class GNNRiskAugmentation:
    """GNN-augmented risk score for an entity."""

    entity_id: str
    entity_kind: str
    traditional_risk_score: float
    gnn_risk_score: float
    critical_node_probability: float
    hidden_dependencies: list[HiddenDependency]
    centrality_rank: int
    centrality_score: float
    bottleneck_score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "entity_kind": self.entity_kind,
            "traditional_risk_score": round(self.traditional_risk_score, 4),
            "gnn_risk_score": round(self.gnn_risk_score, 4),
            "critical_node_probability": round(self.critical_node_probability, 4),
            "hidden_dependencies": [h.to_dict() for h in self.hidden_dependencies],
            "centrality_rank": self.centrality_rank,
            "centrality_score": round(self.centrality_score, 4),
            "bottleneck_score": round(self.bottleneck_score, 4),
            "risk_uplift": round(self.gnn_risk_score - self.traditional_risk_score, 4),
        }


class GNNEngine:
    """Deterministic GNN-style graph analysis engine.

    Operates on the live world model graph, computing embeddings and
    structural features that are then fed into risk scores and decisions.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._cache_version: int = -1
        self._pagerank: dict[UUID, float] = {}
        self._adjacency: dict[UUID, list[tuple[UUID, str]]] = defaultdict(list)
        self._node_metadata: dict[UUID, dict[str, Any]] = {}

    def _build_graph_from_world(self, wm: Any) -> None:
        """(Re)build adjacency from the world model."""
        version = wm.world_state_version
        if version == self._cache_version:
            return
        adj: dict[UUID, list[tuple[UUID, str]]] = defaultdict(list)
        meta: dict[UUID, dict[str, Any]] = {}
        # Iterate all entities
        for entity in wm.iter_all_entities():
            eid = entity.entity_id
            meta[eid] = {
                "kind": entity.kind.value if hasattr(entity.kind, "value") else str(entity.kind),
                "state": dict(entity.state) if hasattr(entity, "state") else {},
                "name": entity.name if hasattr(entity, "name") else str(eid),
            }
        # Iterate relationships (edges)
        if hasattr(wm, "relationships"):
            for edge in wm.iter_relationships():
                src = edge.source_id if hasattr(edge, "source_id") else edge.from_id
                dst = edge.target_id if hasattr(edge, "target_id") else edge.to_id
                rel_type = (
                    edge.relationship_kind.value
                    if hasattr(edge.relationship_kind, "value")
                    else str(edge.relationship_kind)
                )
                adj[src].append((dst, rel_type))
                adj[dst].append((src, rel_type))  # undirected for propagation
        self._adjacency = adj
        self._node_metadata = meta
        self._compute_pagerank()
        self._cache_version = version

    def _compute_pagerank(self, damping: float = 0.85, iterations: int = 20) -> None:
        """Simple power-iteration PageRank for critical node detection."""
        nodes = list(self._adjacency.keys())
        # Include nodes with no edges
        for nid in self._node_metadata:
            if nid not in self._adjacency:
                self._adjacency[nid] = []
                nodes.append(nid)
        nodes = list(set(nodes))
        n = len(nodes)
        if n == 0:
            self._pagerank = {}
            return
        pr = {node: 1.0 / n for node in nodes}
        for _ in range(iterations):
            new_pr = {node: (1 - damping) / n for node in nodes}
            for node in nodes:
                neighbors = self._adjacency.get(node, [])
                if neighbors:
                    share = damping * pr[node] / len(neighbors)
                    for neighbor, _ in neighbors:
                        if neighbor in new_pr:
                            new_pr[neighbor] += share
                else:
                    # Dangling nodes distribute evenly
                    share = damping * pr[node] / n
                    for other in nodes:
                        new_pr[other] += share
            pr = new_pr
        # Normalize
        total = sum(pr.values()) or 1.0
        self._pagerank = {k: v / total for k, v in pr.items()}

    def augment_risk(
        self,
        entity_id: UUID,
        traditional_risk: float,
        *,
        tenant_id: UUID,
        workspace_id: UUID,
        max_depth: int = 3,
    ) -> GNNRiskAugmentation:
        """Augment a traditional risk score with GNN structural signals."""
        with self._lock:
            centrality = self._pagerank.get(entity_id, 0.0)
            # Normalize centrality against the max
            max_c = max(self._pagerank.values()) if self._pagerank else 0.01
            norm_centrality = centrality / max_c if max_c > 0 else 0.0
            # Bottleneck: how many shortest paths from suppliers to orders go through here
            bottleneck = self._compute_bottleneck(entity_id, max_depth)
            # Hidden dependencies
            hidden = self._find_hidden_dependencies(entity_id, max_depth)
            # Critical node probability: combination of centrality, bottleneck, current risk
            critical_prob = min(
                1.0, (norm_centrality * 0.4 + bottleneck * 0.3 + traditional_risk * 0.3)
            )
            # GNN risk score uplifts traditional risk with graph signals
            uplift = norm_centrality * 0.15 + bottleneck * 0.1 + len(hidden) * 0.03
            gnn_score = min(1.0, traditional_risk + uplift)
            # Rank
            ranked = sorted(self._pagerank.items(), key=lambda x: x[1], reverse=True)
            rank = next((i + 1 for i, (nid, _) in enumerate(ranked) if nid == entity_id), 0)
            kind = self._node_metadata.get(entity_id, {}).get("kind", "unknown")
            return GNNRiskAugmentation(
                entity_id=str(entity_id),
                entity_kind=kind,
                traditional_risk_score=traditional_risk,
                gnn_risk_score=gnn_score,
                critical_node_probability=critical_prob,
                hidden_dependencies=hidden,
                centrality_rank=rank,
                centrality_score=norm_centrality,
                bottleneck_score=bottleneck,
            )

    def _compute_bottleneck(self, entity_id: UUID, max_depth: int) -> float:
        """Estimate bottleneck score using BFS and path counting."""
        # Count how many source (supplier) → sink (order/plant) paths pass through this node
        # Simplified: fraction of reachable suppliers that route THROUGH this node to reach orders
        if entity_id not in self._adjacency:
            return 0.0
        # Count nodes reachable from entity within max_depth
        reachable = set()
        queue: deque[tuple[UUID, int]] = deque([(entity_id, 0)])
        while queue:
            node, depth = queue.popleft()
            if depth > max_depth:
                continue
            if node in reachable:
                continue
            reachable.add(node)
            for neighbor, _ in self._adjacency.get(node, []):
                if neighbor not in reachable:
                    queue.append((neighbor, depth + 1))
        # Bottleneck is roughly the betweenness: nodes that, when removed, disconnect parts
        # Approximate via degree and reachable size
        degree = len(self._adjacency.get(entity_id, []))
        n_total = max(1, len(self._adjacency))
        return min(1.0, (degree * len(reachable)) / (n_total * 10))

    def _find_hidden_dependencies(self, entity_id: UUID, max_depth: int) -> list[HiddenDependency]:
        """Find multi-hop dependency chains through intermediaries."""
        hidden: list[HiddenDependency] = []
        if entity_id not in self._adjacency:
            return hidden
        # BFS for paths of length >= 2 where intermediate nodes have low individual risk
        visited = {entity_id}
        queue: deque[tuple[UUID, list[UUID], list[str], int]] = deque()
        for neighbor, rel_type in self._adjacency.get(entity_id, []):
            queue.append((neighbor, [entity_id, neighbor], [rel_type], 1))
        while queue:
            node, path, rels, depth = queue.popleft()
            if depth >= max_depth:
                continue
            if node in visited and depth > 1:
                continue
            visited.add(node)
            # If we've reached a node of different kind with >1 hop, that's a hidden dependency
            if depth >= 2:
                node_kind = self._node_metadata.get(node, {}).get("kind", "")
                src_kind = self._node_metadata.get(entity_id, {}).get("kind", "")
                if node_kind != src_kind:
                    # Count downstream orders impacted
                    downstream = self._count_reachable_by_kind(node, "order", 2)
                    if downstream > 0:
                        risk_contrib = min(0.3, 0.05 * downstream / 10)
                        hidden.append(
                            HiddenDependency(
                                source_entity_id=str(entity_id),
                                path=[str(p) for p in path],
                                path_relation_types=rels,
                                target_entity_id=str(node),
                                risk_contribution=risk_contrib,
                                downstream_order_count=downstream,
                                description=f"{src_kind or 'entity'} → {' → '.join(self._node_metadata.get(p, {}).get('kind', '?') for p in path[1:-1])} → {node_kind or 'entity'}",
                            )
                        )
            for neighbor, rel_type in self._adjacency.get(node, []):
                if neighbor not in path:
                    queue.append((neighbor, path + [neighbor], rels + [rel_type], depth + 1))
        return hidden[:5]  # Top 5 hidden dependencies

    def _count_reachable_by_kind(self, start: UUID, kind: str, max_depth: int) -> int:
        if start not in self._adjacency:
            return 0
        visited = set()
        queue: deque[tuple[UUID, int]] = deque([(start, 0)])
        count = 0
        while queue:
            node, depth = queue.popleft()
            if depth > max_depth or node in visited:
                continue
            visited.add(node)
            node_kind = self._node_metadata.get(node, {}).get("kind", "").lower()
            if kind.lower() in node_kind and depth > 0:
                count += 1
            for neighbor, _ in self._adjacency.get(node, []):
                if neighbor not in visited:
                    queue.append((neighbor, depth + 1))
        return count

    def trace_risk_propagation(
        self,
        entity_id: UUID,
        *,
        max_depth: int = 4,
    ) -> RiskPropagationPath:
        """Trace how risk propagates outward from a failing entity."""
        affected: list[dict[str, Any]] = []
        decays: list[float] = []
        visited = {entity_id}
        queue: deque[tuple[UUID, int]] = deque([(entity_id, 0)])
        revenue_total = 0.0
        while queue:
            node, depth = queue.popleft()
            if depth > max_depth:
                continue
            decay = math.exp(-depth * 0.5)  # Exponential decay with hops
            if depth > 0:
                meta = self._node_metadata.get(node, {})
                state = meta.get("state", {})
                revenue = float(state.get("revenue", state.get("order_value", 0)))
                affected.append(
                    {
                        "entity_id": str(node),
                        "entity_kind": meta.get("kind", "unknown"),
                        "depth": depth,
                        "impact_decay": round(decay, 4),
                        "revenue_at_risk": round(revenue * decay, 2),
                    }
                )
                revenue_total += revenue * decay
                decays.append(decay)
            for neighbor, _ in self._adjacency.get(node, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, depth + 1))
        return RiskPropagationPath(
            origin_entity_id=str(entity_id),
            affected_entities=affected,
            propagation_depth=max_depth,
            total_blast_radius=len(affected),
            revenue_at_risk=revenue_total,
            pagerank_decay=decays,
        )

    def find_similar_suppliers(
        self,
        supplier_id: UUID,
        *,
        top_k: int = 5,
    ) -> SupplierSimilarity:
        """Find similar suppliers using graph-structural similarity + shared SKUs."""
        supp_meta = self._node_metadata.get(supplier_id, {})
        supp_state = supp_meta.get("state", {})
        our_skus = set(supp_state.get("skus", []))
        our_region = supp_state.get("region")
        neighbors = set(n for n, _ in self._adjacency.get(supplier_id, []))
        candidates = []
        for nid, meta in self._node_metadata.items():
            if nid == supplier_id:
                continue
            if "supplier" not in meta.get("kind", "").lower():
                continue
            n_state = meta.get("state", {})
            their_skus = set(n_state.get("skus", []))
            their_region = n_state.get("region")
            # Jaccard similarity on SKUs
            union = our_skus | their_skus
            sku_sim = len(our_skus & their_skus) / len(union) if union else 0
            # Structural similarity: shared neighbors
            their_neighbors = set(n for n, _ in self._adjacency.get(nid, []))
            neighbor_union = neighbors | their_neighbors
            struct_sim = (
                len(neighbors & their_neighbors) / len(neighbor_union) if neighbor_union else 0
            )
            region_bonus = 0.2 if our_region and their_region == our_region else 0.0
            # Capacity
            our_capacity = float(supp_state.get("capacity", 100))
            their_capacity = float(n_state.get("capacity", 0))
            capacity_ratio = min(1.0, their_capacity / max(1, our_capacity * 0.5))
            score = sku_sim * 0.5 + struct_sim * 0.3 + region_bonus + capacity_ratio * 0.2
            candidates.append(
                {
                    "supplier_id": str(nid),
                    "similarity_score": min(1.0, score),
                    "shared_skus": list(our_skus & their_skus)[:10],
                    "shared_regions": our_region == their_region if our_region else False,
                    "can_absorb_pct": capacity_ratio,
                    "name": meta.get("name", str(nid)),
                }
            )
        candidates.sort(key=lambda c: c["similarity_score"], reverse=True)
        return SupplierSimilarity(
            supplier_id=str(supplier_id),
            similar_suppliers=candidates[:top_k],
        )

    def get_critical_nodes(self, top_k: int = 10) -> list[dict[str, Any]]:
        """Return the top-K most critical nodes by PageRank centrality."""
        ranked = sorted(self._pagerank.items(), key=lambda x: x[1], reverse=True)
        results = []
        for nid, score in ranked[:top_k]:
            meta = self._node_metadata.get(nid, {})
            results.append(
                {
                    "entity_id": str(nid),
                    "entity_kind": meta.get("kind", "unknown"),
                    "name": meta.get("name", str(nid)),
                    "pagerank": round(score, 6),
                    "centrality_score": round(score / max((s for _, s in ranked), default=1.0), 4),
                }
            )
        return results

    def refresh(self, wm: Any) -> None:
        """Force a rebuild of the graph from the world model."""
        with self._lock:
            self._cache_version = -1
            self._build_graph_from_world(wm)

    def health(self) -> dict[str, Any]:
        n_nodes = len(self._node_metadata)
        n_edges = sum(len(v) for v in self._adjacency.values()) // 2
        return {
            "nodes": n_nodes,
            "edges": n_edges,
            "cache_version": self._cache_version,
            "graph_density": (2 * n_edges) / (n_nodes * (n_nodes - 1)) if n_nodes > 1 else 0,
        }


_singleton: GNNEngine | None = None


def get_gnn_engine() -> GNNEngine:
    global _singleton
    if _singleton is None:
        _singleton = GNNEngine()
    return _singleton


def reset_gnn_engine() -> None:
    global _singleton
    _singleton = None
