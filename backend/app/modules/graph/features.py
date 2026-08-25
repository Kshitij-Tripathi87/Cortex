"""Graph features — pure deterministic functions over InMemoryGraph.

Every function:
  - Takes InMemoryGraph + identifiers (no DB, no I/O)
  - Returns a numeric result in [0.0, 1.0] for scores, or a non-negative int for counts
  - Is total: never raises; missing nodes → zero, empty graphs → zero
  - Is deterministic: same graph → same result, every run

Feature definitions:

  Degree counts:           in_degree / out_degree / total_degree
  Degree centrality:       total_degree / max_total_degree_in_graph (or 0 if graph empty)
  Downstream reach:        |{nodes reachable via out-edges}| - 1 (excludes self)
  Upstream reach:          |{nodes that can reach this node}| - 1
  Downstream depth:        max shortest-path length following out-edges
  Upstream depth:          max shortest-path length from any source via in-edges
  Criticality:             weighted 함수 of downstream_depth, downstream_reach, degree_centrality
  SPOF score:              high downstream reach × low redundancy × high degree
  Concentration risk:      1 - redundancy_score (relying on few for many demands)
  Redundancy:              average inbound fan-out; many upstream sources → high redundancy
  Betweenness (normalized): fraction of all-pairs shortest paths that pass through this node

Programs D (signals) and E (propagation) consume these via FeatureEngine, never
directly. Keeping functions pure makes this layer the fastest to test and the
hardest to break.
"""

from __future__ import annotations

from collections import deque

from app.modules.graph.traversal import (
    InMemoryGraph,
    neighbors,
    reachable_from,
    reachable_to,
    shortest_path,
)

# ─────────────────────────────────────────────────────────────────────────────
# Degree
# ─────────────────────────────────────────────────────────────────────────────


def in_degree(graph: InMemoryGraph, node_id: str) -> int:
    """Number of edges pointing at this node."""
    if node_id not in graph.nodes:
        return 0
    return len(graph.in_edges.get(node_id, []))


def out_degree(graph: InMemoryGraph, node_id: str) -> int:
    """Number of edges leaving this node."""
    if node_id not in graph.nodes:
        return 0
    return len(graph.out_edges.get(node_id, []))


def total_degree(graph: InMemoryGraph, node_id: str) -> int:
    """Sum of in + out degree."""
    return in_degree(graph, node_id) + out_degree(graph, node_id)


def max_total_degree_in_graph(graph: InMemoryGraph) -> int:
    """Highest total_degree across all nodes — normalization factor."""
    if not graph.nodes:
        return 0
    return max(total_degree(graph, n) for n in graph.nodes) or 1  # avoid div0


def degree_centrality(graph: InMemoryGraph, node_id: str) -> float:
    """total_degree / max_degree. Returns 0..1; isolated graph → 0."""
    if not graph.nodes:
        return 0.0
    m = max_total_degree_in_graph(graph)
    if m == 0:
        return 0.0
    return total_degree(graph, node_id) / m


def in_degree_centrality(graph: InMemoryGraph, node_id: str) -> float:
    if not graph.nodes:
        return 0.0
    m = max((in_degree(graph, n) for n in graph.nodes), default=0) or 1
    return in_degree(graph, node_id) / m


def out_degree_centrality(graph: InMemoryGraph, node_id: str) -> float:
    if not graph.nodes:
        return 0.0
    m = max((out_degree(graph, n) for n in graph.nodes), default=0) or 1
    return out_degree(graph, node_id) / m


# ─────────────────────────────────────────────────────────────────────────────
# Reachability (returns sets, used by feature vector)
# ─────────────────────────────────────────────────────────────────────────────


def downstream_reach_count(graph: InMemoryGraph, node_id: str, *, max_depth: int = 12) -> int:
    """Number of nodes reachable from this node via out-edges, excluding itself."""
    reached = reachable_from(graph, node_id, max_depth=max_depth)
    return max(0, len(reached) - 1)  # reachable_from includes self


def upstream_reach_count(graph: InMemoryGraph, node_id: str, *, max_depth: int = 12) -> int:
    """Number of nodes that can reach this node via out-edges, excluding itself."""
    reached = reachable_to(graph, node_id, max_depth=max_depth)
    return max(0, len(reached) - 1)


