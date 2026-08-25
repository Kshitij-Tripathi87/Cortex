"""Smoke tests for World State Engine — Program J Workstream A.

Verifies core invariants without requiring a database:
- Models are immutable (frozen dataclasses)
- State projection is pure (deterministic)
- Event-to-transition projection works
- State hashes are deterministic
- Diff engine produces correct comparisons
"""

from __future__ import annotations

import pytest

from app.modules.world.state_diff import (
    DiffEngine,
)
from app.modules.world.state_projection import (
    apply_transition,
    create_initial_state,
    create_state_snapshot,
    inventory_var_id,
    project_event_to_transition,
    project_inventory_change,
    project_order_placed,
    validate_state_hash,
)
from app.modules.world.state_validation_helpers import make_event
from app.modules.world.world_models import (
    StateVariable,
    StateVariableType,
)
from app.modules.world.world_validation import WorldValidator


def test_state_variable_is_frozen():
    """State variables are immutable."""
    var = StateVariable(
        variable_id="inventory.wh_001.comp_042",
        variable_type=StateVariableType.INVENTORY,
        entity_id="comp_042",
        entity_type="warehouse",
        value=100,
        unit="units",
    )
    with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
        var.value = 200  # type: ignore[misc]


def test_initial_state_has_version_1():
    """Initial state starts at version 1."""
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
    )
    assert state.version == 1
    assert state.workspace_id == "ws_1"
    assert state.world_id == "world_1"
    assert state.graph_version == 1
    assert state.variables == {}


def test_inventory_projection_increments_value():
    """Inventory projection computes old_value + quantity_change."""
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
        initial_variables={
            inventory_var_id("wh_001", "comp_042"): StateVariable(
                variable_id=inventory_var_id("wh_001", "comp_042"),
                variable_type=StateVariableType.INVENTORY,
                entity_id="comp_042",
                entity_type="warehouse",
                value=100,
                unit="units",
            ),
        },
    )

    transition = project_inventory_change(state, "wh_001", "comp_042", quantity_change=50)
    assert transition.old_values[inventory_var_id("wh_001", "comp_042")] == 100
    assert transition.new_values[inventory_var_id("wh_001", "comp_042")] == 150
    assert transition.transition_type.value == "inventory_change"


def test_apply_transition_produces_new_version():
    """Applying a transition increments version by 1."""
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
        initial_variables={
            inventory_var_id("wh_001", "comp_042"): StateVariable(
                variable_id=inventory_var_id("wh_001", "comp_042"),
                variable_type=StateVariableType.INVENTORY,
                entity_id="comp_042",
                entity_type="warehouse",
                value=100,
                unit="units",
            ),
        },
    )

    transition = project_inventory_change(state, "wh_001", "comp_042", quantity_change=50)
    new_state = apply_transition(state, transition)

    assert new_state.version == state.version + 1
    assert new_state.variables[inventory_var_id("wh_001", "comp_042")].raw_value == 150
    assert state.version == 1  # original state unchanged


def test_state_hash_is_deterministic():
    """Same state produces the same hash."""
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
        initial_variables={
            inventory_var_id("wh_001", "comp_042"): StateVariable(
                variable_id=inventory_var_id("wh_001", "comp_042"),
                variable_type=StateVariableType.INVENTORY,
                entity_id="comp_042",
                entity_type="warehouse",
                value=100,
                unit="units",
            ),
        },
    )

    snap1 = create_state_snapshot(state)
    snap2 = create_state_snapshot(state)

    assert snap1.state_hash == snap2.state_hash
    assert validate_state_hash(state, snap1.state_hash)


def test_event_to_transition_projection():
    """Events can be projected to transitions for replay."""
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
        initial_variables={
            inventory_var_id("wh_001", "comp_042"): StateVariable(
                variable_id=inventory_var_id("wh_001", "comp_042"),
                variable_type=StateVariableType.INVENTORY,
                entity_id="comp_042",
                entity_type="warehouse",
                value=100,
                unit="units",
            ),
        },
    )

    event = make_event(
        event_id="evt_1",
        world_id="world_1",
        workspace_id="ws_1",
        entity_type="warehouse",
        entity_id="wh_001",
        event_type="inventory_changed",
        payload={"warehouse_id": "wh_001", "component_id": "comp_042", "quantity_change": 25},
    )

    transition = project_event_to_transition(state, event)
    assert transition is not None
    assert transition.new_values[inventory_var_id("wh_001", "comp_042")] == 125

    new_state = apply_transition(state, transition)
    assert new_state.variables[inventory_var_id("wh_001", "comp_042")].raw_value == 125


def test_order_placed_decreases_inventory():
    """Order placement consumes inventory."""
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
        initial_variables={
            inventory_var_id("wh_001", "comp_042"): StateVariable(
                variable_id=inventory_var_id("wh_001", "comp_042"),
                variable_type=StateVariableType.INVENTORY,
                entity_id="comp_042",
                entity_type="warehouse",
                value=100,
                unit="units",
            ),
        },
    )

    transition = project_order_placed(state, "wh_001", "comp_042", quantity=30)
    new_state = apply_transition(state, transition)

    assert new_state.variables[inventory_var_id("wh_001", "comp_042")].raw_value == 70


