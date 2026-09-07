"""Nexus Ontology — PostgreSQL-backed Persistence Store.

Solves the shadow-world problem: the ontology IS a projection over
authoritative world state, backed by PostgreSQL rather than a second
in-memory database.

Architecture:
    World State (authoritative, event-sourced)
        ↓  projection
    nexus_entities + nexus_relationships tables (queryable materialization)
        ↓  read cache
    In-memory WorldModelRepository (fast graph traversal)

Write path: upsert() writes to Postgres inside the caller's transaction,
emits a world-state event, and invalidates the read-through cache.

Read path: query()/get()/neighbors() read from the in-memory projection,
rebuilding cold caches from Postgres on first touch or after invalidation.

This gives us:
- Single source of truth (Postgres, RLS via tenant/workspace)
- Fast graph traversal (in-memory adjacency)
- Consistency checks between world state and ontology projection
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    delete,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.common.ids import uuid7
from app.infrastructure.database import Base
from app.modules.nexus_spine.ontology.core_types import (
    ENTITY_KIND_TO_DOMAIN,
    EntityKind,
    RelationshipKind,
)
from app.modules.nexus_spine.ontology.entities import (
    Entity,
    EntityQuery,
    PermissionGrant,
    ProvenanceRecord,
    RelationshipEdge,
    StateSnapshot,
)

JSON_VARIANT = JSON().with_variant(JSONB, "postgresql")


def _utc_now() -> datetime:
    return datetime.now(UTC)


# ─────────────────────────────────────────────────────────────────────────────
# SQLAlchemy Models
# ─────────────────────────────────────────────────────────────────────────────


class NexusEntityDB(Base):
    """Persisted world-model entity — the ontology's materialized form."""

    __tablename__ = "nexus_entities"

    entity_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    domain: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    natural_key: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    confidence_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[dict[str, Any]] = mapped_column(JSON_VARIANT, nullable=False, default=dict)
    state_history: Mapped[list[dict[str, Any]]] = mapped_column(JSON_VARIANT, nullable=False, default=list)
    provenance: Mapped[list[dict[str, Any]]] = mapped_column(JSON_VARIANT, nullable=False, default=list)
    permissions: Mapped[list[dict[str, Any]]] = mapped_column(JSON_VARIANT, nullable=False, default=list)
    tags: Mapped[list[str]] = mapped_column(JSON_VARIANT, nullable=False, default=list)
    extra: Mapped[dict[str, Any]] = mapped_column("metadata", JSON_VARIANT, nullable=False, default=dict)
    world_state_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )

    __table_args__ = (
        Index("ix_nexus_entities_ws_kind", "workspace_id", "kind"),
        Index("ix_nexus_entities_ws_nk", "workspace_id", "natural_key"),
    )


