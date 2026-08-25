"""FeatureEngine — orchestrator that computes feature snapshots over a workspace graph.

Design principle: FeatureEngine depends ONLY on GraphService, never on the
repository directly. This keeps Programs C–E cleanly layered.

The engine:
  1. Loads the workspace graph at a specific snapshot version (via GraphService)
  2. Computes per-node features using pure functions from features.py
  3. Aggregates workspace-level features
  4. Returns a FeatureSnapshot (frozen, keyed by snapshot_version)
  5. Caches the snapshot so re-running on the same version is instant

The cache key is (workspace_id, snapshot_version). When a new snapshot is
sealed, callers should invalidate the cache entry for that workspace.

Programs D (signals) and E (propagation) consume FeatureSnapshot objects
exclusively — they never re-derive features or touch the graph directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.modules.graph.feature_models import (
    FeatureSnapshot,
    NodeFeatures,
    WorkspaceFeatures,
)
from app.modules.graph.features import (
    betweenness,
    concentration_risk,
    connected_components,
    criticality,
    degree_centrality,
    downstream_depth,
    downstream_reach_count,
    in_degree,
    in_degree_centrality,
    out_degree,
    out_degree_centrality,
    p95,
    redundancy,
    single_point_of_failure,
    total_degree,
    upstream_depth,
    upstream_reach_count,
)
from app.modules.graph.service import GraphService, WorkspaceGraph


@dataclass(frozen=True)
class FeatureComputationResult:
    """Return value from FeatureEngine.compute_features()."""

    snapshot: FeatureSnapshot
    cache_hit: bool


class FeatureEngine:
    """Computes and caches feature snapshots for a workspace graph.

    Usage:
        engine = FeatureEngine(graph_service, cache)
        result = await engine.compute_features(workspace_id)
        features = result.snapshot  # FeatureSnapshot keyed by snapshot_version

    The engine never touches the repository — it calls GraphService methods
    exclusively. Swapping the underlying storage (Postgres → Neo4j) requires
    no changes here.
    """

    def __init__(self, service: GraphService, cache: Any | None = None) -> None:
        self._service = service
        self._cache = cache if cache is not None else _NoOpCache()

    async def compute_features(
        self,
        workspace_id: str,
        *,
        use_cache: bool = True,
    ) -> FeatureComputationResult:
        """Compute (or retrieve from cache) the full feature snapshot for a workspace.

        If use_cache=True and a snapshot exists for the current graph version,
        returns the cached result immediately. Otherwise loads the graph,
        computes all features, caches the result, and returns it.

        Returns FeatureComputationResult(snapshot, cache_hit).
        """
        # Load current snapshot metadata to build cache key
        current_snap = await self._service.get_snapshot_for_workspace(workspace_id)
        version = current_snap.version if current_snap else None
        cache_key = f"cortex:features:{workspace_id}:{version}" if version else None

        if use_cache and cache_key:
            cached = await self._cache.get(cache_key)
            if cached is not None:
                # Reconstruct FeatureSnapshot from cached dict
                return FeatureComputationResult(
                    snapshot=_dict_to_feature_snapshot(cached),
                    cache_hit=True,
                )

        # Load graph + compute
        loaded: WorkspaceGraph = await self._service.load_workspace_graph(workspace_id)
        snap_meta = loaded.snapshot

        # Compute per-node features
        by_node: dict[str, NodeFeatures] = {}
        for node_id, node_dto in loaded.graph.nodes.items():
            nf = _compute_node_features(loaded.graph, node_id, node_dto)
            by_node[node_id] = nf

        # Compute workspace aggregates
        ws_features = _compute_workspace_features(
            workspace_id,
            snap_meta,
            list(by_node.values()),
            loaded.graph,
        )

        snapshot = FeatureSnapshot(
            workspace_id=workspace_id,
            snapshot_id=snap_meta.snapshot_id if snap_meta else None,
            snapshot_version=snap_meta.version if snap_meta else None,
            snapshot_hash=snap_meta.snapshot_hash if snap_meta else None,
            by_node=by_node,
            workspace=ws_features,
        )

        # Cache if we have a valid version
        if cache_key:
            await self._cache.set(cache_key, _snapshot_to_dict(snapshot))

        return FeatureComputationResult(snapshot=snapshot, cache_hit=False)

    async def invalidate_workspace(self, workspace_id: str) -> None:
        """Invalidate cached features for a workspace (call when a new snapshot is sealed)."""
        await self._cache.invalidate_workspace(workspace_id)


def _compute_node_features(
    graph: Any,  # InMemoryGraph
    node_id: str,
    node_dto: Any,  # NodeDTO
) -> NodeFeatures:
    """Compute the full feature vector for a single node."""
    return NodeFeatures(
        node_id=node_id,
        entity_type=node_dto.entity_type,
        entity_id=node_dto.entity_id,
        in_degree=in_degree(graph, node_id),
        out_degree=out_degree(graph, node_id),
        total_degree=total_degree(graph, node_id),
        degree_centrality=degree_centrality(graph, node_id),
        in_degree_centrality=in_degree_centrality(graph, node_id),
        out_degree_centrality=out_degree_centrality(graph, node_id),
        downstream_reach=downstream_reach_count(graph, node_id),
        upstream_reach=upstream_reach_count(graph, node_id),
        total_reach=downstream_reach_count(graph, node_id) + upstream_reach_count(graph, node_id),
        downstream_depth=downstream_depth(graph, node_id),
        upstream_depth=upstream_depth(graph, node_id),
        criticality=criticality(graph, node_id),
        single_point_of_failure=single_point_of_failure(graph, node_id),
        concentration_risk=concentration_risk(graph, node_id),
        redundancy=redundancy(graph, node_id),
        betweenness=betweenness(graph, node_id),
    )


def _compute_workspace_features(
    workspace_id: str,
    snap_meta: Any | None,  # SnapshotDTO | None
    node_features: list[NodeFeatures],
    graph: Any,  # InMemoryGraph
) -> WorkspaceFeatures:
    """Aggregate workspace-level features from per-node feature vectors."""
    if not node_features:
        return WorkspaceFeatures(
            workspace_id=workspace_id,
            snapshot_id=snap_meta.snapshot_id if snap_meta else None,
            snapshot_version=snap_meta.version if snap_meta else None,
            snapshot_hash=snap_meta.snapshot_hash if snap_meta else None,
            node_count=0,
            edge_count=0,
            connected_components=0,
        )

    degrees = [nf.total_degree for nf in node_features]
    spof_nodes = sum(1 for nf in node_features if nf.single_point_of_failure > 0.7)
    high_betweenness = sum(1 for nf in node_features if nf.betweenness > 0.5)
    isolated = sum(1 for nf in node_features if nf.total_degree == 0)

    entity_counts: dict[str, int] = {}
    for nf in node_features:
        entity_counts[nf.entity_type] = entity_counts.get(nf.entity_type, 0) + 1

    return WorkspaceFeatures(
        workspace_id=workspace_id,
        snapshot_id=snap_meta.snapshot_id if snap_meta else None,
        snapshot_version=snap_meta.version if snap_meta else None,
        snapshot_hash=snap_meta.snapshot_hash if snap_meta else None,
        node_count=len(node_features),
        edge_count=graph.edge_count,
        connected_components=len(connected_components(graph)),
        max_degree=max(degrees) if degrees else 0,
        avg_degree=sum(degrees) / len(degrees) if degrees else 0.0,
        p95_degree=p95(degrees),
        single_point_of_failure_nodes=spof_nodes,
        high_betweenness_nodes=high_betweenness,
        isolated_nodes=isolated,
        avg_concentration_risk=sum(nf.concentration_risk for nf in node_features)
        / len(node_features),
        avg_redundancy=sum(nf.redundancy for nf in node_features) / len(node_features),
        max_criticality=max(nf.criticality for nf in node_features),
        entity_type_counts=entity_counts,
    )


def _snapshot_to_dict(fs: FeatureSnapshot) -> dict[str, Any]:
    return fs.to_dict()


def _dict_to_feature_snapshot(d: dict[str, Any]) -> FeatureSnapshot:
    ws = d.get("workspace")
    workspace = None
    if ws:
        workspace = WorkspaceFeatures(
            workspace_id=ws["workspace_id"],
            snapshot_id=ws.get("snapshot_id"),
            snapshot_version=ws.get("snapshot_version"),
            snapshot_hash=ws.get("snapshot_hash"),
            node_count=ws["node_count"],
            edge_count=ws["edge_count"],
            connected_components=ws["connected_components"],
            max_degree=ws["max_degree"],
            avg_degree=ws["avg_degree"],
            p95_degree=ws["p95_degree"],
            single_point_of_failure_nodes=ws["single_point_of_failure_nodes"],
            high_betweenness_nodes=ws["high_betweenness_nodes"],
            isolated_nodes=ws["isolated_nodes"],
            avg_concentration_risk=ws["avg_concentration_risk"],
            avg_redundancy=ws["avg_redundancy"],
            max_criticality=ws["max_criticality"],
            entity_type_counts=dict(ws["entity_type_counts"]),
        )
    by_node = {
        nid: NodeFeatures(
            node_id=nid,
            entity_type=nf["entity_type"],
            entity_id=nf["entity_id"],
            in_degree=nf["in_degree"],
            out_degree=nf["out_degree"],
            total_degree=nf["total_degree"],
            degree_centrality=nf["degree_centrality"],
            in_degree_centrality=nf["in_degree_centrality"],
            out_degree_centrality=nf["out_degree_centrality"],
            downstream_reach=nf["downstream_reach"],
            upstream_reach=nf["upstream_reach"],
            total_reach=nf["total_reach"],
            downstream_depth=nf["downstream_depth"],
            upstream_depth=nf["upstream_depth"],
            criticality=nf["criticality"],
            single_point_of_failure=nf["single_point_of_failure"],
            concentration_risk=nf["concentration_risk"],
            redundancy=nf["redundancy"],
            betweenness=nf["betweenness"],
        )
        for nid, nf in d.get("by_node", {}).items()
    }
    return FeatureSnapshot(
        workspace_id=d["workspace_id"],
        snapshot_id=d.get("snapshot_id"),
        snapshot_version=d.get("snapshot_version"),
        snapshot_hash=d.get("snapshot_hash"),
        by_node=by_node,
        workspace=workspace,
    )


class _NoOpCache:
    """Default cache when none is provided — behaves like NoOpCache in cache.py."""

    async def get(self, key: str) -> Any | None:
        return None

    async def set(self, key: str, value: Any, ttl: int = 3600) -> None:
        pass

    async def invalidate_workspace(self, workspace_id: str) -> None:
        pass
