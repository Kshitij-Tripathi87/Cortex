"""Phase 3 Program B tests — Traversal Engine + Temporal + Validation.

The critical Program B property: traversals are pure functions over
InMemoryGraph, so they're testable without a database. These tests
construct known test graphs in-memory and exercise every algorithm
against expected structures.

Test graph (used across many tests):

    SUP-001 ──ORDERS_FROM──> PO-001
                              │
                              SHIPS_TO
                              ↓
                            WH-001 ──STORED_AT──> INV-001
                                                       │
                                                       IS_PRODUCT
                                                       ↓
                                                     SKU-001

    SUP-002 ──ORDERS_FROM──> PO-002
                              │
                              SHIPS_TO
                              ↓
                            WH-002

    WH-001 ──CONNECTS_TO──> WH-002  (route)

This graph has:
  - 7 nodes (3 Suppliers + 1 PO + 1 WH + 1 SKU + 1 INV — actually let me recount below)
  - Multiple paths between SUP-001 and SKU-001
  - Isolated node to test reachability boundary
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.modules.graph.cache import NoOpCache, make_cache_key
from app.modules.graph.entity_keys import ENTITY_FOREIGN_KEYS
from app.modules.graph.repository import EdgeDTO, NodeDTO
from app.modules.graph.traversal import (
    InMemoryGraph,
    bfs,
    build_in_memory_graph,
    dfs,
    find_paths,
    neighbors,
    reachable_from,
    reachable_to,
    shortest_path,
)
from app.modules.graph.validation import _VALID_ENTITY_TYPES, _VALID_RELATIONSHIPS

# ─────────────────────────────────────────────────────────────────────────────
# Test graph fixtures — constructed in-memory, no DB
# ─────────────────────────────────────────────────────────────────────────────


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
def supply_chain_graph() -> InMemoryGraph:
    """A canonical supply chain graph for traversal tests.

    Structure:
        SUP-001 ──> PO-001 ──> WH-001 ──> INV-001 ──> SKU-001
        SUP-002 ──> PO-002 ──> WH-002
        WH-001 ──> WH-002 (route link)
        CUST-001 (isolated — no edges)
    """
    nodes = [
        _node("n-sup-1", "Supplier", "SUP-001"),
        _node("n-sup-2", "Supplier", "SUP-002"),
        _node("n-po-1", "PurchaseOrder", "PO-001"),
        _node("n-po-2", "PurchaseOrder", "PO-002"),
        _node("n-wh-1", "Facility", "WH-001"),
        _node("n-wh-2", "Facility", "WH-002"),
        _node("n-inv-1", "InventoryItem", "INV-001"),
        _node("n-sku-1", "Product", "SKU-001"),
        _node("n-cust-1", "Customer", "CUST-001"),  # isolated
    ]
    edges = [
        _edge("e-1", "n-sup-1", "n-po-1", "ORDERS_FROM"),
        _edge("e-2", "n-sup-2", "n-po-2", "ORDERS_FROM"),
        _edge("e-3", "n-po-1", "n-wh-1", "SHIPS_TO"),
        _edge("e-4", "n-po-2", "n-wh-2", "SHIPS_TO"),
        _edge("e-5", "n-wh-1", "n-inv-1", "STORED_AT"),
        _edge("e-6", "n-inv-1", "n-sku-1", "IS_PRODUCT"),
        _edge("e-7", "n-wh-1", "n-wh-2", "CONNECTS_TO"),
    ]
    return build_in_memory_graph(nodes, edges)


@pytest.fixture
def empty_graph() -> InMemoryGraph:
    return build_in_memory_graph([], [])


# ─────────────────────────────────────────────────────────────────────────────
# Build / structure
# ─────────────────────────────────────────────────────────────────────────────


def test_build_in_memory_graph_counts(supply_chain_graph: InMemoryGraph) -> None:
    assert supply_chain_graph.node_count == 9
    assert supply_chain_graph.edge_count == 7


def test_build_in_memory_graph_skips_orphan_edges() -> None:
    """Edges referencing missing nodes are silently dropped during build."""
    nodes = [_node("n-1", "Supplier", "S-1")]
    edges = [
        _edge("e-1", "n-1", "n-missing", "ORDERS_FROM"),  # target missing
        _edge("e-2", "n-other-missing", "n-1", "STORED_AT"),  # source missing
    ]
    g = build_in_memory_graph(nodes, edges)
    assert g.edge_count == 0  # both edges dropped


def test_in_memory_graph_adjacency_lists(supply_chain_graph: InMemoryGraph) -> None:
    """Out-edges and in-edges should be populated correctly."""
    assert len(supply_chain_graph.out_edges["n-sup-1"]) == 1
    assert len(supply_chain_graph.in_edges["n-po-1"]) == 1
    # Warehouse 1 has outgoing edges to INV-001 and WH-002
    assert len(supply_chain_graph.out_edges["n-wh-1"]) == 2


# ─────────────────────────────────────────────────────────────────────────────
# neighbors — one-hop
# ─────────────────────────────────────────────────────────────────────────────


def test_neighbors_out(supply_chain_graph: InMemoryGraph) -> None:
    result = neighbors(supply_chain_graph, "n-sup-1", direction="out")
    assert len(result) == 1
    edge, neighbor = result[0]
    assert neighbor.entity_id == "PO-001"
    assert edge.relationship_type == "ORDERS_FROM"


def test_neighbors_in(supply_chain_graph: InMemoryGraph) -> None:
    result = neighbors(supply_chain_graph, "n-po-1", direction="in")
    assert len(result) == 1
    _edge, neighbor = result[0]
    assert neighbor.entity_id == "SUP-001"


def test_neighbors_both_directions(supply_chain_graph: InMemoryGraph) -> None:
    """WH-001 has 1 in-edge (from PO-001) and 2 out-edges."""
    result = neighbors(supply_chain_graph, "n-wh-1", direction="both")
    assert len(result) == 3


def test_neighbors_filter_by_relationship(supply_chain_graph: InMemoryGraph) -> None:
    """Filtering by relationship_type narrows the result set."""
    result = neighbors(
        supply_chain_graph, "n-wh-1", direction="out", relationship_type="CONNECTS_TO"
    )
    assert len(result) == 1
    _edge, neighbor = result[0]
    assert neighbor.entity_id == "WH-002"


def test_neighbors_for_missing_node_returns_empty(supply_chain_graph: InMemoryGraph) -> None:
    assert neighbors(supply_chain_graph, "n-does-not-exist") == []


def test_neighbors_for_isolated_node_returns_empty(supply_chain_graph: InMemoryGraph) -> None:
    """CUST-001 has no edges."""
    assert neighbors(supply_chain_graph, "n-cust-1", direction="both") == []


# ─────────────────────────────────────────────────────────────────────────────
# BFS — breadth-first traversal
# ─────────────────────────────────────────────────────────────────────────────


def test_bfs_visits_nodes_in_order(supply_chain_graph: InMemoryGraph) -> None:
    """BFS from SUP-001 should reach PO-001 → WH-001 → INV-001 → SKU-001."""
    result = bfs(supply_chain_graph, "n-sup-1", max_depth=10)
    # SUP-001 first
    assert result.visited[0] == "n-sup-1"
    # After 5 hops should reach SKU-001 (depth 4)
    assert "n-sku-1" in result.visited
    # Should not cross into SUP-002 branch (disconnected)
    assert "n-sup-2" not in result.visited
    assert "n-po-2" not in result.visited
    # Depths are correct
    assert result.depths["n-sup-1"] == 0
    assert result.depths["n-po-1"] == 1
    assert result.depths["n-wh-1"] == 2
    assert result.depths["n-inv-1"] == 3
    assert result.depths["n-sku-1"] == 4


def test_bfs_respects_max_depth(supply_chain_graph: InMemoryGraph) -> None:
    """max_depth=2 should stop at WH-001 and not reach INV-001."""
    result = bfs(supply_chain_graph, "n-sup-1", max_depth=2)
    assert "n-wh-1" in result.visited
    assert "n-inv-1" not in result.visited
    assert "n-sku-1" not in result.visited


def test_bfs_depth_zero_only_visits_seed(supply_chain_graph: InMemoryGraph) -> None:
    result = bfs(supply_chain_graph, "n-sup-1", max_depth=0)
    assert result.visited == ["n-sup-1"]


def test_bfs_parent_chain(supply_chain_graph: InMemoryGraph) -> None:
    """Parent annotations should reconstruct the BFS tree."""
    result = bfs(supply_chain_graph, "n-sup-1", max_depth=4)
    assert result.parents["n-sup-1"] is None
    assert result.parents["n-po-1"] == "n-sup-1"
    assert result.parents["n-wh-1"] == "n-po-1"
    assert result.parents["n-sku-1"] == "n-inv-1"


def test_bfs_on_missing_seed_returns_empty(supply_chain_graph: InMemoryGraph) -> None:
    result = bfs(supply_chain_graph, "n-missing", max_depth=3)
    assert result.visited == []


def test_bfs_on_empty_graph_returns_empty(empty_graph: InMemoryGraph) -> None:
    result = bfs(empty_graph, "n-anything", max_depth=3)
    assert result.visited == []


def test_bfs_in_reverse_direction(supply_chain_graph: InMemoryGraph) -> None:
    """BFS backwards from SKU-001 should reach SUP-001."""
    result = bfs(supply_chain_graph, "n-sku-1", max_depth=10, direction="in")
    assert "n-sup-1" in result.visited
    assert result.depths["n-sku-1"] == 0
    assert result.depths["n-inv-1"] == 1
    assert result.depths["n-wh-1"] == 2
    assert result.depths["n-po-1"] == 3
    assert result.depths["n-sup-1"] == 4


# ─────────────────────────────────────────────────────────────────────────────
# DFS — depth-first traversal
# ─────────────────────────────────────────────────────────────────────────────


def test_dfs_visits_all_reachable(supply_chain_graph: InMemoryGraph) -> None:
    """DFS from SUP-001 should visit every downstream node.

    Supply chain reaches: PO-001, WH-001, INV-001, SKU-001, and WH-002
    (via the CONNECTS_TO route edge from WH-001 to WH-002).
    """
    result = dfs(supply_chain_graph, "n-sup-1", max_depth=10)
    expected = {
        "n-sup-1",
        "n-po-1",
        "n-wh-1",
        "n-inv-1",
        "n-sku-1",
        "n-wh-2",
    }
    assert set(result) == expected
    # SUP-002 branch should not be reached (disconnected from SUP-001)
    assert "n-sup-2" not in result
    assert "n-po-2" not in result
    # CUST-001 is isolated — no path from SUP-001
    assert "n-cust-1" not in result


def test_dfs_respects_max_depth(supply_chain_graph: InMemoryGraph) -> None:
    result = dfs(supply_chain_graph, "n-sup-1", max_depth=2)
    # max_depth=2 means we can go SUP-001 → PO-001 → WH-001, but no further
    assert "n-sup-1" in result
    assert "n-po-1" in result
    assert "n-wh-1" in result
    assert "n-inv-1" not in result


def test_dfs_no_infinite_loop_on_cycle() -> None:
    """DFS must terminate even when the graph has a cycle."""
    nodes = [_node("n-a", "X", "A"), _node("n-b", "X", "B")]
    edges = [
        _edge("e-1", "n-a", "n-b", "LINK"),
        _edge("e-2", "n-b", "n-a", "LINK"),  # cycle
    ]
    g = build_in_memory_graph(nodes, edges)
    result = dfs(g, "n-a", max_depth=10)
    assert set(result) == {"n-a", "n-b"}
    # No node should appear twice (simple DFS, no repeats)
    assert len(result) == len(set(result))


# ─────────────────────────────────────────────────────────────────────────────
# shortest_path
# ─────────────────────────────────────────────────────────────────────────────


def test_shortest_path_direct(supply_chain_graph: InMemoryGraph) -> None:
    """One-hop path from SUP-001 to PO-001."""
    path = shortest_path(supply_chain_graph, "n-sup-1", "n-po-1")
    assert path == ["n-sup-1", "n-po-1"]


def test_shortest_path_multi_hop(supply_chain_graph: InMemoryGraph) -> None:
    """Four-hop path from SUP-001 to SKU-001."""
    path = shortest_path(supply_chain_graph, "n-sup-1", "n-sku-1")
    assert path == ["n-sup-1", "n-po-1", "n-wh-1", "n-inv-1", "n-sku-1"]


def test_shortest_path_via_route(supply_chain_graph: InMemoryGraph) -> None:
    """Shortest path from PO-001 to WH-002 may go via the route edge."""
    path = shortest_path(supply_chain_graph, "n-po-1", "n-wh-2")
    # Both paths length 2: PO-001 → WH-001 → WH-002 (via CONNECTS_TO)
    # And PO-001 → ... is not direct. Verify BFS finds the shortest.
    assert len(path) == 3  # 3 nodes = 2 hops
    assert path[0] == "n-po-1"
    assert path[-1] == "n-wh-2"


def test_shortest_path_no_path_returns_none(supply_chain_graph: InMemoryGraph) -> None:
    """Disconnected components: SUP-001 cannot reach SUP-002."""
    assert shortest_path(supply_chain_graph, "n-sup-1", "n-sup-2") is None


def test_shortest_path_to_self_returns_self(supply_chain_graph: InMemoryGraph) -> None:
    """source == target returns [source]."""
    assert shortest_path(supply_chain_graph, "n-sup-1", "n-sup-1") == ["n-sup-1"]


def test_shortest_path_missing_node_returns_none(supply_chain_graph: InMemoryGraph) -> None:
    assert shortest_path(supply_chain_graph, "n-missing", "n-sup-1") is None
    assert shortest_path(supply_chain_graph, "n-sup-1", "n-missing") is None


def test_shortest_path_reverse(supply_chain_graph: InMemoryGraph) -> None:
    """Reverse shortest path from SKU-001 back to SUP-001."""
    path = shortest_path(supply_chain_graph, "n-sku-1", "n-sup-1", direction="in")
    assert path == ["n-sku-1", "n-inv-1", "n-wh-1", "n-po-1", "n-sup-1"]


# ─────────────────────────────────────────────────────────────────────────────
# Reachability
# ─────────────────────────────────────────────────────────────────────────────


def test_reachable_from_includes_all_downstream(supply_chain_graph: InMemoryGraph) -> None:
    """From SUP-001 we can reach PO-001, WH-001, INV-001, SKU-001, WH-002."""
    reached = reachable_from(supply_chain_graph, "n-sup-1", max_depth=10)
    expected = {"n-sup-1", "n-po-1", "n-wh-1", "n-inv-1", "n-sku-1", "n-wh-2"}
    assert reached == expected


def test_reachable_to_includes_all_upstream(supply_chain_graph: InMemoryGraph) -> None:
    """To SKU-001 we can trace back through INV-001, WH-001, PO-001, SUP-001."""
    reached = reachable_to(supply_chain_graph, "n-sku-1", max_depth=10)
    expected = {"n-sku-1", "n-inv-1", "n-wh-1", "n-po-1", "n-sup-1"}
    assert reached == expected


def test_reachable_from_isolated_node(supply_chain_graph: InMemoryGraph) -> None:
    """CUST-001 has no out-edges; reachable_from is just itself."""
    assert reachable_from(supply_chain_graph, "n-cust-1") == {"n-cust-1"}


def test_reachable_to_isolated_node(supply_chain_graph: InMemoryGraph) -> None:
    """CUST-001 has no in-edges; reachable_to is just itself."""
    assert reachable_to(supply_chain_graph, "n-cust-1") == {"n-cust-1"}


def test_reachable_respects_max_depth(supply_chain_graph: InMemoryGraph) -> None:
    """max_depth=2 from SUP-001 reaches PO-001 and WH-001, but not INV-001."""
    reached = reachable_from(supply_chain_graph, "n-sup-1", max_depth=2)
    assert "n-sup-1" in reached
    assert "n-po-1" in reached
    assert "n-wh-1" in reached
    assert "n-inv-1" not in reached


def test_reachable_filter_by_relationship() -> None:
    """Filtering by relationship restricts what's reachable."""
    nodes = [
        _node("n-a", "X", "A"),
        _node("n-b", "X", "B"),
        _node("n-c", "X", "C"),
    ]
    edges = [
        _edge("e-1", "n-a", "n-b", "STRONG"),
        _edge("e-2", "n-b", "n-c", "WEAK"),
    ]
    g = build_in_memory_graph(nodes, edges)
    # Only following STRONG edges: A reaches B, but B → C is WEAK
    reached = reachable_from(g, "n-a", relationship_type="STRONG")
    assert reached == {"n-a", "n-b"}


