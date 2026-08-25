"""Tests for State Diff Engine, TimeSeriesDiff, and DiffFormatter — Program J Milestone J.2.5.

Covers:
1. DiffEngine.diff across two states (added, removed, modified variables, deltas, directions)
2. DiffEngine.diff_by_type (filtering by StateVariableType)
3. DiffEngine.diff_by_entity (filtering by entity_id)
4. TimeSeriesDiffEngine.compute across multi-version sequences and trends extraction
5. TimeSeriesDiffEngine empty and single-state edge cases
6. DiffFormatter text generation (format_summary, format_variable_change, format_entity_changes)
7. DiffFormatter.format_for_api (FastAPI JSON-compatible schema representation)
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.modules.world.state_diff import (
    DiffEngine,
    DiffFormatter,
    TimeSeriesDiffEngine,
)
from app.modules.world.state_projection import (
    capacity_var_id,
    create_initial_state,
    inventory_var_id,
    lead_time_var_id,
)
from app.modules.world.world_models import (
    StateVariable,
    StateVariableType,
    WorldState,
)


@pytest.fixture
def base_state() -> WorldState:
    workspace_id = "ws_test"
    world_id = "world_test"

    inv_var = StateVariable(
        variable_id=inventory_var_id("wh_1", "comp_a"),
        variable_type=StateVariableType.INVENTORY,
        entity_id="wh_1",
        entity_type="warehouse",
        value=100,
    )
    lt_var = StateVariable(
        variable_id=lead_time_var_id("sup_1"),
        variable_type=StateVariableType.LEAD_TIME,
        entity_id="sup_1",
        entity_type="supplier",
        value=10,
    )
    cap_var = StateVariable(
        variable_id=capacity_var_id("fac_1"),
        variable_type=StateVariableType.CAPACITY,
        entity_id="fac_1",
        entity_type="factory",
        value=90.0,
    )

    return create_initial_state(
        workspace_id=workspace_id,
        world_id=world_id,
        graph_version=1,
        initial_variables={
            inv_var.variable_id: inv_var,
            lt_var.variable_id: lt_var,
            cap_var.variable_id: cap_var,
        },
    )


class TestDiffEngine:
    def test_diff_computes_added_removed_and_modified_variables(
        self, base_state: WorldState
    ) -> None:
        engine = DiffEngine()

        # Create next state:
        # - inv_var: 100 -> 250 (+150 increase)
        # - cap_var: removed
        # - new_inv: added (300 units in wh_2)
        # - lt_var: unchanged (10)
        inv_mod = StateVariable(
            variable_id=inventory_var_id("wh_1", "comp_a"),
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_1",
            entity_type="warehouse",
            value=250,
        )
        inv_new = StateVariable(
            variable_id=inventory_var_id("wh_2", "comp_b"),
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_2",
            entity_type="warehouse",
            value=300,
        )
        lt_same = base_state.variables[lead_time_var_id("sup_1")]

        next_state = WorldState(
            world_id=base_state.world_id,
            workspace_id=base_state.workspace_id,
            version=2,
            graph_version=base_state.graph_version,
            variables={
                inv_mod.variable_id: inv_mod,
                inv_new.variable_id: inv_new,
                lt_same.variable_id: lt_same,
            },
            created_at=datetime.now(UTC),
            metadata={},
        )

        diff = engine.diff(base_state, next_state)

        assert diff.summary.total_variables_before == 3
        assert diff.summary.total_variables_after == 3
        assert diff.summary.variables_added == 1
        assert diff.summary.variables_removed == 1
        assert diff.summary.variables_modified == 1

        assert inv_new.variable_id in diff.added_variables
        assert capacity_var_id("fac_1") in diff.removed_variables

        # Check modified variable diff
        mod_diff = next(d for d in diff.variable_diffs if d.variable_id == inv_mod.variable_id)
        assert mod_diff.old_value == 100
        assert mod_diff.new_value == 250
        assert mod_diff.delta == 150.0
        assert mod_diff.direction == "increase"

    def test_diff_by_type_filters_properly(self, base_state: WorldState) -> None:
        engine = DiffEngine()

        inv_mod = StateVariable(
            variable_id=inventory_var_id("wh_1", "comp_a"),
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_1",
            entity_type="warehouse",
            value=200,
        )
        lt_mod = StateVariable(
            variable_id=lead_time_var_id("sup_1"),
            variable_type=StateVariableType.LEAD_TIME,
            entity_id="sup_1",
            entity_type="supplier",
            value=25,
        )

        next_state = WorldState(
            world_id=base_state.world_id,
            workspace_id=base_state.workspace_id,
            version=2,
            graph_version=base_state.graph_version,
            variables={
                inv_mod.variable_id: inv_mod,
                lt_mod.variable_id: lt_mod,
            },
            created_at=datetime.now(UTC),
            metadata={},
        )

        diff_inv = engine.diff_by_type(
            base_state, next_state, variable_type=StateVariableType.INVENTORY
        )
        assert len(diff_inv.variable_diffs) == 1
        assert diff_inv.variable_diffs[0].variable_id == inv_mod.variable_id

        diff_lt = engine.diff_by_type(
            base_state, next_state, variable_type=StateVariableType.LEAD_TIME
        )
        assert len(diff_lt.variable_diffs) == 1
        assert diff_lt.variable_diffs[0].variable_id == lt_mod.variable_id

    def test_diff_by_entity_filters_properly(self, base_state: WorldState) -> None:
        engine = DiffEngine()

        inv_mod = StateVariable(
            variable_id=inventory_var_id("wh_1", "comp_a"),
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_1",
            entity_type="warehouse",
            value=50,
        )
        lt_mod = StateVariable(
            variable_id=lead_time_var_id("sup_1"),
            variable_type=StateVariableType.LEAD_TIME,
            entity_id="sup_1",
            entity_type="supplier",
            value=20,
        )

        next_state = WorldState(
            world_id=base_state.world_id,
            workspace_id=base_state.workspace_id,
            version=2,
            graph_version=base_state.graph_version,
            variables={
                inv_mod.variable_id: inv_mod,
                lt_mod.variable_id: lt_mod,
            },
            created_at=datetime.now(UTC),
            metadata={},
        )

        entity_diff = engine.diff_by_entity(base_state, next_state, entity_id="wh_1")
        assert len(entity_diff.variable_diffs) == 1
        assert entity_diff.variable_diffs[0].entity_id == "wh_1"
        assert entity_diff.variable_diffs[0].delta == -50.0
        assert entity_diff.variable_diffs[0].direction == "decrease"


class TestTimeSeriesDiffEngine:
    def test_time_series_diff_computes_consecutive_and_cumulative_diffs(
        self, base_state: WorldState
    ) -> None:
        engine = TimeSeriesDiffEngine(DiffEngine())

        v1 = base_state
        v2 = WorldState(
            world_id=v1.world_id,
            workspace_id=v1.workspace_id,
            version=2,
            graph_version=1,
            variables={
                inventory_var_id("wh_1", "comp_a"): StateVariable(
                    variable_id=inventory_var_id("wh_1", "comp_a"),
                    variable_type=StateVariableType.INVENTORY,
                    entity_id="wh_1",
                    entity_type="warehouse",
                    value=150,
                )
            },
            created_at=datetime.now(UTC),
            metadata={},
        )
        v3 = WorldState(
            world_id=v1.world_id,
            workspace_id=v1.workspace_id,
            version=3,
            graph_version=1,
            variables={
                inventory_var_id("wh_1", "comp_a"): StateVariable(
                    variable_id=inventory_var_id("wh_1", "comp_a"),
                    variable_type=StateVariableType.INVENTORY,
                    entity_id="wh_1",
                    entity_type="warehouse",
                    value=300,
                )
            },
            created_at=datetime.now(UTC),
            metadata={},
        )

        ts_diff = engine.compute(world_id=v1.world_id, states=[v1, v2, v3])

        assert ts_diff.versions == [1, 2, 3]
        assert len(ts_diff.changes_per_version) == 2  # v2 and v3
        assert ts_diff.cumulative_diff.from_state.version == 1
        assert ts_diff.cumulative_diff.to_state.version == 3

        inv_key = inventory_var_id("wh_1", "comp_a")
        assert ts_diff.trends[inv_key] == [100.0, 150.0, 300.0]

    def test_time_series_diff_empty_and_single_state_handling(self, base_state: WorldState) -> None:
        engine = TimeSeriesDiffEngine(DiffEngine())

        with pytest.raises(ValueError, match="empty states list"):
            engine.compute(world_id="test", states=[])

        single_ts = engine.compute(world_id=base_state.world_id, states=[base_state])
        assert single_ts.versions == [1]
        assert len(single_ts.changes_per_version) == 0


class TestDiffFormatter:
    def test_format_summary_and_specific_changes(self, base_state: WorldState) -> None:
        engine = DiffEngine()

        inv_mod = StateVariable(
            variable_id=inventory_var_id("wh_1", "comp_a"),
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_1",
            entity_type="warehouse",
            value=250,
        )
        next_state = WorldState(
            world_id=base_state.world_id,
            workspace_id=base_state.workspace_id,
            version=2,
            graph_version=base_state.graph_version,
            variables={
                inv_mod.variable_id: inv_mod,
            },
            created_at=datetime.now(UTC),
            metadata={},
        )

        diff = engine.diff(base_state, next_state)

        # 1. format_summary
        summary_text = DiffFormatter.format_summary(diff)
        assert "State Diff:" in summary_text
        assert "v1 -> v2" in summary_text

        # 2. format_variable_change
        var_text = DiffFormatter.format_variable_change(diff, inv_mod.variable_id)
        assert var_text is not None
        assert "100 -> 250" in var_text
        assert "increase" in var_text

        # 3. format_entity_changes
        entity_text = DiffFormatter.format_entity_changes(diff, "wh_1")
        assert entity_text is not None
        assert "Entity: wh_1" in entity_text

        # 4. format_for_api
        api_data = DiffFormatter.format_for_api(diff)
        assert api_data["from_version"] == 1
        assert api_data["to_version"] == 2
        assert "summary" in api_data
        assert "entity_changes" in api_data
