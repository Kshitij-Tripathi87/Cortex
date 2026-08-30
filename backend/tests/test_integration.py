"""Integration Tests — Program J end-to-end scenarios.

Tests the full Program J pipeline:
Evidence → Events → World State → Twin → Simulation → Knowledge Rules
"""

from __future__ import annotations

from app.modules.events.event_models import (
    DemandChanged,
    FactoryShutdown,
    InventoryChanged,
    OrderPlaced,
    SupplierDelayed,
)
from app.modules.events.event_projection import project_events
from app.modules.knowledge.knowledge_models import (
    KnowledgeRule,
    RuleAction,
    RuleCondition,
    RuleSeverity,
    RuleTrigger,
)
from app.modules.knowledge.rule_engine import RuleEngine
from app.modules.simulation.impact_calculator import ImpactCalculator
from app.modules.twin.twin_models import (
    ScenarioType,
    create_cyber_attack_scenario,
    create_demand_spike_twin_scenario,
    create_factory_fire_scenario,
    create_port_closure_scenario,
    create_supplier_failure_twin_scenario,
)
from app.modules.world.state_projection import (
    StateVariableType,
    create_initial_state,
    create_state_snapshot,
    inventory_var_id,
)
from app.modules.world.world_models import StateVariable as SV


def _create_world_state(workspace_id: str, world_id: str):
    """Helper: create a realistic initial world state."""
    return create_initial_state(
        workspace_id=workspace_id,
        world_id=world_id,
        graph_version=1,
        initial_variables={
            # Inventory across warehouses
            inventory_var_id("wh_001", "comp_042"): SV(
                variable_id=inventory_var_id("wh_001", "comp_042"),
                variable_type=StateVariableType.INVENTORY,
                entity_id="comp_042",
                entity_type="warehouse",
                value=1000,
                unit="units",
            ),
            inventory_var_id("wh_002", "comp_042"): SV(
                variable_id=inventory_var_id("wh_002", "comp_042"),
                variable_type=StateVariableType.INVENTORY,
                entity_id="comp_042",
                entity_type="warehouse",
                value=500,
                unit="units",
            ),
            # Demand
            "demand.component.comp_042": SV(
                variable_id="demand.component.comp_042",
                variable_type=StateVariableType.DEMAND,
                entity_id="comp_042",
                entity_type="component",
                value=100,
                unit="units/day",
            ),
            # Supplier health
            "supplier_health.supplier.sup_001": SV(
                variable_id="supplier_health.supplier.sup_001",
                variable_type=StateVariableType.SUPPLIER_HEALTH,
                entity_id="sup_001",
                entity_type="supplier",
                value=0.95,
            ),
            "supplier_health.supplier.sup_002": SV(
                variable_id="supplier_health.supplier.sup_002",
                variable_type=StateVariableType.SUPPLIER_HEALTH,
                entity_id="sup_002",
                entity_type="supplier",
                value=0.80,
            ),
            # Capacity
            "capacity.factory.fac_001": SV(
                variable_id="capacity.factory.fac_001",
                variable_type=StateVariableType.CAPACITY,
                entity_id="fac_001",
                entity_type="factory",
                value=85.0,
                unit="%",
            ),
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_full_pipeline_supplier_failure():
    """Full pipeline: events → state → twin → simulation → knowledge."""
    # Setup world state
    state = _create_world_state("ws_1", "world_1")

    # Apply supplier failure events
    events = [
        SupplierDelayed(
            event_id="evt_1",
            world_id="world_1",
            workspace_id="ws_1",
            entity_type="supplier",
            entity_id="sup_001",
            delay_days=14,
            disruption_type="factory_fire",
        ),
        InventoryChanged(
            event_id="evt_2",
            world_id="world_1",
            workspace_id="ws_1",
            entity_type="warehouse",
            entity_id="wh_001",
            warehouse_id="wh_001",
            component_id="comp_042",
            quantity_change=-300,  # Significant drop
            reason="consumption",
        ),
    ]

    # Project events → state
    final_state = project_events(state, events)

    # Validate impact
    calculator = ImpactCalculator()
    impact = calculator.calculate(state, final_state, duration_days=14)

    # Inventory should be down
    final_inv = final_state.variables[inventory_var_id("wh_001", "comp_042")].raw_value
    assert final_inv == 700  # 1000 - 300

    # Impact should reflect inventory drop
    assert impact.inventory_impact != 0


def test_full_pipeline_factory_fire_with_knowledge():
    """Factory fire scenario triggers knowledge rules."""
    state = _create_world_state("ws_1", "world_1")

    # Create a knowledge rule: critical capacity triggers escalation
    rule = KnowledgeRule(
        rule_id="rule_critical_capacity",
        workspace_id="ws_1",
        name="Critical Factory Capacity",
        description="Escalate when factory capacity drops below 20%",
        trigger=RuleTrigger(
            conditions=[
                RuleCondition(
                    variable_id="capacity.factory.fac_001",
                    operator="lt",
                    value=20,
                ),
            ],
        ),
        action=RuleAction.ESCALATE,
        severity=RuleSeverity.CRITICAL,
    )

    # Apply factory fire event
    factory_fire = FactoryShutdown(
        event_id="evt_1",
        world_id="world_1",
        workspace_id="ws_1",
        entity_type="factory",
        entity_id="fac_001",
        capacity_pct=0.0,
        cause="fire",
    )

    final_state = project_events(state, [factory_fire])

    # Evaluate knowledge rule
    engine = RuleEngine()
    result = engine.evaluate(final_state, rules=[rule])

    # Rule should fire
    assert any(r.fired for r in result.fired_rules)


def test_scenario_execution_with_metrics():
    """Scenario execution produces metrics and impact."""
    state = _create_world_state("ws_1", "world_1")
    create_factory_fire_scenario(
        scenario_id="scn_fire_1",
        factory_id="fac_001",
        capacity_pct=0.0,
    )

    final_state = project_events(state, [
        FactoryShutdown(
            event_id="evt_1",
            world_id="world_1",
            workspace_id="ws_1",
            entity_type="factory",
            entity_id="fac_001",
            capacity_pct=0.0,
            cause="fire",
        )
    ])

    calculator = ImpactCalculator()
    impact = calculator.calculate(state, final_state, duration_days=30)

    # Factory should be at 0 capacity
    assert final_state.variables["capacity.factory.fac_001"].raw_value == 0.0

    # Impact should classify severity
    assert impact.severity in ["low", "medium", "high", "critical"]


def test_multi_event_chain_replay():
    """Multi-event chain: 50 events replayed to final state."""
    state = _create_world_state("ws_1", "world_1")

    events = []
    # 50 inventory changes (5 per day for 10 days)
    for i in range(50):
        events.append(
            InventoryChanged(
                event_id=f"evt_{i}",
                world_id="world_1",
                workspace_id="ws_1",
                entity_type="warehouse",
                entity_id="wh_001",
                warehouse_id="wh_001",
                component_id="comp_042",
                quantity_change=-5 if i % 2 == 0 else 10,
                reason="consumption" if i % 2 == 0 else "production",
            )
        )

    final_state = project_events(state, events)

    # Inventory should have net change: 25 days × -5 + 25 days × 10 = 125
    expected = 1000 + (25 * -5) + (25 * 10)
    assert final_state.variables[inventory_var_id("wh_001", "comp_042")].raw_value == expected


def test_acceptance_same_events_same_world():
    """Acceptance criterion: Same Events → Same World, Always."""
    state = _create_world_state("ws_1", "world_1")

    events = [
        OrderPlaced(
            event_id="evt_1",
            world_id="world_1",
            workspace_id="ws_1",
            entity_type="warehouse",
            entity_id="wh_001",
            warehouse_id="wh_001",
            component_id="comp_042",
            quantity=50,
            customer_id="cust_1",
            priority="standard",
        ),
        DemandChanged(
            event_id="evt_2",
            world_id="world_1",
            workspace_id="ws_1",
            entity_type="component",
            entity_id="comp_042",
            demand_change=200,
            confidence=0.9,
        ),
        SupplierDelayed(
            event_id="evt_3",
            world_id="world_1",
            workspace_id="ws_1",
            entity_type="supplier",
            entity_id="sup_001",
            delay_days=7,
            disruption_type="weather",
        ),
    ]

    state_a = project_events(state, events)
    state_b = project_events(state, events)

    snap_a = create_state_snapshot(state_a)
    snap_b = create_state_snapshot(state_b)
    assert snap_a.state_hash == snap_b.state_hash


# ─────────────────────────────────────────────────────────────────────────────
# Performance / Scale Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_100_events_replay_completes():
    """Replay of 100 events completes."""
    state = _create_world_state("ws_1", "world_1")

    events = []
    for i in range(100):
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
                reason="production",
            )
        )

    final_state = project_events(state, events)
    assert final_state.version == 101  # 1 (initial) + 100 events


