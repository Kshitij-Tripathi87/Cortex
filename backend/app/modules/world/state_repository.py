"""State Repository — Persistence Layer for World State.

Program J (World State & Digital Twin) persistence architecture:
- world_states: Materialized state snapshots (queryable)
- world_state_events: Immutable event log (source of truth)
- world_snapshots: Periodic checkpoints for fast reconstruction
- world_versions: Version lineage tracking (provenance)
- world_metadata: Provenance, tags, and context

Design principles:
✓ Append-only (events and versions are never updated or deleted)
✓ Immutable (rows are frozen once committed)
✓ Replayable (state can be reconstructed from event log)
✓ Versioned (every state change creates a new version)
✓ Traceable (lineage tracked via parent_version_id)
✓ Boring repository (no domain projection logic, pure persistence)

Note: Python attribute `extra_metadata` maps to DB column `metadata` because
SQLAlchemy reserves the name `metadata` on the Declarative API.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, func, select
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.common.ids import uuid7
from app.infrastructure.database import Base
from app.modules.world.world_models import (
    StateMetadata,
    StateSummary,
    WorldSnapshot,
    WorldState,
)

_DB_METADATA = "metadata"

JSON_VARIANT = JSON().with_variant(JSONB, "postgresql")
ARRAY_VARIANT = JSON().with_variant(ARRAY(String), "postgresql")


# ─────────────────────────────────────────────────────────────────────────────
# Database Models
# ─────────────────────────────────────────────────────────────────────────────


class WorldStateDB(Base):
    """Materialized state at a point in time. Queryable, rebuildable from events."""

    __tablename__ = "world_states"

    state_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    world_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    graph_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    variables: Mapped[dict[str, Any]] = mapped_column(JSON_VARIANT, nullable=False, default=dict)
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(
        _DB_METADATA, JSON_VARIANT, nullable=False, default=dict
    )


class WorldStateEventDB(Base):
    """Immutable event log — the source of truth for state reconstruction.

    Events are append-only. State is derived by projecting events.
    Idempotency is enforced via idempotency_key for deduplication.
    """

    __tablename__ = "world_state_events"

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    world_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON_VARIANT, nullable=False, default=dict)
    caused_by_event_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), index=True
    )
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(
        _DB_METADATA, JSON_VARIANT, nullable=False, default=dict
    )


class WorldSnapshotDB(Base):
    """Periodic checkpoint of world state for fast reconstruction."""

    __tablename__ = "world_snapshots"

    snapshot_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    world_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    graph_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    variable_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_archive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(
        _DB_METADATA, JSON_VARIANT, nullable=False, default=dict
    )

    @classmethod
    def from_domain(cls, snapshot: WorldSnapshot) -> WorldSnapshotDB:
        return cls(
            snapshot_id=snapshot.snapshot_id,
            world_id=snapshot.world_id,
            workspace_id=snapshot.workspace_id,
            version=snapshot.version,
            graph_version=snapshot.graph_version,
            state_hash=snapshot.state_hash,
            variable_count=snapshot.variable_count,
            is_archive=False,
            created_by=snapshot.created_by,
            created_at=snapshot.created_at,
            extra_metadata=snapshot.metadata,
        )

    def to_domain(self) -> WorldSnapshot:
        return WorldSnapshot(
            snapshot_id=self.snapshot_id,
            world_id=self.world_id,
            workspace_id=self.workspace_id,
            version=self.version,
            graph_version=self.graph_version,
            state_hash=self.state_hash,
            variable_count=self.variable_count,
            created_by=self.created_by,
            created_at=self.created_at,
            metadata=self.extra_metadata,
        )


class WorldVersionDB(Base):
    """Version lineage — tracks each new state version and its provenance.

    Sequence number ensures monotonic ordering per (world_id, workspace_id).
    This prevents concurrent writes from creating duplicate or out-of-order versions.
    """

    __tablename__ = "world_versions"

    version_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    world_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    sequence_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    graph_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    parent_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="projection")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), index=True
    )
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(
        _DB_METADATA, JSON_VARIANT, nullable=False, default=dict
    )


class WorldMetadataDB(Base):
    """World provenance, tags, and context metadata."""

    __tablename__ = "world_metadata"

    metadata_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    world_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    graph_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    parent_world_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parent_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    tags: Mapped[list[str]] = mapped_column(ARRAY_VARIANT, nullable=False, default=list)
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(
        _DB_METADATA, JSON_VARIANT, nullable=False, default=dict
    )


# ─────────────────────────────────────────────────────────────────────────────
# Repository Class
# ─────────────────────────────────────────────────────────────────────────────


class StateRepository:
    """Repository for world state persistence operations.

    All write operations are append-only. There are no update or delete
    methods for events or versions — that is by design.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    # ─────────────────────────────────────────────────────────────────────────
    # World State (Materialized)
    # ─────────────────────────────────────────────────────────────────────────

    async def create(self, state: WorldState) -> WorldState:
        """Create the initial world state."""
        db_state = WorldStateDB(
            world_id=state.world_id,
            workspace_id=state.workspace_id,
            version=state.version,
            graph_version=state.graph_version,
            variables={vid: v.to_dict() for vid, v in state.variables.items()},
            state_hash=state.metadata.get("state_hash", ""),
            created_at=state.created_at,
            extra_metadata=state.metadata,
        )
        self.db.add(db_state)
        await self.db.flush()
        return state

    async def get(self, world_id: str, workspace_id: str, version: int | None = None) -> WorldState | None:
        """Get world state by ID and optional version.

        WORKSPACE ISOLATION: Query is scoped to both world_id and workspace_id.
        """
        if version is not None:
            stmt = select(WorldStateDB).where(
                WorldStateDB.world_id == world_id,
                WorldStateDB.workspace_id == workspace_id,
                WorldStateDB.version == version,
            )
        else:
            stmt = (
                select(WorldStateDB)
                .where(
                    WorldStateDB.world_id == world_id,
                    WorldStateDB.workspace_id == workspace_id,
                )
                .order_by(WorldStateDB.version.desc())
                .limit(1)
            )
        result = await self.db.execute(stmt)
        db_state = result.scalar_one_or_none()
        if not db_state:
            return None
        return self._to_domain(db_state)

    async def get_latest(self, workspace_id: str, world_id: str | None = None) -> WorldState | None:
        """Get the latest world state for a workspace."""
        stmt = select(WorldStateDB).where(WorldStateDB.workspace_id == workspace_id)
        if world_id is not None:
            stmt = stmt.where(WorldStateDB.world_id == world_id)
        stmt = stmt.order_by(WorldStateDB.version.desc()).limit(1)
        result = await self.db.execute(stmt)
        db_state = result.scalar_one_or_none()
        if not db_state:
            return None
        return self._to_domain(db_state)

    async def get_latest_for_update(
        self, workspace_id: str, world_id: str | None = None
    ) -> WorldState | None:
        """Get the latest world state with a row lock for atomic transaction sequencing."""
        stmt = select(WorldStateDB).where(WorldStateDB.workspace_id == workspace_id)
        if world_id is not None:
            stmt = stmt.where(WorldStateDB.world_id == world_id)
        stmt = stmt.order_by(WorldStateDB.version.desc()).limit(1)
        # Apply row-level lock if supported by database backend
        import contextlib

        with contextlib.suppress(Exception):
            stmt = stmt.with_for_update()
        result = await self.db.execute(stmt)
        db_state = result.scalar_one_or_none()
        if not db_state:
            return None
        return self._to_domain(db_state)

    async def list_versions(self, world_id: str, workspace_id: str) -> list[WorldState]:
        """List all versions of a world state, oldest first.

        WORKSPACE ISOLATION: Query is scoped to both world_id and workspace_id.
        """
        stmt = (
            select(WorldStateDB)
            .where(
                WorldStateDB.world_id == world_id,
                WorldStateDB.workspace_id == workspace_id,
            )
            .order_by(WorldStateDB.version)
        )
        result = await self.db.execute(stmt)
        return [self._to_domain(row) for row in result.scalars()]

    async def acquire_world_write_lock(self, workspace_id: str, world_id: str) -> None:
        """Serialize concurrent writers for a (workspace, world) pair.

        Uses a PostgreSQL advisory *transaction* lock keyed on the world. A
        writer blocks until the previous writer's transaction commits, then all
        of its subsequent reads are fresh statements that observe the committed
        data. This closes the phantom-insert race that a ``SELECT ... FOR UPDATE
        ORDER BY version DESC LIMIT 1`` cannot close: when a blocked reader is
        released it re-locks the same pre-existing row instead of re-running
        the ORDER BY/LIMIT, so two writers can still project the same version.

        The lock is released automatically when the transaction commits or
        rolls back. No-op on non-PostgreSQL backends (SQLite serializes writes
        at the connection level anyway).
        """
        if self.db.bind.dialect.name != "postgresql":
            return
        from sqlalchemy import text

        lock_key = f"{workspace_id}:{world_id}"
        await self.db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
            {"lock_key": lock_key},
        )

    async def store_version(
        self,
        state: WorldState,
        event_id: str | None = None,
        parent_version_id: str | None = None,
        source: str = "projection",
    ) -> str:
        """Append a new version of a world state with monotonically increasing sequence number.

        Returns the version_id (UUID) of the newly created version.

        CONCURRENCY SAFETY: Writers for a (world_id, workspace_id) are
        serialized by :meth:`acquire_world_write_lock`, which the caller holds
        for the duration of its transaction. Sequence numbers are therefore
        monotonic per (world_id, workspace_id) with no retries required. The
        UNIQUE(world_id, workspace_id, sequence_number) and
        UNIQUE(world_id, workspace_id, version) constraints remain as backstops.
        """
        db_state = WorldStateDB(
            world_id=state.world_id,
            workspace_id=state.workspace_id,
            version=state.version,
            graph_version=state.graph_version,
            variables={vid: v.to_dict() for vid, v in state.variables.items()},
            state_hash=state.metadata.get("state_hash", ""),
            created_at=state.created_at,
            extra_metadata=state.metadata,
        )
        self.db.add(db_state)

        # Genesis (version 1) carries no sequence number; every subsequent
        # version takes max(sequence_number) + 1. The advisory write lock held
        # by the caller makes this read-then-insert safe.
        sequence_number: int | None = None
        if source != "genesis":
            max_seq_stmt = (
                select(func.max(WorldVersionDB.sequence_number))
                .where(
                    WorldVersionDB.world_id == state.world_id,
                    WorldVersionDB.workspace_id == state.workspace_id,
                )
            )
            max_seq_result = await self.db.execute(max_seq_stmt)
            sequence_number = (max_seq_result.scalar() or 0) + 1

        version_id = str(uuid7())
        db_version = WorldVersionDB(
            version_id=version_id,
            world_id=state.world_id,
            workspace_id=state.workspace_id,
            version=state.version,
            sequence_number=sequence_number,
            graph_version=state.graph_version,
            state_hash=state.metadata.get("state_hash", ""),
            event_id=event_id,
            parent_version_id=parent_version_id,
            source=source,
            created_at=state.created_at,
            extra_metadata=state.metadata,
        )
        self.db.add(db_version)
        await self.db.flush()
        return version_id

    async def get_version_id(self, world_id: str, workspace_id: str, version: int) -> str | None:
        """Get the version_id (UUID) for a given world and version.

        WORKSPACE ISOLATION: Query is scoped to both world_id and workspace_id.
        """
        stmt = select(WorldVersionDB.version_id).where(
            WorldVersionDB.world_id == world_id,
            WorldVersionDB.workspace_id == workspace_id,
            WorldVersionDB.version == version,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_version_by_event_id(self, event_id: str, workspace_id: str) -> WorldVersionDB | None:
        """Get the version lineage record associated with a given event ID.

        WORKSPACE ISOLATION: Query is scoped to workspace_id.
        """
        stmt = select(WorldVersionDB).where(
            WorldVersionDB.event_id == event_id,
            WorldVersionDB.workspace_id == workspace_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def append_event(
        self,
        world_id: str,
        workspace_id: str,
        entity_type: str,
        entity_id: str,
        event_type: str,
        payload: dict[str, Any],
        event_id: str | None = None,
        caused_by_event_id: str | None = None,
        occurred_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> str:
        """Append an event to the event log. Returns the event_id.

        Append-only: there is no update or delete for events.
        Idempotency key is used to deduplicate external event submissions.
        """
        evt_id = event_id or str(uuid7())
        db_event = WorldStateEventDB(
            event_id=evt_id,
            world_id=world_id,
            workspace_id=workspace_id,
            entity_type=entity_type,
            entity_id=entity_id,
            event_type=event_type,
            payload=payload,
            caused_by_event_id=caused_by_event_id,
            idempotency_key=idempotency_key,
            occurred_at=occurred_at or datetime.now(UTC),
            extra_metadata=metadata or {},
        )
        self.db.add(db_event)
        await self.db.flush()
        return evt_id

    async def get_events(
        self,
        world_id: str,
        workspace_id: str,
        since: datetime | None = None,
        until: datetime | None = None,
        entity_type: str | None = None,
        event_type: str | None = None,
        limit: int | None = None,
    ) -> list[WorldStateEventDB]:
        """Get events for a world, ordered by occurred_at.

        WORKSPACE ISOLATION: Query is scoped to both world_id and workspace_id.
        """
        stmt = (
            select(WorldStateEventDB)
            .where(
                WorldStateEventDB.world_id == world_id,
                WorldStateEventDB.workspace_id == workspace_id,
            )
            .order_by(WorldStateEventDB.occurred_at)
        )
        if since is not None:
            stmt = stmt.where(WorldStateEventDB.occurred_at >= since)
        if until is not None:
            stmt = stmt.where(WorldStateEventDB.occurred_at <= until)
        if entity_type is not None:
            stmt = stmt.where(WorldStateEventDB.entity_type == entity_type)
        if event_type is not None:
            stmt = stmt.where(WorldStateEventDB.event_type == event_type)
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars())

    async def get_event(self, event_id: str, workspace_id: str) -> WorldStateEventDB | None:
        """Get a specific event by ID.

        WORKSPACE ISOLATION: Query is scoped to workspace_id.
        """
        stmt = select(WorldStateEventDB).where(
            WorldStateEventDB.event_id == event_id,
            WorldStateEventDB.workspace_id == workspace_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_event_by_idempotency_key(
        self,
        world_id: str,
        workspace_id: str,
        idempotency_key: str,
    ) -> WorldStateEventDB | None:
        """Find an event by its idempotency key within a specific world/workspace.

        WORKSPACE ISOLATION: Idempotency lookup is scoped to both world_id and workspace_id,
        matching the UNIQUE constraint: (world_id, workspace_id, idempotency_key).
        This prevents cross-world idempotency key collisions.
        """
        stmt = (
            select(WorldStateEventDB)
            .where(
                WorldStateEventDB.world_id == world_id,
                WorldStateEventDB.workspace_id == workspace_id,
                WorldStateEventDB.idempotency_key == idempotency_key,
            )
            .order_by(WorldStateEventDB.occurred_at.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    # ─────────────────────────────────────────────────────────────────────────
    # Snapshots
    # ─────────────────────────────────────────────────────────────────────────

    async def store_snapshot(
        self,
        snapshot: WorldSnapshot,
    ) -> WorldSnapshot:
        """Store a snapshot checkpoint."""
        db_snapshot = WorldSnapshotDB.from_domain(snapshot)
        self.db.add(db_snapshot)
        await self.db.flush()
        return snapshot

    async def get_snapshot(self, snapshot_id: str, workspace_id: str) -> WorldSnapshot | None:
        """Get a specific snapshot.

        WORKSPACE ISOLATION: Query is scoped to workspace_id.
        """
        stmt = select(WorldSnapshotDB).where(
            WorldSnapshotDB.snapshot_id == snapshot_id,
            WorldSnapshotDB.workspace_id == workspace_id,
        )
        result = await self.db.execute(stmt)
        db_snapshot = result.scalar_one_or_none()
        return db_snapshot.to_domain() if db_snapshot else None

    async def get_latest_snapshot(
        self, world_id: str, workspace_id: str, include_archive: bool = False
    ) -> WorldSnapshot | None:
        """Get the latest non-archive snapshot for a world.

        WORKSPACE ISOLATION: Query is scoped to both world_id and workspace_id.
        """
        stmt = (
            select(WorldSnapshotDB)
            .where(
                WorldSnapshotDB.world_id == world_id,
                WorldSnapshotDB.workspace_id == workspace_id,
            )
            .order_by(WorldSnapshotDB.version.desc())
            .limit(1)
        )
        if not include_archive:
            stmt = stmt.where(WorldSnapshotDB.is_archive.is_(False))
        result = await self.db.execute(stmt)
        db_snapshot = result.scalar_one_or_none()
        return db_snapshot.to_domain() if db_snapshot else None

    # ─────────────────────────────────────────────────────────────────────────
    # Versions (Lineage)
    # ─────────────────────────────────────────────────────────────────────────

    async def get_version(self, world_id: str, workspace_id: str, version: int) -> WorldVersionDB | None:
        """Get a specific world version.

        WORKSPACE ISOLATION: Query is scoped to both world_id and workspace_id.
        """
        stmt = select(WorldVersionDB).where(
            WorldVersionDB.world_id == world_id,
            WorldVersionDB.workspace_id == workspace_id,
            WorldVersionDB.version == version,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_versions(self, world_id: str, workspace_id: str) -> list[WorldVersionDB]:
        """Get all versions for a world, oldest first.

        WORKSPACE ISOLATION: Query is scoped to both world_id and workspace_id.
        """
        stmt = (
            select(WorldVersionDB)
            .where(
                WorldVersionDB.world_id == world_id,
                WorldVersionDB.workspace_id == workspace_id,
            )
            .order_by(WorldVersionDB.version)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars())

    # ─────────────────────────────────────────────────────────────────────────
    # Metadata
    # ─────────────────────────────────────────────────────────────────────────

    async def store_metadata(self, metadata: StateMetadata) -> StateMetadata:
        """Store world state metadata."""
        db_metadata = WorldMetadataDB(
            metadata_id=str(uuid7()),
            workspace_id=metadata.workspace_id,
            world_id=metadata.world_id,
            version=metadata.version,
            graph_version=metadata.graph_version,
            source=metadata.source,
            parent_world_id=metadata.parent_world_id,
            parent_version=metadata.parent_version,
            created_at=metadata.created_at,
            tags=metadata.tags,
            extra_metadata=metadata.metadata,
        )
        self.db.add(db_metadata)
        await self.db.flush()
        return metadata

    async def get_metadata(self, world_id: str, workspace_id: str, version: int | None = None) -> StateMetadata | None:
        """Get world state metadata.

        WORKSPACE ISOLATION: Query is scoped to both world_id and workspace_id.
        """
        if version is not None:
            stmt = select(WorldMetadataDB).where(
                WorldMetadataDB.world_id == world_id,
                WorldMetadataDB.workspace_id == workspace_id,
                WorldMetadataDB.version == version,
            )
        else:
            stmt = (
                select(WorldMetadataDB)
                .where(
                    WorldMetadataDB.world_id == world_id,
                    WorldMetadataDB.workspace_id == workspace_id,
                )
                .order_by(WorldMetadataDB.version.desc())
                .limit(1)
            )
        result = await self.db.execute(stmt)
        db_metadata = result.scalar_one_or_none()
        if not db_metadata:
            return None
        return StateMetadata(
            workspace_id=db_metadata.workspace_id,
            world_id=db_metadata.world_id,
            version=db_metadata.version,
            graph_version=db_metadata.graph_version,
            source=db_metadata.source,
            parent_world_id=db_metadata.parent_world_id,
            parent_version=db_metadata.parent_version,
            created_at=db_metadata.created_at,
            tags=db_metadata.tags,
            metadata=db_metadata.extra_metadata,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Summaries (Listing/Querying)
    # ─────────────────────────────────────────────────────────────────────────

    async def get_workspace_states(self, workspace_id: str) -> list[StateSummary]:
        """Get all world states for a workspace as summaries (latest version per world)."""
        stmt = (
            select(WorldStateDB)
            .where(WorldStateDB.workspace_id == workspace_id)
            .order_by(WorldStateDB.world_id, WorldStateDB.version.desc())
        )
        result = await self.db.execute(stmt)

        seen_worlds: set[str] = set()
        summaries = []
        for db_state in result.scalars():
            if db_state.world_id in seen_worlds:
                continue
            seen_worlds.add(db_state.world_id)

            domain_state = self._to_domain(db_state)
            variables_by_type: dict[str, int] = {}
            for var in domain_state.variables.values():
                vtype = (
                    var.variable_type.value
                    if hasattr(var.variable_type, "value")
                    else str(var.variable_type)
                )
                variables_by_type[vtype] = variables_by_type.get(vtype, 0) + 1

            entities = {var.entity_id for var in domain_state.variables.values()}

            summaries.append(
                StateSummary(
                    workspace_id=domain_state.workspace_id,
                    world_id=domain_state.world_id,
                    version=domain_state.version,
                    graph_version=domain_state.graph_version,
                    variable_count=len(domain_state.variables),
                    variables_by_type=variables_by_type,
                    entities_with_state=len(entities),
                    last_transition_at=domain_state.created_at,
                )
            )
        return summaries

    # ─────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _to_domain(self, db_state: WorldStateDB) -> WorldState:
        """Convert a DB row to a domain WorldState."""
        from app.modules.world.world_models import StateVariable, StateVariableType

        variables = {}
        for vid, vdata in db_state.variables.items():
            variables[vid] = StateVariable(
                variable_id=vid,
                variable_type=StateVariableType(vdata["variable_type"]),
                entity_id=vdata["entity_id"],
                entity_type=vdata["entity_type"],
                value=vdata["value"],
                unit=vdata.get("unit"),
                metadata=vdata.get("metadata", {}),
            )
        return WorldState(
            world_id=db_state.world_id,
            workspace_id=db_state.workspace_id,
            version=db_state.version,
            graph_version=db_state.graph_version,
            variables=variables,
            created_at=db_state.created_at,
            metadata=db_state.extra_metadata,
        )
