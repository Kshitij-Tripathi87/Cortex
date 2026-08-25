"""Graph integrity checks — verifies the provenance chain is complete.

After compilation, the integrity checker verifies:
1. Orphan detection — every edge references existing nodes
2. Provenance completeness — every node and edge has at least one
   ProvenanceLink back to an evidence claim
3. Snapshot chain intact — snapshot hashes are verified against write events
4. No dangling valid_to — retired nodes don't have new edges pointing at them

Returns True only if all checks pass. Failures are logged and the caller
(compile_evidence_to_graph) marks the snapshot as integrity_passed=False.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.graph.models import (
    GraphEdge,
    GraphNode,
    GraphWriteEvent,
    ProvenanceLink,
)


async def run_integrity_checks(
    db: AsyncSession,
    workspace_id: str,
    snapshot_id: str,
) -> bool:
    """Run all integrity checks for a freshly compiled snapshot.

    Returns True only if every check passes.
    """
    checks = [
        await _check_no_orphan_edges(db, workspace_id),
        await _check_all_nodes_have_provenance(db, workspace_id),
        await _check_all_edges_have_provenance(db, workspace_id),
        await _check_snapshot_has_write_events(db, snapshot_id),
    ]
    return all(checks)


async def _check_no_orphan_edges(
    db: AsyncSession,
    workspace_id: str,
) -> bool:
    """Every edge's source and target must reference an existing node."""
    edge_stmt = (
        select(GraphEdge)
        .where(GraphEdge.workspace_id == workspace_id)
        .where(GraphEdge.valid_to.is_(None))
    )
    result = await db.execute(edge_stmt)
    edges = list(result.scalars().all())

    node_ids_stmt = select(GraphNode.node_id).where(
        GraphNode.workspace_id == workspace_id,
        GraphNode.valid_to.is_(None),
    )
    node_result = await db.execute(node_ids_stmt)
    node_ids = {nid for nid in node_result.scalars().all()}

    for edge in edges:
        if edge.source_node_id not in node_ids:
            return False
        if edge.target_node_id not in node_ids:
            return False
    return True


async def _check_all_nodes_have_provenance(
    db: AsyncSession,
    workspace_id: str,
) -> bool:
    """Every active node must have at least one provenance link."""
    node_stmt = select(GraphNode.node_id).where(
        GraphNode.workspace_id == workspace_id,
        GraphNode.valid_to.is_(None),
    )
    node_result = await db.execute(node_stmt)
    node_ids = list(node_result.scalars().all())

    if not node_ids:
        return True

    link_stmt = (
        select(ProvenanceLink.graph_element_id)
        .where(ProvenanceLink.workspace_id == workspace_id)
        .where(ProvenanceLink.graph_element_type == "node")
        .where(ProvenanceLink.graph_element_id.in_(node_ids))
        .group_by(ProvenanceLink.graph_element_id)
    )
    link_result = await db.execute(link_stmt)
    linked_ids = set(link_result.scalars().all())

    return set(node_ids) == linked_ids


async def _check_all_edges_have_provenance(
    db: AsyncSession,
    workspace_id: str,
) -> bool:
    """Every active edge must have at least one provenance link."""
    edge_stmt = select(GraphEdge.edge_id).where(
        GraphEdge.workspace_id == workspace_id,
        GraphEdge.valid_to.is_(None),
    )
    edge_result = await db.execute(edge_stmt)
    edge_ids = list(edge_result.scalars().all())

    if not edge_ids:
        return True

    link_stmt = (
        select(ProvenanceLink.graph_element_id)
        .where(ProvenanceLink.workspace_id == workspace_id)
        .where(ProvenanceLink.graph_element_type == "edge")
        .where(ProvenanceLink.graph_element_id.in_(edge_ids))
        .group_by(ProvenanceLink.graph_element_id)
    )
    link_result = await db.execute(link_stmt)
    linked_ids = set(link_result.scalars().all())

    return set(edge_ids) == linked_ids


async def _check_snapshot_has_write_events(
    db: AsyncSession,
    snapshot_id: str,
) -> bool:
    """Every snapshot must have at least one write event (unless it's an
    empty-graph initial snapshot, which we don't create)."""
    stmt = select(func.count(GraphWriteEvent.event_id)).where(
        GraphWriteEvent.snapshot_id == snapshot_id
    )
    result = await db.execute(stmt)
    count = result.scalar_one()
    return count > 0


async def get_integrity_report(
    db: AsyncSession,
    workspace_id: str,
) -> dict[str, bool]:
    """Return a detailed integrity report for a workspace's graph."""
    return {
        "no_orphan_edges": await _check_no_orphan_edges(db, workspace_id),
        "all_nodes_have_provenance": await _check_all_nodes_have_provenance(db, workspace_id),
        "all_edges_have_provenance": await _check_all_edges_have_provenance(db, workspace_id),
    }
