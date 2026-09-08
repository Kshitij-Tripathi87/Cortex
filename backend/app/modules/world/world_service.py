"""World State Service — Authoritative Orchestration Layer for State Transitions.

Program J (World State & Digital Twin) — J.2.3 Service & Persistence Contract.

This service is the SOLE write path for world state mutations in Cortex.
It coordinates:
1. Structural and domain validation (via validate_event and WorldValidator)
2. Idempotency enforcement (workspace_id + idempotency_key / source_event_id)
3. Atomic sequencing (monotonically increasing version per workspace/world)
4. Canonical projection (EVENT_PROJECTORS -> apply_transition)
5. State persistence & version lineage tracking
6. Checkpoint snapshot generation
7. Strict transactional integrity (all-or-nothing rollback)
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from app.modules.events.event_models import WorldEvent
from app.modules.events.event_validation import validate_event
from app.modules.world.state_projection import (
    apply_transition,
    create_initial_state,
    create_state_snapshot,
    project_event_to_transition,
)
from app.modules.world.state_repository import StateRepository
from app.modules.world.world_models import (
    StateSummary,
    StateVariable,
    WorldSnapshot,
    WorldState,
)
from app.modules.world.world_validation import WorldValidator


@dataclass(frozen=True)
class SubmitEventResult:
    """Result of submitting an event to the world state service."""

    event_id: str
    version_id: str
    version: int
    state: WorldState
    is_snapshot_created: bool = False
    is_duplicate: bool = False
    snapshot: WorldSnapshot | None = None


class WorldStateService:
    """Orchestrates the world state update pipeline.

    Invariants:
    - Zero direct domain mutation logic in service or repository
    - Deterministic transitions via canonical EVENT_PROJECTORS
    - Workspace isolation (no cross-workspace reads/writes)
    - Append-only event and version persistence
    - Atomic transaction boundary (rollback on any failure)
    - Monotonic version progression (1, 2, 3, ...)
    """

    def __init__(
        self,
        repository: StateRepository,
        validator: WorldValidator | None = None,
        snapshot_interval: int = 10,
    ) -> None:
        self.repository = repository
        self.validator = validator if validator is not None else WorldValidator()
        self.snapshot_interval = snapshot_interval

    @asynccontextmanager
    async def _transaction(self) -> AsyncGenerator[None]:
        """Manage transaction boundaries, handling nested transactions gracefully."""
        if self.repository.db.in_transaction():
            async with self.repository.db.begin_nested():
                yield
        else:
            async with self.repository.db.begin():
                yield

    async def initialize_world(
        self,
        workspace_id: str,
        world_id: str,
        graph_version: int = 1,
        initial_variables: dict[str, StateVariable] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WorldState:
        """Initialize genesis state (version 1) for a workspace/world."""
        async with self._transaction():
            # Serialize concurrent genesis creation for the same world
            await self.repository.acquire_world_write_lock(workspace_id, world_id)

            # Check if state already exists for this world
            existing = await self.repository.get(world_id, workspace_id)
            if existing is not None:
                raise ValueError(
                    f"World {world_id} already initialized at version {existing.version}"
                )

            state = create_initial_state(
                workspace_id=workspace_id,
                world_id=world_id,
                graph_version=graph_version,
                initial_variables=initial_variables or {},
            )
            if metadata:
                from dataclasses import replace

                state = replace(state, metadata={**state.metadata, **metadata})

            # Store version 1 (materializes state and records version lineage)
            await self.repository.store_version(
                state,
                event_id=None,
                parent_version_id=None,
                source="genesis",
            )

            # Create and store genesis checkpoint snapshot
            genesis_snapshot = create_state_snapshot(state, created_by="system_genesis")
            await self.repository.store_snapshot(genesis_snapshot)

            return state

    async def _resolve_duplicate(
        self, event: WorldEvent, eff_idempotency_key: str | None
    ) -> SubmitEventResult | None:
        """Resolve a previously processed idempotency key, if any.

        Returns the SubmitEventResult of the original submission (is_duplicate=True)
        or None when the key has not been processed yet.
        """
        if not eff_idempotency_key:
            return None
        existing_event = await self.repository.get_event_by_idempotency_key(
            world_id=event.world_id,
            workspace_id=event.workspace_id,
            idempotency_key=str(eff_idempotency_key),
        )
        if existing_event is None:
            return None
        version_record = await self.repository.get_version_by_event_id(
            existing_event.event_id,
            event.workspace_id,
        )
        existing_state = (
            await self.repository.get(
                existing_event.world_id,
                event.workspace_id,
                version=version_record.version,
            )
            if version_record
            else await self.repository.get_latest(event.workspace_id, event.world_id)
        )
        if existing_state is None:
            return None
        return SubmitEventResult(
            event_id=existing_event.event_id,
            version_id=version_record.version_id if version_record else "",
            version=existing_state.version,
            state=existing_state,
            is_snapshot_created=False,
            is_duplicate=True,
            snapshot=None,
        )

    async def submit_event(
        self,
        event: WorldEvent,
        *,
        idempotency_key: str | None = None,
        create_snapshot_if_interval: bool = True,
    ) -> SubmitEventResult:
        """Submit a single event to advance the world state.

        Orchestration pipeline:
            Acquire World Write Lock → Idempotency Check → Validate → Lock State → Re-Check Idempotency → Project → Apply → Append Event → Store Version → Snapshot

        Args:
            event: The world event to submit.
            idempotency_key: Optional key to enforce idempotent event processing.
            create_snapshot_if_interval: Whether to auto-create snapshot at configured intervals.

        Returns:
            SubmitEventResult with the new state and lineage IDs.

        Raises:
            ValueError: If validation fails, initial state missing, or projection fails.
        """
        async with self._transaction():
            # 1. Serialize concurrent writers for this world: acquire the
            # PostgreSQL advisory write lock BEFORE any read of the current
            # version, so the projected version and appended sequence are
            # strictly monotonic across concurrent submissions.
            await self.repository.acquire_world_write_lock(event.workspace_id, event.world_id)

            # 2. Resolve effective idempotency key
            eff_idempotency_key = (
                idempotency_key
                or event.metadata.get("idempotency_key")
                or event.metadata.get("source_event_id")
            )

            # 3. Idempotency check (fast path): if event with this key was already
            # processed, return existing state
            existing = await self._resolve_duplicate(event, eff_idempotency_key)
            if existing is not None:
                return existing

            # 4. Validate event structure, types, and domain payloads
            validate_event(event)

            # 5. Lock current state for the workspace/world to ensure atomic monotonic sequencing
            current_state = await self.repository.get_latest_for_update(
                workspace_id=event.workspace_id,
                world_id=event.world_id,
            )
            if current_state is None:
                raise ValueError(
                    f"No initial state found for workspace {event.workspace_id} in world {event.world_id}. "
                    "Please initialize world state before submitting events."
                )

            # 6. Re-check idempotency AFTER acquiring the world write lock. A concurrent
            # submission with the same key may have committed while we were
            # waiting on the lock; without this second check both transactions
            # would append the event and one would surface a unique-constraint
            # violation.
            existing = await self._resolve_duplicate(event, eff_idempotency_key)
            if existing is not None:
                return existing

            # 7. Project event to state transition
            transition = project_event_to_transition(current_state, event)
            if transition is None:
                raise ValueError(
                    f"Could not project event of type {event.event_type} (event_id={event.event_id})"
                )

            # 8. Apply transition to compute the new state (version incremented deterministically)
            new_state = apply_transition(current_state, transition)

            # 9. Append event to immutable log
            event_metadata = dict(event.metadata)
            if eff_idempotency_key:
                event_metadata["idempotency_key"] = str(eff_idempotency_key)

            event_id = await self.repository.append_event(
                world_id=event.world_id,
                workspace_id=event.workspace_id,
                entity_type=event.entity_type,
                entity_id=event.entity_id,
                event_type=event.event_type.value,
                payload=event.to_payload(),
                event_id=event.event_id,
                caused_by_event_id=event.caused_by_event_id,
                occurred_at=event.occurred_at,
                metadata=event_metadata,
                idempotency_key=eff_idempotency_key,
            )

            # 10. Persist new version & lineage
            parent_version_id = await self.repository.get_version_id(
                world_id=event.world_id,
                workspace_id=event.workspace_id,
                version=current_state.version,
            )
            version_id = await self.repository.store_version(
                new_state,
                event_id=event_id,
                parent_version_id=parent_version_id,
                source="submit_event",
            )

            # 10. Periodic checkpoint snapshotting
            is_snapshot_created = False
            snapshot: WorldSnapshot | None = None
            if (
                create_snapshot_if_interval
                and self.snapshot_interval > 0
                and (new_state.version % self.snapshot_interval == 0)
            ):
                snapshot = create_state_snapshot(new_state, created_by="system_interval")
                await self.repository.store_snapshot(snapshot)
                is_snapshot_created = True

            return SubmitEventResult(
                event_id=event_id,
                version_id=version_id,
                version=new_state.version,
                state=new_state,
                is_snapshot_created=is_snapshot_created,
                is_duplicate=False,
                snapshot=snapshot,
            )

    async def submit_events(
        self,
        events: list[WorldEvent],
        *,
        idempotency_key: str | None = None,
    ) -> list[SubmitEventResult]:
        """Submit a batch of events atomically within a single transaction."""
        results: list[SubmitEventResult] = []
        async with self._transaction():
            for idx, event in enumerate(events):
                event_key = f"{idempotency_key}_{idx}" if idempotency_key else None
                result = await self.submit_event(
                    event,
                    idempotency_key=event_key,
                )
                results.append(result)
        return results

    async def get_current_state(
        self,
        workspace_id: str,
        world_id: str | None = None,
    ) -> WorldState | None:
        """Get latest authoritative world state for a workspace."""
        return await self.repository.get_latest(workspace_id, world_id)

    async def get_state_at_version(
        self,
        world_id: str,
        workspace_id: str,
        version: int,
    ) -> WorldState | None:
        """Get state at a specific historical version."""
        return await self.repository.get(world_id, workspace_id, version)

    async def create_snapshot(
        self,
        workspace_id: str,
        world_id: str,
        created_by: str | None = None,
    ) -> WorldSnapshot:
        """Explicitly create and persist a checkpoint snapshot for current state."""
        async with self._transaction():
            current_state = await self.repository.get_latest(workspace_id, world_id)
            if current_state is None:
                raise ValueError(f"No state found for world {world_id} in workspace {workspace_id}")

            snapshot = create_state_snapshot(
                current_state, created_by=created_by or "user_explicit"
            )
            return await self.repository.store_snapshot(snapshot)

    # ─────────────────────────────────────────────────────────────────────────
    # History, Replay & Time Travel Orchestration
    # ─────────────────────────────────────────────────────────────────────────

    async def replay_from_genesis(
        self,
        world_id: str,
        workspace_id: str,
        initial_variables: dict[str, StateVariable] | None = None,
    ) -> Any:
        """Replay all historical events from genesis to reproduce the authoritative state."""
        from app.modules.world.state_history import ReplayEngine

        engine = ReplayEngine(self.repository)
        return await engine.replay_from_genesis(
            world_id, workspace_id, initial_variables=initial_variables
        )

    async def time_travel(
        self,
        world_id: str,
        workspace_id: str,
        target_version: int,
        initial_variables: dict[str, StateVariable] | None = None,
    ) -> Any:
        """Reconstruct state at any historical version using checkpoints + delta projection."""
        from app.modules.world.state_history import ReplayEngine

        engine = ReplayEngine(self.repository)
        return await engine.replay_to_version(
            world_id, workspace_id, target_version, initial_variables=initial_variables
        )

    async def compare_versions(
        self,
        world_id: str,
        workspace_id: str,
        from_version: int,
        to_version: int,
    ) -> Any:
        """Compare two historical versions and produce a semantic diff."""
        from app.modules.world.state_history import compare_states

        return await compare_states(
            self.repository, world_id, workspace_id, from_version, to_version
        )

    async def rollback_world(
        self,
        workspace_id: str,
        world_id: str,
        target_version: int,
        reason: str,
    ) -> Any:
        """Perform an append-only rollback restoring historical state variables as a new version."""
        from app.modules.world.state_history import RollbackEngine

        async with self._transaction():
            engine = RollbackEngine(self.repository)
            return await engine.rollback(
                workspace_id=workspace_id,
                world_id=world_id,
                target_version=target_version,
                reason=reason,
            )

    async def get_history(
        self,
        world_id: str,
        workspace_id: str,
        limit: int = 100,
    ) -> list[StateSummary]:
        """Get summary history of states for a world, newest first."""
        from app.modules.world.state_history import get_state_history

        return await get_state_history(self.repository, world_id, workspace_id, limit=limit)
