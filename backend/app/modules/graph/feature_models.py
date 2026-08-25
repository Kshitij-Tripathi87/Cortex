"""Graph feature dataclasses — frozen DTOs returned by the FeatureEngine.

All numeric features use float so they aggregate cleanly downstream. Scores
are normalized to [0.0, 1.0] unless otherwise documented.

These types are intentionally plain — no methods, no DB relationships,
no Pydantic. They cross the API boundary via to_dict() and the FastAPI
Pydantic response models defined in api/v1/graph.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class NodeFeatures:
    """Per-node feature vector for a single snapshot of the graph.

    All scores are in [0.0, 1.0] unless documented otherwise; see
    features.py for the exact definition of each.
    """

    node_id: str
    entity_type: str
    entity_id: str

    # ─── Degree counts ─────────────────────────────────────────────────────
    in_degree: int = 0  # number of incoming edges
    out_degree: int = 0  # number of outgoing edges
    total_degree: int = 0  # in + out

    # ─── Normalized scores ──────────────────────────────────────────────────
    degree_centrality: float = 0.0  # total_degree / max_degree_in_workspace (0..1)
    in_degree_centrality: float = 0.0
    out_degree_centrality: float = 0.0

    # ─── Reachability counts ───────────────────────────────────────────────
    downstream_reach: int = 0  # |reachable_from(seed)| - 1 (excluding self)
    upstream_reach: int = 0  # |reachable_to(seed)| - 1
    total_reach: int = 0  # downstream + upstream

    # ─── Path / depth features ──────────────────────────────────────────────
    downstream_depth: int = 0  # longest shortest-path distance from this node
    upstream_depth: int = 0  # longest shortest-path distance to this node
    criticality: float = 0.0  # weighted forward + backward impact (0..1)

    # ─── Risk / resilience features ────────────────────────────────────────
    single_point_of_failure: float = 0.0  # 0..1; higher = more critical
    concentration_risk: float = 0.0  # 0..1; supplier/customer reliance
    redundancy: float = 0.0  # 0..1; 1 = many alternatives, 0 = single-source

    # ─── Network features ──────────────────────────────────────────────────
    betweenness: float = 0.0  # normalized shortest-path participation (0..1)


@dataclass(frozen=True)
class WorkspaceFeatures:
    """Workspace-level aggregate features over a single snapshot."""

    workspace_id: str
    snapshot_id: str | None
    snapshot_version: int | None
    snapshot_hash: str | None

    node_count: int = 0
    edge_count: int = 0
    connected_components: int = 0

    # Distribution of degree centrality
    max_degree: int = 0
    avg_degree: float = 0.0
    p95_degree: int = 0  # 95th percentile degree

    # Critical node counts
    single_point_of_failure_nodes: int = 0
    high_betweenness_nodes: int = 0
    isolated_nodes: int = 0  # degree == 0

    # Aggregate risk
    avg_concentration_risk: float = 0.0
    avg_redundancy: float = 0.0
    max_criticality: float = 0.0

    # Entity-type breakdown
    entity_type_counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class FeatureSnapshot:
    """A complete computed feature set for one graph snapshot.

    The FeatureEngine returns this and caches it under the (workspace_id,
    snapshot_version) key. Programs D (signals) and E (propagation) read
    exclusively from this object — they never re-derive features.
    """

    workspace_id: str
    snapshot_id: str | None
    snapshot_version: int | None
    snapshot_hash: str | None

    by_node: dict[str, NodeFeatures] = field(default_factory=dict)
    workspace: WorkspaceFeatures | None = None

    def to_dict(self) -> dict[str, Any]:
        """Flat JSON-friendly representation (for API responses and cache)."""
        return {
            "workspace_id": self.workspace_id,
            "snapshot_id": self.snapshot_id,
            "snapshot_version": self.snapshot_version,
            "snapshot_hash": self.snapshot_hash,
            "workspace": _ws_to_dict(self.workspace) if self.workspace else None,
            "by_node": {nid: _node_to_dict(nf) for nid, nf in self.by_node.items()},
        }


def _node_to_dict(nf: NodeFeatures) -> dict[str, Any]:
    return {
        "node_id": nf.node_id,
        "entity_type": nf.entity_type,
        "entity_id": nf.entity_id,
        "in_degree": nf.in_degree,
        "out_degree": nf.out_degree,
        "total_degree": nf.total_degree,
        "degree_centrality": nf.degree_centrality,
        "in_degree_centrality": nf.in_degree_centrality,
        "out_degree_centrality": nf.out_degree_centrality,
        "downstream_reach": nf.downstream_reach,
        "upstream_reach": nf.upstream_reach,
        "total_reach": nf.total_reach,
        "downstream_depth": nf.downstream_depth,
        "upstream_depth": nf.upstream_depth,
        "criticality": nf.criticality,
        "single_point_of_failure": nf.single_point_of_failure,
        "concentration_risk": nf.concentration_risk,
        "redundancy": nf.redundancy,
        "betweenness": nf.betweenness,
    }


def _ws_to_dict(ws: WorkspaceFeatures | None) -> dict[str, Any] | None:
    if ws is None:
        return None
    return {
        "workspace_id": ws.workspace_id,
        "snapshot_id": ws.snapshot_id,
        "snapshot_version": ws.snapshot_version,
        "snapshot_hash": ws.snapshot_hash,
        "node_count": ws.node_count,
        "edge_count": ws.edge_count,
        "connected_components": ws.connected_components,
        "max_degree": ws.max_degree,
        "avg_degree": ws.avg_degree,
        "p95_degree": ws.p95_degree,
        "single_point_of_failure_nodes": ws.single_point_of_failure_nodes,
        "high_betweenness_nodes": ws.high_betweenness_nodes,
        "isolated_nodes": ws.isolated_nodes,
        "avg_concentration_risk": ws.avg_concentration_risk,
        "avg_redundancy": ws.avg_redundancy,
        "max_criticality": ws.max_criticality,
        "entity_type_counts": dict(ws.entity_type_counts),
    }