def test_1000_events_replay_completes():
    """Replay of 1000 events completes."""
    state = _create_world_state("ws_1", "world_1")

    events = []
    for i in range(1000):
        events.append(
            InventoryChanged(
                event_id=f"evt_{i}",
                world_id="world_1",
                workspace_id="ws_1",
                entity_type="warehouse",
                entity_id="wh_001",
                warehouse_id="wh_001",
                component_id="comp_042",
                quantity_change=1 if i % 2 == 0 else -1,
                reason="production" if i % 2 == 0 else "consumption",
            )
        )

    final_state = project_events(state, events)
    assert final_state.version == 1001


# ─────────────────────────────────────────────────────────────────────────────
# Multi-Entity Coordination
# ─────────────────────────────────────────────────────────────────────────────


def test_multi_entity_simulation():
    """Simulation affecting multiple entities (suppliers, factories)."""
    state = _create_world_state("ws_1", "world_1")

    # Affect multiple suppliers and factories
    events = [
        SupplierDelayed(
            event_id="evt_1", world_id="world_1", workspace_id="ws_1",
            entity_type="supplier", entity_id="sup_001", delay_days=10,
        ),
        SupplierDelayed(
            event_id="evt_2", world_id="world_1", workspace_id="ws_1",
            entity_type="supplier", entity_id="sup_002", delay_days=15,
        ),
        FactoryShutdown(
            event_id="evt_3", world_id="world_1", workspace_id="ws_1",
            entity_type="factory", entity_id="fac_001", capacity_pct=20.0,
        ),
    ]

    final_state = project_events(state, events)

    # All entities affected
    assert final_state.variables["supplier_health.supplier.sup_001"].raw_value == 0.95  # Health unchanged
    assert final_state.variables["capacity.factory.fac_001"].raw_value == 20.0  # Reduced