# ─────────────────────────────────────────────────────────────────────────────
# find_paths — all simple paths between two nodes
# ─────────────────────────────────────────────────────────────────────────────


def test_find_paths_single_path(supply_chain_graph: InMemoryGraph) -> None:
    paths = find_paths(supply_chain_graph, "n-sup-1", "n-sku-1", max_depth=5)
    assert len(paths) == 1
    assert paths[0] == ["n-sup-1", "n-po-1", "n-wh-1", "n-inv-1", "n-sku-1"]


def test_find_paths_multiple_paths() -> None:
    """When there are multiple paths, find_paths returns all of them."""
    nodes = [
        _node("n-a", "X", "A"),
        _node("n-b", "X", "B"),
        _node("n-c", "X", "C"),
        _node("n-d", "X", "D"),
    ]
    edges = [
        _edge("e-1", "n-a", "n-b", "LINK"),
        _edge("e-2", "n-a", "n-c", "LINK"),
        _edge("e-3", "n-b", "n-d", "LINK"),
        _edge("e-4", "n-c", "n-d", "LINK"),
    ]
    g = build_in_memory_graph(nodes, edges)
    paths = find_paths(g, "n-a", "n-d", max_depth=4)
    # Two paths: A→B→D and A→C→D
    assert len(paths) == 2
    path_sets = [tuple(p) for p in paths]
    assert ("n-a", "n-b", "n-d") in path_sets
    assert ("n-a", "n-c", "n-d") in path_sets


