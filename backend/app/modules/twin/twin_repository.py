"""Twin Repository — Persistence Layer for Digital Twins (Program J.3.1).

J.3.1 Twin Lifecycle persistence architecture:
- twins: Twin identity + IMMUTABLE lineage + lifecycle status
- twin_runs: Append-only execution log (each run persists its final state)

Design principles (mirrors StateRepository):
✓ Boring repository (no domain projection logic, pure persistence)
✓ Mutation boundary twins are immutable EXCEPT lifecycle status.
  The repository exposes NO update path for lineage fields
  (parent_world_id, parent_version, snapshot_id, fork_of_twin_id,
  fork_from_run_id, created_at). Lineage is frozen at CREATE.
✓ Append-only runs: twin_runs rows are inserted once (completed) and
  never updated or deleted except by an explicit twin destroy.
✓ Isolation twin namespace only. This repository never writes to
  world_states, world_state_events, world_snapshots, world_versions,
  or world_metadata. Production state is READ via StateRepository.
✓ Workspace isolation: every read is scoped to workspace_id.

Note: Python attribute `extra_metadata` maps to DB column `metadata` because
SQLAlchemy reserves the name `metadata` on the Declarative API.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String, func, select
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.common.ids import uuid7
from app.infrastructure.database import Base
from app.modules.twin.twin_models import (
    TWIN_ENGINE_VERSION,
    TWIN_RNG_VERSION,
    TWIN_SIMULATION_VERSION,
    DigitalTwin,
    TwinRunStatus,
    TwinScenario,
    TwinStatus,
    compute_twin_lineage_hash,
)

_DB_METADATA = "metadata"

JSON_VARIANT = JSON().with_variant(JSONB, "postgresql")
ARRAY_VARIANT = JSON().with_variant(ARRAY(String), "postgresql")

# ─────────────────────────────────────────────────────────────────────────────
# Database Models
# ─────────────────────────────────────────────────────────────────────────────


class TwinDB(Base):
    """A digital twin: identity + immutable lineage + lifecycle status.

    Lineage columns (organization_id, parent_world_id, parent_version, snapshot_id,
    fork_of_twin_id, fork_from_run_id, created_at, lineage_hash) are
    written ONCE at creation and never mutated. The only mutable column is
    `status`, updated exclusively via :meth:`TwinRepository.transition_status`.
    """

    __tablename__ = "twins"

    twin_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    parent_world_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    parent_version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_id: Mapped[str] = mapped_column(String(36), nullable=False)
    fork_of_twin_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    fork_from_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    tags: Mapped[list[str]] = mapped_column(ARRAY_VARIANT, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=TwinStatus.READY.value)
    lineage_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(
        _DB_METADATA, JSON_VARIANT, nullable=False, default=dict
    )

    # Keep in sync with the lineage fields hashed by compute_twin_lineage_hash.
    LINEAGE_FIELDS = (
        "twin_id",
        "organization_id",
        "workspace_id",
        "parent_world_id",
        "parent_version",
        "snapshot_id",
        "fork_of_twin_id",
        "fork_from_run_id",
        "created_at",
    )

    @classmethod
    def from_domain(cls, twin: DigitalTwin) -> TwinDB:
        return cls(
            twin_id=twin.twin_id,
            organization_id=twin.organization_id,
            workspace_id=twin.workspace_id,
            parent_world_id=twin.parent_world_id,
            parent_version=twin.parent_version,
            snapshot_id=twin.snapshot_id,
            fork_of_twin_id=twin.fork_of_twin_id,
            fork_from_run_id=twin.fork_from_run_id,
            name=twin.name,
            description=twin.description,
            tags=list(twin.tags),
            status=twin.status.value if isinstance(twin.status, TwinStatus) else str(twin.status),
            lineage_hash=twin.lineage_hash or compute_twin_lineage_hash(twin),
            created_by=twin.created_by,
            created_at=twin.created_at,
            updated_at=twin.created_at,
            extra_metadata=twin.metadata,
        )

    def to_domain(self) -> DigitalTwin:
        # Normalize naive stored timestamps (SQLite) to aware-UTC, matching
        # the J.2.3 convention that domain datetimes are aware-UTC.
        created_at = self.created_at
        if created_at.tzinfo is None:
            from datetime import UTC

            created_at = created_at.replace(tzinfo=UTC)
        return DigitalTwin(
            twin_id=self.twin_id,
            organization_id=self.organization_id,
            workspace_id=self.workspace_id,
            parent_world_id=self.parent_world_id,
            parent_version=self.parent_version,
            snapshot_id=self.snapshot_id,
            fork_of_twin_id=self.fork_of_twin_id,
            fork_from_run_id=self.fork_from_run_id,
            name=self.name,
            status=TwinStatus(self.status),
            description=self.description,
            tags=list(self.tags or []),
            lineage_hash=self.lineage_hash,
            created_at=created_at,
            created_by=self.created_by,
            metadata=self.extra_metadata,
        )


class TwinRunDB(Base):
    """A completed scenario execution against a twin.

    Append-only: one row per successful run, carrying the run's final state
    (twin namespace — NOT production world_* tables) so forks and replay can
    reconstruct the exact twin state a run ended in.
    """

    __tablename__ = "twin_runs"

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    twin_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    scenario_id: Mapped[str] = mapped_column(String(64), nullable=False)
    scenario_type: Mapped[str] = mapped_column(String(64), nullable=False, default="custom")
    seed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=TwinRunStatus.SUCCEEDED.value
    )
    injected_events: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_VARIANT, nullable=False, default=list
    )
    final_variables: Mapped[dict[str, Any]] = mapped_column(
        JSON_VARIANT, nullable=False, default=dict
    )
    final_state_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    final_version: Mapped[int] = mapped_column(Integer, nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON_VARIANT, nullable=False, default=dict)
    comparison: Mapped[dict[str, Any] | None] = mapped_column(
        JSON_VARIANT, nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(
        _DB_METADATA, JSON_VARIANT, nullable=False, default=dict
    )

    def to_domain_dict(self) -> dict[str, Any]:
        """Serialize a run to its API/test representation."""
        return {
            "run_id": self.run_id,
            "twin_id": self.twin_id,
            "scenario_id": self.scenario_id,
            "scenario_type": self.scenario_type,
            "seed": self.seed,
            "status": self.status,
            "injected_events": list(self.injected_events or []),
            "final_variables": dict(self.final_variables or {}),
            "final_state_hash": self.final_state_hash,
            "final_version": self.final_version,
            "metrics": dict(self.metrics or {}),
            "comparison": dict(self.comparison) if self.comparison else None,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_values(
        cls,
        twin_id: str,
        workspace_id: str,
        scenario: TwinScenario,
        seed: int,
        injected_events: list[dict[str, Any]],
        final_variables: dict[str, Any],
        final_state_hash: str,
        final_version: int,
        metrics: dict[str, Any],
        comparison: dict[str, Any] | None,
        created_at: datetime,
        finished_at: datetime,
        rng_version: str = TWIN_RNG_VERSION,
        engine_version: str = TWIN_ENGINE_VERSION,
        simulation_version: str = TWIN_SIMULATION_VERSION,
    ) -> TwinRunDB:
        return cls(
            twin_id=twin_id,
            workspace_id=workspace_id,
            scenario_id=scenario.scenario_id,
            scenario_type=scenario.scenario_type.value,
            seed=seed,
            status=TwinRunStatus.SUCCEEDED.value,
            injected_events=injected_events,
            final_variables=final_variables,
            final_state_hash=final_state_hash,
            final_version=final_version,
            metrics=metrics,
            comparison=comparison,
            created_at=created_at,
            finished_at=finished_at,
            extra_metadata={
                "rng_version": rng_version,
                "engine_version": engine_version,
                "simulation_version": simulation_version,
            },
        )


# ─────────────────────────────────────────────────────────────────────────────
# Twin Event Sourcing (separate persistence boundary from production)
# ─────────────────────────────────────────────────────────────────────────────


class TwinEventDB(Base):
    """Individual event in a twin's execution log.

    Separate from production world_state_events. Each event belongs to a run.
    """

    __tablename__ = "twin_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    twin_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON_VARIANT, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(
        _DB_METADATA, JSON_VARIANT, nullable=False, default=dict
    )


class TwinVersionDB(Base):
    """Twin state version lineage — each run creates a new version.

    Mirrors world_versions but for the twin namespace. Append-only.
    """

    __tablename__ = "twin_versions"

    version_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    twin_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    variable_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(
        _DB_METADATA, JSON_VARIANT, nullable=False, default=dict
    )


class TwinStateDB(Base):
    """Twin state snapshot at a specific version.

    Stores the full variable state for replay and comparison.
    """

    __tablename__ = "twin_state"

    state_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    twin_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    variables: Mapped[dict[str, Any]] = mapped_column(JSON_VARIANT, nullable=False, default=dict)
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    graph_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(
        _DB_METADATA, JSON_VARIANT, nullable=False, default=dict
    )


class TwinResultDB(Base):
    """Aggregated run result for query/analysis.

    Separate from twin_runs (which stores raw execution data). This stores
    the computed KPIs and comparison for fast retrieval.
    """

    __tablename__ = "twin_results"

    result_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True, index=True)
    twin_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    scenario_id: Mapped[str] = mapped_column(String(64), nullable=False)
    final_state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    final_version: Mapped[int] = mapped_column(Integer, nullable=False)
    events_processed: Mapped[int] = mapped_column(Integer, nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON_VARIANT, nullable=False, default=dict)
    timeline: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_VARIANT, nullable=False, default=list
    )
    comparison: Mapped[dict[str, Any] | None] = mapped_column(JSON_VARIANT, nullable=True)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON_VARIANT, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(
        _DB_METADATA, JSON_VARIANT, nullable=False, default=dict
    )


# ─────────────────────────────────────────────────────────────────────────────
# Repository Class
# ─────────────────────────────────────────────────────────────────────────────


class TwinRepository:
    """Repository for digital twin persistence operations.

    MUTATION BOUNDARY (the J.3.1 invariant):
    - twins: create once; only `status` is ever updated afterwards.
    - twin_runs: insert once; no updates, no deletes (except twin destroy).

    There is intentionally no `update_lineage` or generic update method.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    # ─────────────────────────────────────────────────────────────────────────
    # Twins (create + read + status transitions)
    # ─────────────────────────────────────────────────────────────────────────

    async def create_twin(self, twin: DigitalTwin) -> DigitalTwin:
        """Persist a new twin. Lineage is frozen at this point (immutable)."""
        row = TwinDB.from_domain(twin)
        self.db.add(row)
        await self.db.flush()
        return twin

    async def get_twin(self, twin_id: str, workspace_id: str | None = None) -> DigitalTwin | None:
        """Get a twin by ID. Workspace-isolated when a workspace is given."""
        stmt = select(TwinDB).where(TwinDB.twin_id == twin_id)
        if workspace_id is not None:
            stmt = stmt.where(TwinDB.workspace_id == workspace_id)
        result = await self.db.execute(stmt)
        row = result.scalar_one_or_none()
        return row.to_domain() if row else None

    async def list_twins(
        self,
        workspace_id: str,
        status: TwinStatus | str | None = None,
        include_archived: bool = True,
    ) -> list[DigitalTwin]:
        """List twins for a workspace, oldest first.

        WORKSPACE ISOLATION: query is strictly scoped to workspace_id.
        """
        stmt = select(TwinDB).where(TwinDB.workspace_id == workspace_id)
        if status is not None:
            stmt = stmt.where(
                TwinDB.status == (status.value if isinstance(status, TwinStatus) else status)
            )
        elif not include_archived:
            stmt = stmt.where(TwinDB.status != TwinStatus.ARCHIVED.value)
        stmt = stmt.order_by(TwinDB.created_at)
        result = await self.db.execute(stmt)
        return [row.to_domain() for row in result.scalars()]

    async def transition_status(
        self, twin_id: str, workspace_id: str, new_status: TwinStatus
    ) -> bool:
        """The ONLY permitted mutation on a persistent twin record.

        Updates `status` and `updated_at` only. Returns True if a row was
        updated, False if the twin does not exist in that workspace.
        """
        from sqlalchemy import update as sa_update

        now = datetime.now(UTC)
        stmt = (
            sa_update(TwinDB)
            .where(TwinDB.twin_id == twin_id, TwinDB.workspace_id == workspace_id)
            .values(
                status=new_status.value if isinstance(new_status, TwinStatus) else str(new_status),
                updated_at=now,
            )
        )
        result = await self.db.execute(stmt)
        await self.db.flush()
        return (result.rowcount or 0) > 0  # type: ignore[attr-defined]

    async def delete_twin(self, twin_id: str, workspace_id: str) -> bool:
        """Permanently destroy a twin and all its runs (twin namespace only).

        This is the ONE destructive operation. It never touches production
        world_* tables. Returns True if the twin existed and was removed.
        """
        existing = await self.get_twin(twin_id, workspace_id)
        if existing is None:
            return False
        await self.delete_runs_for_twin(twin_id, workspace_id)
        from sqlalchemy import delete as sa_delete

        stmt = sa_delete(TwinDB).where(
            TwinDB.twin_id == twin_id, TwinDB.workspace_id == workspace_id
        )
        await self.db.execute(stmt)
        await self.db.flush()
        return True

    # ─────────────────────────────────────────────────────────────────────────
    # Twin Runs (append-only)
    # ─────────────────────────────────────────────────────────────────────────

    async def append_run(self, run: TwinRunDB) -> TwinRunDB:
        """Append a completed run. Append-only — no update or delete methods."""
        self.db.add(run)
        await self.db.flush()
        return run

    async def get_run(self, run_id: str, workspace_id: str) -> TwinRunDB | None:
        """Get a specific run by ID. Workspace-isolated."""
        stmt = select(TwinRunDB).where(
            TwinRunDB.run_id == run_id, TwinRunDB.workspace_id == workspace_id
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_runs(self, twin_id: str, workspace_id: str) -> list[TwinRunDB]:
        """Get all runs for a twin, in execution order (oldest first).

        WORKSPACE ISOLATION: query is scoped to both twin_id and workspace_id.
        """
        stmt = (
            select(TwinRunDB)
            .where(TwinRunDB.twin_id == twin_id, TwinRunDB.workspace_id == workspace_id)
            .order_by(TwinRunDB.created_at, TwinRunDB.run_id)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars())

    async def get_latest_run(self, twin_id: str, workspace_id: str) -> TwinRunDB | None:
        """Get the most recent run for a twin (used as fork/replay starting state)."""
        stmt = (
            select(TwinRunDB)
            .where(TwinRunDB.twin_id == twin_id, TwinRunDB.workspace_id == workspace_id)
            .order_by(TwinRunDB.created_at.desc(), TwinRunDB.run_id.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def count_runs(self, twin_id: str, workspace_id: str) -> int:
        """Count runs for a twin."""
        stmt = select(func.count(TwinRunDB.run_id)).where(
            TwinRunDB.twin_id == twin_id, TwinRunDB.workspace_id == workspace_id
        )
        result = await self.db.execute(stmt)
        return int(result.scalar() or 0)

    async def delete_runs_for_twin(self, twin_id: str, workspace_id: str) -> int:
        """Delete a twin's runs. Called ONLY by delete_twin (destroy)."""
        from sqlalchemy import delete as sa_delete

        stmt = sa_delete(TwinRunDB).where(
            TwinRunDB.twin_id == twin_id, TwinRunDB.workspace_id == workspace_id
        )
        result = await self.db.execute(stmt)
        await self.db.flush()
        return int(result.rowcount or 0)  # type: ignore[attr-defined]
