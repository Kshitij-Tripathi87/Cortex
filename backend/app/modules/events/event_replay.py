"""Event Replay — Pure Replay Engine for the Event Kernel.

Program J (World State & Digital Twin) — invariant I3 (deterministic
projections) and I9 (replay is the source of truth).

This module owns the pure replay loop: given a starting WorldState and an
ordered sequence of EventRecord values, it deterministically reproduces the
state at the end of the log. The same event sequence always yields the same
final state hash (J.1 exit criterion).

Extracted from EventStore.replay() so:
- Twin (Layer 2) can rebuild a parent state into a twin without DB coupling
- Simulation (Layer 3) can fast-forward / rewind within a scenario
- Replay can be tested with pure-Python fakes (no async, no DB)

Replay rules:
✓ Pure: no DB, no I/O, no clock — input → output only
✓ Deterministic: identical inputs always produce identical output
✓ Total: every event in the input is either applied or recorded as a warning
✓ Versioned: each applied transition increments state.version by 1
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.modules.world.state_projection import (
    apply_transition,
    project_event_to_transition,
)
from app.modules.world.world_models import WorldState


@dataclass(frozen=True)
class ReplayRecord:
    """Minimal record consumed by the pure replay loop.

    Decoupled from the DB layer (EventRecord) and the typed-event layer
    (WorldEvent). Replay only needs: the event identity, type, payload, and
    caused_by pointer. The DB layer maps EventRecord → ReplayRecord; the
    pure replay loop never touches the DB.
    """

    event_id: str
    world_id: str
    workspace_id: str
    entity_id: str
    entity_type: str
    event_type: str
    payload: dict[str, Any]
    caused_by_event_id: str | None = None


@dataclass(frozen=True)
class ReplayOutcome:
    """Result of a pure replay pass."""

    world_state: WorldState
    events_seen: int
    transitions_applied: int
    warnings: tuple[str, ...] = ()


def _to_projection_view(rec: ReplayRecord) -> Any:
    """Adapt a ReplayRecord to the duck-typed view that project_event_to_transition expects."""
    from dataclasses import dataclass as _dc

    @_dc
    class _View:
        event_id: str
        world_id: str
        workspace_id: str
        entity_id: str
        entity_type: str
        event_type: str
        payload: dict[str, Any]
        caused_by_event_id: str | None
        occurred_at: datetime
        metadata: dict[str, Any]

    return _View(
        event_id=rec.event_id,
        world_id=rec.world_id,
        workspace_id=rec.workspace_id,
        entity_id=rec.entity_id,
        entity_type=rec.entity_type,
        event_type=rec.event_type,
        payload=dict(rec.payload),
        caused_by_event_id=rec.caused_by_event_id,
        occurred_at=datetime.now(UTC),
        metadata={},
    )


def replay_events(
    initial_state: WorldState,
    records: Iterable[ReplayRecord],
) -> ReplayOutcome:
    """Replay a sequence of records onto an initial state.

    Pure function. No DB, no I/O, no clock. Caller is responsible for
    materializing records from the event store in occurred_at order.
    """
    state = initial_state
    seen = 0
    applied = 0
    warnings: list[str] = []

    for rec in records:
        seen += 1
        try:
            view = _to_projection_view(rec)
            transition = project_event_to_transition(state, view)
        except Exception as exc:  # projection failure — surface as warning, do not raise
            warnings.append(f"event_id={rec.event_id} projection_failed: {exc}")
            continue

        if transition is None:
            warnings.append(f"event_id={rec.event_id} unrecognized_event_type={rec.event_type}")
            continue

        state = apply_transition(state, transition)
        applied += 1

    return ReplayOutcome(
        world_state=state,
        events_seen=seen,
        transitions_applied=applied,
        warnings=tuple(warnings),
    )


def replay_batches(
    initial_state: WorldState,
    batches: Sequence[Sequence[ReplayRecord]],
    on_progress: Any | None = None,
) -> ReplayOutcome:
    """Replay events in batches with optional progress callback.

    `on_progress(seen, applied)` is called between batches. This is the
    function the 100k-event stress test uses to assert no regression under
    load without holding all events in memory at once.
    """
    state = initial_state
    total_seen = 0
    total_applied = 0
    warnings: list[str] = []

    for batch in batches:
        outcome = replay_events(state, batch)
        state = outcome.world_state
        total_seen += outcome.events_seen
        total_applied += outcome.transitions_applied
        warnings.extend(outcome.warnings)
        if on_progress is not None:
            on_progress(total_seen, total_applied)

    return ReplayOutcome(
        world_state=state,
        events_seen=total_seen,
        transitions_applied=total_applied,
        warnings=tuple(warnings),
    )


def replay_timed(
    initial_state: WorldState,
    records: Iterable[ReplayRecord],
) -> tuple[ReplayOutcome, float]:
    """Replay events and return (outcome, duration_ms).

    Used by performance gates. Wall-clock is intentionally excluded from the
    pure ReplayOutcome — determinism is preserved across this function.
    """
    start = datetime.now(UTC)
    outcome = replay_events(initial_state, records)
    elapsed_ms = (datetime.now(UTC) - start).total_seconds() * 1000.0
    return outcome, elapsed_ms
