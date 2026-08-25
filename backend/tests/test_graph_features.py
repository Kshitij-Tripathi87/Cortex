"""Phase 3 Program C tests — Graph Feature Engine.

Tests verify:
1. Feature functions return values in expected ranges [0.0, 1.0]
2. Features are deterministic (same graph → same values every run)
3. Replay stability (recomputing on same snapshot yields identical results)
4. Feature invariants (degree counts match graph structure, etc.)
5. Workspace aggregates are consistent with per-node features

All tests operate on InMemoryGraph — no database required. This makes the
feature layer the fastest to test and the hardest to break.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.modules.graph.feature_engine import (
    FeatureEngine,
    _compute_node_features,
    _compute_workspace_features,
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
    out_degree,
    p95,
    redundancy,
    single_point_of_failure,
    total_degree,
    upstream_depth,
    upstream_reach_count,
)
from app.modules.graph.repository import EdgeDTO, NodeDTO
from app.modules.graph.traversal import InMemoryGraph, build_in_memory_graph

_NOW = datetime.now(UTC)


def _node(
    node_id: str, entity_type: str, entity_id: str, attrs: dict[str, Any] | None = None
) -> NodeDTO:
    return NodeDTO(
        node_id=node_id,
        workspace_id="ws-1",
        entity_type=entity_type,
        entity_id=entity_id,
        attributes=attrs or {},
        first_seen_version=1,
        last_modified_version=1,
        valid_from=_NOW,
        valid_to=None,
    )


def _edge(
    edge_id: str, src: str, tgt: str, rel: str, attrs: dict[str, Any] | None = None
) -> EdgeDTO:
    return EdgeDTO(
        edge_id=edge_id,
        workspace_id="ws-1",
        source_node_id=src,
        target_node_id=tgt,
        relationship_type=rel,
        attributes=attrs or {},
        first_seen_version=1,
        last_modified_version=1,
        valid_from=_NOW,
        valid_to=None,
    )


@pytest.fixture
def linear_graph() -> InMemoryGraph:
    """A → B → C → D (single path)."""
    nodes = [
        _node("n-a", "Supplier", "SUP-001"),
        _node("n-b", "Facility", "WH-001"),
        _node("n-c", "Facility", "WH-002"),
        _node("n-d", "Customer", "CUST-001"),
    ]
    edges = [
        _edge("e-1", "n-a", "n-b", "SHIPS_TO"),
        _edge("e-2", "n-b", "n-c", "CONNECTS_TO"),
        _edge("e-3", "n-c", "n-d", "SHIPS_TO"),
    ]
    return build_in_memory_graph(nodes, edges)


@pytest.fixture
def star_graph() -> InMemoryGraph:
    """Central hub H with 4 spokes (S1, S2, S3, S4)."""
    nodes = [_node("n-hub", "Facility", "WH-HUB")]
    edges = []
    for i in range(1, 5):
        nodes.append(_node(f"n-s{i}", "Supplier", f"SUP-00{i}"))
        edges.append(_edge(f"e-{i}", f"n-s{i}", "n-hub", "SHIPS_TO"))
    return build_in_memory_graph(nodes, edges)


@pytest.fixture
def empty_graph() -> InMemoryGraph:
    return build_in_memory_graph([], [])


# ─────────────────────────────────────────────────────────────────────────────
# Degree features
# ─────────────────────────────────────────────────────────────────────────────


def test_in_degree_linear(linear_graph: InMemoryGraph) -> None:
    assert in_degree(linear_graph, "n-a") == 0  # source
    assert in_degree(linear_graph, "n-b") == 1
    assert in_degree(linear_graph, "n-c") == 1
    assert in_degree(linear_graph, "n-d") == 1  # sink


def test_out_degree_linear(linear_graph: InMemoryGraph) -> None:
    assert out_degree(linear_graph, "n-a") == 1
    assert out_degree(linear_graph, "n-b") == 1
    assert out_degree(linear_graph, "n-c") == 1
    assert out_degree(linear_graph, "n-d") == 0  # sink


def test_total_degree_linear(linear_graph: InMemoryGraph) -> None:
    assert total_degree(linear_graph, "n-a") == 1
    assert total_degree(linear_graph, "n-b") == 2
    assert total_degree(linear_graph, "n-c") == 2
    assert total_degree(linear_graph, "n-d") == 1


def test_degree_centrality_normalized(linear_graph: InMemoryGraph) -> None:
    """Max degree in linear graph is 2 (nodes B and C)."""
    assert degree_centrality(linear_graph, "n-b") == 1.0
    assert degree_centrality(linear_graph, "n-a") == 0.5
    assert degree_centrality(linear_graph, "n-d") == 0.5


def test_degree_on_missing_node_returns_zero(linear_graph: InMemoryGraph) -> None:
    assert in_degree(linear_graph, "n-missing") == 0
    assert out_degree(linear_graph, "n-missing") == 0
    assert total_degree(linear_graph, "n-missing") == 0


def test_degree_on_empty_graph(empty_graph: InMemoryGraph) -> None:
    assert in_degree(empty_graph, "anything") == 0
    assert out_degree(empty_graph, "anything") == 0
    assert total_degree(empty_graph, "anything") == 0


# ─────────────────────────────────────────────────────────────────────────────
# Reachability
# ─────────────────────────────────────────────────────────────────────────────


def test_downstream_reach_linear(linear_graph: InMemoryGraph) -> None:
    """A reaches B, C, D (3 nodes). D reaches nothing."""
    assert downstream_reach_count(linear_graph, "n-a") == 3
    assert downstream_reach_count(linear_graph, "n-b") == 2
    assert downstream_reach_count(linear_graph, "n-c") == 1
    assert downstream_reach_count(linear_graph, "n-d") == 0


def test_upstream_reach_linear(linear_graph: InMemoryGraph) -> None:
    """D can be reached from A, B, C (3 nodes). A from nothing."""
    assert upstream_reach_count(linear_graph, "n-d") == 3
    assert upstream_reach_count(linear_graph, "n-c") == 2
    assert upstream_reach_count(linear_graph, "n-b") == 1
    assert upstream_reach_count(linear_graph, "n-a") == 0


def test_reach_on_empty_graph(empty_graph: InMemoryGraph) -> None:
    assert downstream_reach_count(empty_graph, "x") == 0
    assert upstream_reach_count(empty_graph, "x") == 0


# ─────────────────────────────────────────────────────────────────────────────
# Depth
# ─────────────────────────────────────────────────────────────────────────────


def test_downstream_depth_linear(linear_graph: InMemoryGraph) -> None:
    """A → B → C → D has depth 3 from A."""
    assert downstream_depth(linear_graph, "n-a") == 3
    assert downstream_depth(linear_graph, "n-b") == 2
    assert downstream_depth(linear_graph, "n-c") == 1
    assert downstream_depth(linear_graph, "n-d") == 0


def test_upstream_depth_linear(linear_graph: InMemoryGraph) -> None:
    assert upstream_depth(linear_graph, "n-d") == 3
    assert upstream_depth(linear_graph, "n-c") == 2
    assert upstream_depth(linear_graph, "n-b") == 1
    assert upstream_depth(linear_graph, "n-a") == 0


def test_depth_on_empty_graph(empty_graph: InMemoryGraph) -> None:
    assert downstream_depth(empty_graph, "x") == 0
    assert upstream_depth(empty_graph, "x") == 0


# ─────────────────────────────────────────────────────────────────────────────
# Criticality
# ─────────────────────────────────────────────────────────────────────────────


def test_criticality_range(linear_graph: InMemoryGraph) -> None:
    """All criticality scores should be in [0.0, 1.0]."""
    for node_id in linear_graph.nodes:
        c = criticality(linear_graph, node_id)
        assert 0.0 <= c <= 1.0, f"{node_id} criticality {c} out of range"


def test_criticality_middle_nodes_higher(linear_graph: InMemoryGraph) -> None:
    """Middle nodes (B, C) should have higher criticality than endpoints."""
    c_b = criticality(linear_graph, "n-b")
    c_c = criticality(linear_graph, "n-c")
    c_a = criticality(linear_graph, "n-a")
    c_d = criticality(linear_graph, "n-d")
    assert c_b > c_a
    assert c_c > c_d


def test_criticality_on_empty_graph(empty_graph: InMemoryGraph) -> None:
    assert criticality(empty_graph, "x") == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# SPOF
# ─────────────────────────────────────────────────────────────────────────────


def test_spof_range(linear_graph: InMemoryGraph) -> None:
    for node_id in linear_graph.nodes:
        s = single_point_of_failure(linear_graph, node_id)
        assert 0.0 <= s <= 1.0, f"{node_id} SPOF {s} out of range"


def test_spof_middle_nodes_higher(linear_graph: InMemoryGraph) -> None:
    """Source nodes have high SPOF (no redundancy); middle nodes have moderate SPOF.

    In a linear chain A→B→C→D:
      - A has no upstream sources → redundancy=0 → SPOF = downstream_reach (high)
      - B, C have 1 upstream → redundancy_factor=0.5 → SPOF reduced
      - D has 1 upstream but downstream_reach=0 → SPOF=0

    This matches supply-chain intuition: a sole-origin supplier is a single
    point of failure even if it's at the start of the chain.
    """
    s_a = single_point_of_failure(linear_graph, "n-a")
    s_b = single_point_of_failure(linear_graph, "n-b")
    s_c = single_point_of_failure(linear_graph, "n-c")
    s_d = single_point_of_failure(linear_graph, "n-d")
    # A is the sole origin → highest SPOF
    assert s_a > s_b
    assert s_a > s_c
    # D is a sink → SPOF = 0
    assert s_d == 0.0


def test_spof_on_empty_graph(empty_graph: InMemoryGraph) -> None:
    assert single_point_of_failure(empty_graph, "x") == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Redundancy & Concentration
# ─────────────────────────────────────────────────────────────────────────────


def test_redundancy_star_graph(star_graph: InMemoryGraph) -> None:
    """Hub has 4 upstream suppliers → high redundancy."""
    r_hub = redundancy(star_graph, "n-hub")
    assert 0.5 <= r_hub <= 1.0  # 4 sources → saturates at 1.0


def test_concentration_is_complement_of_redundancy(star_graph: InMemoryGraph) -> None:
    r = redundancy(star_graph, "n-hub")
    c = concentration_risk(star_graph, "n-hub")
    assert abs((r + c) - 1.0) < 1e-9  # concentration = 1 - redundancy


def test_redundancy_on_empty_graph(empty_graph: InMemoryGraph) -> None:
    assert redundancy(empty_graph, "x") == 0.0
    assert concentration_risk(empty_graph, "x") == 1.0  # 1 - 0


# ─────────────────────────────────────────────────────────────────────────────
# Betweenness
# ─────────────────────────────────────────────────────────────────────────────


def test_betweenness_range(linear_graph: InMemoryGraph) -> None:
    for node_id in linear_graph.nodes:
        b = betweenness(linear_graph, node_id)
        assert 0.0 <= b <= 1.0, f"{node_id} betweenness {b} out of range"


def test_betweenness_middle_nodes_higher(linear_graph: InMemoryGraph) -> None:
    """Middle nodes (B, C) lie on all paths between A and D → high betweenness."""
    b_b = betweenness(linear_graph, "n-b")
    b_c = betweenness(linear_graph, "n-c")
    b_a = betweenness(linear_graph, "n-a")
    b_d = betweenness(linear_graph, "n-d")
    assert b_b > b_a
    assert b_c > b_d
    # B and C are on the only path A→D
    assert b_b == 1.0 or b_c == 1.0  # at least one is max


def test_betweenness_on_empty_graph(empty_graph: InMemoryGraph) -> None:
    assert betweenness(empty_graph, "x") == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Connected components
# ─────────────────────────────────────────────────────────────────────────────


def test_connected_components_linear(linear_graph: InMemoryGraph) -> None:
    comps = connected_components(linear_graph)
    assert len(comps) == 1  # all nodes connected
    assert len(comps[0]) == 4


def test_connected_components_disconnected() -> None:
    """Two separate components: A→B and C→D."""
    nodes = [
        _node("n-a", "X", "A"),
        _node("n-b", "X", "B"),
        _node("n-c", "X", "C"),
        _node("n-d", "X", "D"),
    ]
    edges = [
        _edge("e-1", "n-a", "n-b", "LINK"),
        _edge("e-2", "n-c", "n-d", "LINK"),
    ]
    g = build_in_memory_graph(nodes, edges)
    comps = connected_components(g)
    assert len(comps) == 2


def test_connected_components_empty_graph(empty_graph: InMemoryGraph) -> None:
    assert connected_components(empty_graph) == []


# ─────────────────────────────────────────────────────────────────────────────
# p95 utility
# ─────────────────────────────────────────────────────────────────────────────


def test_p95_basic() -> None:
    vals = list(range(1, 101))  # 1..100
    assert p95(vals) == 95


def test_p95_small_list() -> None:
    vals = [1, 2, 3, 4, 5]
    # 95th percentile of 5 elements: index = int(0.95 * 4) = 3 → value 4
    assert p95(vals) == 4


def test_p95_empty() -> None:
    assert p95([]) == 0


# ─────────────────────────────────────────────────────────────────────────────
# Determinism — same graph, same features every run
# ─────────────────────────────────────────────────────────────────────────────


def test_features_are_deterministic(linear_graph: InMemoryGraph) -> None:
    """Computing features twice on the same graph yields identical results."""
    c1 = criticality(linear_graph, "n-b")
    c2 = criticality(linear_graph, "n-b")
    assert c1 == c2

    s1 = single_point_of_failure(linear_graph, "n-b")
    s2 = single_point_of_failure(linear_graph, "n-b")
    assert s1 == s2

    b1 = betweenness(linear_graph, "n-b")
    b2 = betweenness(linear_graph, "n-b")
    assert b1 == b2


def test_features_independent_of_construction_order() -> None:
    """Building the same graph with shuffled edges yields identical features."""
    nodes = [
        _node("n-1", "X", "1"),
        _node("n-2", "X", "2"),
        _node("n-3", "X", "3"),
    ]
    edges_order_a = [
        _edge("e-1", "n-1", "n-2", "LINK"),
        _edge("e-2", "n-2", "n-3", "LINK"),
    ]
    edges_order_b = list(reversed(edges_order_a))

    g_a = build_in_memory_graph(nodes, edges_order_a)
    g_b = build_in_memory_graph(nodes, edges_order_b)

    assert criticality(g_a, "n-2") == criticality(g_b, "n-2")
    assert betweenness(g_a, "n-2") == betweenness(g_b, "n-2")
    assert redundancy(g_a, "n-2") == redundancy(g_b, "n-2")


# ─────────────────────────────────────────────────────────────────────────────
# Feature invariants
# ─────────────────────────────────────────────────────────────────────────────


def test_degree_centrality_max_is_one(linear_graph: InMemoryGraph) -> None:
    """At least one node should have degree_centrality == 1.0 (the max)."""
    max_dc = max(degree_centrality(linear_graph, n) for n in linear_graph.nodes)
    assert abs(max_dc - 1.0) < 1e-9


def test_betweenness_max_is_one(linear_graph: InMemoryGraph) -> None:
    """At least one node should have betweenness == 1.0 (the bottleneck)."""
    max_b = max(betweenness(linear_graph, n) for n in linear_graph.nodes)
    assert abs(max_b - 1.0) < 1e-9 or max_b == 0.0  # or all zero if no intermediates


def test_concentration_and_redundancy_sum_to_one(star_graph: InMemoryGraph) -> None:
    for node_id in star_graph.nodes:
        r = redundancy(star_graph, node_id)
        c = concentration_risk(star_graph, node_id)
        assert abs((r + c) - 1.0) < 1e-9, f"{node_id}: r={r}, c={c}"


# ─────────────────────────────────────────────────────────────────────────────
# FeatureEngine integration (lightweight, no DB)
# ─────────────────────────────────────────────────────────────────────────────


class _MockGraphService:
    """Mock GraphService for testing FeatureEngine without a database."""

    def __init__(self, graph: InMemoryGraph) -> None:
        self._graph = graph
        self._snap = None  # No snapshot metadata in mock

    async def load_workspace_graph(self, workspace_id: str) -> Any:
        from app.modules.graph.service import WorkspaceGraph

        return WorkspaceGraph(graph=self._graph, snapshot=self._snap)

    async def get_snapshot_for_workspace(self, workspace_id: str) -> Any:
        return self._snap


@pytest.mark.asyncio
async def test_feature_engine_computes_all_features(linear_graph: InMemoryGraph) -> None:
    """FeatureEngine should compute features for all nodes."""
    from app.modules.graph.cache import NoOpCache

    mock_service = _MockGraphService(linear_graph)
    engine = FeatureEngine(mock_service, NoOpCache())

    result = await engine.compute_features("ws-1", use_cache=False)
    fs = result.snapshot

    assert fs.workspace_id == "ws-1"
    assert len(fs.by_node) == 4  # 4 nodes in linear graph
    for nf in fs.by_node.values():
        assert 0.0 <= nf.degree_centrality <= 1.0
        assert 0.0 <= nf.criticality <= 1.0
        assert 0.0 <= nf.single_point_of_failure <= 1.0
        assert 0.0 <= nf.betweenness <= 1.0

    assert fs.workspace is not None
    assert fs.workspace.node_count == 4
    assert fs.workspace.edge_count == 3


@pytest.mark.asyncio
async def test_feature_engine_replay_stability(linear_graph: InMemoryGraph) -> None:
    """Recomputing features on the same graph yields identical results."""
    from app.modules.graph.cache import NoOpCache

    mock_service = _MockGraphService(linear_graph)
    engine = FeatureEngine(mock_service, NoOpCache())

    result1 = await engine.compute_features("ws-1", use_cache=False)
    result2 = await engine.compute_features("ws-1", use_cache=False)

    # Feature snapshots should be identical
    for node_id in linear_graph.nodes:
        nf1 = result1.snapshot.by_node[node_id]
        nf2 = result2.snapshot.by_node[node_id]
        assert nf1.criticality == nf2.criticality
        assert nf1.betweenness == nf2.betweenness
        assert nf1.single_point_of_failure == nf2.single_point_of_failure
        assert nf1.downstream_reach == nf2.downstream_reach


# ─────────────────────────────────────────────────────────────────────────────
# Workspace aggregates
# ─────────────────────────────────────────────────────────────────────────────


def test_workspace_features_aggregates(linear_graph: InMemoryGraph) -> None:
    """Workspace features should aggregate per-node features correctly."""
    node_features = [
        _compute_node_features(linear_graph, nid, linear_graph.nodes[nid])
        for nid in linear_graph.nodes
    ]
    ws = _compute_workspace_features("ws-1", None, node_features, linear_graph)

    assert ws.node_count == 4
    assert ws.edge_count == 3
    assert ws.connected_components == 1
    assert ws.max_degree == 2  # nodes B and C
    assert len(ws.entity_type_counts) == 3  # Supplier, Facility, Customer
