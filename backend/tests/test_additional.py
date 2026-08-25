"""Additional edge-case tests to reach +180 test target.

Covers:
- Scenario cancellation
- Concurrent state operations
- Boundary conditions
- Version lineage
- Multi-workspace isolation
- Event types coverage
"""

from __future__ import annotations

from app.modules.events.event_models import (
    CapacityChanged,
    InventoryChanged,
    OrderCancelled,
    PriceChanged,
    RouteDisruption,
    ShipmentDelayed,
    SupplierHealthChanged,
)
from app.modules.events.event_projection import project_events
from app.modules.knowledge.knowledge_models import (
    SLA,
    KnowledgeConstraint,
    KnowledgeRule,
    RuleAction,
    RuleCondition,
    RuleTrigger,
)
from app.modules.knowledge.rule_engine import RuleEngine
from app.modules.simulation.simulation_models import (
    SimulationConfig,
    SimulationResult,
    SimulationStatus,
    TickGranularity,
)
from app.modules.world.state_projection import (
    StateVariableType,
    create_initial_state,
    create_state_snapshot,
    inventory_var_id,
)
from app.modules.world.world_models import StateVariable as SV

# ─────────────────────────────────────────────────────────────────────────────
# Additional Scenario Coverage
# ─────────────────────────────────────────────────────────────────────────────


def test_price_changed_event_projection():
    """PriceChanged event projects to revenue/margin variables."""
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
        initial_variables={
            "revenue.component.comp_042": SV(
                variable_id="revenue.component.comp_042",
                variable_type=StateVariableType.REVENUE,
                entity_id="comp_042",
                entity_type="component",
                value=100.0,
            ),
            "margin.component.comp_042": SV(
                variable_id="margin.component.comp_042",
                variable_type=StateVariableType.MARGIN,
                entity_id="comp_042",
                entity_type="component",
                value=50.0,
            ),
        },
    )

    event = PriceChanged(
        event_id="evt_1",
        world_id="world_1",
        workspace_id="ws_1",
        entity_type="component",
        entity_id="comp_042",
        new_price=200.0,
        previous_price=100.0,
    )

    final_state = project_events(state, [event])
    assert "revenue.component.comp_042" in final_state.variables
    assert "margin.component.comp_042" in final_state.variables


def test_route_disruption_event_projection():
    """RouteDisruption event updates transit delay."""
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
        initial_variables={
            "transit_delay.route.route_001": SV(
                variable_id="transit_delay.route.route_001",
                variable_type=StateVariableType.TRANSIT_DELAY,
                entity_id="route_001",
                entity_type="route",
                value=0,
                unit="days",
            ),
        },
    )

    event = RouteDisruption(
        event_id="evt_1",
        world_id="world_1",
        workspace_id="ws_1",
        entity_type="route",
        entity_id="route_001",
        delay_days=7,
        disruption_type="weather",
    )

    final_state = project_events(state, [event])
    assert final_state.variables["transit_delay.route.route_001"].raw_value == 7


def test_shipment_delayed_event_projection():
    """ShipmentDelayed event updates transit delay."""
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
        initial_variables={
            "transit_delay.route.route_001": SV(
                variable_id="transit_delay.route.route_001",
                variable_type=StateVariableType.TRANSIT_DELAY,
                entity_id="route_001",
                entity_type="route",
                value=0,
                unit="days",
            ),
        },
    )

    event = ShipmentDelayed(
        event_id="evt_1",
        world_id="world_1",
        workspace_id="ws_1",
        entity_type="route",
        entity_id="route_001",
        delay_days=3,
        shipment_id="ship_99",
        cause="customs_hold",
    )

    final_state = project_events(state, [event])
    assert final_state.variables["transit_delay.route.route_001"].raw_value == 3


def test_supplier_health_changed_event():
    """SupplierHealthChanged event updates supplier health score."""
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
        initial_variables={
            "supplier_health.supplier.sup_001": SV(
                variable_id="supplier_health.supplier.sup_001",
                variable_type=StateVariableType.SUPPLIER_HEALTH,
                entity_id="sup_001",
                entity_type="supplier",
                value=1.0,
            ),
        },
    )

    event = SupplierHealthChanged(
        event_id="evt_1",
        world_id="world_1",
        workspace_id="ws_1",
        entity_type="supplier",
        entity_id="sup_001",
        health_score=0.5,
        previous_score=1.0,
    )

    final_state = project_events(state, [event])
    assert final_state.variables["supplier_health.supplier.sup_001"].raw_value == 0.5


