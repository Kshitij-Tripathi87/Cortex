"""Nexus Ontology — In-Memory World Model Repository.

This is the operational source of truth for the world model. It supports:
- CRUD on entities (with tenant + workspace isolation enforced)
- Relationship management
- Query by kind, domain, natural key, tag, text search
- Graph traversal (BFS) with depth limits
- Content-hash state snapshots for evidence chain integration
- Change tracking via publish_event() — the realtime event fabric listens

The repository is in-memory for now (Phase A); persistence is added in
Phase H. This is intentional: world state needs to be queryable from many
components (graph, signals, Vanessa, decision memory) without DB round-trips
on every read.

All mutating operations emit a `nexus.world-state` event so the realtime
fabric and downstream consumers (signals engine, graph, UI) can react.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import threading
from collections import defaultdict
from collections.abc import Iterable, Iterator
from typing import Any
from uuid import UUID

from app.modules.nexus_spine.ontology.core_types import (
    ENTITY_KIND_TO_DOMAIN,
    EntityKind,
    RelationshipKind,
)
from app.modules.nexus_spine.ontology.entities import (
    Entity,
    EntityPage,
    EntityQuery,
    ProvenanceRecord,
    RelationshipEdge,
    StateSnapshot,
)


def canonical_state_hash(state: dict[str, Any]) -> str:
    """Compute a deterministic content hash of a state dict.

    Uses json canonicalization (sort_keys=True, separators=(",", ":"))
    so identical state always produces the same hash regardless of
    dict ordering.
    """
    canonical = json.dumps(state, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class WorldModelRepository:
    """Thread-safe in-memory world model repository.

    Indexes:
    - _entities: dict[(tenant_id, workspace_id, entity_id)] -> Entity
    - _by_natural_key: dict[(tenant_id, workspace_id, natural_key)] -> entity_id
    - _by_kind: dict[(tenant_id, workspace_id, kind)] -> set[entity_id]
    - _out_edges: dict[entity_id] -> list[RelationshipEdge]
    - _in_edges: dict[entity_id] -> list[RelationshipEdge]

    World state version counter increments on every successful mutation;
    callers capture the new version with the result so downstream consumers
    can correlate causal chains.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._entities: dict[tuple[UUID, UUID, UUID], Entity] = {}
        self._by_natural_key: dict[tuple[UUID, UUID, str], UUID] = {}
        self._by_kind: dict[tuple[UUID, UUID, EntityKind], set[UUID]] = defaultdict(set)
        self._by_tag: dict[tuple[UUID, UUID, str], set[UUID]] = defaultdict(set)
        self._out_edges: dict[UUID, list[RelationshipEdge]] = defaultdict(list)
        self._in_edges: dict[UUID, list[RelationshipEdge]] = defaultdict(list)
        self._world_state_version: int = 0
        self._published_events: list[dict[str, Any]] = []
        self._change_subscribers: list[callable] = []

    # ── Properties ────────────────────────────────────────────────────────

    @property
    def world_state_version(self) -> int:
        with self._lock:
            return self._world_state_version

    @property
    def events(self) -> list[dict[str, Any]]:
        """Return a copy of the published events (read-only)."""
        with self._lock:
            return list(self._published_events)

    # ── Subscription ──────────────────────────────────────────────────────

    def subscribe(self, callback: callable) -> None:
        """Register a callback to receive world-state change events."""
        with self._lock:
            self._change_subscribers.append(callback)

    # ── CRUD ───────────────────────────────────────────────────────────────

    def upsert(self, entity: Entity, *, actor: str = "system") -> tuple[Entity, int]:
        """Insert or update an entity. Returns (entity, new_world_state_version)."""
        with self._lock:
            self._world_state_version += 1
            new_version = self._world_state_version
            key = (entity.tenant_id, entity.workspace_id, entity.entity_id)
            existing = self._entities.get(key)

            # If this is an insert, record provenance
            if existing is None:
                entity.provenance.append(
                    ProvenanceRecord(
                        actor=actor,
                        action="create",
                        source=entity.source,
                        new_hash=canonical_state_hash(dict(entity.state)),
                    )
                )

            # Append a state snapshot whenever state changes
            if existing is None or existing.state != entity.state:
                snapshot = StateSnapshot(
                    version=entity.current_version,
                    state=dict(entity.state),
                    state_hash=canonical_state_hash(dict(entity.state)),
                    world_state_version=new_version,
                    confidence=entity.confidence,
                )
                entity.state_history.append(snapshot)

            entity.updated_at = entity.updated_at or entity.created_at
            self._entities[key] = entity
            self._by_natural_key[(entity.tenant_id, entity.workspace_id, entity.natural_key)] = (
                entity.entity_id
            )
            self._by_kind[(entity.tenant_id, entity.workspace_id, entity.kind)].add(
                entity.entity_id
            )
            for tag in entity.tags:
                self._by_tag[(entity.tenant_id, entity.workspace_id, tag)].add(entity.entity_id)

            self._publish_event(
                kind="WORLD_STATE_CHANGED",
                entity_id=str(entity.entity_id),
                entity_kind=entity.kind.value,
                action="upsert" if existing is None else "update",
                world_state_version=new_version,
                actor=actor,
            )
            return entity, new_version

    def get(
        self,
        tenant_id: UUID,
        workspace_id: UUID,
        entity_id: UUID,
    ) -> Entity | None:
        with self._lock:
            return self._entities.get((tenant_id, workspace_id, entity_id))

    def get_by_natural_key(
        self,
        tenant_id: UUID,
        workspace_id: UUID,
        natural_key: str,
    ) -> Entity | None:
        with self._lock:
            entity_id = self._by_natural_key.get((tenant_id, workspace_id, natural_key))
            if entity_id is None:
                return None
            return self._entities.get((tenant_id, workspace_id, entity_id))

    def delete(
        self, tenant_id: UUID, workspace_id: UUID, entity_id: UUID, *, actor: str = "system"
    ) -> bool:
        with self._lock:
            key = (tenant_id, workspace_id, entity_id)
            entity = self._entities.pop(key, None)
            if entity is None:
                return False
            self._by_natural_key.pop((tenant_id, workspace_id, entity.natural_key), None)
            self._by_kind[(tenant_id, workspace_id, entity.kind)].discard(entity_id)
            for tag in entity.tags:
                self._by_tag[(tenant_id, workspace_id, tag)].discard(entity_id)
            self._world_state_version += 1
            self._publish_event(
                kind="WORLD_STATE_CHANGED",
                entity_id=str(entity_id),
                entity_kind=entity.kind.value,
                action="delete",
                world_state_version=self._world_state_version,
                actor=actor,
            )
            return True

    # ── Query ──────────────────────────────────────────────────────────────

    def query(self, q: EntityQuery) -> EntityPage:
        with self._lock:
            candidates: Iterable[Entity]
            if q.kinds:
                candidate_ids: set[UUID] = set()
                for kind in q.kinds:
                    candidate_ids.update(
                        self._by_kind.get((q.tenant_id, q.workspace_id, kind), set())
                    )
                candidates = [
                    self._entities[(q.tenant_id, q.workspace_id, eid)] for eid in candidate_ids
                ]
            elif q.domain:
                candidate_ids: set[UUID] = set()
                for kind, dom in ENTITY_KIND_TO_DOMAIN.items():
                    if dom == q.domain:
                        candidate_ids.update(
                            self._by_kind.get((q.tenant_id, q.workspace_id, kind), set())
                        )
                candidates = [
                    self._entities[(q.tenant_id, q.workspace_id, eid)] for eid in candidate_ids
                ]
            elif q.natural_keys:
                candidates = []
                for nk in q.natural_keys:
                    eid = self._by_natural_key.get((q.tenant_id, q.workspace_id, nk))
                    if eid:
                        ent = self._entities.get((q.tenant_id, q.workspace_id, eid))
                        if ent:
                            candidates.append(ent)
            else:
                candidates = [
                    e
                    for (t, w, _), e in self._entities.items()
                    if t == q.tenant_id and w == q.workspace_id
                ]

            items = list(candidates)
            if q.tags:
                tag_set = set(q.tags)
                items = [e for e in items if tag_set.intersection(e.tags)]
            if q.min_confidence > 0.0:
                items = [e for e in items if e.confidence >= q.min_confidence]
            if q.text_search:
                needle = q.text_search.lower()
                items = [
                    e for e in items if needle in e.name.lower() or needle in e.description.lower()
                ]
            total = len(items)
            page = items[q.offset : q.offset + q.limit]
            return EntityPage(
                items=page,
                total=total,
                limit=q.limit,
                offset=q.offset,
                has_more=q.offset + q.limit < total,
            )

    def count(
        self,
        tenant_id: UUID,
        workspace_id: UUID,
        kind: EntityKind | None = None,
    ) -> int:
        with self._lock:
            if kind is not None:
                return len(self._by_kind.get((tenant_id, workspace_id, kind), set()))
            return sum(1 for (t, w, _) in self._entities if t == tenant_id and w == workspace_id)

    # ── Relationships ──────────────────────────────────────────────────────

    def add_relationship(
        self,
        edge: RelationshipEdge,
        *,
        actor: str = "system",
    ) -> int:
        with self._lock:
            self._out_edges[edge.from_entity_id].append(edge)
            self._in_edges[edge.to_entity_id].append(edge)
            self._world_state_version += 1
            self._publish_event(
                kind="WORLD_STATE_CHANGED",
                entity_id=str(edge.from_entity_id),
                entity_kind="relationship",
                action="add_relationship",
                world_state_version=self._world_state_version,
                actor=actor,
                edge_kind=edge.kind.value,
                to_entity_id=str(edge.to_entity_id),
            )
            return self._world_state_version

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
        """BFS traversal up to max_depth. Returns (target_entity_id, traversed_edge) pairs."""
        if max_depth < 1:
            return []
        results: list[tuple[UUID, RelationshipEdge]] = []
        visited: set[UUID] = set()
        frontier: list[tuple[UUID, int]] = [(entity_id, 0)]
        with self._lock:
            while frontier:
                current, depth = frontier.pop(0)
                if current in visited:
                    continue
                visited.add(current)
                if depth >= max_depth:
                    continue
                edges = (
                    self._out_edges.get(current, [])
                    if direction in ("out", "both")
                    else self._in_edges.get(current, [])
                )
                if direction == "both":
                    edges = list(edges) + list(self._in_edges.get(current, []))
                for edge in edges:
                    if kinds and edge.kind not in kinds:
                        continue
                    target = edge.to_entity_id if direction != "in" else edge.from_entity_id
                    if target not in visited:
                        results.append((target, edge))
                        frontier.append((target, depth + 1))
        return results

    def traverse_supply_chain(
        self,
        tenant_id: UUID,
        workspace_id: UUID,
        seed_entity_id: UUID,
        *,
        max_depth: int = 4,
    ) -> dict[UUID, list[RelationshipEdge]]:
        """Return all paths out from `seed_entity_id` up to `max_depth`.

        Used for blast-radius analysis: starting at a supplier, find all
        dependent orders/products/etc.
        """
        paths: dict[UUID, list[RelationshipEdge]] = defaultdict(list)
        visited: set[UUID] = {seed_entity_id}
        frontier: list[tuple[UUID, int]] = [(seed_entity_id, 0)]
        with self._lock:
            while frontier:
                current, depth = frontier.pop(0)
                if depth >= max_depth:
                    continue
                for edge in self._out_edges.get(current, []):
                    if edge.to_entity_id not in visited:
                        visited.add(edge.to_entity_id)
                        paths[edge.to_entity_id].append(edge)
                        frontier.append((edge.to_entity_id, depth + 1))
        return dict(paths)

    # ── Iteration ──────────────────────────────────────────────────────────

    def iter_entities(
        self,
        tenant_id: UUID,
        workspace_id: UUID,
    ) -> Iterator[Entity]:
        with self._lock:
            for (t, w, _), entity in self._entities.items():
                if t == tenant_id and w == workspace_id:
                    yield entity

    # ── Internals ──────────────────────────────────────────────────────────

    def _publish_event(self, **payload: Any) -> None:
        event = {
            "timestamp": __import__("datetime")
            .datetime.now(__import__("datetime").UTC)
            .isoformat(),
            **payload,
        }
        self._published_events.append(event)
        for callback in self._change_subscribers:
            # Subscriber errors must not affect the world model — fail open
            # at the subscription boundary but never corrupt the source of truth.
            with contextlib.suppress(Exception):
                callback(event)
                # Subscriber errors must not affect the world model — fail open
                # at the subscription boundary but never corrupt the source of
                # truth.
                pass


_singleton: WorldModelRepository | None = None


def get_world_model() -> WorldModelRepository:
    """Return the process-wide singleton WorldModelRepository."""
    global _singleton
    if _singleton is None:
        _singleton = WorldModelRepository()
    return _singleton


def reset_world_model() -> None:
    """Reset the singleton — used by tests only."""
    global _singleton
    _singleton = None
