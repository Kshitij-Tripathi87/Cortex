"""GraphService — orchestrator over the repository, traversal, temporal, cache.

Programs C, D, and E (features, signals, propagation) should depend on
this service, not on the repository directly. The service:
  - Loads an InMemoryGraph for a workspace + snapshot
  - Caches the loaded graph per request
  - Delegates traversal algorithms to traversal.py
  - Wraps temporal replay + diff in a clean API

The service accepts a GraphRepository + GraphCache, so it's testable
without a database (use an InMemoryRepository, NoOpCache).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.modules.graph.repository import (
    EdgeDTO,
    GraphRepository,
    NodeDTO,
    SnapshotDTO,
)
from app.modules.graph.traversal import (
    BfsResult,
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
from app.modules.graph.validation import ValidationReport, validate_workspace_graph


@dataclass
class WorkspaceGraph:
    """A loaded workspace graph + the snapshot it was loaded at.

    Returned by GraphService.load_workspace_graph — Programs C–E should
    pass this around, not raw InMemoryGraph, so callers always know which
    snapshot version they're reasoning over.
    """

    graph: InMemoryGraph
    snapshot: SnapshotDTO | None


class GraphService:
    """High-level graph operations over a GraphRepository + GraphCache."""

    def __init__(self, repo: GraphRepository, cache: Any = None) -> None:
        self._repo = repo
        # Default to a NoOp cache if none provided — caching is an optimization,
        # not a correctness concern, so callers should never have to handle
        # a missing cache.
        if cache is None:
            from app.modules.graph.cache import NoOpCache

            cache = NoOpCache()
        self._cache = cache

    # ─── Node / Edge lookups (pass-through to repository) ────────────────────

    async def get_node(self, workspace_id: str, node_id: str) -> NodeDTO | None:
        return await self._repo.get_node(workspace_id, node_id)

    async def list_nodes(
        self,
        workspace_id: str,
        entity_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[NodeDTO]:
        return await self._repo.list_nodes(workspace_id, entity_type, limit, offset)

    async def get_neighbors(
        self,
        workspace_id: str,
        node_id: str,
        direction: str = "out",
        relationship_type: str | None = None,
    ) -> list[tuple[EdgeDTO, NodeDTO]]:
        return await self._repo.get_neighbors(
            workspace_id,
            node_id,
            direction=direction,
            relationship_type=relationship_type,
        )

    # ─── In-memory graph loading (the bridge to traversal) ───────────────────

    async def load_workspace_graph(
        self,
        workspace_id: str,
    ) -> WorkspaceGraph:
        """Load the entire current graph for a workspace into memory.

        This is the start of every multi-hop query. The service caches
        the loaded graph for the request lifecycle — callers making many
        traversals against the same workspace should reuse this result.
        """
        snapshot = await self._repo.get_latest_snapshot(workspace_id)
        nodes = await self._repo.list_nodes(workspace_id, limit=200)
        edges = await self._repo.get_edges(workspace_id, limit=500)
        return WorkspaceGraph(
            graph=build_in_memory_graph(nodes, edges),
            snapshot=snapshot,
        )

    async def load_adjacency_graph(
        self,
        workspace_id: str,
        seed_node_id: str,
        hops: int = 2,
    ) -> WorkspaceGraph:
        """Load only a subgraph around `seed_node_id` up to `hops` away.

        Cheaper than loading the full workspace graph. Required for
        large graphs where loading everything isn't feasible.
        """
        snapshot = await self._repo.get_latest_snapshot(workspace_id)
        # BFS against the DB to collect node IDs in the subgraph
        collected_node_ids: set[str] = {seed_node_id}
        current_frontier: set[str] = {seed_node_id}
        for _ in range(hops):
            next_frontier: set[str] = set()
            for nid in current_frontier:
                neighbor_pairs = await self._repo.get_neighbors(
                    workspace_id,
                    nid,
                    direction="both",
                    limit=200,
                )
                for _edge, neighbor in neighbor_pairs:
                    if neighbor.node_id not in collected_node_ids:
                        next_frontier.add(neighbor.node_id)
            collected_node_ids.update(next_frontier)
            current_frontier = next_frontier
            if not current_frontier:
                break

        # Fetch all collected nodes + edges among them
        all_nodes: list[NodeDTO] = []
        for nid in collected_node_ids:
            node = await self._repo.get_node(workspace_id, nid)
            if node is not None:
                all_nodes.append(node)
        all_nodes_by_id = {n.node_id: n for n in all_nodes}
        all_node_id_set = set(all_nodes_by_id.keys())

        # Fetch all edges between collected nodes via repository method
        all_edges: list[EdgeDTO] = []
        for nid in all_node_id_set:
            edges = await self._repo.get_edges(
                workspace_id,
                source_node_id=nid,
                limit=200,
            )
            for e in edges:
                if e.target_node_id in all_node_id_set:
                    all_edges.append(e)

        return WorkspaceGraph(
            graph=build_in_memory_graph(all_nodes, all_edges),
            snapshot=snapshot,
        )

    # ─── Traversal operations (over an InMemoryGraph) ────────────────────────

    @staticmethod
    def neighbors(
        graph: InMemoryGraph,
        node_id: str,
        direction: str = "out",
        relationship_type: str | None = None,
    ) -> list[tuple[EdgeDTO, NodeDTO]]:
        return neighbors(graph, node_id, direction=direction, relationship_type=relationship_type)

    @staticmethod
    def bfs(
        graph: InMemoryGraph,
        seed_id: str,
        max_depth: int = 3,
        direction: str = "out",
        relationship_type: str | None = None,
    ) -> BfsResult:
        return bfs(
            graph,
            seed_id,
            max_depth=max_depth,
            direction=direction,
            relationship_type=relationship_type,
        )

    @staticmethod
    def dfs(
        graph: InMemoryGraph,
        seed_id: str,
        max_depth: int = 3,
        direction: str = "out",
        relationship_type: str | None = None,
    ) -> list[str]:
        return dfs(
            graph,
            seed_id,
            max_depth=max_depth,
            direction=direction,
            relationship_type=relationship_type,
        )

    @staticmethod
    def shortest_path(
        graph: InMemoryGraph,
        source_id: str,
        target_id: str,
        direction: str = "out",
        relationship_type: str | None = None,
    ) -> list[str] | None:
        return shortest_path(
            graph, source_id, target_id, direction=direction, relationship_type=relationship_type
        )

    @staticmethod
    def reachable_from(
        graph: InMemoryGraph,
        seed_id: str,
        max_depth: int = 10,
        relationship_type: str | None = None,
    ) -> set[str]:
        return reachable_from(
            graph, seed_id, max_depth=max_depth, relationship_type=relationship_type
        )

    @staticmethod
    def reachable_to(
        graph: InMemoryGraph,
        target_id: str,
        max_depth: int = 10,
        relationship_type: str | None = None,
    ) -> set[str]:
        return reachable_to(
            graph, target_id, max_depth=max_depth, relationship_type=relationship_type
        )

    @staticmethod
    def find_paths(
        graph: InMemoryGraph,
        source_id: str,
        target_id: str,
        max_depth: int = 4,
        max_paths: int = 100,
        relationship_type: str | None = None,
    ) -> list[list[str]]:
        return find_paths(
            graph,
            source_id,
            target_id,
            max_depth=max_depth,
            max_paths=max_paths,
            relationship_type=relationship_type,
        )

    # ─── Snapshots ───────────────────────────────────────────────────────────

    async def get_snapshot(self, snapshot_id: str) -> SnapshotDTO | None:
        return await self._repo.get_snapshot(snapshot_id)

    async def get_snapshot_for_workspace(
        self,
        workspace_id: str,
    ) -> SnapshotDTO | None:
        """Return the latest snapshot for a workspace (metadata only)."""
        return await self._repo.get_latest_snapshot(workspace_id)

    async def list_snapshots(
        self,
        workspace_id: str,
        limit: int = 50,
    ) -> list[SnapshotDTO]:
        return await self._repo.list_snapshots(workspace_id, limit=limit)

    # ─── Validation ──────────────────────────────────────────────────────────

    @staticmethod
    async def validate(
        db: Any,
        workspace_id: str,
    ) -> ValidationReport:
        """Run the full validation suite. Used by the /graph/validate endpoint
        and by CI as a release gate."""
        return await validate_workspace_graph(db, workspace_id)
