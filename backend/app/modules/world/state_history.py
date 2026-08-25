"""State History — Replay, Time-Travel, and State Reconstruction.

Program J (World State & Digital Twin) — Milestone J.2.4 History & Replay Engine.

Architecture:
- Events are the immutable source of truth (stored in world_state_events)
- StateTransitions are deterministically projected from events
- WorldState is materialized by applying transitions in monotonic order
- Checkpoint snapshots provide accelerated time-travel reconstruction
- Rollback is append-only (advances version, preserves history)

Capabilities:
✓ Full replay from genesis (event log)
✓ Checkpoint-accelerated replay (latest snapshot checkpoint + delta events)
✓ Time-travel reconstruction to any historical version
✓ State comparison and semantic diff across versions
✓ Append-only rollback (preserves immutable lineage)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.modules.world.state_projection import (
    apply_transition,
    create_initial_state,
    project_event_to_transition,
)
from app.modules.world.state_repository import StateRepository
from app.modules.world.world_models import (
    StateSummary,
    StateVariable,
    WorldState,
)

# ─────────────────────────────────────────────────────────────────────────────
# Result Types
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ReplayResult:
    """Result of a state replay operation."""

    state: WorldState
    events_applied: int
    transitions_applied: int
    from_version: int
    to_version: int
    started_at: datetime
    completed_at: datetime
    duration_ms: float
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TimeTravelResult:
    """Result of a time-travel query."""

    state: WorldState
    target_version: int
    reconstruction_method: str  # "full_replay" | "from_snapshot" | "materialized_cache"
    transitions_replayed: int
    snapshot_used: str | None = None


@dataclass(frozen=True)
class StateComparison:
    """Comparison between two world states."""

    from_state: WorldState
    to_state: WorldState
    variables_added: list[str]
    variables_removed: list[str]
    variables_changed: list[str]
    changes: dict[str, dict[str, Any]]  # var_id -> {old, new, diff}
    total_variables_delta: int


@dataclass(frozen=True)
class RollbackResult:
    """Result of a rollback operation."""

    new_state: WorldState
    rolled_back_from_version: int
    rolled_back_to_version: int
    events_appended: int


# ─────────────────────────────────────────────────────────────────────────────
# Replay Engine
# ─────────────────────────────────────────────────────────────────────────────


class ReplayEngine:
    """Engine for replaying world state from the event log."""

    def __init__(self, repository: StateRepository) -> None:
        self.repository = repository

    async def replay_from_genesis(
        self,
        world_id: str,
        workspace_id: str,
        initial_variables: dict[str, StateVariable] | None = None,
    ) -> ReplayResult:
        """Replay all events from genesis to produce current state."""
        start_time = datetime.now(UTC)
        start_perf = time.perf_counter()
        warnings: list[str] = []

        events = await self.repository.get_events(world_id, workspace_id)
        metadata = await self.repository.get_metadata(world_id, workspace_id)

        workspace_id = metadata.workspace_id if metadata else workspace_id
        graph_version = metadata.graph_version if metadata else 1

        state = create_initial_state(
            workspace_id=workspace_id,
            world_id=world_id,
            graph_version=graph_version,
            initial_variables=initial_variables or {},
        )

        transitions_applied = 0
        for event in events:
            try:
                transition = project_event_to_transition(state, event)
                if transition is None:
                    warnings.append(
                        f"Unrecognized event_type={event.event_type} event_id={event.event_id}"
                    )
                    continue
                state = apply_transition(state, transition)
                transitions_applied += 1
            except Exception as exc:
                warnings.append(f"Failed to apply event {event.event_id}: {exc}")

        end_perf = time.perf_counter()
        end_time = datetime.now(UTC)

        return ReplayResult(
            state=state,
            events_applied=len(events),
            transitions_applied=transitions_applied,
            from_version=1,
            to_version=state.version,
            started_at=start_time,
            completed_at=end_time,
            duration_ms=(end_perf - start_perf) * 1000,
            warnings=warnings,
        )

    async def replay_to_version(
        self,
        world_id: str,
        workspace_id: str,
        target_version: int,
        initial_variables: dict[str, StateVariable] | None = None,
    ) -> TimeTravelResult:
        """Time-travel: reconstruct state at a specific historical version.

        Uses checkpoint snapshot if available at or before target_version,
        falling back to full replay from genesis.
        """
        # 1. First check if materialized state is already available in repository
        cached_state = await self.repository.get(world_id, workspace_id, version=target_version)
        if cached_state is not None:
            return TimeTravelResult(
                state=cached_state,
                target_version=target_version,
                reconstruction_method="materialized_cache",
                transitions_replayed=0,
                snapshot_used=None,
            )

        metadata = await self.repository.get_metadata(world_id, workspace_id)
        workspace_id = metadata.workspace_id if metadata else workspace_id
        graph_version = metadata.graph_version if metadata else 1

        # 2. Check for latest snapshot at or before target_version
        latest_snapshot = await self.repository.get_latest_snapshot(world_id, workspace_id)

        if latest_snapshot and latest_snapshot.version <= target_version:
            # Reconstruct starting from checkpoint state
            checkpoint_state = await self.repository.get(world_id, workspace_id, version=latest_snapshot.version)
            if checkpoint_state is None:
                checkpoint_state = create_initial_state(
                    workspace_id=workspace_id,
                    world_id=world_id,
                    graph_version=graph_version,
                    initial_variables=initial_variables or {},
                )

            events = await self.repository.get_events(world_id, workspace_id)
            transitions_count = 0
            state = checkpoint_state

            for event in events:
                if state.version >= target_version:
                    break
                transition = project_event_to_transition(state, event)
                if transition is not None:
                    state = apply_transition(state, transition)
                    transitions_count += 1

            return TimeTravelResult(
                state=state,
                target_version=target_version,
                reconstruction_method="from_snapshot",
                transitions_replayed=transitions_count,
                snapshot_used=latest_snapshot.snapshot_id,
            )

        # 3. Fallback: full replay from genesis
        events = await self.repository.get_events(world_id, workspace_id)
        state = create_initial_state(
            workspace_id=workspace_id,
            world_id=world_id,
            graph_version=graph_version,
            initial_variables=initial_variables or {},
        )
        transitions_replayed = 0
        for event in events:
            if state.version >= target_version:
                break
            transition = project_event_to_transition(state, event)
            if transition is None:
                continue
            state = apply_transition(state, transition)
            transitions_replayed += 1

        return TimeTravelResult(
            state=state,
            target_version=target_version,
            reconstruction_method="full_replay",
            transitions_replayed=transitions_replayed,
            snapshot_used=None,
        )

    async def replay_range(
        self,
        world_id: str,
        workspace_id: str,
        from_version: int,
        to_version: int,
    ) -> list[WorldState]:
        """Replay and collect states at each version in a range (inclusive)."""
        states: list[WorldState] = []
        for v in range(from_version, to_version + 1):
            result = await self.replay_to_version(world_id, workspace_id, v)
            states.append(result.state)
        return states


# ─────────────────────────────────────────────────────────────────────────────
# State Diff Engine
# ─────────────────────────────────────────────────────────────────────────────


class StateDiffEngine:
    """Engine for comparing two world states."""

    def compare(self, from_state: WorldState, to_state: WorldState) -> StateComparison:
        from_vars = from_state.variables
        to_vars = to_state.variables

        from_ids = set(from_vars.keys())
        to_ids = set(to_vars.keys())

        added = sorted(to_ids - from_ids)
        removed = sorted(from_ids - to_ids)
        common = from_ids & to_ids

        changed: list[str] = []
        changes: dict[str, dict[str, Any]] = {}

        for var_id in sorted(common):
            old_var = from_vars[var_id]
            new_var = to_vars[var_id]

            if old_var.raw_value != new_var.raw_value:
                changed.append(var_id)
                diff = None
                if isinstance(old_var.raw_value, (int, float)) and isinstance(
                    new_var.raw_value, (int, float)
                ):
                    diff = new_var.raw_value - old_var.raw_value
                changes[var_id] = {
                    "old_value": old_var.raw_value,
                    "new_value": new_var.raw_value,
                    "old_unit": old_var.unit,
                    "new_unit": new_var.unit,
                    "diff": diff,
                }

        return StateComparison(
            from_state=from_state,
            to_state=to_state,
            variables_added=added,
            variables_removed=removed,
            variables_changed=changed,
            changes=changes,
            total_variables_delta=len(to_vars) - len(from_vars),
        )

    def summarize_changes(self, comparison: StateComparison) -> dict[str, Any]:
        """Generate a structured summary of state changes."""
        summary: dict[str, Any] = {
            "total_changes": len(comparison.variables_changed),
            "variables_added": len(comparison.variables_added),
            "variables_removed": len(comparison.variables_removed),
            "total_variables_delta": comparison.total_variables_delta,
            "significant_changes": [],
        }

        for var_id, change in comparison.changes.items():
            diff = change.get("diff")
            if diff is not None and isinstance(diff, (int, float)) and abs(diff) > 0:
                summary["significant_changes"].append(
                    {
                        "variable_id": var_id,
                        "old_value": change["old_value"],
                        "new_value": change["new_value"],
                        "delta": diff,
                        "direction": "increase" if diff > 0 else "decrease",
                    }
                )

        summary["significant_changes"].sort(key=lambda x: abs(x["delta"]), reverse=True)
        summary["significant_changes"] = summary["significant_changes"][:10]
        return summary


# ─────────────────────────────────────────────────────────────────────────────
# Rollback Engine
# ─────────────────────────────────────────────────────────────────────────────


class RollbackEngine:
    """Engine for rolling back world state to a previous version.

    Rollback creates a new state version whose variables equal an older
    version's variables, and appends a rollback event to the event log.
    The history is preserved — nothing is destroyed.
    """

    def __init__(self, repository: StateRepository) -> None:
        self.repository = repository

    async def rollback(
        self,
        workspace_id: str,
        world_id: str,
        target_version: int,
        reason: str,
    ) -> RollbackResult:
        # Serialize against concurrent event submissions for the same world:
        # the new version number and the appended rollback event must observe
        # the latest committed state.
        await self.repository.acquire_world_write_lock(workspace_id, world_id)

        replay_engine = ReplayEngine(self.repository)
        time_travel = await replay_engine.replay_to_version(world_id, workspace_id, target_version)

        latest_state = await self.repository.get_latest(workspace_id, world_id)
        if latest_state is None:
            return RollbackResult(
                new_state=time_travel.state,
                rolled_back_from_version=1,
                rolled_back_to_version=target_version,
                events_appended=0,
            )

        rollback_state = WorldState(
            world_id=world_id,
            workspace_id=workspace_id,
            version=latest_state.version + 1,
            graph_version=latest_state.graph_version,
            variables=dict(time_travel.state.variables),
            created_at=datetime.now(UTC),
            metadata={
                **latest_state.metadata,
                "rollback": True,
                "rolled_back_to_version": target_version,
                "reason": reason,
            },
        )

        event_id = await self.repository.append_event(
            world_id=world_id,
            workspace_id=workspace_id,
            entity_type="world",
            entity_id=world_id,
            event_type="rollback",
            payload={
                "rolled_back_to_version": target_version,
                "rolled_back_from_version": latest_state.version,
                "reason": reason,
            },
            metadata={"rollback": True},
        )

        parent_version_id = await self.repository.get_version_id(
            world_id, workspace_id, latest_state.version
        )
        await self.repository.store_version(
            rollback_state,
            event_id=event_id,
            parent_version_id=parent_version_id,
            source="rollback",
        )

        return RollbackResult(
            new_state=rollback_state,
            rolled_back_from_version=latest_state.version,
            rolled_back_to_version=target_version,
            events_appended=1,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Convenience Functions
# ─────────────────────────────────────────────────────────────────────────────


async def compare_states(
    repository: StateRepository,
    world_id: str,
    workspace_id: str,
    from_version: int,
    to_version: int,
) -> StateComparison:
    from_state = await repository.get(world_id, workspace_id, from_version)
    to_state = await repository.get(world_id, workspace_id, to_version)
    if from_state is None or to_state is None:
        raise ValueError(
            f"One or both versions not found for world {world_id}: ({from_version}, {to_version})"
        )
    return StateDiffEngine().compare(from_state, to_state)


async def get_state_at_time(
    repository: StateRepository,
    world_id: str,
    workspace_id: str,
    at_version: int,
) -> WorldState:
    replay_engine = ReplayEngine(repository)
    result = await replay_engine.replay_to_version(world_id, workspace_id, at_version)
    return result.state


async def get_state_history(
    repository: StateRepository,
    world_id: str,
    workspace_id: str,
    limit: int = 100,
) -> list[StateSummary]:
    versions = await repository.get_versions(world_id, workspace_id)
    versions.sort(key=lambda v: v.version, reverse=True)

    summaries: list[StateSummary] = []
    for v in versions[:limit]:
        state = await repository.get(world_id, workspace_id, v.version)
        if state is None:
            continue
        variables_by_type: dict[str, int] = {}
        for var in state.variables.values():
            vtype = (
                var.variable_type.value
                if hasattr(var.variable_type, "value")
                else str(var.variable_type)
            )
            variables_by_type[vtype] = variables_by_type.get(vtype, 0) + 1
        entities = {var.entity_id for var in state.variables.values()}
        summaries.append(
            StateSummary(
                workspace_id=state.workspace_id,
                world_id=state.world_id,
                version=state.version,
                graph_version=state.graph_version,
                variable_count=len(state.variables),
                variables_by_type=variables_by_type,
                entities_with_state=len(entities),
                last_transition_at=state.created_at,
            )
        )
    return summaries
