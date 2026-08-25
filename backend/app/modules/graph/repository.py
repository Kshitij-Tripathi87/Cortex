"""GraphRepository — storage abstraction over the operational graph.

Everything above this layer (service, traversal, features, signals) talks
to the repository, not to the DB. This lets us swap backends later
(PostgreSQL graph tables today; Neo4j/Memgraph optionally; in-memory for
tests) without touching the reasoning layer.

Conventions:
- All methods are async (DB-backed impl) and take workspace_id explicitly
  to preserve tenant isolation.
- All methods return dataclasses or None — never ORM objects — so callers
  don't accidentally mutate DB state.
- list_* methods accept limit/offset; max limit is enforced by the impl.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.graph.models import (
    GraphEdge,
    GraphNode,
    GraphSnapshot,
    GraphWriteEvent,
    ProvenanceLink,
)
from app.modules.graph.versioning import get_next_version as get_db_next_version

# ─────────────────────────────────────────────────────────────────────────────
# DTOs — plain data returned by the repository
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class NodeDTO:
    node_id: str
    workspace_id: str
    entity_type: str
    entity_id: str
    attributes: dict[str, Any]
    first_seen_version: int
    last_modified_version: int
    valid_from: datetime
    valid_to: datetime | None


@dataclass(frozen=True)
class EdgeDTO:
    edge_id: str
    workspace_id: str
    source_node_id: str
    target_node_id: str
    relationship_type: str
    attributes: dict[str, Any]
    first_seen_version: int
    last_modified_version: int
    valid_from: datetime
    valid_to: datetime | None


@dataclass(frozen=True)
class SnapshotDTO:
    snapshot_id: str
    workspace_id: str
    version: int
    prev_snapshot_id: str | None
    prev_snapshot_hash: str | None
    snapshot_hash: str
    node_count: int
    edge_count: int
    source_batch_id: str | None
    sealed_at: datetime


@dataclass(frozen=True)
class WriteEventDTO:
    event_id: str
    workspace_id: str
    snapshot_id: str
    operation: str
    element_type: str
    element_id: str
    payload: dict[str, Any]
    provenance_claim_ids: list[str]
    occurred_at: datetime


def _node_to_dto(n: GraphNode) -> NodeDTO:
    return NodeDTO(
        node_id=n.node_id,
        workspace_id=n.workspace_id,
        entity_type=n.entity_type,
        entity_id=n.entity_id,
        attributes=dict(n.attributes),
        first_seen_version=n.first_seen_version,
        last_modified_version=n.last_modified_version,
        valid_from=n.valid_from,
        valid_to=n.valid_to,
    )


def _edge_to_dto(e: GraphEdge) -> EdgeDTO:
    return EdgeDTO(
        edge_id=e.edge_id,
        workspace_id=e.workspace_id,
        source_node_id=e.source_node_id,
        target_node_id=e.target_node_id,
        relationship_type=e.relationship_type,
        attributes=dict(e.attributes),
        first_seen_version=e.first_seen_version,
        last_modified_version=e.last_modified_version,
        valid_from=e.valid_from,
        valid_to=e.valid_to,
    )


def _snap_to_dto(s: GraphSnapshot) -> SnapshotDTO:
    return SnapshotDTO(
        snapshot_id=s.snapshot_id,
        workspace_id=s.workspace_id,
        version=s.version,
        prev_snapshot_id=s.prev_snapshot_id,
        prev_snapshot_hash=s.prev_snapshot_hash,
        snapshot_hash=s.snapshot_hash,
        node_count=s.node_count,
        edge_count=s.edge_count,
        source_batch_id=s.source_batch_id,
        sealed_at=s.sealed_at,
    )


def _evt_to_dto(e: GraphWriteEvent) -> WriteEventDTO:
    return WriteEventDTO(
        event_id=e.event_id,
        workspace_id=e.workspace_id,
        snapshot_id=e.snapshot_id,
        operation=e.operation,
        element_type=e.element_type,
        element_id=e.element_id,
        payload=dict(e.payload),
        provenance_claim_ids=list(e.provenance_claim_ids),
        occurred_at=e.occurred_at,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Repository Protocol — the contract everything above relies on
# ─────────────────────────────────────────────────────────────────────────────


class GraphRepository(Protocol):
    """Abstract graph storage.

    Programs C, D, E should never import SQLAlchemy directly. They talk
    to a GraphRepository. Today's impl is SqlGraphRepository; later
    implementations can target Neo4j or Memgraph without changing callers.
    """

    async def get_node(self, workspace_id: str, node_id: str) -> NodeDTO | None: ...
    async def get_node_by_entity(
        self, workspace_id: str, entity_type: str, entity_id: str
    ) -> NodeDTO | None: ...
    async def list_nodes(
        self,
        workspace_id: str,
        entity_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[NodeDTO]: ...
    async def count_nodes(self, workspace_id: str) -> int: ...
    async def get_edges(
        self,
        workspace_id: str,
        source_node_id: str | None = None,
        target_node_id: str | None = None,
        relationship_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[EdgeDTO]: ...
    async def count_edges(self, workspace_id: str) -> int: ...
    async def get_neighbors(
        self,
        workspace_id: str,
        node_id: str,
        direction: str = "out",
        relationship_type: str | None = None,
        limit: int = 200,
    ) -> list[tuple[EdgeDTO, NodeDTO]]: ...
    async def get_snapshot(self, snapshot_id: str) -> SnapshotDTO | None: ...
    async def get_latest_snapshot(self, workspace_id: str) -> SnapshotDTO | None: ...
    async def list_snapshots(
        self,
        workspace_id: str,
        limit: int = 50,
    ) -> list[SnapshotDTO]: ...
    async def get_write_events(self, snapshot_id: str) -> list[WriteEventDTO]: ...
    async def get_provenance(
        self, workspace_id: str, element_type: str, element_id: str
    ) -> list[str]: ...


# ─────────────────────────────────────────────────────────────────────────────
# SqlGraphRepository — current implementation against PostgreSQL
# ─────────────────────────────────────────────────────────────────────────────


class SqlGraphRepository:
    """PostgreSQL-backed GraphRepository.

    Stateless — accepts an AsyncSession per call. Adds nothing beyond
    SQLAlchemy queries except the DTO conversion + Protocol conformance.
    """

    MAX_LIMIT = 200

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    def _cap(self, limit: int) -> int:
        return max(1, min(limit, self.MAX_LIMIT))

    async def get_node(self, workspace_id: str, node_id: str) -> NodeDTO | None:
        n = await self._db.get(GraphNode, node_id)
        if n is None or n.workspace_id != workspace_id:
            return None
        return _node_to_dto(n)

    async def get_node_by_entity(
        self, workspace_id: str, entity_type: str, entity_id: str
    ) -> NodeDTO | None:
        stmt = (
            select(GraphNode)
            .where(GraphNode.workspace_id == workspace_id)
            .where(GraphNode.entity_type == entity_type)
            .where(GraphNode.entity_id == entity_id)
            .where(GraphNode.valid_to.is_(None))
            .limit(1)
        )
        result = await self._db.execute(stmt)
        n = result.scalar_one_or_none()
        return _node_to_dto(n) if n else None

    async def list_nodes(
        self,
        workspace_id: str,
        entity_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[NodeDTO]:
        stmt = (
            select(GraphNode)
            .where(GraphNode.workspace_id == workspace_id)
            .where(GraphNode.valid_to.is_(None))
            .order_by(GraphNode.entity_type, GraphNode.entity_id)
            .offset(offset)
            .limit(self._cap(limit))
        )
        if entity_type:
            stmt = stmt.where(GraphNode.entity_type == entity_type)
        result = await self._db.execute(stmt)
        return [_node_to_dto(n) for n in result.scalars().all()]

    async def count_nodes(self, workspace_id: str) -> int:
        stmt = (
            select(func.count(GraphNode.node_id))
            .where(GraphNode.workspace_id == workspace_id)
            .where(GraphNode.valid_to.is_(None))
        )
        result = await self._db.execute(stmt)
        return int(result.scalar_one())

    async def get_edges(
        self,
        workspace_id: str,
        source_node_id: str | None = None,
        target_node_id: str | None = None,
        relationship_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[EdgeDTO]:
        stmt = (
            select(GraphEdge)
            .where(GraphEdge.workspace_id == workspace_id)
            .where(GraphEdge.valid_to.is_(None))
            .order_by(GraphEdge.relationship_type, GraphEdge.edge_id)
            .offset(offset)
            .limit(self._cap(limit))
        )
        if source_node_id:
            stmt = stmt.where(GraphEdge.source_node_id == source_node_id)
        if target_node_id:
            stmt = stmt.where(GraphEdge.target_node_id == target_node_id)
        if relationship_type:
            stmt = stmt.where(GraphEdge.relationship_type == relationship_type)
        result = await self._db.execute(stmt)
        return [_edge_to_dto(e) for e in result.scalars().all()]

    async def count_edges(self, workspace_id: str) -> int:
        stmt = (
            select(func.count(GraphEdge.edge_id))
            .where(GraphEdge.workspace_id == workspace_id)
            .where(GraphEdge.valid_to.is_(None))
        )
        result = await self._db.execute(stmt)
        return int(result.scalar_one())

    async def get_neighbors(
        self,
        workspace_id: str,
        node_id: str,
        direction: str = "out",
        relationship_type: str | None = None,
        limit: int = 200,
    ) -> list[tuple[EdgeDTO, NodeDTO]]:
        """Return [(edge, neighbor_node)] for the given node.

        direction: 'out' (follow source_node_id), 'in' (follow target_node_id),
                   or 'both'.
        """
        capped = self._cap(limit)
        if direction == "out":
            edge_stmt = (
                select(GraphEdge)
                .where(GraphEdge.workspace_id == workspace_id)
                .where(GraphEdge.source_node_id == node_id)
                .where(GraphEdge.valid_to.is_(None))
                .limit(capped)
            )
        elif direction == "in":
            edge_stmt = (
                select(GraphEdge)
                .where(GraphEdge.workspace_id == workspace_id)
                .where(GraphEdge.target_node_id == node_id)
                .where(GraphEdge.valid_to.is_(None))
                .limit(capped)
            )
        else:  # both
            edge_stmt = (
                select(GraphEdge)
                .where(GraphEdge.workspace_id == workspace_id)
                .where(GraphEdge.valid_to.is_(None))
                .where(
                    (GraphEdge.source_node_id == node_id) | (GraphEdge.target_node_id == node_id)
                )
                .limit(capped)
            )
        if relationship_type:
            edge_stmt = edge_stmt.where(GraphEdge.relationship_type == relationship_type)

        result = await self._db.execute(edge_stmt)
        edges = list(result.scalars().all())

        out: list[tuple[EdgeDTO, NodeDTO]] = []
        for e in edges:
            neighbor_id = e.target_node_id if e.source_node_id == node_id else e.source_node_id
            neighbor = await self._db.get(GraphNode, neighbor_id)
            if neighbor is not None and neighbor.valid_to is None:
                out.append((_edge_to_dto(e), _node_to_dto(neighbor)))
        return out

    async def get_snapshot(self, snapshot_id: str) -> SnapshotDTO | None:
        s = await self._db.get(GraphSnapshot, snapshot_id)
        return _snap_to_dto(s) if s else None

    async def get_latest_snapshot(self, workspace_id: str) -> SnapshotDTO | None:
        stmt = (
            select(GraphSnapshot)
            .where(GraphSnapshot.workspace_id == workspace_id)
            .order_by(GraphSnapshot.version.desc())
            .limit(1)
        )
        result = await self._db.execute(stmt)
        s = result.scalar_one_or_none()
        return _snap_to_dto(s) if s else None

    async def list_snapshots(
        self,
        workspace_id: str,
        limit: int = 50,
    ) -> list[SnapshotDTO]:
        stmt = (
            select(GraphSnapshot)
            .where(GraphSnapshot.workspace_id == workspace_id)
            .order_by(GraphSnapshot.version.desc())
            .limit(self._cap(limit))
        )
        result = await self._db.execute(stmt)
        return [_snap_to_dto(s) for s in result.scalars().all()]

    async def get_write_events(self, snapshot_id: str) -> list[WriteEventDTO]:
        stmt = (
            select(GraphWriteEvent)
            .where(GraphWriteEvent.snapshot_id == snapshot_id)
            .order_by(GraphWriteEvent.occurred_at, GraphWriteEvent.event_id)
        )
        result = await self._db.execute(stmt)
        return [_evt_to_dto(e) for e in result.scalars().all()]

    async def get_provenance(
        self, workspace_id: str, element_type: str, element_id: str
    ) -> list[str]:
        """Return the list of claim_ids that justify this graph element."""
        stmt = (
            select(ProvenanceLink.claim_id)
            .where(ProvenanceLink.workspace_id == workspace_id)
            .where(ProvenanceLink.graph_element_type == element_type)
            .where(ProvenanceLink.graph_element_id == element_id)
        )
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def get_next_snapshot_version(self, workspace_id: str) -> int:
        """Get the next snapshot version number for a workspace.

        Uses DB-backed monotonic versioning from snapshot_sequences table.
        """
        # Use the new centralized versioning module
        # Note: This requires a session flush to work correctly
        return await get_db_next_version(self._db, workspace_id, "graph")
