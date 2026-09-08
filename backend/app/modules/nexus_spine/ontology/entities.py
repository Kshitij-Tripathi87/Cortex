"""Nexus Ontology — Entity Models with Identity, Provenance, Permissions, History.

Every entity in the world model carries:
- identity        (entity_id, natural_key)
- tenant/workspace isolation (mandatory)
- source          (where the data came from)
- timestamp       (when it was created/last updated)
- confidence      (how certain we are about the data, 0.0-1.0)
- current state   (the present view)
- historical state (append-only change log)
- relationships   (typed edges to other entities)
- permissions     (who can read/write)
- provenance      (chain of custody)

The world model is the single substrate that Vanessa, the graph, the decision
memory, and the digital twin all read from.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.nexus_spine.ontology.core_types import (
    EntityDomain,
    EntityKind,
    RelationshipKind,
    domain_of,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ProvenanceRecord(BaseModel):
    """One step in an entity's chain of custody.

    Every mutation to an entity appends a ProvenanceRecord. This gives the
    system an immutable audit trail suitable for evidence retrieval, compliance
    review, and root-cause analysis.
    """

    model_config = ConfigDict(frozen=True)

    step_id: UUID = Field(default_factory=uuid4)
    actor: str = Field(description="User/agent/system identifier")
    action: str = Field(description="create | update | delete | import | derive")
    timestamp: datetime = Field(default_factory=_utc_now)
    source: str = Field(description="System/process that produced the change")
    reason: str | None = Field(default=None, description="Human-readable rationale")
    previous_hash: str | None = Field(default=None)
    new_hash: str | None = Field(default=None)
    metadata: Mapping[str, Any] = Field(default_factory=dict)


class PermissionGrant(BaseModel):
    """A single read/write permission grant on an entity.

    Permissions are scoped to (tenant, workspace, role). The combination of
    tenant + workspace is enforced via RLS at the DB layer; this model
    carries the higher-level (role-based) permissions.
    """

    model_config = ConfigDict(frozen=True)

    role: str = Field(description="Role granted access (e.g. 'analyst')")
    can_read: bool = True
    can_write: bool = False
    can_approve: bool = False
    granted_by: str = Field(description="Who granted the permission")
    granted_at: datetime = Field(default_factory=_utc_now)
    expires_at: datetime | None = Field(default=None)


class StateSnapshot(BaseModel):
    """A snapshot of an entity's state at a specific point in time.

    State snapshots form the historical state vector — every entity has one
    current snapshot and an append-only history. Snapshots are content-hashed
    so the truth-loop (forecast vs reality) can correlate predictions with
    actual world state.
    """

    model_config = ConfigDict(frozen=True)

    version: int = Field(ge=1)
    timestamp: datetime = Field(default_factory=_utc_now)
    state: Mapping[str, Any] = Field(default_factory=dict)
    state_hash: str = Field(description="Content hash of the canonicalized state")
    world_state_version: int = Field(
        ge=0, description="World-state version when snapshot was taken"
    )
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)


class RelationshipEdge(BaseModel):
    """A typed, directed edge from one entity to another.

    The world model's graph view is a collection of these edges. Every edge
    carries provenance + confidence so the system can reason about the
    reliability of the connection (e.g. "inferred from supply tender" vs
    "confirmed via direct integration").
    """

    model_config = ConfigDict(frozen=True)

    edge_id: UUID = Field(default_factory=uuid4)
    from_entity_id: UUID
    to_entity_id: UUID
    kind: RelationshipKind
    timestamp: datetime = Field(default_factory=_utc_now)
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    provenance: ProvenanceRecord | None = Field(default=None)
    attributes: Mapping[str, Any] = Field(default_factory=dict)


class Entity(BaseModel):
    """The base world-model entity.

    Subclasses specialize `state` for each kind (supplier state, order state,
    inventory state, etc.). All entities share the identity, provenance,
    history, and permission envelope defined here.
    """

    model_config = ConfigDict(frozen=False, validate_assignment=True)

    entity_id: UUID = Field(default_factory=uuid4)
    tenant_id: UUID
    workspace_id: UUID
    kind: EntityKind
    natural_key: str = Field(
        description="Stable, source-system identifier (e.g. SAP supplier code)"
    )
    name: str
    description: str = ""

    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    source: str = Field(description="System that produced this entity")

    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    confidence_reason: str | None = Field(default=None)

    state: Mapping[str, Any] = Field(default_factory=dict)
    state_history: list[StateSnapshot] = Field(default_factory=list)

    relationships_out: list[RelationshipEdge] = Field(default_factory=list)
    relationships_in: list[RelationshipEdge] = Field(default_factory=list)

    provenance: list[ProvenanceRecord] = Field(default_factory=list)
    permissions: list[PermissionGrant] = Field(default_factory=list)

    tags: list[str] = Field(default_factory=list)
    metadata: Mapping[str, Any] = Field(default_factory=dict)

    @field_validator("natural_key")
    @classmethod
    def _validate_natural_key(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("natural_key must be a non-empty string")
        return value.strip()

    @property
    def domain(self) -> EntityDomain:
        return domain_of(self.kind)

    @property
    def current_version(self) -> int:
        """The next version number to assign to a state update."""
        if not self.state_history:
            return 1
        return max(s.version for s in self.state_history) + 1

    def append_state_snapshot(
        self,
        new_state: Mapping[str, Any],
        world_state_version: int,
        state_hash: str,
        actor: str,
        action: str = "update",
        reason: str | None = None,
        confidence: float | None = None,
    ) -> StateSnapshot:
        """Append a new state snapshot to history (does NOT mutate current state)."""
        snapshot = StateSnapshot(
            version=self.current_version,
            state=dict(new_state),
            state_hash=state_hash,
            world_state_version=world_state_version,
            confidence=confidence if confidence is not None else self.confidence,
        )
        self.state_history.append(snapshot)
        self.state = dict(new_state)
        self.updated_at = _utc_now()
        self.provenance.append(
            ProvenanceRecord(
                actor=actor,
                action=action,
                source=self.source,
                reason=reason,
                new_hash=state_hash,
            )
        )
        return snapshot

    def add_relationship(self, edge: RelationshipEdge) -> None:
        """Register an outgoing relationship."""
        self.relationships_out.append(edge)

    def grant_permission(self, grant: PermissionGrant) -> None:
        self.permissions.append(grant)


class EntityQuery(BaseModel):
    """A query against the world model.

    Used by Vanessa's tool registry, the graph view, and the /v1/entities
    API. Filters are composable; pagination is required for large result sets.
    """

    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    workspace_id: UUID
    kinds: list[EntityKind] | None = Field(default=None)
    domain: EntityDomain | None = Field(default=None)
    natural_keys: list[str] | None = Field(default=None)
    tags: list[str] | None = Field(default=None)
    min_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    text_search: str | None = Field(default=None, description="Substring match on name/description")
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)


class EntityPage(BaseModel):
    """A paginated result set from an EntityQuery."""

    items: list[Entity]
    total: int
    limit: int
    offset: int
    has_more: bool