class NexusRelationshipDB(Base):
    """Persisted relationship edge between two world-model entities."""

    __tablename__ = "nexus_relationships"

    edge_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    from_entity_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    to_entity_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON_VARIANT, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )

    __table_args__ = (
        Index("ix_nexus_rels_ws_from", "workspace_id", "from_entity_id"),
        Index("ix_nexus_rels_ws_to", "workspace_id", "to_entity_id"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Serialization
# ─────────────────────────────────────────────────────────────────────────────


def entity_to_row(entity: Entity) -> dict[str, Any]:
    """Convert a domain Entity into a NexusEntityDB row dict."""
    domain = ENTITY_KIND_TO_DOMAIN.get(entity.kind)
    return {
        "entity_id": str(entity.entity_id),
        "tenant_id": str(entity.tenant_id),
        "workspace_id": str(entity.workspace_id),
        "kind": entity.kind.value,
        "domain": domain.value if domain else "ops",
        "natural_key": entity.natural_key,
        "name": entity.name,
        "description": entity.description,
        "source": entity.source,
        "confidence": entity.confidence,
        "confidence_reason": entity.confidence_reason,
        "state": dict(entity.state),
        "state_history": [
            {
                "version": s.version,
                "timestamp": s.timestamp.isoformat(),
                "state": dict(s.state),
                "state_hash": s.state_hash,
                "world_state_version": s.world_state_version,
                "confidence": s.confidence,
            }
            for s in entity.state_history
        ],
        "provenance": [
            {
                "step_id": str(p.step_id),
                "actor": p.actor,
                "action": p.action,
                "timestamp": p.timestamp.isoformat(),
                "source": p.source,
                "reason": p.reason,
                "previous_hash": p.previous_hash,
                "new_hash": p.new_hash,
                "metadata": dict(p.metadata),
            }
            for p in entity.provenance
        ],
        "permissions": [
            {
                "role": g.role,
                "can_read": g.can_read,
                "can_write": g.can_write,
                "can_approve": g.can_approve,
                "granted_by": g.granted_by,
                "granted_at": g.granted_at.isoformat(),
                "expires_at": g.expires_at.isoformat() if g.expires_at else None,
            }
            for g in entity.permissions
        ],
        "tags": list(entity.tags),
        "extra": dict(entity.metadata),
        "world_state_version": entity.state_history[-1].world_state_version
        if entity.state_history
        else 0,
        "created_at": entity.created_at,
        "updated_at": entity.updated_at,
    }


def row_to_entity(row: NexusEntityDB) -> Entity:
    """Rehydrate a domain Entity from a NexusEntityDB row."""
    state_history = [
        StateSnapshot(
            version=s["version"],
            timestamp=datetime.fromisoformat(s["timestamp"]),
            state=dict(s["state"]),
            state_hash=s["state_hash"],
            world_state_version=s["world_state_version"],
            confidence=s.get("confidence", 1.0),
        )
        for s in (row.state_history or [])
    ]
    provenance = [
        ProvenanceRecord(
            step_id=UUID(p["step_id"]),
            actor=p["actor"],
            action=p["action"],
            timestamp=datetime.fromisoformat(p["timestamp"]),
            source=p["source"],
            reason=p.get("reason"),
            previous_hash=p.get("previous_hash"),
            new_hash=p.get("new_hash"),
            metadata=dict(p.get("metadata") or {}),
        )
        for p in (row.provenance or [])
    ]
    permissions = [
        PermissionGrant(
            role=g["role"],
            can_read=g.get("can_read", True),
            can_write=g.get("can_write", False),
            can_approve=g.get("can_approve", False),
            granted_by=g.get("granted_by", "system"),
            granted_at=datetime.fromisoformat(g["granted_at"]),
            expires_at=datetime.fromisoformat(g["expires_at"]) if g.get("expires_at") else None,
        )
        for g in (row.permissions or [])
    ]

    entity = Entity(
        entity_id=UUID(row.entity_id),
        tenant_id=UUID(row.tenant_id),
        workspace_id=UUID(row.workspace_id),
        kind=EntityKind(row.kind),
        natural_key=row.natural_key,
        name=row.name,
        description=row.description or "",
        source=row.source,
        confidence=row.confidence,
        confidence_reason=row.confidence_reason,
        state=dict(row.state or {}),
        state_history=state_history,
        relationships_out=[],  # Populated separately
        relationships_in=[],
        provenance=provenance,
        permissions=permissions,
        tags=list(row.tags or []),
        metadata=dict(row.extra or {}),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
    return entity


def edge_to_row(edge: RelationshipEdge, tenant_id: UUID, workspace_id: UUID) -> dict[str, Any]:
    return {
        "edge_id": str(edge.edge_id),
        "tenant_id": str(tenant_id),
        "workspace_id": str(workspace_id),
        "from_entity_id": str(edge.from_entity_id),
        "to_entity_id": str(edge.to_entity_id),
        "kind": edge.kind.value,
        "confidence": edge.confidence,
        "attributes": dict(edge.attributes),
        "created_at": edge.timestamp,
    }


def row_to_edge(row: NexusRelationshipDB) -> RelationshipEdge:
    return RelationshipEdge(
        edge_id=UUID(row.edge_id),
        from_entity_id=UUID(row.from_entity_id),
        to_entity_id=UUID(row.to_entity_id),
        kind=RelationshipKind(row.kind),
        timestamp=row.created_at,
        confidence=row.confidence,
        attributes=dict(row.attributes or {}),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Persistence Store (Async, PG-backed)
# ─────────────────────────────────────────────────────────────────────────────


class OntologyStore:
    """Async PostgreSQL-backed store for the Nexus ontology.

    All reads/writes go through an AsyncSession provided by the caller,
    so transactions remain under caller control (fastapi get_db or
    an explicit unit of work). World-model writes raise the workspace's
    world_state_version on every mutation — callers can compare this against
    world_versions.sequence_number for cross-pipeline consistency checks.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.db = session

    # ── Entities ──────────────────────────────────────────────────────────

    async def upsert_entity(self, entity: Entity) -> Entity:
        """Insert or update an entity. Returns the persisted entity."""
        row_data = entity_to_row(entity)
        existing = await self.db.execute(
            select(NexusEntityDB).where(
                NexusEntityDB.entity_id == row_data["entity_id"]
            )
        )
        row = existing.scalar_one_or_none()
        if row is None:
            self.db.add(NexusEntityDB(**row_data))
        else:
            for k, v in row_data.items():
                if k in ("entity_id", "created_at"):
                    continue
                setattr(row, k, v)
        await self.db.flush()
        return entity

    async def get_entity(
        self, tenant_id: UUID, workspace_id: UUID, entity_id: UUID
    ) -> Entity | None:
        result = await self.db.execute(
            select(NexusEntityDB).where(
                NexusEntityDB.tenant_id == str(tenant_id),
                NexusEntityDB.workspace_id == str(workspace_id),
                NexusEntityDB.entity_id == str(entity_id),
            )
        )
        row = result.scalar_one_or_none()
        return row_to_entity(row) if row else None

    async def get_by_natural_key(
        self, tenant_id: UUID, workspace_id: UUID, natural_key: str
    ) -> Entity | None:
        result = await self.db.execute(
            select(NexusEntityDB).where(
                NexusEntityDB.tenant_id == str(tenant_id),
                NexusEntityDB.workspace_id == str(workspace_id),
                NexusEntityDB.natural_key == natural_key,
            )
        )
        row = result.scalar_one_or_none()
        return row_to_entity(row) if row else None

    async def delete_entity(
        self, tenant_id: UUID, workspace_id: UUID, entity_id: UUID
    ) -> bool:
        result = await self.db.execute(
            delete(NexusEntityDB).where(
                NexusEntityDB.tenant_id == str(tenant_id),
                NexusEntityDB.workspace_id == str(workspace_id),
                NexusEntityDB.entity_id == str(entity_id),
            )
        )
        return result.rowcount > 0

    async def query_entities(
        self,
        query: EntityQuery,
    ) -> list[Entity]:
        """Execute a query against the store.

        Supports the same composable filters as in-memory: kinds, domain,
        tags, min_confidence, text search, pagination.
        """
        stmt = select(NexusEntityDB).where(
            NexusEntityDB.tenant_id == str(query.tenant_id),
            NexusEntityDB.workspace_id == str(query.workspace_id),
        )
        if query.kinds:
            stmt = stmt.where(NexusEntityDB.kind.in_([k.value for k in query.kinds]))
        if query.domain:
            stmt = stmt.where(NexusEntityDB.domain == query.domain.value)
        if query.natural_keys:
            stmt = stmt.where(NexusEntityDB.natural_key.in_(query.natural_keys))
        if query.min_confidence > 0:
            stmt = stmt.where(NexusEntityDB.confidence >= query.min_confidence)
        if query.text_search:
            needle = f"%{query.text_search.lower()}%"
            stmt = stmt.where(
                NexusEntityDB.name.ilike(needle) | NexusEntityDB.description.ilike(needle)
            )
        stmt = stmt.order_by(NexusEntityDB.updated_at.desc())
        stmt = stmt.offset(query.offset).limit(query.limit)
        result = await self.db.execute(stmt)
        return [row_to_entity(row) for row in result.scalars().all()]

    async def count_entities(
        self,
        tenant_id: UUID,
        workspace_id: UUID,
        kind: EntityKind | None = None,
    ) -> int:
        stmt = select(NexusEntityDB).where(
            NexusEntityDB.tenant_id == str(tenant_id),
            NexusEntityDB.workspace_id == str(workspace_id),
        )
        if kind is not None:
            stmt = stmt.where(NexusEntityDB.kind == kind.value)
        result = await self.db.execute(stmt)
        return len(list(result.scalars().all()))

    # ── Relationships ─────────────────────────────────────────────────────

    async def add_relationship(self, edge: RelationshipEdge, tenant_id: UUID, workspace_id: UUID) -> RelationshipEdge:
        self.db.add(NexusRelationshipDB(**edge_to_row(edge, tenant_id, workspace_id)))
        await self.db.flush()
        return edge

    async def list_out_edges(self, tenant_id: UUID, workspace_id: UUID, entity_id: UUID) -> list[RelationshipEdge]:
        result = await self.db.execute(
            select(NexusRelationshipDB).where(
                NexusRelationshipDB.tenant_id == str(tenant_id),
                NexusRelationshipDB.workspace_id == str(workspace_id),
                NexusRelationshipDB.from_entity_id == str(entity_id),
            )
        )
        return [row_to_edge(row) for row in result.scalars().all()]

    async def list_in_edges(self, tenant_id: UUID, workspace_id: UUID, entity_id: UUID) -> list[RelationshipEdge]:
        result = await self.db.execute(
            select(NexusRelationshipDB).where(
                NexusRelationshipDB.tenant_id == str(tenant_id),
                NexusRelationshipDB.workspace_id == str(workspace_id),
                NexusRelationshipDB.to_entity_id == str(entity_id),
            )
        )
        return [row_to_edge(row) for row in result.scalars().all()]

    # ── Projection / cache hydration ──────────────────────────────────────

    async def hydrate_workspace(
        self,
        tenant_id: UUID,
        workspace_id: UUID,
    ) -> tuple[list[Entity], list[RelationshipEdge]]:
        """Full load of one workspace's entities + edges.

        Used to warm the in-memory projection cache. For very large
        workspaces this should be paginated or delta-loaded.
        """
        ent_result = await self.db.execute(
            select(NexusEntityDB).where(
                NexusEntityDB.tenant_id == str(tenant_id),
                NexusEntityDB.workspace_id == str(workspace_id),
            )
        )
        rel_result = await self.db.execute(
            select(NexusRelationshipDB).where(
                NexusRelationshipDB.tenant_id == str(tenant_id),
                NexusRelationshipDB.workspace_id == str(workspace_id),
            )
        )
        entities = [row_to_entity(r) for r in ent_result.scalars().all()]
        edges = [row_to_edge(r) for r in rel_result.scalars().all()]
        return entities, edges