def test_diff_engine_detects_changes():
    """Diff engine identifies added, removed, and changed variables."""
    from_state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
        initial_variables={
            "inventory.a.b": StateVariable(
                variable_id="inventory.a.b",
                variable_type=StateVariableType.INVENTORY,
                entity_id="b",
                entity_type="a",
                value=100,
            ),
            "demand.x": StateVariable(
                variable_id="demand.x",
                variable_type=StateVariableType.DEMAND,
                entity_id="x",
                entity_type="component",
                value=50,
            ),
        },
    )

    to_state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
        initial_variables={
            "inventory.a.b": StateVariable(
                variable_id="inventory.a.b",
                variable_type=StateVariableType.INVENTORY,
                entity_id="b",
                entity_type="a",
                value=150,  # changed
            ),
            "capacity.f1": StateVariable(  # added
                variable_id="capacity.f1",
                variable_type=StateVariableType.CAPACITY,
                entity_id="f1",
                entity_type="factory",
                value=75.0,
            ),
            # demand.x removed
        },
    )

    diff = DiffEngine().diff(from_state, to_state)
    assert any(d.variable_id == "inventory.a.b" for d in diff.variable_diffs)
    assert "capacity.f1" in diff.added_variables
    assert "demand.x" in diff.removed_variables


def test_world_validator_detects_negative_inventory():
    """Validator flags negative inventory."""
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
        initial_variables={
            inventory_var_id("wh_001", "comp_042"): StateVariable(
                variable_id=inventory_var_id("wh_001", "comp_042"),
                variable_type=StateVariableType.INVENTORY,
                entity_id="comp_042",
                entity_type="warehouse",
                value=-50,  # Invalid!
                unit="units",
            ),
        },
    )

    validator = WorldValidator()
    result = validator.validate(state)
    assert not result.is_valid
    assert any(
        "negative" in issue.message.lower() or "inventory" in issue.message.lower()
        for issue in result.issues
    )


def test_world_validator_detects_invalid_capacity():
    """Validator flags capacity outside [0, 100] as a warning."""
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
        initial_variables={
            "capacity.f1": StateVariable(
                variable_id="capacity.f1",
                variable_type=StateVariableType.CAPACITY,
                entity_id="f1",
                entity_type="factory",
                value=150.0,  # Invalid: > 100%
            ),
        },
    )

    validator = WorldValidator()
    result = validator.validate(state)
    # Over-capacity is a warning (temporary surge), not a hard error
    assert any(i.rule == "over_capacity" for i in result.issues)


def test_state_variables_are_serializable():
    """State variables serialize/deserialize via to_dict."""
    var = StateVariable(
        variable_id="inventory.wh_001.comp_042",
        variable_type=StateVariableType.INVENTORY,
        entity_id="comp_042",
        entity_type="warehouse",
        value=100,
        unit="units",
        metadata={"source": "test"},
    )
    d = var.to_dict()
    assert d["variable_id"] == "inventory.wh_001.comp_042"
    assert d["variable_type"] == "inventory"
    assert d["value"] == 100
    assert d["metadata"] == {"source": "test"}


def test_world_state_get_variables_by_type():
    """WorldState.query_by_type returns correct variables."""
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
        initial_variables={
            "inventory.wh_001.comp_042": StateVariable(
                variable_id="inventory.wh_001.comp_042",
                variable_type=StateVariableType.INVENTORY,
                entity_id="comp_042",
                entity_type="warehouse",
                value=100,
            ),
            "inventory.wh_002.comp_042": StateVariable(
                variable_id="inventory.wh_002.comp_042",
                variable_type=StateVariableType.INVENTORY,
                entity_id="comp_042",
                entity_type="warehouse",
                value=200,
            ),
            "demand.comp_042": StateVariable(
                variable_id="demand.comp_042",
                variable_type=StateVariableType.DEMAND,
                entity_id="comp_042",
                entity_type="component",
                value=50,
            ),
        },
    )

    inventory_vars = state.get_variables_by_type(StateVariableType.INVENTORY)
    assert len(inventory_vars) == 2

    demand_vars = state.get_variables_by_type(StateVariableType.DEMAND)
    assert len(demand_vars) == 1


def test_replay_determinism():
    """Same events produce same final state (replay determinism — Acceptance criterion)."""
    initial = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
        initial_variables={
            inventory_var_id("wh_001", "comp_042"): StateVariable(
                variable_id=inventory_var_id("wh_001", "comp_042"),
                variable_type=StateVariableType.INVENTORY,
                entity_id="comp_042",
                entity_type="warehouse",
                value=100,
            ),
        },
    )

    events = [
        make_event(
            event_id=f"evt_{i}",
            world_id="world_1",
            workspace_id="ws_1",
            entity_type="warehouse",
            entity_id="wh_001",
            event_type="inventory_changed",
            payload={"warehouse_id": "wh_001", "component_id": "comp_042", "quantity_change": 10},
        )
        for i in range(5)
    ]

    state_a = initial
    state_b = initial
    for event in events:
        t_a = project_event_to_transition(state_a, event)
        t_b = project_event_to_transition(state_b, event)
        assert t_a is not None and t_b is not None
        state_a = apply_transition(state_a, t_a)
        state_b = apply_transition(state_b, t_b)

    snap_a = create_state_snapshot(state_a)
    snap_b = create_state_snapshot(state_b)
    assert snap_a.state_hash == snap_b.state_hash
    assert state_a.variables == state_b.variables