def test_find_paths_no_paths_returns_empty(supply_chain_graph: InMemoryGraph) -> None:
    """No path between disconnected components → empty list."""
    assert find_paths(supply_chain_graph, "n-sup-1", "n-sup-2") == []


def test_find_paths_respects_max_paths() -> None:
    """The max_paths bound should prevent runaway enumeration."""
    nodes = [_node(f"n-{i}", "X", str(i)) for i in range(100)]
    # Linear chain: 0 → 1 → 2 → ... → 99
    edges = [_edge(f"e-{i}", f"n-{i}", f"n-{i + 1}", "LINK") for i in range(99)]
    g = build_in_memory_graph(nodes, edges)
    paths = find_paths(g, "n-0", "n-99", max_depth=200, max_paths=5)
    assert len(paths) <= 5


# ─────────────────────────────────────────────────────────────────────────────
# Cache key determinism
# ─────────────────────────────────────────────────────────────────────────────


def test_cache_key_deterministic() -> None:
    """Same inputs → same cache key."""
    k1 = make_cache_key("ws-1", 3, "neighbors", {"node_id": "n-1", "depth": 2})
    k2 = make_cache_key("ws-1", 3, "neighbors", {"node_id": "n-1", "depth": 2})
    assert k1 == k2


def test_cache_key_args_order_invariant() -> None:
    """Cache key is order-invariant in its arguments (uses sorted JSON)."""
    k1 = make_cache_key("ws-1", 1, "op", {"a": 1, "b": 2})
    k2 = make_cache_key("ws-1", 1, "op", {"b": 2, "a": 1})
    assert k1 == k2


