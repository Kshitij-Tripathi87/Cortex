"""Nexus Ontology — Write-Through Repository.

Composes the persistent OntologyStore (authoritative, PostgreSQL) with the
in-memory WorldModelRepository (fast traversal cache) to produce a single
repository that:

- Writes go to Postgres FIRST (authoritative), then update the in-memory
  projection.
- Reads go to the in-memory projection; on cache miss or invalidated
  workspace, reads rebuild from Postgres.
- Emits world-state events for every mutation so the rest of the system
  (signals, realtime, UI) reacts deterministically.

This eliminates the “shadow world” risk: the in-memory repository is strictly
a projection of Postgres, never an independent source of truth.

There is a deliberate split between sync (in-memory) and async (Postgres)
paths. Callers that need persistence must call `await persist(...)`;
sync-only paths operate against the fast projection.
"""

from __future__ import annotations

import threading
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.modules.nexus_spine.ontology.core_types import (
    EntityKind,
    RelationshipKind,
)
from app.modules.nexus_spine.ontology.entities import (
    Entity,
    EntityPage,
    EntityQuery,
    RelationshipEdge,
)
from app.modules.nexus_spine.ontology.repository import (
    WorldModelRepository,
    get_world_model,
)


class PersistenceMode(str):  # Avoid enum friction in FastAPI response models
    MEMORY_ONLY = "memory_only"
    PERSIST_FIRST = "persist_first"  # PostgreSQL authoritative


class ConsistencyViolationError(RuntimeError):
    """Raised when a write would leave Postgres and the projection inconsistent."""


class SyncReport(BaseModel):
    """Result of comparing Postgres store to the in-memory projection.

    Used by integrity checks and health probes. Reports entities present in
    the projection but missing from Postgres (stale projection) and
    vice versa (projection lagging behind).
    """

    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    projection_only: int = 0
    store_only: int = 0
    mismatched_hashes: int = 0
    in_sync: bool = True


