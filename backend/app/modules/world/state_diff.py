"""State Diff — Difference Engine for World State Changes.

Provides detailed comparison between world states:
- Variable-level changes (added, removed, modified)
- Entity-level impact analysis
- Time-series diff (state evolution)
- Human-readable summaries
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.modules.world.world_models import (
    StateVariable,
    StateVariableType,
    WorldState,
)


@dataclass(frozen=True)
class VariableDiff:
    """Diff for a single variable."""

    variable_id: str
    variable_type: StateVariableType
    entity_id: str
    entity_type: str
    old_value: Any
    new_value: Any
    unit: str | None = None
    changed: bool = False
    delta: float | None = None
    direction: str | None = None  # "increase", "decrease", "unchanged"


@dataclass(frozen=True)
class EntityDiff:
    """Diff for a single entity's state variables."""

    entity_id: str
    entity_type: str
    variables: list[VariableDiff]
    added_variables: list[str]
    removed_variables: list[str]


@dataclass(frozen=True)
class StateDiff:
    """Complete diff between two world states."""

    from_state: WorldState
    to_state: WorldState
    variable_diffs: list[VariableDiff]
    entity_diffs: list[EntityDiff]
    added_variables: list[str]
    removed_variables: list[str]
    summary: DiffSummary


@dataclass(frozen=True)
class DiffSummary:
    """Summary of differences between two states."""

    total_variables_before: int
    total_variables_after: int
    variables_added: int
    variables_removed: int
    variables_modified: int
    entities_affected: int
    largest_changes: list[VariableDiff]  # Top 10 by magnitude
    by_type: dict[str, int]  # variable_type -> count of changes
    by_entity_type: dict[str, int]  # entity_type -> count of changes


# ─────────────────────────────────────────────────────────────────────────────
# Diff Engine
# ─────────────────────────────────────────────────────────────────────────────


