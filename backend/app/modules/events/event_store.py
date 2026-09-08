"""Event Store — Append-Only Log for World State Events.

Program J (World State & Digital Twin) event sourcing.

The event store is the source of truth for all state changes.
Key invariants (ADR-015):
✓ Append-only — events are never updated or deleted (I1)
✓ Ordered — events are returned in occurred_at order
✓ Verifiable — every event can be hashed and chain-verified (I2)
✓ Replayable — full history is preserved (I3, I9)

Public methods:
- append(): Add a new event to the log
- load(): Retrieve a specific event by ID
- stream(): Iterate events in order
- replay(): Reconstruct state at a point in time
- verify(): Validate event chain integrity

This module is the async, DB-coupled facade. Hashing logic lives in
`event_hashing`, replay logic lives in `event_replay`, and structural
validation lives in `event_validation`. Keeping this module thin (a
DB adapter) is what makes those pure modules testable in isolation and
reusable by the Twin and Simulation layers.

Storage: Uses the WorldStateEventDB model from
app.modules.world.state_repository. The event_store provides a clean,
typed interface over the DB layer.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.events.event_hashing import (
    compute_event_hash,
)
from app.modules.events.event_hashing import (
    verify_chain as _verify_chain_pure,
)
from app.modules.events.event_models import (
    WorldEvent,
    WorldEventType,
    deserialize_event,
)
from app.modules.events.event_replay import (
    ReplayOutcome,
    ReplayRecord,
)
from app.modules.events.event_replay import (
    replay_events as _replay_events_pure,
)
from app.modules.world.state_projection import (
    WorldState,
    create_initial_state,
)
from app.modules.world.state_repository import WorldStateEventDB


@dataclass(frozen=True)
class EventRecord:
    """A typed event record returned from the event store."""

    event: WorldEvent
    payload: dict[str, Any]
    event_hash: str
    prev_event_hash: str | None
    sequence: int


@dataclass(frozen=True)
class AppendResult:
    """Result of appending an event."""

    event_id: str
    event_hash: str
    sequence: int


@dataclass(frozen=True)
class ReplayResult:
    """Result of a replay operation."""

    world_state: WorldState
    events_processed: int
    transitions_applied: int
    started_at: datetime
    completed_at: datetime
    duration_ms: float
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class VerificationResult:
    """Result of an event chain verification."""

    is_valid: bool
    total_events: int
    verified_events: int
    first_invalid_event_id: str | None
    error_message: str | None


class EventStore:
    """Append-only event store with replay and verification capabilities.

    All write operations append to the log. There are no update or delete
    methods — this is the fundamental invariant of event sourcing.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    # ─────────────────────────────────────────────────────────────────────────
    # Append
    # ─────────────────────────────────────────────────────────────────────────

    async def append(self, event: WorldEvent) -> AppendResult:
        """Append a new event to the log.

        Computes:
        - event_hash: SHA256 of the canonical event representation
        - prev_event_hash: hash of the immediately preceding event in the same world
        - sequence: monotonically increasing position in the log
        """
        payload = event.to_payload()
        event_hash = compute_event_hash(event, payload)

        prev_event_hash = await self._get_latest_event_hash(event.world_id)
        sequence = await self._get_next_sequence(event.world_id)

        db_event = WorldStateEventDB(
            event_id=event.event_id,
            world_id=event.world_id,
            workspace_id=event.workspace_id,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            event_type=event.event_type.value,
            payload=payload,
            caused_by_event_id=event.caused_by_event_id,
            occurred_at=event.occurred_at,
            extra_metadata={
                **event.metadata,
                "event_hash": event_hash,
                "prev_event_hash": prev_event_hash,
                "sequence": sequence,
            },
        )
        self.db.add(db_event)
        await self.db.flush()

        return AppendResult(
            event_id=event.event_id,
            event_hash=event_hash,
            sequence=sequence,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Load
    # ─────────────────────────────────────────────────────────────────────────

    async def load(self, event_id: str) -> EventRecord | None:
        """Load a specific event by ID."""
        db_event = await self._get_db_event(event_id)
        if db_event is None:
            return None
        return self._to_record(db_event)

    async def load_typed(self, event_id: str) -> WorldEvent | None:
        """Load a specific event and deserialize it to its typed form."""
        db_event = await self._get_db_event(event_id)
        if db_event is None:
            return None
        return deserialize_event(
            event_id=db_event.event_id,
            world_id=db_event.world_id,
            workspace_id=db_event.workspace_id,
            entity_type=db_event.entity_type,
            entity_id=db_event.entity_id,
            event_type=db_event.event_type,
            payload=db_event.payload,
            occurred_at=db_event.occurred_at,
            caused_by_event_id=db_event.caused_by_event_id,
            metadata=db_event.extra_metadata,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Stream
    # ─────────────────────────────────────────────────────────────────────────

    async def stream(
        self,
        world_id: str,
        since: datetime | None = None,
        until: datetime | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        event_type: WorldEventType | str | None = None,
    ) -> AsyncIterator[EventRecord]:
        """Stream events for a world in occurred_at order.

        Async iterator so very large event logs can be processed
        without loading the entire log into memory.
        """
        stmt = (
            select(WorldStateEventDB)
            .where(WorldStateEventDB.world_id == world_id)
            .order_by(WorldStateEventDB.occurred_at, WorldStateEventDB.event_id)
        )
        if since is not None:
            stmt = stmt.where(WorldStateEventDB.occurred_at >= since)
        if until is not None:
            stmt = stmt.where(WorldStateEventDB.occurred_at <= until)
        if entity_type is not None:
            stmt = stmt.where(WorldStateEventDB.entity_type == entity_type)
        if entity_id is not None:
            stmt = stmt.where(WorldStateEventDB.entity_id == entity_id)
        if event_type is not None:
            et = event_type.value if isinstance(event_type, WorldEventType) else str(event_type)
            stmt = stmt.where(WorldStateEventDB.event_type == et)

        result = await self.db.execute(stmt)
        for db_event in result.scalars():
            yield self._to_record(db_event)

    async def list_events(
        self,
        world_id: str,
        since: datetime | None = None,
        until: datetime | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        event_type: WorldEventType | str | None = None,
        limit: int | None = None,
    ) -> list[EventRecord]:
        """List events for a world (eager load — for small windows only)."""
        records: list[EventRecord] = []
        async for record in self.stream(
            world_id=world_id,
            since=since,
            until=until,
            entity_type=entity_type,
            entity_id=entity_id,
            event_type=event_type,
        ):
            records.append(record)
            if limit is not None and len(records) >= limit:
                break
        return records

    # ─────────────────────────────────────────────────────────────────────────
    # Replay (thin async wrapper around the pure event_replay module)
    # ─────────────────────────────────────────────────────────────────────────

    async def replay(
        self,
        world_id: str,
        workspace_id: str,
        graph_version: int,
        initial_variables: dict[str, Any] | None = None,
        until: datetime | None = None,
    ) -> ReplayResult:
        """Replay all events to reconstruct world state.

        This is the canonical replay operation:
        1. Start with initial state (version 1, empty variables)
        2. Project each event to a transition
        3. Apply the transition to advance state
        4. Return the final state + stats

        The pure replay loop lives in event_replay.py — this method
        only handles DB I/O and materializes records into ReplayRecords.
        """
        start = datetime.now(UTC)

        initial = create_initial_state(
            workspace_id=workspace_id,
            world_id=world_id,
            graph_version=graph_version,
            initial_variables=initial_variables,
        )

        records: list[ReplayRecord] = []
        async for er in self.stream(world_id=world_id, until=until):
            records.append(
                ReplayRecord(
                    event_id=er.event.event_id,
                    world_id=er.event.world_id,
                    workspace_id=er.event.workspace_id,
                    entity_id=er.event.entity_id,
                    entity_type=er.event.entity_type,
                    event_type=er.event.event_type.value,
                    payload=er.payload,
                    caused_by_event_id=er.event.caused_by_event_id,
                )
            )

        outcome: ReplayOutcome = _replay_events_pure(initial, records)

        end = datetime.now(UTC)
        return ReplayResult(
            world_state=outcome.world_state,
            events_processed=outcome.events_seen,
            transitions_applied=outcome.transitions_applied,
            started_at=start,
            completed_at=end,
            duration_ms=(end - start).total_seconds() * 1000,
            warnings=list(outcome.warnings),
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Verify (thin async wrapper around the pure event_hashing module)
    # ─────────────────────────────────────────────────────────────────────────

    async def verify(self, world_id: str) -> VerificationResult:
        """Verify the integrity of the event chain for a world.

        Delegates the chain invariant checks (hash, prev_hash, sequence)
        to event_hashing.verify_chain. This method only handles DB I/O
        and materializes records into (hash, prev_hash, sequence) triples.
        """
        triples: list[tuple[str, str | None, int]] = []
        async for er in self.stream(world_id=world_id):
            triples.append((er.event_hash, er.prev_event_hash, er.sequence))

        result = _verify_chain_pure(triples)
        first_error = result.first_error
        return VerificationResult(
            is_valid=result.is_valid,
            total_events=result.total_records,
            verified_events=result.verified_records,
            first_invalid_event_id=first_error.event_id if first_error else None,
            error_message=(
                f"{first_error.error_code}: expected={first_error.expected} actual={first_error.actual}"
                if first_error
                else None
            ),
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────────────────

    async def _get_db_event(self, event_id: str) -> WorldStateEventDB | None:
        stmt = select(WorldStateEventDB).where(WorldStateEventDB.event_id == event_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_latest_event_hash(self, world_id: str) -> str | None:
        stmt = (
            select(WorldStateEventDB.extra_metadata["event_hash"].astext)
            .where(WorldStateEventDB.world_id == world_id)
            .order_by(WorldStateEventDB.occurred_at.desc(), WorldStateEventDB.event_id.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        row = result.scalar_one_or_none()
        return str(row) if row is not None else None

    async def _get_next_sequence(self, world_id: str) -> int:
        # Coalesce returns None when no rows exist; default to 0 then +1
        stmt = (
            select(WorldStateEventDB.extra_metadata["sequence"].astext)
            .where(WorldStateEventDB.world_id == world_id)
            .order_by(WorldStateEventDB.occurred_at.desc(), WorldStateEventDB.event_id.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return 1
        try:
            return int(row) + 1
        except (TypeError, ValueError):
            return 1

    def _to_record(self, db_event: WorldStateEventDB) -> EventRecord:
        event = deserialize_event(
            event_id=db_event.event_id,
            world_id=db_event.world_id,
            workspace_id=db_event.workspace_id,
            entity_type=db_event.entity_type,
            entity_id=db_event.entity_id,
            event_type=db_event.event_type,
            payload=db_event.payload,
            occurred_at=db_event.occurred_at,
            caused_by_event_id=db_event.caused_by_event_id,
            metadata=db_event.extra_metadata,
        )
        meta = db_event.extra_metadata or {}
        return EventRecord(
            event=event,
            payload=db_event.payload,
            event_hash=str(meta.get("event_hash", "")),
            prev_event_hash=(
                str(meta["prev_event_hash"]) if meta.get("prev_event_hash") is not None else None
            ),
            sequence=int(meta.get("sequence", 0)),
        )
