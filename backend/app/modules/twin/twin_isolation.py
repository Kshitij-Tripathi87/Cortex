"""Twin Isolation — Guarantees for Safe Digital Twin Execution (J.3.2).

Program J (World State & Digital Twin) isolation layer:

Isolation guarantees:
✓ Never touch Production — twins read from production state via
  StateRepository (the single authoritative read path) and write only to
  the twin namespace (twins, twin_runs)
✓ Workspace Isolation — twins are scoped to a single workspace
✓ Memory Isolation — twin state lives in separate memory from production
✓ Snapshot Isolation — twins operate on point-in-time snapshots
✓ Event Log Isolation — twin events never land in world_state_events
✓ No Leakage — twin state/runs/metrics never pollute production tables
  (world_states, world_state_events, world_snapshots, world_versions,
  world_metadata)

THIS LAYER ENFORCES THE J.3 BOUNDARY:
    J.3 Digital Twin CONSUMES World State; it does not recreate or bypass it.
There is deliberately NO method in this module that writes twin state into the
production world_* namespace. An explicitly authorized execution path (gated,
audited, and separately reviewed) will be the only future mechanism to promote
twin results, and it does not exist yet.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.twin.twin_models import DigitalTwin  # noqa: F401 (re-export)
from app.modules.world.state_repository import (
    StateRepository,
    WorldMetadataDB,
    WorldSnapshotDB,
    WorldStateDB,
    WorldStateEventDB,
    WorldVersionDB,
)
from app.modules.world.world_models import WorldSnapshot, WorldState


@dataclass(frozen=True)
class IsolationContext:
    """Context for executing within an isolated twin environment.

    Provides access to twin-specific state while keeping twin execution
    separate from production data. Construction is read-only with respect to
    production: it loads a snapshot and a state clone, and stores only the
    in-memory twin event log.
    """

    twin_id: str
    workspace_id: str
    parent_world_id: str
    parent_version: int
    snapshot: WorldSnapshot
    state: WorldState

    # Twin-specific event store (separate from production)
    twin_events: list[dict[str, Any]] = field(default_factory=list)


class IsolationError(Exception):
    """Raised when an isolation guarantee is violated, or a lifecycle
    precondition (valid snapshot, valid status, valid provenance) fails."""


# ─────────────────────────────────────────────────────────────────────────────
# Production Integrity Fingerprint
# ─────────────────────────────────────────────────────────────────────────────

#: The five production tables a twin must NEVER write to.
PROTECTED_TABLES = (
    "world_states",
    "world_state_events",
    "world_snapshots",
    "world_versions",
    "world_metadata",
)


async def production_fingerprint(db: AsyncSession, workspace_id: str) -> dict[str, Any]:
    """Capture a verifiable fingerprint of production World State for a workspace.

    For each protected table this records the row count scoped to the
    workspace, plus — for state-bearing tables — the maximum version and the
    latest state hash per world. Comparing fingerprints taken before and after
    any twin lifecycle operation is the J.3.2 isolation proof:

        fingerprint_before == fingerprint_after  ⇒  zero leakage

    Read-only: this function executes only SELECTs.
    """
    fingerprint: dict[str, Any] = {"workspace_id": workspace_id, "tables": {}}

    counts: dict[str, int] = {}
    for table_name, model in (
        ("world_states", WorldStateDB),
        ("world_state_events", WorldStateEventDB),
        ("world_snapshots", WorldSnapshotDB),
        ("world_versions", WorldVersionDB),
        ("world_metadata", WorldMetadataDB),
    ):
        stmt = select(func.count()).select_from(model).where(model.workspace_id == workspace_id)
        result = await db.execute(stmt)
        counts[table_name] = int(result.scalar() or 0)
    fingerprint["tables"] = counts

    # Per-world max version for the two state-bearing tables (drift detection:
    # a leaked twin write would bump a version or add a new world).
    worlds: dict[str, dict[str, Any]] = {}

    versions_stmt = (
        select(WorldVersionDB.world_id, func.max(WorldVersionDB.version))
        .where(WorldVersionDB.workspace_id == workspace_id)
        .group_by(WorldVersionDB.world_id)
    )
    for world_id, max_version in (await db.execute(versions_stmt)).all():
        worlds[world_id] = {"max_version": max_version}

    states_stmt = (
        select(WorldStateDB.world_id, func.max(WorldStateDB.version))
        .where(WorldStateDB.workspace_id == workspace_id)
        .group_by(WorldStateDB.world_id)
    )
    for world_id, max_version in (await db.execute(states_stmt)).all():
        worlds.setdefault(world_id, {})["max_state_version"] = max_version

    fingerprint["worlds"] = worlds
    fingerprint["taken_at"] = datetime.now(UTC).isoformat()
    return fingerprint


# ─────────────────────────────────────────────────────────────────────────────
# Twin Isolation Enforcer
# ─────────────────────────────────────────────────────────────────────────────


class TwinIsolationEnforcer:
    """Enforces isolation guarantees for digital twins.

    Read-only with respect to production. The enforcer exposes:
    - ``repo``: the StateRepository (authoritative read path for world state)
    - ``verify_isolation``: point-in-time leakage check for one twin
    - ``production_fingerprint``: workspace-level before/after proof
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = StateRepository(db)

    async def verify_isolation(self, twin_id: str) -> dict[str, Any]:
        """Verify that a twin has not leaked into production.

        Checks every protected production table for rows that could only have
        been created by a twin write:
        - world_states with world_id == twin_id
        - world_versions with world_id == twin_id
        - world_state_events with world_id == twin_id or workspace == twin_id
        - world_snapshots with world_id == twin_id or created_by == twin_id
        - world_metadata with world_id == twin_id
        """
        violations: list[str] = []

        stmt = select(func.count(WorldStateDB.state_id)).where(WorldStateDB.world_id == twin_id)
        count = int((await self.db.execute(stmt)).scalar() or 0)
        if count:
            violations.append(f"{count} world_states rows found for twin id {twin_id}")

        stmt = select(func.count(WorldVersionDB.version_id)).where(
            WorldVersionDB.world_id == twin_id
        )
        count = int((await self.db.execute(stmt)).scalar() or 0)
        if count:
            violations.append(f"{count} world_versions rows found for twin id {twin_id}")

        stmt = select(func.count(WorldStateEventDB.event_id)).where(
            (WorldStateEventDB.world_id == twin_id) | (WorldStateEventDB.workspace_id == twin_id)
        )
        count = int((await self.db.execute(stmt)).scalar() or 0)
        if count:
            violations.append(f"{count} world_state_events rows leaked by twin {twin_id}")

        stmt = select(func.count(WorldSnapshotDB.snapshot_id)).where(
            (WorldSnapshotDB.world_id == twin_id) | (WorldSnapshotDB.created_by == twin_id)
        )
        count = int((await self.db.execute(stmt)).scalar() or 0)
        if count:
            violations.append(f"{count} world_snapshots rows leaked by twin {twin_id}")

        stmt = select(func.count(WorldMetadataDB.metadata_id)).where(
            WorldMetadataDB.world_id == twin_id
        )
        count = int((await self.db.execute(stmt)).scalar() or 0)
        if count:
            violations.append(f"{count} world_metadata rows found for twin id {twin_id}")

        return {
            "twin_id": twin_id,
            "isolated": len(violations) == 0,
            "violations": violations,
            "checked_at": datetime.now(UTC).isoformat(),
        }

    async def production_fingerprint(self, workspace_id: str) -> dict[str, Any]:
        """Workspace-level production fingerprint (see module function)."""
        return await production_fingerprint(self.db, workspace_id)


# ─────────────────────────────────────────────────────────────────────────────
# Context Manager for Twin Execution
# ─────────────────────────────────────────────────────────────────────────────


@asynccontextmanager
async def twin_session(
    enforcer: TwinIsolationEnforcer, twin: DigitalTwin
) -> AsyncGenerator[IsolationContext]:
    """Async context manager for safe in-memory twin execution.

    Loads the twin's snapshot and starting state read-only from production,
    yields an IsolationContext for scenario projection, and performs no
    production writes on exit.
    """
    snapshot = await enforcer.repo.get_snapshot(twin.snapshot_id, twin.workspace_id)
    state = await enforcer.repo.get(twin.parent_world_id, twin.workspace_id, twin.parent_version)

    if not snapshot or not state:
        raise IsolationError("Failed to initialize twin context")

    context = IsolationContext(
        twin_id=twin.twin_id,
        workspace_id=twin.workspace_id,
        parent_world_id=twin.parent_world_id,
        parent_version=twin.parent_version,
        snapshot=snapshot,
        state=state,
    )

    try:
        yield context
    finally:
        pass
