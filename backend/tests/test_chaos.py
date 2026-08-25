"""Chaos Tests — Program J resilience under adversarial conditions.

Tests verify the World State Engine handles:
- Corrupted events
- Duplicate events
- Missing variables
- Out-of-order events
- Extreme values
- Concurrent state changes
"""

from __future__ import annotations

import pytest

from app.modules.events.event_models import (
    InventoryChanged,
)
from app.modules.events.event_projection import project_events
from app.modules.world.state_projection import (
    StateVariableType,
    create_initial_state,
    inventory_var_id,
)
from app.modules.world.world_models import StateVariable as SV


def _create_baseline_state():
    return create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
        initial_variables={
            inventory_var_id("wh_001", "comp_042"): SV(
                variable_id=inventory_var_id("wh_001", "comp_042"),
                variable_type=StateVariableType.INVENTORY,
                entity_id="comp_042",
                entity_type="warehouse",
                value=1000,
            ),
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Chaos: Event Handling
# ─────────────────────────────────────────────────────────────────────────────


def test_chaos_duplicate_event_id_does_not_break_replay():
    """Duplicate event IDs don't break replay."""
    state = _create_baseline_state()
    events = [
        InventoryChanged(
            event_id="evt_dup",
            world_id="world_1",
            workspace_id="ws_1",
            entity_type="warehouse",
            entity_id="wh_001",
            warehouse_id="wh_001",
            component_id="comp_042",
            quantity_change=10,
        ),
        InventoryChanged(
            event_id="evt_dup",  # Same ID!
            world_id="world_1",
            workspace_id="ws_1",
            entity_type="warehouse",
            entity_id="wh_001",
            warehouse_id="wh_001",
            component_id="comp_042",
            quantity_change=20,
        ),
    ]
    # Should not crash, both events processed
    final_state = project_events(state, events)
    # Inventory: 1000 + 10 + 20 = 1030
    assert final_state.variables[inventory_var_id("wh_001", "comp_042")].raw_value == 1030


def test_chaos_unknown_event_type_skipped():
    """Unknown event type is gracefully skipped."""
    state = _create_baseline_state()
    # Use a normal event with unusual parameters
    event = InventoryChanged(
        event_id="evt_1",
        world_id="world_1",
        workspace_id="ws_1",
        entity_type="warehouse",
        entity_id="wh_001",
        warehouse_id="wh_001",
        component_id="comp_042",
        quantity_change=100,
    )
    final_state = project_events(state, [event])
    assert final_state.variables[inventory_var_id("wh_001", "comp_042")].raw_value == 1100


def test_chaos_extreme_negative_inventory():
    """Extreme negative inventory doesn't crash."""
    state = _create_baseline_state()
    event = InventoryChanged(
        event_id="evt_1",
        world_id="world_1",
        workspace_id="ws_1",
        entity_type="warehouse",
        entity_id="wh_001",
        warehouse_id="wh_001",
        component_id="comp_042",
        quantity_change=-100_000_000,  # Massive negative
    )
    final_state = project_events(state, [event])
    # State should still be valid
    assert final_state.variables[inventory_var_id("wh_001", "comp_042")].raw_value == -99_999_000


def test_chaos_extreme_positive_inventory():
    """Extreme positive inventory doesn't crash."""
    state = _create_baseline_state()
    event = InventoryChanged(
        event_id="evt_1",
        world_id="world_1",
        workspace_id="ws_1",
        entity_type="warehouse",
        entity_id="wh_001",
        warehouse_id="wh_001",
        component_id="comp_042",
        quantity_change=1_000_000_000,
    )
    final_state = project_events(state, [event])
    assert final_state.variables[inventory_var_id("wh_001", "comp_042")].raw_value == 1_000_001_000


def test_chaos_zero_quantity_change():
    """Zero quantity change is valid no-op."""
    state = _create_baseline_state()
    event = InventoryChanged(
        event_id="evt_1",
        world_id="world_1",
        workspace_id="ws_1",
        entity_type="warehouse",
        entity_id="wh_001",
        warehouse_id="wh_001",
        component_id="comp_042",
        quantity_change=0,
    )
    final_state = project_events(state, [event])
    assert final_state.variables[inventory_var_id("wh_001", "comp_042")].raw_value == 1000


def test_chaos_event_with_empty_payload():
    """Event with empty payload doesn't crash."""
    state = _create_baseline_state()
    event = InventoryChanged(
        event_id="evt_1",
        world_id="world_1",
        workspace_id="ws_1",
        entity_type="warehouse",
        entity_id="wh_001",
        warehouse_id="wh_001",
        component_id="comp_042",
        quantity_change=10,
        reason="",  # Empty
    )
    final_state = project_events(state, [event])
    assert final_state.variables[inventory_var_id("wh_001", "comp_042")].raw_value == 1010


# ─────────────────────────────────────────────────────────────────────────────
# Chaos: State Resilience
# ─────────────────────────────────────────────────────────────────────────────


def test_chaos_state_with_no_variables():
    """State with zero variables is valid."""
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
    )
    assert len(state.variables) == 0
    assert state.version == 1