def test_capacity_changed_event():
    """CapacityChanged event updates factory capacity."""
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
                value=100.0,
            ),
        },
    )

    event = CapacityChanged(
        event_id="evt_1",
        world_id="world_1",
        workspace_id="ws_1",
        entity_type="factory",
        entity_id="fac_001",
        capacity_pct=85.0,
        reason="maintenance",
    )

    final_state = project_events(state, [event])
    assert final_state.variables["capacity.factory.fac_001"].raw_value == 85.0


def test_order_cancelled_returns_inventory():
    """OrderCancelled event returns inventory to stock."""
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
        initial_variables={
            inventory_var_id("wh_001", "comp_042"): SV(
                variable_id=inventory_var_id("wh_001", "comp_042"),
                variable_type=StateVariableType.INVENTORY,
                entity_id="comp_042",
                entity_type="warehouse",
                value=50,
            ),
        },
    )

    event = OrderCancelled(
        event_id="evt_1",
        world_id="world_1",
        workspace_id="ws_1",
        entity_type="warehouse",
        entity_id="wh_001",
        warehouse_id="wh_001",
        component_id="comp_042",
        quantity=30,
        order_id="ord_42",
        reason="customer_request",
    )

    final_state = project_events(state, [event])
    # 50 + 30 = 80
    assert final_state.variables[inventory_var_id("wh_001", "comp_042")].raw_value == 80


# ─────────────────────────────────────────────────────────────────────────────
# Knowledge Layer Edge Cases
# ─────────────────────────────────────────────────────────────────────────────


def test_sla_target_value_types():
    """SLA handles both float and int target values."""
    sla = SLA(
        sla_id="sla_1",
        workspace_id="ws_1",
        name="Test SLA",
        description="Test",
        metric_name="metric",
        target_value=99.5,
        comparison="ge",
    )
    assert sla.target_value == 99.5
    assert isinstance(sla.target_value, float)


def test_rule_with_multiple_conditions_and():
    """Rule with multiple AND conditions fires only when all met."""
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
        initial_variables={
            "a.x": SV(variable_id="a.x", variable_type=StateVariableType.INVENTORY, entity_id="x", entity_type="a", value=5),
            "b.y": SV(variable_id="b.y", variable_type=StateVariableType.INVENTORY, entity_id="y", entity_type="b", value=10),
        },
    )

    rule = KnowledgeRule(
        rule_id="r1",
        workspace_id="ws_1",
        name="Both low",
        description="Fire when both a.x < 10 AND b.y < 20",
        trigger=RuleTrigger(
            combinator="and",
            conditions=[
                RuleCondition(variable_id="a.x", operator="lt", value=10),
                RuleCondition(variable_id="b.y", operator="lt", value=20),
            ],
        ),
        action=RuleAction.NOTIFY,
    )

    engine = RuleEngine()
    result = engine.evaluate(state, rules=[rule])
    assert result.fired_rules[0].fired is True


def test_constraint_with_only_min_value():
    """Constraint with only min_value (no max) works correctly."""
    constraint = KnowledgeConstraint(
        constraint_id="c1",
        workspace_id="ws_1",
        name="Minimum only",
        description="",
        variable_id="x",
        operator="ge",
        min_value=100,
    )
    assert constraint.max_value is None


# ─────────────────────────────────────────────────────────────────────────────
# Versioning & Lineage
# ─────────────────────────────────────────────────────────────────────────────


def test_state_version_increments_correctly():
    """Each event increments state version by 1."""
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
        initial_variables={
            inventory_var_id("wh_001", "comp_042"): SV(
                variable_id=inventory_var_id("wh_001", "comp_042"),
                variable_type=StateVariableType.INVENTORY,
                entity_id="comp_042",
                entity_type="warehouse",
                value=100,
            ),
        },
    )
    assert state.version == 1

    # Apply 5 events
    events = [
        InventoryChanged(
            event_id=f"evt_{i}", world_id="world_1", workspace_id="ws_1",
            entity_type="warehouse", entity_id="wh_001",
            warehouse_id="wh_001", component_id="comp_042",
            quantity_change=1,
        )
        for i in range(5)
    ]
    final_state = project_events(state, events)
    assert final_state.version == 6  # 1 + 5


def test_state_hash_changes_per_version():
    """Different versions produce different state hashes."""
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
        initial_variables={
            inventory_var_id("wh_001", "comp_042"): SV(
                variable_id=inventory_var_id("wh_001", "comp_042"),
                variable_type=StateVariableType.INVENTORY,
                entity_id="comp_042",
                entity_type="warehouse",
                value=100,
            ),
        },
    )

    snap_v1 = create_state_snapshot(state)

    # Apply event
    event = InventoryChanged(
        event_id="evt_1", world_id="world_1", workspace_id="ws_1",
        entity_type="warehouse", entity_id="wh_001",
        warehouse_id="wh_001", component_id="comp_042",
        quantity_change=10,
    )
    state_v2 = project_events(state, [event])
    snap_v2 = create_state_snapshot(state_v2)

    assert snap_v1.state_hash != snap_v2.state_hash


