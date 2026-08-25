"""Tests for Simulation Runtime — Program J Workstream D.

Verifies:
- Simulation models are immutable and serializable
- Timeline tracks ticks correctly
- Impact calculator computes correct severity
- Scenario registry has all Program J scenarios
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.simulation.impact_calculator import (
    ImpactCalculator,
    ImpactThresholds,
)
from app.modules.simulation.scenario_registry import (
    ScenarioRegistry,
    ScenarioTemplate,
    get_scenario_registry,
)
from app.modules.simulation.simulation_models import (
    ImpactSummary,
    SimulationConfig,
    SimulationResult,
    SimulationStatus,
    SimulationTick,
    TickGranularity,
)
from app.modules.simulation.timeline import Timeline
from app.modules.twin.twin_models import ScenarioType
from app.modules.world.state_projection import (
    StateVariableType,
    create_initial_state,
)
from app.modules.world.world_models import StateVariable

# ─────────────────────────────────────────────────────────────────────────────
# Simulation Models Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_simulation_config_defaults():
    """SimulationConfig has sensible defaults."""
    config = SimulationConfig(config_id="cfg_1")
    assert config.max_ticks == 30
    assert config.tick_granularity == TickGranularity.DAY
    assert config.include_recovery is True
    assert config.recovery_ticks == 7


def test_simulation_status_enum():
    """SimulationStatus has expected values."""
    assert SimulationStatus.PENDING == "pending"
    assert SimulationStatus.RUNNING == "running"
    assert SimulationStatus.COMPLETED == "completed"
    assert SimulationStatus.FAILED == "failed"
    assert SimulationStatus.CANCELLED == "cancelled"


def test_tick_granularity_enum():
    """TickGranularity has expected values."""
    assert TickGranularity.HOUR == "hour"
    assert TickGranularity.DAY == "day"
    assert TickGranularity.WEEK == "week"
    assert TickGranularity.MONTH == "month"


def test_simulation_tick_serialization():
    """SimulationTick serializes to dict correctly."""
    tick = SimulationTick(
        tick_id="tick_1",
        simulation_id="sim_1",
        tick_number=1,
        simulated_time=datetime.now(UTC),
        events=[{"event_type": "test"}],
        state_hash="abc123",
        metrics={"inventory": 100.0},
    )
    d = tick.to_dict()
    assert d["tick_id"] == "tick_1"
    assert d["tick_number"] == 1
    assert d["state_hash"] == "abc123"
    assert d["metrics"]["inventory"] == 100.0


def test_impact_summary_serialization():
    """ImpactSummary serializes correctly."""
    impact = ImpactSummary(
        revenue_impact=50000.0,
        margin_impact=10000.0,
        inventory_impact=-500.0,
        customers_impacted=10,
        factories_affected=2,
        routes_affected=3,
        suppliers_affected=1,
        duration_days=7,
        severity="medium",
    )
    d = impact.to_dict()
    assert d["revenue_impact"] == 50000.0
    assert d["severity"] == "medium"
    assert d["customers_impacted"] == 10


# ─────────────────────────────────────────────────────────────────────────────
# Timeline Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_timeline_advance():
    """Timeline advances through ticks correctly."""

    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
    )
    timeline = Timeline(
        simulation_id="sim_1",
        config_id="cfg_1",
        granularity=TickGranularity.DAY,
        start_time=datetime(2026, 1, 1, tzinfo=UTC),
    )

    initial_time = timeline.current_time
    tick = timeline.advance(
        events=[{"event_type": "test"}],
        state=state,
        metrics={"test": 1.0},
        state_hash="abc",
    )
    assert timeline.current_time == initial_time + timedelta(days=1)
    assert tick.tick_number == 0
    assert tick.simulated_time == initial_time + timedelta(days=1)
    assert len(timeline.ticks) == 1


def test_timeline_granularity_hour():
    """Timeline advances by hour when granularity is HOUR."""
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
    )
    timeline = Timeline(
        simulation_id="sim_1",
        config_id="cfg_1",
        granularity=TickGranularity.HOUR,
        start_time=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
    )
    initial_time = timeline.current_time
    timeline.advance(events=[], state=state, metrics={}, state_hash="abc")
    assert timeline.current_time == initial_time + timedelta(hours=1)


def test_timeline_granularity_week():
    """Timeline advances by week when granularity is WEEK."""
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
    )
    timeline = Timeline(
        simulation_id="sim_1",
        config_id="cfg_1",
        granularity=TickGranularity.WEEK,
        start_time=datetime(2026, 1, 1, tzinfo=UTC),
    )
    initial_time = timeline.current_time
    timeline.advance(events=[], state=state, metrics={}, state_hash="abc")
    assert timeline.current_time == initial_time + timedelta(weeks=1)


def test_timeline_get_tick():
    """Timeline.get_tick returns the correct tick."""
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
    )
    timeline = Timeline(
        simulation_id="sim_1",
        config_id="cfg_1",
        granularity=TickGranularity.DAY,
    )
    timeline.advance(events=[], state=state, metrics={}, state_hash="abc1")
    timeline.advance(events=[], state=state, metrics={}, state_hash="abc2")
    timeline.advance(events=[], state=state, metrics={}, state_hash="abc3")

    assert timeline.get_tick(0).state_hash == "abc1"
    assert timeline.get_tick(1).state_hash == "abc2"
    assert timeline.get_tick(2).state_hash == "abc3"
    assert timeline.get_tick(3) is None


def test_timeline_last_tick():
    """Timeline.get_last_tick returns the most recent tick."""
    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
    )
    timeline = Timeline(
        simulation_id="sim_1",
        config_id="cfg_1",
        granularity=TickGranularity.DAY,
    )
    assert timeline.get_last_tick() is None
    timeline.advance(events=[], state=state, metrics={}, state_hash="abc1")
    timeline.advance(events=[], state=state, metrics={}, state_hash="abc2")
    assert timeline.get_last_tick().state_hash == "abc2"


# ─────────────────────────────────────────────────────────────────────────────
# Impact Calculator Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_impact_calculator_low_severity():
    """Small revenue impact = low severity."""
    baseline = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
    )
    final = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=2,
    )

    calculator = ImpactCalculator()
    impact = calculator.calculate(baseline, final, duration_days=1)
    assert impact.severity == "low"


def test_impact_calculator_classifies_severity():
    """Impact calculator severity classification is correct."""
    thresholds = ImpactThresholds()
    calculator = ImpactCalculator(thresholds)

    # Below low threshold
    assert calculator._classify_severity(100, 10, 5) == "low"

    # Between low and medium
    assert calculator._classify_severity(50_000, 1_000, 100) == "medium"

    # Between medium and high
    assert calculator._classify_severity(500_000, 10_000, 1_000) == "high"

    # Above critical threshold
    assert calculator._classify_severity(50_000_000, 1_000_000, 100_000) == "critical"


def test_impact_calculator_calculates_revenue_delta():
    """Impact calculator computes revenue delta correctly."""
    from app.modules.world.world_models import StateVariable

    baseline = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
        initial_variables={
            "revenue.component.comp_042": StateVariable(
                variable_id="revenue.component.comp_042",
                variable_type=StateVariableType.REVENUE,
                entity_id="comp_042",
                entity_type="component",
                value=100_000.0,
            ),
        },
    )
    final = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=2,
        initial_variables={
            "revenue.component.comp_042": StateVariable(
                variable_id="revenue.component.comp_042",
                variable_type=StateVariableType.REVENUE,
                entity_id="comp_042",
                entity_type="component",
                value=150_000.0,  # +50,000
            ),
        },
    )

    calculator = ImpactCalculator()
    impact = calculator.calculate(baseline, final, duration_days=7)
    assert impact.revenue_impact == 50_000.0


def test_impact_calculator_counts_affected_entities():
    """Impact calculator counts affected entities."""
    from app.modules.world.world_models import StateVariable

    baseline = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
        initial_variables={
            "capacity.factory.fac_001": StateVariable(
                variable_id="capacity.factory.fac_001",
                variable_type=StateVariableType.CAPACITY,
                entity_id="fac_001",
                entity_type="factory",
                value=100.0,
            ),
            "capacity.factory.fac_002": StateVariable(
                variable_id="capacity.factory.fac_002",
                variable_type=StateVariableType.CAPACITY,
                entity_id="fac_002",
                entity_type="factory",
                value=100.0,
            ),
        },
    )
    final = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=2,
        initial_variables={
            "capacity.factory.fac_001": StateVariable(
                variable_id="capacity.factory.fac_001",
                variable_type=StateVariableType.CAPACITY,
                entity_id="fac_001",
                entity_type="factory",
                value=50.0,  # Changed
            ),
            "capacity.factory.fac_002": StateVariable(
                variable_id="capacity.factory.fac_002",
                variable_type=StateVariableType.CAPACITY,
                entity_id="fac_002",
                entity_type="factory",
                value=100.0,  # Unchanged
            ),
        },
    )

    calculator = ImpactCalculator()
    impact = calculator.calculate(baseline, final, duration_days=1)
    # fac_001 changed, fac_002 didn't
    assert impact.factories_affected == 1


# ─────────────────────────────────────────────────────────────────────────────
# Scenario Registry Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_scenario_registry_has_all_builtin_scenarios():
    """All Program J scenarios are registered."""
    registry = get_scenario_registry()
    templates = registry.list_all()
    assert len(templates) >= 10


def test_scenario_registry_by_type():
    """Registry can filter by scenario type."""
    registry = get_scenario_registry()
    supplier_templates = registry.list_by_type(ScenarioType.SUPPLIER_FAILURE)
    assert len(supplier_templates) >= 1
    assert all(t.scenario_type == ScenarioType.SUPPLIER_FAILURE for t in supplier_templates)


def test_scenario_registry_by_tag():
    """Registry can filter by tag."""
    registry = get_scenario_registry()
    critical_templates = registry.list_by_tag("critical")
    assert len(critical_templates) >= 1
    assert all("critical" in t.tags for t in critical_templates)


def test_scenario_registry_instantiate():
    """Registry can instantiate a scenario from template."""
    registry = get_scenario_registry()
    template = registry.get("supplier_failure_v1")
    assert template is not None

    scenario = registry.instantiate(
        "supplier_failure_v1",
        {"supplier_id": "sup_001", "delay_days": 5},
    )
    assert scenario.scenario_type == ScenarioType.SUPPLIER_FAILURE
    assert len(scenario.events) >= 1


def test_scenario_registry_missing_params():
    """Registry raises error for missing required params."""
    registry = get_scenario_registry()
    with pytest.raises(ValueError, match="Missing required parameters"):
        registry.instantiate("supplier_failure_v1", {"supplier_id": "sup_001"})


def test_scenario_registry_unknown_template():
    """Registry raises error for unknown template."""
    registry = get_scenario_registry()
    with pytest.raises(ValueError, match="Unknown scenario template"):
        registry.instantiate("nonexistent_v999", {})


def test_scenario_registry_custom_registration():
    """Custom scenarios can be registered."""
    from app.modules.twin.twin_models import TwinScenario

    registry = ScenarioRegistry()

    def custom_factory(scenario_id, **kwargs):
        return TwinScenario(
            scenario_id=scenario_id,
            name="Custom Test",
            description="A test scenario",
            scenario_type=ScenarioType.CUSTOM,
            events=[],
        )

    template = ScenarioTemplate(
        template_id="custom_test_v1",
        name="Custom Test",
        description="For testing",
        scenario_type=ScenarioType.CUSTOM,
        factory=custom_factory,
    )
    registry.register(template)

    assert registry.get("custom_test_v1") is not None
    scenario = registry.instantiate("custom_test_v1", {})
    assert scenario.name == "Custom Test"


# ─────────────────────────────────────────────────────────────────────────────
# Simulation Engine Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_simulation_engine_days_per_tick():
    """Days per tick conversion is correct."""
    from app.modules.simulation.simulation_engine import SimulationEngine

    # We can't easily instantiate without DB, but we can test the method
    # by creating a mock
    class MockEngine:
        pass

    engine = SimulationEngine.__new__(MockEngine)
    assert SimulationEngine._days_per_tick(engine, TickGranularity.HOUR) == 0
    assert SimulationEngine._days_per_tick(engine, TickGranularity.DAY) == 1
    assert SimulationEngine._days_per_tick(engine, TickGranularity.WEEK) == 7
    assert SimulationEngine._days_per_tick(engine, TickGranularity.MONTH) == 30


def test_simulation_engine_compute_metrics():
    """Simulation engine computes metrics from state."""
    from app.modules.simulation.simulation_engine import SimulationEngine

    state = create_initial_state(
        workspace_id="ws_1",
        world_id="world_1",
        graph_version=1,
        initial_variables={
            "inventory.warehouse.wh_001": StateVariable(
                variable_id="inventory.warehouse.wh_001",
                variable_type=StateVariableType.INVENTORY,
                entity_id="wh_001",
                entity_type="warehouse",
                value=100,
            ),
            "inventory.warehouse.wh_002": StateVariable(
                variable_id="inventory.warehouse.wh_002",
                variable_type=StateVariableType.INVENTORY,
                entity_id="wh_002",
                entity_type="warehouse",
                value=200,
            ),
            "capacity.factory.fac_001": StateVariable(
                variable_id="capacity.factory.fac_001",
                variable_type=StateVariableType.CAPACITY,
                entity_id="fac_001",
                entity_type="factory",
                value=75.0,
            ),
        },
    )

    class MockEngine:
        pass

    engine = SimulationEngine.__new__(MockEngine)
    metrics = SimulationEngine._compute_metrics(engine, state)

    assert metrics["total_inventory"] == 300.0
    assert metrics["avg_capacity"] == 75.0


def test_simulation_result_serialization():
    """SimulationResult serializes correctly."""
    result = SimulationResult(
        simulation_id="sim_1",
        twin_id="twin_1",
        scenario_id="scn_1",
        status=SimulationStatus.COMPLETED,
        ticks_executed=10,
        final_state_hash="abc123",
        final_version=11,
        duration_ms=1234.5,
    )
    d = result.to_dict()
    assert d["simulation_id"] == "sim_1"
    assert d["status"] == "completed"
    assert d["ticks_executed"] == 10
    assert d["duration_ms"] == 1234.5