# ─────────────────────────────────────────────────────────────────────────────
# Path depth (longest shortest-path)
# ─────────────────────────────────────────────────────────────────────────────


def _bfs_distances(
    graph: InMemoryGraph, seed_id: str, *, direction: str = "out", max_depth: int = 12
) -> dict[str, int]:
    """One-source BFS distances. Returns {} if seed missing."""
    if seed_id not in graph.nodes:
        return {}
    dists: dict[str, int] = {seed_id: 0}
    q: deque[str] = deque([seed_id])
    while q:
        cur = q.popleft()
        d = dists[cur]
        if d >= max_depth:
            continue
        for _edge, neighbor in neighbors(graph, cur, direction=direction):
            if neighbor.node_id not in dists:
                dists[neighbor.node_id] = d + 1
                q.append(neighbor.node_id)
    return dists


def downstream_depth(graph: InMemoryGraph, node_id: str, *, max_depth: int = 12) -> int:
    """Maximum shortest-path distance from node_id downstream. 0 if none."""
    dists = _bfs_distances(graph, node_id, direction="out", max_depth=max_depth)
    if len(dists) <= 1:
        return 0
    return max(d for nid, d in dists.items() if nid != node_id)


def upstream_depth(graph: InMemoryGraph, node_id: str, *, max_depth: int = 12) -> int:
    """Maximum shortest-path distance from any source upstream. 0 if none."""
    dists = _bfs_distances(graph, node_id, direction="in", max_depth=max_depth)
    if len(dists) <= 1:
        return 0
    return max(d for nid, d in dists.items() if nid != node_id)


# ─────────────────────────────────────────────────────────────────────────────
# Criticality — blended impact score
# ─────────────────────────────────────────────────────────────────────────────


def max_reach_in_graph(graph: InMemoryGraph) -> int:
    if not graph.nodes:
        return 0
    return (
        max(
            (downstream_reach_count(graph, n) + upstream_reach_count(graph, n)) for n in graph.nodes
        )
        or 1
    )


def max_depth_in_graph(graph: InMemoryGraph) -> int:
    if not graph.nodes:
        return 0
    return max(max(downstream_depth(graph, n), upstream_depth(graph, n)) for n in graph.nodes) or 1


def criticality(graph: InMemoryGraph, node_id: str) -> float:
    """Operational criticality score [0.0, 1.0].

    Weighted combination of:
      - downstream reach (impact breadth)
      - upstream reach (dependency breadth)
      - degree centrality (network importance)

    All three are normalized to graph maximums so the score is comparable
    across workspaces of different sizes. Output always in [0.0, 1.0].
    """
    if not graph.nodes or node_id not in graph.nodes:
        return 0.0
    mr = max_reach_in_graph(graph)
    md = max_depth_in_graph(graph)
    dc = degree_centrality(graph, node_id)
    dr = downstream_reach_count(graph, node_id) / mr if mr > 0 else 0.0
    ur = upstream_reach_count(graph, node_id) / mr if mr > 0 else 0.0
    dd_ = downstream_depth(graph, node_id) / md if md > 0 else 0.0
    ud_ = upstream_depth(graph, node_id) / md if md > 0 else 0.0
    # Weights sum to 1.0. Reach dominates criticality in supply chains.
    score = 0.30 * dr + 0.30 * ur + 0.15 * dd_ + 0.15 * ud_ + 0.10 * dc
    return min(1.0, max(0.0, score))


# ─────────────────────────────────────────────────────────────────────────────
# Single Point of Failure (SPOF)
# ─────────────────────────────────────────────────────────────────────────────


def single_point_of_failure(graph: InMemoryGraph, node_id: str) -> float:
    """SPOF score [0.0, 1.0].

    High if the node has:
      - large downstream reach (many things depend on it)
      - high in_degree_centrality-like concentration (few upstreams feed it)
      - low redundancy
    """
    if not graph.nodes or node_id not in graph.nodes:
        return 0.0
    mr = max_reach_in_graph(graph)
    dr = downstream_reach_count(graph, node_id) / mr if mr > 0 else 0.0
    in_deg = in_degree(graph, node_id)
    # If many upstream sources feed this node, removing one is less catastrophic
    redundancy_factor = min(1.0, in_deg / 2.0)  # 2+ sources → factor saturates at 1
    spof = dr * (1.0 - redundancy_factor * 0.6)
    return min(1.0, max(0.0, spof))


