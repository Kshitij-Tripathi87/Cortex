"""Traversal Engine — pure functions over an in-memory graph.

Key design principle: traversals NEVER hit the database during the algorithm.
The service loads a workspace's graph into an InMemoryGraph once (or a
subgraph around a seed node), then traversal functions operate on it.
This is the only way to get acceptable performance for multi-hop queries
and the only way to keep traversal logic unit-testable.

All functions here are:
  - Deterministic (no random walks, no ML)
  - Pure (no side effects, no I/O)
  - Total (no exceptions on missing nodes — return empty results)

Supported operations:
  - build_in_memory_graph   — load from NodeDTO/EdgeDTO lists
  - neighbors               — one-hop neighbors (with optional direction/rel filter)
  - bfs                     — breadth-first traversal up to max_depth
  - dfs                     — depth-first traversal up to max_depth
  - shortest_path           — BFS-based shortest path between two nodes
  - reachable_from          — every node reachable from a seed
  - reachable_to            — every node that can reach a target (reverse traversal)
  - find_paths              — all simple paths up to max_depth
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field

from app.modules.graph.repository import EdgeDTO, NodeDTO

# ─────────────────────────────────────────────────────────────────────────────
# InMemoryGraph — the data structure traversals operate on
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class InMemoryGraph:
    """A graph fully loaded in memory. Built once, traversed many times.

    Adjacency lists are precomputed at construction time so traversal
    functions are O(neighbors) per hop with no further indexing needed.
    """

    nodes: dict[str, NodeDTO] = field(default_factory=dict)
    out_edges: dict[str, list[EdgeDTO]] = field(default_factory=lambda: defaultdict(list))
    in_edges: dict[str, list[EdgeDTO]] = field(default_factory=lambda: defaultdict(list))
    edges: list[EdgeDTO] = field(default_factory=list)

    def add_node(self, node: NodeDTO) -> None:
        self.nodes[node.node_id] = node

    def add_edge(self, edge: EdgeDTO) -> None:
        self.edges.append(edge)
        self.out_edges[edge.source_node_id].append(edge)
        self.in_edges[edge.target_node_id].append(edge)

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    def has_node(self, node_id: str) -> bool:
        return node_id in self.nodes

    def get_node(self, node_id: str) -> NodeDTO | None:
        return self.nodes.get(node_id)


def build_in_memory_graph(
    nodes: list[NodeDTO],
    edges: list[EdgeDTO],
) -> InMemoryGraph:
    """Construct an InMemoryGraph from lists of NodeDTO and EdgeDTO."""
    g = InMemoryGraph()
    for n in nodes:
        g.add_node(n)
    for e in edges:
        # Silently skip edges referencing missing nodes; the integrity
        # check (validation.py) surfaces orphan edges as a separate concern.
        if e.source_node_id in g.nodes and e.target_node_id in g.nodes:
            g.add_edge(e)
    return g


# ─────────────────────────────────────────────────────────────────────────────
# Neighbor query — one hop
# ─────────────────────────────────────────────────────────────────────────────


def neighbors(
    graph: InMemoryGraph,
    node_id: str,
    *,
    direction: str = "out",
    relationship_type: str | None = None,
) -> list[tuple[EdgeDTO, NodeDTO]]:
    """Return [(edge, neighbor_node)] one hop from `node_id`.

    direction: 'out' (follow source), 'in' (follow target), or 'both'.
    relationship_type: optional filter — only edges of this type.
    """
    if node_id not in graph.nodes:
        return []

    results: list[tuple[EdgeDTO, NodeDTO]] = []
    seen_edges: set[str] = set()

    if direction in ("out", "both"):
        for edge in graph.out_edges.get(node_id, []):
            if relationship_type and edge.relationship_type != relationship_type:
                continue
            if edge.edge_id in seen_edges:
                continue
            seen_edges.add(edge.edge_id)
            neighbor = graph.get_node(edge.target_node_id)
            if neighbor is not None:
                results.append((edge, neighbor))

    if direction in ("in", "both"):
        for edge in graph.in_edges.get(node_id, []):
            if relationship_type and edge.relationship_type != relationship_type:
                continue
            if edge.edge_id in seen_edges:
                continue
            seen_edges.add(edge.edge_id)
            neighbor = graph.get_node(edge.source_node_id)
            if neighbor is not None:
                results.append((edge, neighbor))

    return results


# ─────────────────────────────────────────────────────────────────────────────
# BFS — breadth-first up to max_depth
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BfsResult:
    """Result of a BFS traversal."""

    visited: list[str]  # node_ids in BFS order
    depths: dict[str, int]  # node_id → hop distance from seed
    parents: dict[str, str | None]  # node_id → parent_id (seed → None)


def bfs(
    graph: InMemoryGraph,
    seed_id: str,
    *,
    max_depth: int = 3,
    direction: str = "out",
    relationship_type: str | None = None,
) -> BfsResult:
    """Breadth-first traversal from `seed_id` up to `max_depth` hops.

    Visits each node at most once. Returns nodes in BFS order, with depth
    and parent annotations suitable for reconstructing the search tree.
    """
    if seed_id not in graph.nodes or max_depth < 0:
        return BfsResult(visited=[], depths={}, parents={})

    visited: list[str] = []
    depths: dict[str, int] = {seed_id: 0}
    parents: dict[str, str | None] = {seed_id: None}
    queue: deque[str] = deque([seed_id])

    while queue:
        current = queue.popleft()
        visited.append(current)
        current_depth = depths[current]
        if current_depth >= max_depth:
            continue
        for _edge, neighbor in neighbors(
            graph,
            current,
            direction=direction,
            relationship_type=relationship_type,
        ):
            if neighbor.node_id not in depths:
                depths[neighbor.node_id] = current_depth + 1
                parents[neighbor.node_id] = current
                queue.append(neighbor.node_id)

    return BfsResult(visited=visited, depths=depths, parents=parents)


# ─────────────────────────────────────────────────────────────────────────────
# DFS — depth-first up to max_depth
# ─────────────────────────────────────────────────────────────────────────────


def dfs(
    graph: InMemoryGraph,
    seed_id: str,
    *,
    max_depth: int = 3,
    direction: str = "out",
    relationship_type: str | None = None,
) -> list[str]:
    """Depth-first traversal returning visited node_ids in DFS order."""
    if seed_id not in graph.nodes or max_depth < 0:
        return []

    visited: list[str] = []
    seen: set[str] = set()

    # Iterative DFS with explicit stack of (node_id, depth)
    stack: list[tuple[str, int]] = [(seed_id, 0)]
    while stack:
        current, depth = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        visited.append(current)
        if depth >= max_depth:
            continue
        # Push neighbors in reverse order so we visit them in natural order
        nxt = neighbors(graph, current, direction=direction, relationship_type=relationship_type)
        for _edge, neighbor in reversed(nxt):
            if neighbor.node_id not in seen:
                stack.append((neighbor.node_id, depth + 1))
    return visited


# ─────────────────────────────────────────────────────────────────────────────
# Shortest path — BFS-based, deterministic
# ─────────────────────────────────────────────────────────────────────────────


def shortest_path(
    graph: InMemoryGraph,
    source_id: str,
    target_id: str,
    *,
    direction: str = "out",
    relationship_type: str | None = None,
) -> list[str] | None:
    """Return the shortest path (list of node_ids) from source to target.

    Returns None if no path exists. If source == target, returns [source].
    Tie-breaking is deterministic: among same-length paths we return the one
    discovered by BFS first, which is order-of-adjacency-deterministic.
    """
    if source_id not in graph.nodes or target_id not in graph.nodes:
        return None
    if source_id == target_id:
        return [source_id]

    parents: dict[str, str | None] = {source_id: None}
    queue: deque[str] = deque([source_id])

    while queue:
        current = queue.popleft()
        for _edge, neighbor in neighbors(
            graph,
            current,
            direction=direction,
            relationship_type=relationship_type,
        ):
            if neighbor.node_id not in parents:
                parents[neighbor.node_id] = current
                if neighbor.node_id == target_id:
                    return _reconstruct_path(parents, target_id)
                queue.append(neighbor.node_id)
    return None


def _reconstruct_path(
    parents: dict[str, str | None],
    target: str,
) -> list[str]:
    path: list[str] = []
    cur: str | None = target
    while cur is not None:
        path.append(cur)
        cur = parents.get(cur)
    path.reverse()
    return path


# ─────────────────────────────────────────────────────────────────────────────
# Reachability — forward and reverse
# ─────────────────────────────────────────────────────────────────────────────


def reachable_from(
    graph: InMemoryGraph,
    seed_id: str,
    *,
    max_depth: int = 10,
    relationship_type: str | None = None,
) -> set[str]:
    """Every node reachable from `seed_id` following out-edges up to max_depth."""
    result = bfs(
        graph, seed_id, max_depth=max_depth, direction="out", relationship_type=relationship_type
    )
    return set(result.visited)


def reachable_to(
    graph: InMemoryGraph,
    target_id: str,
    *,
    max_depth: int = 10,
    relationship_type: str | None = None,
) -> set[str]:
    """Every node that can reach `target_id` following out-edges up to max_depth.

    Computed by running BFS backwards from `target_id` along in-edges.
    Equivalent to "what can affect this target through the graph".
    """
    result = bfs(
        graph, target_id, max_depth=max_depth, direction="in", relationship_type=relationship_type
    )
    return set(result.visited)


# ─────────────────────────────────────────────────────────────────────────────
# All simple paths up to max_depth (used by propagation engine later)
# ─────────────────────────────────────────────────────────────────────────────


def find_paths(
    graph: InMemoryGraph,
    source_id: str,
    target_id: str,
    *,
    max_depth: int = 4,
    max_paths: int = 100,
    relationship_type: str | None = None,
) -> list[list[str]]:
    """Return all simple paths (no repeated nodes) from source to target.

    Bounded by max_depth and max_paths to prevent combinatorial blow-up.
    Returns paths in DFS discovery order — deterministic.
    """
    if source_id not in graph.nodes or target_id not in graph.nodes:
        return []
    if source_id == target_id:
        return [[source_id]]

    paths: list[list[str]] = []
    seen_paths: set[tuple[str, ...]] = set()

    def _dfs(current: str, path: list[str]) -> None:
        if len(paths) >= max_paths:
            return
        if len(path) - 1 >= max_depth:
            return
        for _edge, neighbor in neighbors(
            graph,
            current,
            direction="out",
            relationship_type=relationship_type,
        ):
            if neighbor.node_id in path:
                continue  # simple path — no repeats
            new_path = path + [neighbor.node_id]
            if neighbor.node_id == target_id:
                key = tuple(new_path)
                if key not in seen_paths:
                    seen_paths.add(key)
                    paths.append(new_path)
                continue
            _dfs(neighbor.node_id, new_path)

    _dfs(source_id, [source_id])
    return paths