class DiffEngine:
    """Engine for computing differences between world states."""

    def diff(self, from_state: WorldState, to_state: WorldState) -> StateDiff:
        """Compute complete diff between two world states."""
        from_vars = from_state.variables
        to_vars = to_state.variables

        from_ids = set(from_vars.keys())
        to_ids = set(to_vars.keys())

        added_ids = list(to_ids - from_ids)
        removed_ids = list(from_ids - to_ids)
        common_ids = from_ids & to_ids

        # Compute variable diffs
        variable_diffs = []
        by_type: dict[str, int] = {}
        by_entity_type: dict[str, int] = {}
        entity_diffs_map: dict[str, EntityDiff] = {}

        for var_id in common_ids:
            old_var = from_vars[var_id]
            new_var = to_vars[var_id]

            diff = self._compute_variable_diff(old_var, new_var)
            if diff.changed:
                variable_diffs.append(diff)
                by_type[diff.variable_type.value] = by_type.get(diff.variable_type.value, 0) + 1
                by_entity_type[diff.entity_type] = by_entity_type.get(diff.entity_type, 0) + 1

                # Group by entity
                if diff.entity_id not in entity_diffs_map:
                    entity_diffs_map[diff.entity_id] = EntityDiff(
                        entity_id=diff.entity_id,
                        entity_type=diff.entity_type,
                        variables=[],
                        added_variables=[],
                        removed_variables=[],
                    )
                entity_diffs_map[diff.entity_id].variables.append(diff)

        # Handle added variables
        for var_id in added_ids:
            var = to_vars[var_id]
            diff = VariableDiff(
                variable_id=var_id,
                variable_type=var.variable_type,
                entity_id=var.entity_id,
                entity_type=var.entity_type,
                old_value=None,
                new_value=var.raw_value,
                unit=var.unit,
                changed=True,
                delta=None,
                direction="added",
            )
            variable_diffs.append(diff)
            by_type[var.variable_type.value] = by_type.get(var.variable_type.value, 0) + 1
            by_entity_type[var.entity_type] = by_entity_type.get(var.entity_type, 0) + 1

            if var.entity_id not in entity_diffs_map:
                entity_diffs_map[var.entity_id] = EntityDiff(
                    entity_id=var.entity_id,
                    entity_type=var.entity_type,
                    variables=[],
                    added_variables=[],
                    removed_variables=[],
                )
            entity_diffs_map[var.entity_id].added_variables.append(var_id)

        # Handle removed variables
        for var_id in removed_ids:
            var = from_vars[var_id]
            diff = VariableDiff(
                variable_id=var_id,
                variable_type=var.variable_type,
                entity_id=var.entity_id,
                entity_type=var.entity_type,
                old_value=var.raw_value,
                new_value=None,
                unit=var.unit,
                changed=True,
                delta=None,
                direction="removed",
            )
            variable_diffs.append(diff)
            by_type[var.variable_type.value] = by_type.get(var.variable_type.value, 0) + 1
            by_entity_type[var.entity_type] = by_entity_type.get(var.entity_type, 0) + 1

            if var.entity_id not in entity_diffs_map:
                entity_diffs_map[var.entity_id] = EntityDiff(
                    entity_id=var.entity_id,
                    entity_type=var.entity_type,
                    variables=[],
                    added_variables=[],
                    removed_variables=[],
                )
            entity_diffs_map[var.entity_id].removed_variables.append(var_id)

        # Sort variable diffs by magnitude of change
        variable_diffs.sort(key=lambda d: abs(d.delta) if d.delta else 0, reverse=True)

        # Build summary
        summary = DiffSummary(
            total_variables_before=len(from_ids),
            total_variables_after=len(to_ids),
            variables_added=len(added_ids),
            variables_removed=len(removed_ids),
            variables_modified=len(
                [d for d in variable_diffs if d.changed and d.direction not in ("added", "removed")]
            ),
            entities_affected=len(entity_diffs_map),
            largest_changes=variable_diffs[:10],
            by_type=by_type,
            by_entity_type=by_entity_type,
        )

        return StateDiff(
            from_state=from_state,
            to_state=to_state,
            variable_diffs=variable_diffs,
            entity_diffs=list(entity_diffs_map.values()),
            added_variables=added_ids,
            removed_variables=removed_ids,
            summary=summary,
        )

    def _compute_variable_diff(
        self, old_var: StateVariable, new_var: StateVariable
    ) -> VariableDiff:
        """Compute diff for a single variable."""
        old_val = old_var.raw_value
        new_val = new_var.raw_value

        changed = old_val != new_val
        delta = None
        direction = "unchanged"

        if changed and isinstance(old_val, (int, float)) and isinstance(new_val, (int, float)):
            delta = float(new_val) - float(old_val)
            direction = "increase" if delta > 0 else "decrease"

        return VariableDiff(
            variable_id=old_var.variable_id,
            variable_type=old_var.variable_type,
            entity_id=old_var.entity_id,
            entity_type=old_var.entity_type,
            old_value=old_val,
            new_value=new_val,
            unit=old_var.unit,
            changed=changed,
            delta=delta,
            direction=direction,
        )

    def diff_by_type(
        self,
        from_state: WorldState,
        to_state: WorldState,
        variable_type: StateVariableType,
    ) -> StateDiff:
        """Compute diff filtered by variable type."""
        full_diff = self.diff(from_state, to_state)
        filtered_diffs = [d for d in full_diff.variable_diffs if d.variable_type == variable_type]

        # Rebuild summary with filtered diffs
        filtered_summary = DiffSummary(
            total_variables_before=len(
                [v for v in from_state.variables.values() if v.variable_type == variable_type]
            ),
            total_variables_after=len(
                [v for v in to_state.variables.values() if v.variable_type == variable_type]
            ),
            variables_added=len([d for d in filtered_diffs if d.direction == "added"]),
            variables_removed=len([d for d in filtered_diffs if d.direction == "removed"]),
            variables_modified=len(
                [d for d in filtered_diffs if d.changed and d.direction not in ("added", "removed")]
            ),
            entities_affected=len(set(d.entity_id for d in filtered_diffs)),
            largest_changes=filtered_diffs[:10],
            by_type={variable_type.value: len(filtered_diffs)},
            by_entity_type={},
        )

        return StateDiff(
            from_state=full_diff.from_state,
            to_state=full_diff.to_state,
            variable_diffs=filtered_diffs,
            entity_diffs=[],
            added_variables=[d.variable_id for d in filtered_diffs if d.direction == "added"],
            removed_variables=[d.variable_id for d in filtered_diffs if d.direction == "removed"],
            summary=filtered_summary,
        )

    def diff_by_entity(
        self,
        from_state: WorldState,
        to_state: WorldState,
        entity_id: str,
    ) -> StateDiff:
        """Compute diff for a specific entity."""
        full_diff = self.diff(from_state, to_state)
        filtered_diffs = [d for d in full_diff.variable_diffs if d.entity_id == entity_id]

        filtered_summary = DiffSummary(
            total_variables_before=len(
                [v for v in from_state.variables.values() if v.entity_id == entity_id]
            ),
            total_variables_after=len(
                [v for v in to_state.variables.values() if v.entity_id == entity_id]
            ),
            variables_added=len([d for d in filtered_diffs if d.direction == "added"]),
            variables_removed=len([d for d in filtered_diffs if d.direction == "removed"]),
            variables_modified=len(
                [d for d in filtered_diffs if d.changed and d.direction not in ("added", "removed")]
            ),
            entities_affected=1 if filtered_diffs else 0,
            largest_changes=filtered_diffs[:10],
            by_type={},
            by_entity_type={entity_id: len(filtered_diffs)},
        )

        entity_diffs = []
        for diff in full_diff.entity_diffs:
            if diff.entity_id == entity_id:
                entity_diffs.append(diff)

        return StateDiff(
            from_state=full_diff.from_state,
            to_state=full_diff.to_state,
            variable_diffs=filtered_diffs,
            entity_diffs=entity_diffs,
            added_variables=[d.variable_id for d in filtered_diffs if d.direction == "added"],
            removed_variables=[d.variable_id for d in filtered_diffs if d.direction == "removed"],
            summary=filtered_summary,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Time-Series Diff
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TimeSeriesDiff:
    """Diff across multiple versions (time-series view)."""

    world_id: str
    versions: list[int]
    states: list[WorldState]
    changes_per_version: dict[int, StateDiff]
    cumulative_diff: StateDiff
    trends: dict[str, list[float]]  # variable_id -> values over time


class TimeSeriesDiffEngine:
    """Engine for computing time-series diffs (state evolution over time)."""

    def __init__(self, diff_engine: DiffEngine):
        self.diff_engine = diff_engine

    def compute(
        self,
        world_id: str,
        states: list[WorldState],
    ) -> TimeSeriesDiff:
        """Compute time-series diff across multiple state versions."""
        if not states:
            raise ValueError("Cannot compute time-series diff on empty states list")

        if len(states) == 1:
            single = states[0]
            empty_diff = self.diff_engine.diff(single, single)
            trends_single: dict[str, list[float]] = {
                var_id: [float(var.raw_value) if isinstance(var.raw_value, (int, float)) else 0.0]
                for var_id, var in single.variables.items()
            }
            return TimeSeriesDiff(
                world_id=world_id,
                versions=[single.version],
                states=states,
                changes_per_version={},
                cumulative_diff=empty_diff,
                trends=trends_single,
            )

        versions = [s.version for s in states]
        changes_per_version: dict[int, StateDiff] = {}

        # Compute diff for each consecutive pair
        for i in range(1, len(states)):
            prev_state = states[i - 1]
            curr_state = states[i]
            diff = self.diff_engine.diff(prev_state, curr_state)
            changes_per_version[curr_state.version] = diff

        # Cumulative diff (first to last)
        cumulative_diff = self.diff_engine.diff(states[0], states[-1])

        # Compute trends (value over time for each variable)
        trends: dict[str, list[float]] = {}
        for state in states:
            for var_id, var in state.variables.items():
                if var_id not in trends:
                    trends[var_id] = []
                trends[var_id].append(
                    float(var.raw_value) if isinstance(var.raw_value, (int, float)) else 0.0
                )

        return TimeSeriesDiff(
            world_id=world_id,
            versions=versions,
            states=states,
            changes_per_version=changes_per_version,
            cumulative_diff=cumulative_diff,
            trends=trends,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Human-Readable Summaries
# ─────────────────────────────────────────────────────────────────────────────


class DiffFormatter:
    """Format diffs for human consumption."""

    @staticmethod
    def format_summary(diff: StateDiff) -> str:
        """Format a human-readable summary of the diff."""
        s = diff.summary
        lines = [
            f"State Diff: {diff.from_state.world_id} v{diff.from_state.version} -> v{diff.to_state.version}",
            f"  Variables: {s.total_variables_before} -> {s.total_variables_after} ({s.total_variables_after - s.total_variables_before:+d})",
            f"  Added: {s.variables_added}, Removed: {s.variables_removed}, Modified: {s.variables_modified}",
            f"  Entities affected: {s.entities_affected}",
        ]

        if s.largest_changes:
            lines.append("  Largest changes:")
            for change in s.largest_changes[:5]:
                delta_str = f" ({change.delta:+.2f})" if change.delta else ""
                lines.append(
                    f"    {change.variable_id}: {change.old_value} -> {change.new_value}{delta_str}"
                )

        if s.by_type:
            lines.append("  By type:")
            for var_type, count in sorted(s.by_type.items()):
                lines.append(f"    {var_type}: {count}")

        if s.by_entity_type:
            lines.append("  By entity type:")
            for entity_type, count in sorted(s.by_entity_type.items()):
                lines.append(f"    {entity_type}: {count}")

        return "\n".join(lines)

    @staticmethod
    def format_variable_change(diff: StateDiff, variable_id: str) -> str | None:
        """Format a specific variable change."""
        for var_diff in diff.variable_diffs:
            if var_diff.variable_id == variable_id:
                return (
                    f"{variable_id}: {var_diff.old_value} -> {var_diff.new_value} "
                    f"({var_diff.direction}{' ' + str(var_diff.delta) if var_diff.delta else ''})"
                )
        return None

    @staticmethod
    def format_entity_changes(diff: StateDiff, entity_id: str) -> str | None:
        """Format changes for a specific entity."""
        entity_diff = next((e for e in diff.entity_diffs if e.entity_id == entity_id), None)
        if not entity_diff:
            return None

        lines = [f"Entity: {entity_id} ({entity_diff.entity_type})"]
        if entity_diff.added_variables:
            lines.append(f"  Added: {', '.join(entity_diff.added_variables)}")
        if entity_diff.removed_variables:
            lines.append(f"  Removed: {', '.join(entity_diff.removed_variables)}")
        if entity_diff.variables:
            lines.append("  Modified:")
            for var in entity_diff.variables:
                delta_str = f" ({var.delta:+.2f})" if var.delta else ""
                lines.append(
                    f"    {var.variable_id}: {var.old_value} -> {var.new_value}{delta_str}"
                )
        return "\n".join(lines)

    @staticmethod
    def format_for_api(diff: StateDiff) -> dict[str, Any]:
        """Format diff for API response."""
        return {
            "from_version": diff.from_state.version,
            "to_version": diff.to_state.version,
            "summary": {
                "total_variables_before": diff.summary.total_variables_before,
                "total_variables_after": diff.summary.total_variables_after,
                "variables_added": diff.summary.variables_added,
                "variables_removed": diff.summary.variables_removed,
                "variables_modified": diff.summary.variables_modified,
                "entities_affected": diff.summary.entities_affected,
                "largest_changes": [
                    {
                        "variable_id": c.variable_id,
                        "entity_id": c.entity_id,
                        "variable_type": c.variable_type.value,
                        "old_value": c.old_value,
                        "new_value": c.new_value,
                        "delta": c.delta,
                        "direction": c.direction,
                    }
                    for c in diff.summary.largest_changes
                ],
                "by_type": diff.summary.by_type,
                "by_entity_type": diff.summary.by_entity_type,
            },
            "entity_changes": [
                {
                    "entity_id": e.entity_id,
                    "entity_type": e.entity_type,
                    "added_variables": e.added_variables,
                    "removed_variables": e.removed_variables,
                    "modified_variables": [
                        {
                            "variable_id": v.variable_id,
                            "variable_type": v.variable_type.value,
                            "old_value": v.old_value,
                            "new_value": v.new_value,
                            "delta": v.delta,
                            "direction": v.direction,
                        }
                        for v in e.variables
                    ],
                }
                for e in diff.entity_diffs
            ],
        }