# ─────────────────────────────────────────────────────────────────────────────
# Concentration risk & redundancy
# ─────────────────────────────────────────────────────────────────────────────


def redundancy(graph: InMemoryGraph, node_id: str) -> float:
    """Redundancy score [0.0, 1.0].

    How many independent upstream suppliers can feed this node. Mirrors dual-
    sourcing in supply chains. 0 = single-source; 1 = 4+ sources.

    Computed from in_degree on the out-graph's reverse: an entity has
    redundancy if multiple upstream nodes feed it through distinct edges.
    """
    if node_id not in graph.nodes:
        return 0.0
    in_deg = in_degree(graph, node_id)
    if in_deg == 0:
        return 0.0
    # Saturates at 1.0 once 4 distinct upstream feeds exist
    return min(1.0, in_deg / 4.0)


def concentration_risk(graph: InMemoryGraph, node_id: str) -> float:
    """Concentration risk [0.0, 1.0]. 1 - redundancy_score.

    High when the node relies on a single upstream — the classic single-source
    supplier problem. Low when diversified across multiple upstreams.
    """
    return 1.0 - redundancy(graph, node_id)


# ─────────────────────────────────────────────────────────────────────────────
# Betweenness — fraction of shortest paths through this node
# ─────────────────────────────────────────────────────────────────────────────


def _all_pairs_shortest_paths(
    graph: InMemoryGraph, *, max_paths_to_compute: int = 5000
) -> dict[str, int]:
    """For each node, count how many shortest paths (between any (s, t) pair
    where s != t) pass through it.

    Bounded by max_paths_to_compute to keep cost acceptable on large graphs.
    For Phase 3 v1 we use unweighted BFS shortest paths.
    """
    through_count: dict[str, int] = {n_id: 0 for n_id in graph.nodes}
    node_ids = list(graph.nodes.keys())
    paths_computed = 0
    for i, src in enumerate(node_ids):
        for j, tgt in enumerate(node_ids):
            if i == j or paths_computed >= max_paths_to_compute:
                continue
            # We only need one direction per pair — BFS is symmetric here
            if j <= i:
                continue
            path = shortest_path(graph, src, tgt)
            if path is None or len(path) < 3:
                # Path doesn't exist or is direct (no intermediate node)
                paths_computed += 1
                continue
            # Interior nodes are intermediate
            for internal in path[1:-1]:
                through_count[internal] = through_count.get(internal, 0) + 1
            paths_computed += 1
    return through_count


def betweenness(graph: InMemoryGraph, node_id: str) -> float:
    """Normalized betweenness score [0.0, 1.0].

    Scaled by the max betweenness in the graph. Bottleneck nodes on critical
    paths between large parts of the network surface here.
    """
    if not graph.nodes or node_id not in graph.nodes:
        return 0.0
    through_counts = _all_pairs_shortest_paths(graph)
    if not through_counts:
        return 0.0
    m = max(through_counts.values()) if through_counts else 0
    if m == 0:
        return 0.0
    return through_counts.get(node_id, 0) / m


# ─────────────────────────────────────────────────────────────────────────────
# Workspace-level aggregates
# ─────────────────────────────────────────────────────────────────────────────


def connected_components(graph: InMemoryGraph) -> list[set[str]]:
    """Return node-id sets, one per weakly connected component (ignores direction)."""
    seen: set[str] = set()
    components: list[set[str]] = []
    for start in graph.nodes:
        if start in seen:
            continue
        # Multi-source BFS in 'both' direction
        component: set[str] = set()
        q: deque[str] = deque([start])
        seen.add(start)
        while q:
            cur = q.popleft()
            component.add(cur)
            for _edge, neighbor in neighbors(graph, cur, direction="both"):
                if neighbor.node_id not in seen:
                    seen.add(neighbor.node_id)
                    q.append(neighbor.node_id)
        components.append(component)
    return components


def p95(values: list[int]) -> int:
    """95th percentile of integer values. Returns 0 for empty list."""
    if not values:
        return 0
    sorted_vals = sorted(values)
    idx = int(0.95 * (len(sorted_vals) - 1))
    return sorted_vals[idx]