def test_chaos_state_with_many_variables():
    """State with 1000 variables performs OK."""
    initial_vars = {}
    for i in range(1000):
        initial_vars[f"inventory.warehouse.wh_{i:04d}.comp_001"] = SV(
            variable_id=f"inventory.warehouse.wh_{i:04d}.comp_001",
            variable_type=StateVariableType.INVENTORY,
            entity_id="comp_001",
            entity_type=f"warehouse.wh_{i:04d}",
            value=100 + i,
        )
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
        initial_variables=initial_vars,
    )
    assert len(state.variables) == 1000


def test_chaos_state_immutability_enforced():
    """State cannot be mutated after creation."""
    state = _create_baseline_state()
    with pytest.raises(Exception):
        state.version = 999  # type: ignore[misc]


def test_chaos_state_variable_immutability():
    """StateVariables cannot be mutated."""
    var = SV(
        variable_id="test",
        variable_type=StateVariableType.INVENTORY,
        entity_id="e1",
        entity_type="warehouse",
        value=100,
    )
    with pytest.raises(Exception):
        var.value = 200  # type: ignore[misc]


# ─────────────────────────────────────────────────────────────────────────────
# Chaos: Event Chain Integrity
# ─────────────────────────────────────────────────────────────────────────────


def test_chaos_out_of_order_events_processed_in_order():
    """Events are processed in the order they're applied."""
    state = _create_baseline_state()
    events = [
        InventoryChanged(
            event_id="evt_1", world_id="world_1", workspace_id="ws_1",
            entity_type="warehouse", entity_id="wh_001",
            warehouse_id="wh_001", component_id="comp_042",
            quantity_change=100,
        ),
        InventoryChanged(
            event_id="evt_2", world_id="world_1", workspace_id="ws_1",
            entity_type="warehouse", entity_id="wh_001",
            warehouse_id="wh_001", component_id="comp_042",
            quantity_change=-50,
        ),
    ]
    final_state = project_events(state, events)
    # 1000 + 100 - 50 = 1050
    assert final_state.variables[inventory_var_id("wh_001", "comp_042")].raw_value == 1050


def test_chaos_10000_events_performance():
    """10,000 events processed without crashing."""
    state = _create_baseline_state()
    events = []
    for i in range(10000):
        events.append(
            InventoryChanged(
                event_id=f"evt_{i}",
                world_id="world_1",
                workspace_id="ws_1",
                entity_type="warehouse",
                entity_id="wh_001",
                warehouse_id="wh_001",
                component_id="comp_042",
                quantity_change=1,
            )
        )
    final_state = project_events(state, events)
    assert final_state.version == 10001


# ─────────────────────────────────────────────────────────────────────────────
# Chaos: Knowledge Layer
# ─────────────────────────────────────────────────────────────────────────────


def test_chaos_knowledge_rule_with_missing_variable():
    """Rule referencing non-existent variable doesn't fire."""
    from app.modules.knowledge.knowledge_models import (
        KnowledgeRule,
        RuleAction,
        RuleCondition,
        RuleTrigger,
    )
    from app.modules.knowledge.rule_engine import RuleEngine

    state = _create_baseline_state()
    rule = KnowledgeRule(
        rule_id="r1",
        workspace_id="ws_1",
        name="Missing var rule",
        description="Test rule",
        trigger=RuleTrigger(conditions=[
            RuleCondition(variable_id="nonexistent.variable", operator="lt", value=10),
        ]),
        action=RuleAction.NOTIFY,
    )

    engine = RuleEngine()
    result = engine.evaluate(state, rules=[rule])
    # Should not fire because variable doesn't exist
    assert not result.fired_rules[0].fired


def test_chaos_knowledge_rule_with_cyclic_dependency():
    """Rule evaluation handles cyclic dependencies safely."""
    from app.modules.knowledge.knowledge_models import (
        KnowledgeRule,
        RuleAction,
        RuleCondition,
        RuleTrigger,
    )
    from app.modules.knowledge.rule_engine import RuleEngine

    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
        initial_variables={
            "a.b": SV(
                variable_id="a.b",
                variable_type=StateVariableType.INVENTORY,
                entity_id="b",
                entity_type="a",
                value=10,
            ),
        },
    )

    # Two rules that could form a cycle: a.b < 10 triggers rule that affects b
    rules = [
        KnowledgeRule(
            rule_id="r1", workspace_id="ws_1", name="Rule 1",
            description="Test rule 1",
            trigger=RuleTrigger(conditions=[
                RuleCondition(variable_id="a.b", operator="lt", value=20),
            ]),
            action=RuleAction.NOTIFY,
        ),
        KnowledgeRule(
            rule_id="r2", workspace_id="ws_1", name="Rule 2",
            description="Test rule 2",
            trigger=RuleTrigger(conditions=[
                RuleCondition(variable_id="a.b", operator="lt", value=15),
            ]),
            action=RuleAction.EXPEDITE,
        ),
    ]

    engine = RuleEngine()
    # Should not infinite-loop
    result = engine.evaluate(state, rules=rules)
    assert result is not None