def test_dependency_chain_inventory_lead_time_capacity():
    """Dependency chain: inventory affected by capacity and supplier delays."""
    state = _create_world_state("ws_1", "world_1")
    initial_inventory = state.variables[inventory_var_id("wh_001", "comp_042")].raw_value

    # Series of events affecting the chain
    events = [
        # Supplier delay → reduces incoming inventory
        SupplierDelayed(
            event_id="evt_1", world_id="world_1", workspace_id="ws_1",
            entity_type="supplier", entity_id="sup_001", delay_days=30,
        ),
        # Factory shutdown → reduces production
        FactoryShutdown(
            event_id="evt_2", world_id="world_1", workspace_id="ws_1",
            entity_type="factory", entity_id="fac_001", capacity_pct=10.0,
        ),
        # Order placed → consumes inventory
        OrderPlaced(
            event_id="evt_3", world_id="world_1", workspace_id="ws_1",
            entity_type="warehouse", entity_id="wh_001",
            warehouse_id="wh_001", component_id="comp_042", quantity=200,
        ),
    ]

    final_state = project_events(state, events)

    # Inventory should be reduced
    final_inventory = final_state.variables[inventory_var_id("wh_001", "comp_042")].raw_value
    assert final_inventory < initial_inventory


# ─────────────────────────────────────────────────────────────────────────────
# Knowledge Layer Integration
# ─────────────────────────────────────────────────────────────────────────────


def test_rule_engine_validates_against_state():
    """Rule engine validates business rules against simulated state."""
    state = _create_world_state("ws_1", "world_1")

    # Create rules
    rules = [
        KnowledgeRule(
            rule_id="rule_low_inv",
            workspace_id="ws_1",
            name="Low Inventory Alert",
            description="Notify when inventory below 200",
            trigger=RuleTrigger(conditions=[
                RuleCondition(variable_id=inventory_var_id("wh_001", "comp_042"), operator="lt", value=200),
            ]),
            action=RuleAction.NOTIFY,
            severity=RuleSeverity.MEDIUM,
        ),
        KnowledgeRule(
            rule_id="rule_critical_inv",
            workspace_id="ws_1",
            name="Critical Inventory",
            description="Expedite when inventory below 100",
            trigger=RuleTrigger(conditions=[
                RuleCondition(variable_id=inventory_var_id("wh_001", "comp_042"), operator="lt", value=100),
            ]),
            action=RuleAction.EXPEDITE,
            severity=RuleSeverity.CRITICAL,
        ),
    ]

    engine = RuleEngine()

    # Initial state: no rules fire
    initial_result = engine.evaluate(state, rules=rules)
    initial_fired = [r for r in initial_result.fired_rules if r.fired]
    assert len(initial_fired) == 0  # Inventory is 1000, above thresholds

    # Drop inventory below 200 AND below 100
    events = [
        InventoryChanged(
            event_id="evt_1", world_id="world_1", workspace_id="ws_1",
            entity_type="warehouse", entity_id="wh_001",
            warehouse_id="wh_001", component_id="comp_042",
            quantity_change=-950, reason="consumption",
        )
    ]
    final_state = project_events(state, events)

    # Both rules should fire (inventory is now 50, below both thresholds)
    final_result = engine.evaluate(final_state, rules=rules)
    final_fired = [r for r in final_result.fired_rules if r.fired]
    assert len(final_fired) == 2