def test_cache_key_changes_with_args() -> None:
    k1 = make_cache_key("ws-1", 1, "op", {"a": 1})
    k2 = make_cache_key("ws-1", 1, "op", {"a": 2})
    assert k1 != k2


def test_cache_key_changes_with_version() -> None:
    k1 = make_cache_key("ws-1", 1, "op", {"a": 1})
    k2 = make_cache_key("ws-1", 2, "op", {"a": 1})
    assert k1 != k2


def test_noop_cache_is_noop() -> None:
    import asyncio

    cache = NoOpCache()
    # Should never raise, never return anything other than None on get
    assert asyncio.run(cache.get("anything")) is None
    asyncio.run(cache.set("k", "v"))
    asyncio.run(cache.invalidate_workspace("ws-1"))
    asyncio.run(cache.invalidate_snapshot("ws-1", 1))


# ─────────────────────────────────────────────────────────────────────────────
# Validation registries — completeness invariants
# ─────────────────────────────────────────────────────────────────────────────


def test_every_entity_type_can_be_referenced_in_relationships() -> None:
    """Every entity type that appears as an FK target should be a valid type."""
    for (src, fk), (tgt, _rel) in ENTITY_FOREIGN_KEYS.items():
        if tgt != "Facility" and tgt != "Organization":
            assert tgt in _VALID_ENTITY_TYPES, (
                f"FK target '{tgt}' (from {src}.{fk}) is not in valid entity types"
            )


