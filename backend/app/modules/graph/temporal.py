"""Temporal Traversal — historical graph state, replay, and diff.

The operational graph is versioned: each snapshot seals a set of write
events that mutated the graph from its previous state. This module lets
callers:

  - reconstruct the graph as it existed at any snapshot
  - replay mutations between two snapshots
  - diff two snapshots to see what changed (added/removed/modified)

This is invaluable for investigations: "Why did the graph look different
last week?" requires exactly this kind of temporal query.

Diff contract:
  added   — present in `to` but not in `from`
  removed — present in `from` but not in `to`
  modified — same element_id but attributes changed
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.graph.models import (
    GraphEdge,
    GraphNode,
    GraphSnapshot,
    GraphWriteEvent,
)
from app.modules.graph.repository import (
    EdgeDTO,
    NodeDTO,
    _edge_to_dto,
    _node_to_dto,
)
from app.modules.graph.traversal import InMemoryGraph, build_in_memory_graph


@dataclass(frozen=True)
class NodeDiff:
    added: list[NodeDTO] = field(default_factory=list)
    removed: list[NodeDTO] = field(default_factory=list)
    modified: list[tuple[NodeDTO, NodeDTO]] = field(default_factory=list)  # (before, after)


@dataclass(frozen=True)
class EdgeDiff:
    added: list[EdgeDTO] = field(default_factory=list)
    removed: list[EdgeDTO] = field(default_factory=list)
    modified: list[tuple[EdgeDTO, EdgeDTO]] = field(default_factory=list)


@dataclass(frozen=True)
class SnapshotDiff:
    from_version: int
    to_version: int
    nodes: NodeDiff
    edges: EdgeDiff
    is_replay_consistent: bool  # raw writes match the structural diff


async def load_graph_at_snapshot(
    db: AsyncSession,
    workspace_id: str,
    snapshot_id: str,
) -> InMemoryGraph:
    """Reconstruct the InMemoryGraph as it existed at the given snapshot.

    Approach: replay every write event up to and including `snapshot_id`,
    in chronological order, applying upserts and retires to a working set.
    This gives the exact graph state at that point in time.

    For Phase 3 v1 we assume snapshots are append-only (no retire
    operations yet); upserts are the only write operations. Future
    retire-node / retire-edge operations will be handled here too.
    """
    # Get the target snapshot to learn its version
    snapshot = await db.get(GraphSnapshot, snapshot_id)
    if snapshot is None or snapshot.workspace_id != workspace_id:
        return InMemoryGraph()

    target_version = snapshot.version

    # Fetch all snapshots up to and including the target, ordered by version
    snap_stmt = (
        select(GraphSnapshot)
        .where(GraphSnapshot.workspace_id == workspace_id)
        .where(GraphSnapshot.version <= target_version)
        .order_by(GraphSnapshot.version.asc())
    )
    snap_result = await db.execute(snap_stmt)
    snapshots_in_range = list(snap_result.scalars().all())
    snapshot_ids = [s.snapshot_id for s in snapshots_in_range]

    if not snapshot_ids:
        return InMemoryGraph()

    # Replay every write event across all snapshots up to and including target
    evt_stmt = (
        select(GraphWriteEvent)
        .where(GraphWriteEvent.workspace_id == workspace_id)
        .where(GraphWriteEvent.snapshot_id.in_(snapshot_ids))
        .order_by(GraphWriteEvent.occurred_at, GraphWriteEvent.event_id)
    )
    evt_result = await db.execute(evt_stmt)
    events = list(evt_result.scalars().all())

    # Replay into a working set keyed by (entity_type, entity_id) for nodes
    # and (source_node_id, target_node_id, rel) for edges.
    node_map: dict[str, NodeDTO] = {}
    edge_map: dict[str, EdgeDTO] = {}

    for evt in events:
        op = evt.operation
        if op == "upsert_node":
            payload = evt.payload
            # Real node_ids are stored on the GraphWriteEvent.element_id
            node_id = evt.element_id
            node_map[node_id] = _node_to_dto(
                _make_graph_node(node_id, workspace_id, payload, target_version)
            )
        elif op == "upsert_edge":
            payload = evt.payload
            edge_id = evt.element_id
            edge_map[edge_id] = _edge_to_dto(
                _make_graph_edge(edge_id, workspace_id, payload, target_version)
            )
        elif op == "retire_node":
            node_map.pop(evt.element_id, None)
        elif op == "retire_edge":
            edge_map.pop(evt.element_id, None)

    return build_in_memory_graph(list(node_map.values()), list(edge_map.values()))


def _make_graph_node(
    node_id: str,
    workspace_id: str,
    payload: dict[str, Any],
    version: int,
) -> GraphNode:
    """Rebuild a GraphNode ORM object from a write-event payload."""
    return GraphNode(
        node_id=node_id,
        workspace_id=workspace_id,
        entity_type=payload.get("entity_type", "Unknown"),
        entity_id=payload.get("entity_id", ""),
        attributes=payload.get("attributes", {}),
        first_seen_version=version,
        last_modified_version=version,
    )


def _make_graph_edge(
    edge_id: str,
    workspace_id: str,
    payload: dict[str, Any],
    version: int,
) -> GraphEdge:
    """Rebuild a GraphEdge ORM object from a write-event payload."""
    # Note: the persisted edge has resolved source/target_node_ids, not the
    # entity strings in the payload. For the temporal load we don't have
    # the resolved IDs without joining back to the GraphEdge table. So
    # we fall back to reading the actual GraphEdge row if we still have one.
    # For Phase 3 v1, we accept that snapshot replay may need to look up
    # the edge row by id. The build_in_memory_graph call later looks up
    # nodes by IDs in the edge, so we need real IDs here.
    # We'll set ID fields passed through in payload if present.
    return GraphEdge(
        edge_id=edge_id,
        workspace_id=workspace_id,
        source_node_id=payload.get("_source_node_id", ""),
        target_node_id=payload.get("_target_node_id", ""),
        relationship_type=payload.get("relationship_type", "UNKNOWN"),
        attributes=payload.get("attributes", {}),
        first_seen_version=version,
        last_modified_version=version,
    )


async def diff_snapshots(
    db: AsyncSession,
    workspace_id: str,
    from_snapshot_id: str,
    to_snapshot_id: str,
) -> SnapshotDiff:
    """Compute the structural diff between two snapshots.

    Replays both snapshots to InMemoryGraph and compares element-by-element.
    The diff distinguishes added/removed/modified for nodes and edges.
    """
    from_graph = await load_graph_at_snapshot(db, workspace_id, from_snapshot_id)
    to_graph = await load_graph_at_snapshot(db, workspace_id, to_snapshot_id)

    from_snap = await db.get(GraphSnapshot, from_snapshot_id)
    to_snap = await db.get(GraphSnapshot, to_snapshot_id)

    # Node diff
    from_node_ids = set(from_graph.nodes.keys())
    to_node_ids = set(to_graph.nodes.keys())

    added_nodes: list[NodeDTO] = []
    removed_nodes: list[NodeDTO] = []
    modified_nodes: list[tuple[NodeDTO, NodeDTO]] = []

    for nid in to_node_ids - from_node_ids:
        added_nodes.append(to_graph.nodes[nid])
    for nid in from_node_ids - to_node_ids:
        removed_nodes.append(from_graph.nodes[nid])
    for nid in from_node_ids & to_node_ids:
        n1 = from_graph.nodes[nid]
        n2 = to_graph.nodes[nid]
        if n1.attributes != n2.attributes or n1.entity_type != n2.entity_type:
            modified_nodes.append((n1, n2))

    # Edge diff
    from_edge_ids = {e.edge_id for e in from_graph.edges}
    to_edge_ids = {e.edge_id for e in to_graph.edges}

    added_edges: list[EdgeDTO] = []
    removed_edges: list[EdgeDTO] = []
    modified_edges: list[tuple[EdgeDTO, EdgeDTO]] = []

    by_id_from = {e.edge_id: e for e in from_graph.edges}
    by_id_to = {e.edge_id: e for e in to_graph.edges}

    for eid in to_edge_ids - from_edge_ids:
        added_edges.append(by_id_to[eid])
    for eid in from_edge_ids - to_edge_ids:
        removed_edges.append(by_id_from[eid])
    for eid in from_edge_ids & to_edge_ids:
        e1 = by_id_from[eid]
        e2 = by_id_to[eid]
        if e1.attributes != e2.attributes or e1.relationship_type != e2.relationship_type:
            modified_edges.append((e1, e2))

    # Replay consistency check: the diff should be reproducible from write events
    is_consistent = True
    if from_snap and to_snap:
        evt_stmt = (
            select(GraphWriteEvent)
            .where(GraphWriteEvent.workspace_id == workspace_id)
            .where(GraphWriteEvent.snapshot_id == to_snapshot_id)
        )
        evt_result = await db.execute(evt_stmt)
        to_events = list(evt_result.scalars().all())
        expected_node_adds = sum(1 for e in to_events if e.operation == "upsert_node")
        expected_edge_adds = sum(1 for e in to_events if e.operation == "upsert_edge")
        # The events in `to` snapshot add up to the to_state — diff vs from
        # gives added = (in to, not in from). For an append-only graph this
        # equals the number of upserts in `to` snapshot. If this invariant
        # fails we mark the diff as replay-inconsistent.
        if len(added_nodes) != expected_node_adds:
            is_consistent = False
        if len(added_edges) != expected_edge_adds:
            is_consistent = False

    return SnapshotDiff(
        from_version=from_snap.version if from_snap else 0,
        to_version=to_snap.version if to_snap else 0,
        nodes=NodeDiff(added=added_nodes, removed=removed_nodes, modified=modified_nodes),
        edges=EdgeDiff(added=added_edges, removed=removed_edges, modified=modified_edges),
        is_replay_consistent=is_consistent,
    )


def summarize_diff(diff: SnapshotDiff) -> dict[str, int]:
    """Return a flat summary of a diff for telemetry and API responses."""
    return {
        "from_version": diff.from_version,
        "to_version": diff.to_version,
        "nodes_added": len(diff.nodes.added),
        "nodes_removed": len(diff.nodes.removed),
        "nodes_modified": len(diff.nodes.modified),
        "edges_added": len(diff.edges.added),
        "edges_removed": len(diff.edges.removed),
        "edges_modified": len(diff.edges.modified),
        "replay_consistent": int(diff.is_replay_consistent),
    }