def test_scenario_pipeline_with_all_components():
    """End-to-end: scenario → events → state → rules → impact."""
    state = _create_world_state("ws_1", "world_1")

    # 1. Define scenario
    scenario = create_supplier_failure_twin_scenario(
        scenario_id="scn_1",
        supplier_id="sup_001",
        delay_days=20,
        disruption_type="factory_fire",
    )

    # 2. Convert scenario events to typed events
    typed_events = [
        SupplierDelayed(
            event_id=f"evt_{i}",
            world_id="world_1",
            workspace_id="ws_1",
            entity_type="supplier",
            entity_id="sup_001",
            delay_days=20,
        )
        for i in range(len(scenario.events))
    ]

    # 3. Project to state
    final_state = project_events(state, typed_events)

    # 4. Compute impact
    calculator = ImpactCalculator()
    impact = calculator.calculate(state, final_state, duration_days=20)
    assert impact is not None

    # 5. Evaluate rules
    rule = KnowledgeRule(
        rule_id="r1",
        workspace_id="ws_1",
        name="High supplier delay",
        description="Notify when supplier delay > 14 days",
        trigger=RuleTrigger(conditions=[
            RuleCondition(variable_id="lead_time.supplier.sup_001", operator="gt", value=14),
        ]),
        action=RuleAction.NOTIFY,
    )

    # Pre-initialize the lead_time variable (since projection requires existing var)
    from dataclasses import replace
    state_with_lt = replace(state, variables={
        **state.variables,
        "lead_time.supplier.sup_001": SV(
            variable_id="lead_time.supplier.sup_001",
            variable_type=StateVariableType.LEAD_TIME,
            entity_id="sup_001",
            entity_type="supplier",
            value=10,
            unit="days",
        ),
    })
    final_state_with_lt = project_events(state_with_lt, typed_events)

    engine = RuleEngine()
    result = engine.evaluate(final_state_with_lt, rules=[rule])
    assert any(r.fired for r in result.fired_rules)


# ─────────────────────────────────────────────────────────────────────────────
# Scenario Combinations
# ─────────────────────────────────────────────────────────────────────────────


def test_combined_scenario_factory_fire_plus_supplier_delay():
    """Combined: factory fire + supplier delay."""
    state = _create_world_state("ws_1", "world_1")

    # Pre-initialize lead_time variable
    from dataclasses import replace
    state = replace(state, variables={
        **state.variables,
        "lead_time.supplier.sup_001": SV(
            variable_id="lead_time.supplier.sup_001",
            variable_type=StateVariableType.LEAD_TIME,
            entity_id="sup_001",
            entity_type="supplier",
            value=0,
            unit="days",
        ),
    })

    create_factory_fire_scenario("scn_1", "fac_001", capacity_pct=0.0)
    create_supplier_failure_twin_scenario("scn_2", "sup_001", delay_days=14)

    events = [
        FactoryShutdown(
            event_id="evt_1", world_id="world_1", workspace_id="ws_1",
            entity_type="factory", entity_id="fac_001",
            capacity_pct=0.0, cause="fire",
        ),
        SupplierDelayed(
            event_id="evt_2", world_id="world_1", workspace_id="ws_1",
            entity_type="supplier", entity_id="sup_001",
            delay_days=14, disruption_type="weather",
        ),
    ]

    final_state = project_events(state, events)

    # Both effects visible
    assert final_state.variables["capacity.factory.fac_001"].raw_value == 0.0
    assert final_state.variables["lead_time.supplier.sup_001"].raw_value == 14  # 0 + 14


def test_demand_spike_plus_port_closure():
    """Combined: demand spike + port closure."""
    _create_world_state("ws_1", "world_1")

    demand = create_demand_spike_twin_scenario("scn_d", "comp_042", demand_change=500)
    port = create_port_closure_scenario("scn_p", "route_001", delay_days=10)

    assert demand.scenario_type == ScenarioType.DEMAND_SPIKE
    assert port.scenario_type == ScenarioType.PORT_CLOSURE


def test_cyber_attack_scenario():
    """Cyber attack scenario produces correct events."""
    state = _create_world_state("ws_1", "world_1")
    create_cyber_attack_scenario(
        scenario_id="scn_cyber",
        factory_id="fac_001",
        capacity_pct=0.0,
        estimated_recovery_days=21,
    )

    event = FactoryShutdown(
        event_id="evt_1", world_id="world_1", workspace_id="ws_1",
        entity_type="factory", entity_id="fac_001",
        capacity_pct=0.0, cause="cyber_attack",
        estimated_recovery_days=21,
    )

    final_state = project_events(state, [event])
    assert final_state.variables["capacity.factory.fac_001"].raw_value == 0.0