def test_every_relationship_in_registry_is_uppercase() -> None:
    for rel in _VALID_RELATIONSHIPS:
        assert rel.isupper(), f"relationship '{rel}' must be UPPERCASE"


def test_valid_entity_types_include_facility_and_organization() -> None:
    assert "Facility" in _VALID_ENTITY_TYPES
    assert "Organization" in _VALID_ENTITY_TYPES
    # And every concrete entity type from the ontology
    for ent in ["Supplier", "Customer", "Carrier", "Product", "PurchaseOrder", "Shipment", "Route"]:
        assert ent in _VALID_ENTITY_TYPES, f"{ent} missing from valid entity types"


# ─────────────────────────────────────────────────────────────────────────────
# Determinism — same graph, same queries, same answers every time
# ─────────────────────────────────────────────────────────────────────────────


def test_traversal_is_deterministic_across_runs(
    supply_chain_graph: InMemoryGraph,
) -> None:
    """Same traversal called twice produces identical results."""
    p1 = shortest_path(supply_chain_graph, "n-sup-1", "n-sku-1")
    p2 = shortest_path(supply_chain_graph, "n-sup-1", "n-sku-1")
    assert p1 == p2

    r1 = reachable_from(supply_chain_graph, "n-sup-1", max_depth=10)
    r2 = reachable_from(supply_chain_graph, "n-sup-1", max_depth=10)
    assert r1 == r2

    b1 = bfs(supply_chain_graph, "n-sup-1", max_depth=10)
    b2 = bfs(supply_chain_graph, "n-sup-1", max_depth=10)
    assert b1.visited == b2.visited
    assert b1.depths == b2.depths
    assert b1.parents == b2.parents


def test_traversal_independent_of_construction_order() -> None:
    """Building the same graph with shuffled edges yields identical traversal.

    The traversal functions operate on adjacency lists keyed by node_id,
    so edge insertion order doesn't matter. This makes the graph
    deterministic across compilations — the Phase 3 success metric.
    """
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

    assert g_a.node_count == g_b.node_count
    assert g_a.edge_count == g_b.edge_count
    assert (
        shortest_path(g_a, "n-1", "n-3")
        == shortest_path(g_b, "n-1", "n-3")
        == ["n-1", "n-2", "n-3"]
    )