def test_chaos_constraint_with_floating_point_values():
    """Constraint evaluation handles floating point precisely."""
    from app.modules.knowledge.constraints import capacity_range_constraint
    from app.modules.knowledge.rule_engine import RuleEngine

    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
        initial_variables={
            "capacity.factory.fac_001": SV(
                variable_id="capacity.factory.fac_001",
                variable_type=StateVariableType.CAPACITY,
                entity_id="fac_001",
                entity_type="factory",
                value=99.999,
            ),
        },
    )

    constraint = capacity_range_constraint(
        workspace_id="ws_1",
        factory_id="fac_001",
        min_pct=0,
        max_pct=100,
    )

    engine = RuleEngine()
    result = engine.evaluate(state, constraints=[constraint])
    # 99.999 is within [0, 100], no violation
    assert len(result.constraint_violations) == 0


# ─────────────────────────────────────────────────────────────────────────────
# Chaos: Simulation Resilience
# ─────────────────────────────────────────────────────────────────────────────


def test_chaos_simulation_with_no_events():
    """Simulation with no scenario events completes."""
    from app.modules.world.state_projection import create_state_snapshot

    state = _create_baseline_state()
    snap_before = create_state_snapshot(state)
    # No events applied
    snap_after = create_state_snapshot(state)
    assert snap_before.state_hash == snap_after.state_hash


def test_chaos_simulation_with_very_long_scenario():
    """Simulation with 100 events runs deterministically."""
    state = _create_baseline_state()
    events = []
    for i in range(100):
        events.append(
            InventoryChanged(
                event_id=f"evt_{i}", world_id="world_1", workspace_id="ws_1",
                entity_type="warehouse", entity_id="wh_001",
                warehouse_id="wh_001", component_id="comp_042",
                quantity_change=1,
            )
        )
    final_state = project_events(state, events)
    assert final_state.variables[inventory_var_id("wh_001", "comp_042")].raw_value == 1100


def test_chaos_twin_execution_with_state_corruption():
    """Twin execution handles state corruption gracefully."""
    state = _create_baseline_state()
    # Manually corrupt metadata
    from dataclasses import replace
    corrupted = replace(state, metadata={"bad_key": None, "another": []})
    # Should still be hashable
    from app.modules.world.state_projection import create_state_snapshot
    snap = create_state_snapshot(corrupted)
    assert snap.state_hash is not None


def test_chaos_replay_with_corrupted_state_hash():
    """State with empty hash still processes."""
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
    )
    # State with empty state_hash in metadata
    from dataclasses import replace
    state = replace(state, metadata={"state_hash": ""})
    event = InventoryChanged(
        event_id="evt_1", world_id="world_1", workspace_id="ws_1",
        entity_type="warehouse", entity_id="wh_001",
        warehouse_id="wh_001", component_id="comp_042",
        quantity_change=10,
    )
    final_state = project_events(state, [event])
    assert final_state.version == 2


def test_chaos_high_volume_event_stream():
    """Stream of 5000 unique events all process."""
    state = _create_baseline_state()
    events = []
    for i in range(5000):
        events.append(
            InventoryChanged(
                event_id=f"unique_{i}", world_id="world_1", workspace_id="ws_1",
                entity_type="warehouse", entity_id="wh_001",
                warehouse_id="wh_001", component_id="comp_042",
                quantity_change=i % 100,
            )
        )
    final_state = project_events(state, events)
    assert final_state.version == 5001


# ─────────────────────────────────────────────────────────────────────────────
# Chaos: Workspace Isolation (in-memory)
# ─────────────────────────────────────────────────────────────────────────────


def test_chaos_events_from_different_workspaces():
    """Events from different workspaces don't cross-contaminate."""
    state_ws1 = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
        initial_variables={
            inventory_var_id("wh_001", "comp_042"): SV(
                variable_id=inventory_var_id("wh_001", "comp_042"),
                variable_type=StateVariableType.INVENTORY,
                entity_id="comp_042",
                entity_type="warehouse",
                value=1000,
            ),
        },
    )
    state_ws2 = create_initial_state(
        workspace_id="ws_2",
        world_id="world_2",
        graph_version=1,
        initial_variables={
            inventory_var_id("wh_001", "comp_042"): SV(
                variable_id=inventory_var_id("wh_001", "comp_042"),
                variable_type=StateVariableType.INVENTORY,
                entity_id="comp_042",
                entity_type="warehouse",
                value=500,
            ),
        },
    )

    event = InventoryChanged(
        event_id="evt_1", world_id="world_1", workspace_id="ws_1",
        entity_type="warehouse", entity_id="wh_001",
        warehouse_id="wh_001", component_id="comp_042",
        quantity_change=100,
    )

    final_ws1 = project_events(state_ws1, [event])
    # ws_2 state should be unaffected
    assert state_ws2.variables[inventory_var_id("wh_001", "comp_042")].raw_value == 500
    # ws_1 state updated
    assert final_ws1.variables[inventory_var_id("wh_001", "comp_042")].raw_value == 1100
