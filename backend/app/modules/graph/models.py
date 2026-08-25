"""Operational Graph DB models.

Every element of the graph carries provenance back to evidence claims via
the provenance_links table. Snapshots are immutable and hash-chained —
the same as audit events. The graph is the reasoning substrate, not just
storage: each node and edge knows exactly why it exists.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.common.ids import uuid7
from app.infrastructure.database import Base


class GraphNode(Base):
    """A node in the operational graph — one per canonical entity instance.

    Uniqueness: (workspace_id, entity_type, entity_id). Upsert semantics —
    recompiling the same evidence produces the same node_id.
    """

    __tablename__ = "graph_nodes"

    node_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(128), nullable=False)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    first_seen_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_modified_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class GraphEdge(Base):
    """A directed edge in the operational graph — one per canonical relationship.

    Uniqueness: (workspace_id, source_node_id, target_node_id, relationship_type).
    """

    __tablename__ = "graph_edges"

    edge_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    source_node_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    target_node_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    relationship_type: Mapped[str] = mapped_column(String(64), nullable=False)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    first_seen_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_modified_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class GraphSnapshot(Base):
    """An immutable, hash-chained snapshot of the graph state.

    Each snapshot seals a set of graph write events into a tamper-evident
    chain. snapshot_hash = SHA256(prev_hash || canonical_sort(write_event_hashes)).
    The same inputs always produce the same hash (determinism contract).
    """

    __tablename__ = "graph_snapshots"

    snapshot_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    prev_snapshot_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    prev_snapshot_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    node_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    edge_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    sealed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class GraphWriteEvent(Base):
    """A single graph mutation — upsert_node, upsert_edge, retire_node, retire_edge.

    Each event records exactly which evidence claims justify it, providing
    full provenance from graph element back to immutable evidence.
    """

    __tablename__ = "graph_write_events"

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    snapshot_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    element_type: Mapped[str] = mapped_column(String(16), nullable=False)
    element_id: Mapped[str] = mapped_column(String(36), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    provenance_claim_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )


class ProvenanceLink(Base):
    """Links every graph element (node or edge) back to the evidence claims
    that justify its existence. This is the provenance chain required by the
    Phase 3 success metric: every recommendation must be reconstructable
    from immutable evidence through deterministic graph reasoning.
    """

    __tablename__ = "provenance_links"

    link_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    graph_element_type: Mapped[str] = mapped_column(String(16), nullable=False)
    graph_element_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    claim_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