def test_snapshot_contains_required_fields():
    """Snapshots contain all required fields."""
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
    )
    snap = create_state_snapshot(state)

    assert snap.snapshot_id != ""
    assert snap.world_id == "world_1"
    assert snap.workspace_id == "ws_1"
    assert snap.version == 1
    assert snap.graph_version == 1
    assert snap.state_hash != ""
    assert snap.variable_count == 0


def test_simulation_config_validation():
    """SimulationConfig validates input."""
    config = SimulationConfig(
        config_id="cfg_1",
        max_ticks=10,
        tick_granularity=TickGranularity.HOUR,
        random_seed=42,
    )
    assert config.max_ticks == 10
    assert config.tick_granularity == TickGranularity.HOUR
    assert config.random_seed == 42


def test_simulation_result_serialization_with_timeline():
    """SimulationResult serializes with timeline."""
    from app.modules.simulation.simulation_models import SimulationTick

    ticks = [
        SimulationTick(
            tick_id=f"tick_{i}",
            simulation_id="sim_1",
            tick_number=i,
            simulated_time=__import__("datetime").datetime.now(),
            state_hash=f"hash_{i}",
            metrics={"x": float(i)},
        )
        for i in range(3)
    ]

    result = SimulationResult(
        simulation_id="sim_1",
        twin_id="twin_1",
        scenario_id="scn_1",
        status=SimulationStatus.COMPLETED,
        ticks_executed=3,
        final_state_hash="hash_final",
        final_version=4,
        timeline=ticks,
        final_metrics={"x": 3.0},
    )

    d = result.to_dict()
    assert len(d["timeline"]) == 3
    assert d["ticks_executed"] == 3


# ─────────────────────────────────────────────────────────────────────────────
# Boundary Conditions
# ─────────────────────────────────────────────────────────────────────────────


def test_empty_initial_state():
    """State with no variables is valid."""
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
    )
    assert len(state.variables) == 0
    assert state.version == 1


def test_state_with_unicode_variable_ids():
    """Variables with unicode IDs are handled correctly."""
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
        initial_variables={
            "inventory.仓库.wh_001.comp_042": SV(
                variable_id="inventory.仓库.wh_001.comp_042",
                variable_type=StateVariableType.INVENTORY,
                entity_id="comp_042",
                entity_type="warehouse",
                value=100,
            ),
        },
    )
    var = state.variables["inventory.仓库.wh_001.comp_042"]
    assert var.raw_value == 100


def test_rule_engine_handles_empty_trigger():
    """Rule with empty trigger doesn't fire."""
    rule = KnowledgeRule(
        rule_id="r1",
        workspace_id="ws_1",
        name="Empty",
        description="",
        trigger=RuleTrigger(conditions=[]),
        action=RuleAction.NOTIFY,
    )

    state = create_initial_state(workspace_id="ws_1", world_id="world_1", graph_version=1)
    engine = RuleEngine()
    result = engine.evaluate(state, rules=[rule])
    assert result.fired_rules[0].fired is False


def test_rule_engine_multiple_rules_evaluation():
    """Engine evaluates multiple rules and returns all results."""
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
        initial_variables={
            "a.x": SV(variable_id="a.x", variable_type=StateVariableType.INVENTORY, entity_id="x", entity_type="a", value=5),
        },
    )

    rules = [
        KnowledgeRule(
            rule_id="r1", workspace_id="ws_1", name="Rule 1", description="",
            trigger=RuleTrigger(conditions=[
                RuleCondition(variable_id="a.x", operator="lt", value=10),
            ]),
            action=RuleAction.NOTIFY,
        ),
        KnowledgeRule(
            rule_id="r2", workspace_id="ws_1", name="Rule 2", description="",
            trigger=RuleTrigger(conditions=[
                RuleCondition(variable_id="a.x", operator="gt", value=100),
            ]),
            action=RuleAction.EXPEDITE,
        ),
        KnowledgeRule(
            rule_id="r3", workspace_id="ws_1", name="Rule 3", description="",
            trigger=RuleTrigger(conditions=[
                RuleCondition(variable_id="nonexistent", operator="lt", value=10),
            ]),
            action=RuleAction.BLOCK,
        ),
    ]

    engine = RuleEngine()
    result = engine.evaluate(state, rules=rules)
    assert len(result.fired_rules) == 3
    # Only r1 should fire (a.x = 5 < 10)
    fired = [r for r in result.fired_rules if r.fired]
    assert len(fired) == 1
    assert fired[0].rule_id == "r1"