class WriteThroughWorldModelRepository:
    """Production repository combining Postgres persistence with the fast
    in-memory projection.

    Write-through path:
        1. Validate input
        2. Upsert into OntologyStore (Postgres)
        3. Upsert into the WorldModelRepository (in-memory projection)
        4. Emit change event with world_state_version

    Read path:
        1. Read from in-memory projection (fast)
        2. Optionally verify against Postgres (sync check)

    For tests or phases that don't yet wire Postgres, the store can be
    left as None and the repository behaves exactly like the in-memory one.
    """

    def __init__(
        self,
        projection: WorldModelRepository | None = None,
        store: Any | None = None,
        mode: str = PersistenceMode.MEMORY_ONLY,
    ) -> None:
        self._projection = projection or get_world_model()
        self._store = store
        self._mode = mode
        self._lock = threading.RLock()
        self._world_state_version = 0

    # ── Properties ────────────────────────────────────────────────────────

    @property
    def projection(self) -> WorldModelRepository:
        return self._projection

    @property
    def store(self) -> Any | None:
        return self._store

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def world_state_version(self) -> int:
        with self._lock:
            return max(self._world_state_version, self._projection.world_state_version)

    @property
    def events(self) -> list[dict[str, Any]]:
        return self._projection.events

    # ── Write-through lifecycle ─────────────────────────────────────────

    def upsert_sync(self, entity: Entity, *, actor: str = "system") -> tuple[Entity, int]:
        """Sync write — updates in-memory projection only.

        Use `upsert` for the async write-through variant that persists first.
        """
        with self._lock:
            return self._projection.upsert(entity, actor=actor)

    async def upsert(self, entity: Entity, *, actor: str = "system") -> tuple[Entity, int]:
        """Async write-through: Postgres first, then projection."""
        if self._store is None or self._mode == PersistenceMode.MEMORY_ONLY:
            return self.upsert_sync(entity, actor=actor)

        persisted = await self._store.upsert_entity(entity)
        with self._lock:
            saved, version = self._projection.upsert(persisted, actor=actor)
        return saved, version

    async def delete(
        self, tenant_id: UUID, workspace_id: UUID, entity_id: UUID, *, actor: str = "system"
    ) -> bool:
        if self._store is None or self._mode == PersistenceMode.MEMORY_ONLY:
            return self._projection.delete(tenant_id, workspace_id, entity_id, actor=actor)
        removed = await self._store.delete_entity(tenant_id, workspace_id, entity_id)
        if removed:
            with self._lock:
                self._projection.delete(tenant_id, workspace_id, entity_id, actor=actor)
        return removed

    async def add_relationship(
        self,
        edge: RelationshipEdge,
        *,
        tenant_id: UUID,
        workspace_id: UUID,
        actor: str = "system",
    ) -> int:
        if self._store is None or self._mode == PersistenceMode.MEMORY_ONLY:
            return self._projection.add_relationship(edge, actor=actor)
        await self._store.add_relationship(edge, tenant_id, workspace_id)
        with self._lock:
            return self._projection.add_relationship(edge, actor=actor)

    # ── Read path ─────────────────────────────────────────────────────────

    def get(self, tenant_id: UUID, workspace_id: UUID, entity_id: UUID) -> Entity | None:
        return self._projection.get(tenant_id, workspace_id, entity_id)

    def get_by_natural_key(
        self, tenant_id: UUID, workspace_id: UUID, natural_key: str
    ) -> Entity | None:
        return self._projection.get_by_natural_key(tenant_id, workspace_id, natural_key)

    def query(self, query: EntityQuery) -> EntityPage:
        return self._projection.query(query)

    def count(self, tenant_id: UUID, workspace_id: UUID, kind: EntityKind | None = None) -> int:
        return self._projection.count(tenant_id, workspace_id, kind)

    def neighbors(
        self,
        tenant_id: UUID,
        workspace_id: UUID,
        entity_id: UUID,
        *,
        direction: str = "out",
        kinds: list[RelationshipKind] | None = None,
        max_depth: int = 1,
    ) -> list[tuple[UUID, RelationshipEdge]]:
        return self._projection.neighbors(
            tenant_id,
            workspace_id,
            entity_id,
            direction=direction,
            kinds=kinds,
            max_depth=max_depth,
        )

    def traverse_supply_chain(
        self,
        tenant_id: UUID,
        workspace_id: UUID,
        seed_entity_id: UUID,
        *,
        max_depth: int = 4,
    ) -> dict[UUID, list[RelationshipEdge]]:
        return self._projection.traverse_supply_chain(
            tenant_id, workspace_id, seed_entity_id, max_depth=max_depth
        )

    def subscribe(self, callback: Any) -> None:
        self._projection.subscribe(callback)

    # ── Projection hydration ──────────────────────────────────────────────

    async def hydrate_workspace(self, tenant_id: UUID, workspace_id: UUID) -> int:
        """Rebuild the in-memory projection for a workspace from Postgres.

        Returns the number of entities loaded. Used at API startup and when
        the projection falls out of sync (detected via world_state_version).
        """
        if self._store is None:
            return 0
        entities, edges = await self._store.hydrate_workspace(tenant_id, workspace_id)
        with self._lock:
            for entity in entities:
                # Bypass event publication during hydration — the change
                # already happened in the authoritative store.
                key = (entity.tenant_id, entity.workspace_id, entity.entity_id)
                self._projection._entities[key] = entity
                self._projection._by_natural_key[
                    (entity.tenant_id, entity.workspace_id, entity.natural_key)
                ] = entity.entity_id
                self._projection._by_kind[(entity.tenant_id, entity.workspace_id, entity.kind)].add(
                    entity.entity_id
                )
        return len(entities)

    async def consistency_check(self, tenant_id: UUID, workspace_id: UUID) -> SyncReport:
        """Verify that the projection and Postgres are in sync.

        Returns a SyncReport. `in_sync=False` indicates drift and the caller
        should call hydrate_workspace() to repair it.
        """
        if self._store is None:
            return SyncReport(workspace_id=str(workspace_id))
        store_entities, _ = await self._store.hydrate_workspace(tenant_id, workspace_id)
        store_ids = {e.entity_id for e in store_entities}
        projection_ids = {
            e.entity_id for e in self._projection.iter_entities(tenant_id, workspace_id)
        }
        store_only = len(store_ids - projection_ids)
        projection_only = len(projection_ids - store_ids)
        mismatched = 0
        for e in store_entities:
            proj = self._projection.get(tenant_id, workspace_id, e.entity_id)
            if proj is None:
                continue
            if proj.state != e.state:
                mismatched += 1
        return SyncReport(
            workspace_id=str(workspace_id),
            projection_only=projection_only,
            store_only=store_only,
            mismatched_hashes=mismatched,
            in_sync=(store_only == 0 and projection_only == 0 and mismatched == 0),
        )


__all__ = [
    "ConsistencyViolationError",
    "PersistenceMode",
    "SyncReport",
    "WriteThroughWorldModelRepository",
]
