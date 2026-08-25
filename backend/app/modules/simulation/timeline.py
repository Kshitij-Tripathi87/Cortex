"""Timeline — Time-based Tracking for Simulations.

Program J (World State & Digital Twin) timeline layer:

The Timeline tracks how state evolves over the course of a simulation.
Each tick captures a snapshot of state, events, and metrics.

Responsibilities:
- Track tick progression
- Capture state snapshots at each tick
- Record events that occurred during each tick
- Compute time-based deltas (changes since last tick)
- Provide replay/visualization data
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.modules.simulation.simulation_models import (
    SimulationTick,
    TickGranularity,
)
from app.modules.world.state_projection import WorldState


@dataclass(frozen=True)
class TickDelta:
    """Changes that occurred during a tick."""

    variables_added: list[str] = field(default_factory=list)
    variables_removed: list[str] = field(default_factory=list)
    variables_changed: dict[str, dict[str, Any]] = field(default_factory=dict)
    total_delta: int = 0


@dataclass
class Timeline:
    """Mutable timeline that accumulates ticks during simulation.

    Not frozen because we accumulate ticks during execution.
    After simulation completes, convert to immutable SimulationResult.
    """

    simulation_id: str
    config_id: str
    granularity: TickGranularity = TickGranularity.DAY
    ticks: list[SimulationTick] = field(default_factory=list)
    start_time: datetime = field(default_factory=lambda: datetime.now(UTC))
    current_time: datetime = field(default_factory=lambda: datetime.now(UTC))

    def advance(
        self,
        events: list[dict[str, Any]],
        state: WorldState,
        metrics: dict[str, float],
        state_hash: str,
    ) -> SimulationTick:
        """Advance the timeline by one tick.

        Returns the new tick.
        """
        from app.common.ids import uuid7

        tick_number = len(self.ticks)
        next_time = self._compute_next_time(self.current_time)

        # Compute deltas vs. previous tick
        deltas = TickDelta()
        if self.ticks:
            previous_state_vars = set()  # Would need to reconstruct from previous tick
            current_state_vars = set(state.variables.keys())

            deltas = TickDelta(
                variables_added=list(current_state_vars - previous_state_vars),
                variables_removed=list(previous_state_vars - current_state_vars),
                total_delta=len(current_state_vars) - len(previous_state_vars),
            )

        tick = SimulationTick(
            tick_id=str(uuid7()),
            simulation_id=self.simulation_id,
            tick_number=tick_number,
            simulated_time=next_time,
            events=events,
            state_hash=state_hash,
            metrics=metrics,
            variable_changes=deltas.variables_changed,
        )

        self.ticks.append(tick)
        self.current_time = next_time
        return tick

    def get_tick(self, tick_number: int) -> SimulationTick | None:
        """Get a specific tick by number."""
        if 0 <= tick_number < len(self.ticks):
            return self.ticks[tick_number]
        return None

    def get_last_tick(self) -> SimulationTick | None:
        """Get the most recent tick."""
        return self.ticks[-1] if self.ticks else None

    def total_duration(self) -> timedelta:
        """Total simulated duration covered by the timeline."""
        if not self.ticks:
            return timedelta(0)
        return self.current_time - self.start_time

    @property
    def last_tick(self) -> SimulationTick | None:
        """Get the most recent tick."""
        return self.ticks[-1] if self.ticks else None

    @property
    def timeline_hash(self) -> str:
        """Deterministic sha256 hash of entire tick sequence and state hashes."""
        import hashlib
        import json

        canonical = [
            {"tick": t.tick_number, "hash": t.state_hash, "metrics": t.metrics} for t in self.ticks
        ]
        return hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()

    def to_result_format(self) -> list[dict[str, Any]]:
        """Convert timeline to API-friendly format."""
        return [tick.to_dict() for tick in self.ticks]

    def _compute_next_time(self, current: datetime) -> datetime:
        """Compute the next tick time based on granularity."""
        if self.granularity == TickGranularity.HOUR:
            return current + timedelta(hours=1)
        if self.granularity == TickGranularity.DAY:
            return current + timedelta(days=1)
        if self.granularity == TickGranularity.WEEK:
            return current + timedelta(weeks=1)
        if self.granularity == TickGranularity.MONTH:
            # Approximate month as 30 days
            return current + timedelta(days=30)
        return current + timedelta(days=1)
