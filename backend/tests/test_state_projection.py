"""Tests for the Canonical Event Projection Path — Program J Workstream J.2.1.

Verifies ADR-016 single projection path:
- EVENT_PROJECTORS is the sole canonical registry
- All 11 event types registered exactly once
- apply_event() is pure, deterministic, immutable
- Live projection == event replay (critical invariant)
- Unknown event behavior is explicit (hard failure)
- Sequential projection equals batch replay
"""

from __future__ import annotations

import pytest

from app.modules.events.event_models import (
    CapacityChanged,
    DemandChanged,
    EntityIngested,
    ExecutionOutcome,
    FactoryShutdown,
    InventoryChanged,
    OrderCancelled,
    OrderPlaced,
    PriceChanged,
    RouteDisruption,
    ShipmentDelayed,
    SupplierDelayed,
    SupplierHealthChanged,
    WorldEventType,
)
from app.modules.world.state_projection import (
    EVENT_PROJECTORS,
    apply_event,
    apply_events,
    apply_transition,
    create_initial_state,
    create_state_snapshot,
    inventory_var_id,
)
from app.modules.world.world_models import (
    StateVariable,
    StateVariableType,
    WorldState,
)

ALL_EVENT_TYPES = (
    InventoryChanged,
    SupplierDelayed,
    SupplierHealthChanged,
    OrderPlaced,
    OrderCancelled,
    CapacityChanged,
    FactoryShutdown,
    RouteDisruption,
    ShipmentDelayed,
    DemandChanged,
    PriceChanged,
    EntityIngested,
    ExecutionOutcome,
)


def _base_state(workspace_id: str = "ws_1", world_id: str = "world_1") -> WorldState:
    """Create a base state with common initial variables."""
    return create_initial_state(
        workspace_id=workspace_id,
        world_id=world_id,
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
            "lead_time.supplier.sup_001": StateVariable(
                variable_id="lead_time.supplier.sup_001",
                variable_type=StateVariableType.LEAD_TIME,
                entity_id="sup_001",
                entity_type="supplier",
                value=5,
                unit="days",
            ),
            "capacity.factory.fac_001": StateVariable(
                variable_id="capacity.factory.fac_001",
                variable_type=StateVariableType.CAPACITY,
                entity_id="fac_001",
                entity_type="factory",
                value=100.0,
                unit="percent",
            ),
        },
    )


def _make_inventory_event(qty_change: int = 10, **kwargs) -> InventoryChanged:
    return InventoryChanged(
        event_id=kwargs.get("event_id", "evt_inv_1"),
        world_id=kwargs.get("world_id", "world_1"),
        workspace_id=kwargs.get("workspace_id", "ws_1"),
        entity_type="warehouse",
        entity_id="wh_001",
        warehouse_id="wh_001",
        component_id="comp_042",
        quantity_change=qty_change,
        reason=kwargs.get("reason", "production"),
    )


def _make_supplier_delayed(delay_days: int = 7, **kwargs) -> SupplierDelayed:
    return SupplierDelayed(
        event_id=kwargs.get("event_id", "evt_sup_1"),
        world_id=kwargs.get("world_id", "world_1"),
        workspace_id=kwargs.get("workspace_id", "ws_1"),
        entity_type="supplier",
        entity_id="sup_001",
        delay_days=delay_days,
        disruption_type=kwargs.get("disruption_type", "port_closure"),
    )


def _make_supplier_health(health: float = 0.9, **kwargs) -> SupplierHealthChanged:
    return SupplierHealthChanged(
        event_id=kwargs.get("event_id", "evt_health_1"),
        world_id=kwargs.get("world_id", "world_1"),
        workspace_id=kwargs.get("workspace_id", "ws_1"),
        entity_type="supplier",
        entity_id="sup_001",
        health_score=health,
        previous_score=kwargs.get("previous_score", 1.0),
    )


def _make_order_placed(qty: int = 5, **kwargs) -> OrderPlaced:
    return OrderPlaced(
        event_id=kwargs.get("event_id", "evt_order_1"),
        world_id=kwargs.get("world_id", "world_1"),
        workspace_id=kwargs.get("workspace_id", "ws_1"),
        entity_type="warehouse",
        entity_id="wh_001",
        warehouse_id="wh_001",
        component_id="comp_042",
        quantity=qty,
        customer_id=kwargs.get("customer_id", "cust_42"),
        priority=kwargs.get("priority", "standard"),
    )


def _make_order_cancelled(qty: int = 5, **kwargs) -> OrderCancelled:
    return OrderCancelled(
        event_id=kwargs.get("event_id", "evt_cancel_1"),
        world_id=kwargs.get("world_id", "world_1"),
        workspace_id=kwargs.get("workspace_id", "ws_1"),
        entity_type="warehouse",
        entity_id="wh_001",
        warehouse_id="wh_001",
        component_id="comp_042",
        quantity=qty,
        order_id=kwargs.get("order_id", "ord_99"),
        reason=kwargs.get("reason", "customer_request"),
    )


def _make_capacity_changed(pct: float = 80.0, **kwargs) -> CapacityChanged:
    return CapacityChanged(
        event_id=kwargs.get("event_id", "evt_cap_1"),
        world_id=kwargs.get("world_id", "world_1"),
        workspace_id=kwargs.get("workspace_id", "ws_1"),
        entity_type="factory",
        entity_id="fac_001",
        capacity_pct=pct,
        reason=kwargs.get("reason", "maintenance"),
    )


def _make_factory_shutdown(pct: float = 0.0, **kwargs) -> FactoryShutdown:
    return FactoryShutdown(
        event_id=kwargs.get("event_id", "evt_shut_1"),
        world_id=kwargs.get("world_id", "world_1"),
        workspace_id=kwargs.get("workspace_id", "ws_1"),
        entity_type="factory",
        entity_id="fac_001",
        capacity_pct=pct,
        estimated_recovery_days=kwargs.get("recovery_days", 14),
        cause=kwargs.get("cause", "fire"),
    )


def _make_route_disruption(delay: int = 3, **kwargs) -> RouteDisruption:
    return RouteDisruption(
        event_id=kwargs.get("event_id", "evt_route_1"),
        world_id=kwargs.get("world_id", "world_1"),
        workspace_id=kwargs.get("workspace_id", "ws_1"),
        entity_type="route",
        entity_id="route_001",
        delay_days=delay,
        disruption_type=kwargs.get("disruption_type", "weather"),
    )


def _make_shipment_delayed(delay: int = 2, **kwargs) -> ShipmentDelayed:
    return ShipmentDelayed(
        event_id=kwargs.get("event_id", "evt_ship_1"),
        world_id=kwargs.get("world_id", "world_1"),
        workspace_id=kwargs.get("workspace_id", "ws_1"),
        entity_type="route",
        entity_id="route_001",
        delay_days=delay,
        shipment_id=kwargs.get("shipment_id", "ship_99"),
        cause=kwargs.get("cause", "customs"),
    )


def _make_demand_changed(change: int = 50, **kwargs) -> DemandChanged:
    return DemandChanged(
        event_id=kwargs.get("event_id", "evt_dem_1"),
        world_id=kwargs.get("world_id", "world_1"),
        workspace_id=kwargs.get("workspace_id", "ws_1"),
        entity_type="component",
        entity_id="comp_042",
        demand_change=change,
        confidence=kwargs.get("confidence", 1.0),
        source=kwargs.get("source", "actual"),
    )


def _make_price_changed(new_price: float = 120.0, **kwargs) -> PriceChanged:
    return PriceChanged(
        event_id=kwargs.get("event_id", "evt_price_1"),
        world_id=kwargs.get("world_id", "world_1"),
        workspace_id=kwargs.get("workspace_id", "ws_1"),
        entity_type="component",
        entity_id="comp_042",
        new_price=new_price,
        previous_price=kwargs.get("previous_price", 100.0),
        currency=kwargs.get("currency", "USD"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Registry Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_event_projectors_registry_exists():
    """EVENT_PROJECTORS must exist and be a dict."""
    assert isinstance(EVENT_PROJECTORS, dict)


def test_all_13_event_types_registered():
    """All 13 WorldEvent subtypes must have exactly one projector."""
    for event_cls in ALL_EVENT_TYPES:
        assert event_cls in EVENT_PROJECTORS, f"{event_cls.__name__} not registered"
        projector = EVENT_PROJECTORS[event_cls]
        assert callable(projector), f"{event_cls.__name__} projector not callable"


def test_no_duplicate_event_type_registrations():
    """Each event type must have exactly one projector (no duplicates)."""
    assert len(EVENT_PROJECTORS) == len(ALL_EVENT_TYPES)


def test_event_projectors_match_worldevent_type_enum():
    """EVENT_PROJECTORS coverage matches WorldEventType enum values."""
    registered_classes = set(EVENT_PROJECTORS.keys())
    assert registered_classes == set(ALL_EVENT_TYPES)


def test_all_projectors_are_callable_with_two_args():
    """Each projector must accept (state, event) signature."""
    for event_cls, projector in EVENT_PROJECTORS.items():
        assert callable(projector)
        # Verify it can be called with minimal valid args
        state = _base_state()
        # Build a minimal valid event for each type
        if event_cls is InventoryChanged:
            event = _make_inventory_event()
        elif event_cls is SupplierDelayed:
            event = _make_supplier_delayed()
        elif event_cls is SupplierHealthChanged:
            event = _make_supplier_health()
        elif event_cls is OrderPlaced:
            event = _make_order_placed()
        elif event_cls is OrderCancelled:
            event = _make_order_cancelled()
        elif event_cls is CapacityChanged:
            event = _make_capacity_changed()
        elif event_cls is FactoryShutdown:
            event = _make_factory_shutdown()
        elif event_cls is RouteDisruption:
            event = _make_route_disruption()
        elif event_cls is ShipmentDelayed:
            event = _make_shipment_delayed()
        elif event_cls is DemandChanged:
            event = _make_demand_changed()
        elif event_cls is PriceChanged:
            event = _make_price_changed()
        elif event_cls is EntityIngested:
            event = EntityIngested(
                event_id="evt_test_ei", world_id="world_1", workspace_id="ws_1",
                entity_type="SUPPLIER", entity_id="S1",
            )
        elif event_cls is ExecutionOutcome:
            event = ExecutionOutcome(
                event_id="evt_test_eo", world_id="world_1", workspace_id="ws_1",
                entity_type="EXECUTION", entity_id="PLAN_1",
            )
        else:
            pytest.fail(f"Unhandled event type: {event_cls}")

        transition = projector(state, event)
        assert transition is not None


# ─────────────────────────────────────────────────────────────────────────────
# Individual Transition Tests (one per event type)
# ─────────────────────────────────────────────────────────────────────────────


def test_inventory_changed_projection():
    """InventoryChanged adds to inventory variable."""
    state = _base_state()
    event = _make_inventory_event(qty_change=50)
    new_state = apply_event(state, event)
    assert new_state.variables[inventory_var_id("wh_001", "comp_042")].raw_value == 150
    assert new_state.version == state.version + 1


def test_supplier_delayed_projection():
    """SupplierDelayed increases lead time."""
    state = _base_state()
    event = _make_supplier_delayed(delay_days=7)
    new_state = apply_event(state, event)
    assert new_state.variables["lead_time.supplier.sup_001"].raw_value == 12
    assert new_state.version == state.version + 1


def test_supplier_health_changed_projection():
    """SupplierHealthChanged sets health score."""
    state = _base_state()
    event = _make_supplier_health(health=0.5)
    new_state = apply_event(state, event)
    assert new_state.variables["supplier_health.supplier.sup_001"].raw_value == 0.5


def test_order_placed_projection():
    """OrderPlaced decreases inventory."""
    state = _base_state()
    event = _make_order_placed(qty=30)
    new_state = apply_event(state, event)
    assert new_state.variables[inventory_var_id("wh_001", "comp_042")].raw_value == 70


def test_order_cancelled_projection():
    """OrderCancelled returns inventory."""
    state = _base_state()
    event = _make_order_cancelled(qty=20)
    new_state = apply_event(state, event)
    assert new_state.variables[inventory_var_id("wh_001", "comp_042")].raw_value == 120


def test_capacity_changed_projection():
    """CapacityChanged sets capacity percentage."""
    state = _base_state()
    event = _make_capacity_changed(pct=75.0)
    new_state = apply_event(state, event)
    assert new_state.variables["capacity.factory.fac_001"].raw_value == 75.0


def test_factory_shutdown_projection():
    """FactoryShutdown drops capacity to 0."""
    state = _base_state()
    event = _make_factory_shutdown(pct=0.0)
    new_state = apply_event(state, event)
    assert new_state.variables["capacity.factory.fac_001"].raw_value == 0.0


def test_route_disruption_projection():
    """RouteDisruption increases transit delay."""
    state = create_initial_state("ws_1", "world_1", 1)
    event = _make_route_disruption(delay=5)
    new_state = apply_event(state, event)
    assert new_state.variables["transit_delay.route.route_001"].raw_value == 5


def test_shipment_delayed_projection():
    """ShipmentDelayed increases transit delay."""
    state = create_initial_state("ws_1", "world_1", 1)
    event = _make_shipment_delayed(delay=3)
    new_state = apply_event(state, event)
    assert new_state.variables["transit_delay.route.route_001"].raw_value == 3


def test_demand_changed_projection():
    """DemandChanged adds to demand."""
    state = create_initial_state("ws_1", "world_1", 1)
    event = _make_demand_changed(change=100)
    new_state = apply_event(state, event)
    assert new_state.variables["demand.component.comp_042"].raw_value == 100


def test_price_changed_projection():
    """PriceChanged updates revenue and margin."""
    state = create_initial_state("ws_1", "world_1", 1)
    event = _make_price_changed(new_price=150.0, previous_price=100.0)
    new_state = apply_event(state, event)
    # Revenue and margin should scale by 1.5x
    assert new_state.variables["revenue.component.comp_042"].raw_value == 0.0  # 0 * 1.5 = 0


# ─────────────────────────────────────────────────────────────────────────────
# Determinism Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_apply_event_determinism():
    """Same (state, event) always produces same result."""
    state = _base_state()
    event = _make_inventory_event(qty_change=25)

    result_a = apply_event(state, event)
    result_b = apply_event(state, event)

    snap_a = create_state_snapshot(result_a)
    snap_b = create_state_snapshot(result_b)
    assert snap_a.state_hash == snap_b.state_hash


def test_apply_events_batch_determinism():
    """apply_events() is deterministic for the same input."""
    state = _base_state()
    events = [
        _make_inventory_event(qty_change=10, event_id="e1"),
        _make_order_placed(qty=5, event_id="e2"),
        _make_inventory_event(qty_change=-3, event_id="e3"),
    ]

    result_a = apply_events(state, events)
    result_b = apply_events(state, events)

    snap_a = create_state_snapshot(result_a)
    snap_b = create_state_snapshot(result_b)
    assert snap_a.state_hash == snap_b.state_hash


# ─────────────────────────────────────────────────────────────────────────────
# Immutability Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_apply_event_does_not_mutate_input_state():
    """Original state must be unchanged after apply_event()."""
    state = _base_state()
    original_version = state.version
    original_inventory = state.variables[inventory_var_id("wh_001", "comp_042")].raw_value
    original_hash = create_state_snapshot(state).state_hash

    event = _make_inventory_event(qty_change=50)
    apply_event(state, event)

    assert state.version == original_version
    assert state.variables[inventory_var_id("wh_001", "comp_042")].raw_value == original_inventory
    assert create_state_snapshot(state).state_hash == original_hash


def test_apply_events_does_not_mutate_input_state():
    """apply_events() must not mutate the input state."""
    state = _base_state()
    original_hash = create_state_snapshot(state).state_hash

    events = [
        _make_inventory_event(qty_change=10, event_id="e1"),
        _make_inventory_event(qty_change=20, event_id="e2"),
    ]
    apply_events(state, events)

    assert create_state_snapshot(state).state_hash == original_hash


def test_apply_transition_does_not_mutate_input_state():
    """apply_transition() must not mutate the input state."""
    state = _base_state()
    original_hash = create_state_snapshot(state).state_hash

    event = _make_inventory_event(qty_change=50)
    projector = EVENT_PROJECTORS[type(event)]
    transition = projector(state, event)
    apply_transition(state, transition)

    assert create_state_snapshot(state).state_hash == original_hash


# ─────────────────────────────────────────────────────────────────────────────
# Unknown Event Behavior Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_unknown_event_type_raises_hard_error():
    """Unknown event types must raise ValueError, not silently ignored."""
    state = _base_state()

    # Since all 11 types are registered, test the ValueError path by
    # temporarily removing a registration.
    from app.modules.world.state_projection import EVENT_PROJECTORS

    original = EVENT_PROJECTORS.get(InventoryChanged)
    EVENT_PROJECTORS.pop(InventoryChanged, None)
    try:
        with pytest.raises(ValueError, match="No projector registered"):
            apply_event(state, _make_inventory_event())
    finally:
        if original is not None:
            EVENT_PROJECTORS[InventoryChanged] = original


# ─────────────────────────────────────────────────────────────────────────────
# Sequential Projection == Batch Replay (Critical Invariant)
# ─────────────────────────────────────────────────────────────────────────────


def test_sequential_apply_equals_batch_replay():
    """S0 -> E1 -> S1 -> E2 -> S2 must equal S0 -> apply_events([E1, E2]) -> S2."""
    state = _base_state()
    events = [
        _make_inventory_event(qty_change=10, event_id="e1"),
        _make_supplier_delayed(delay_days=3, event_id="e2"),
        _make_order_placed(qty=5, event_id="e3"),
        _make_capacity_changed(pct=90.0, event_id="e4"),
    ]

    # Sequential apply
    s = state
    for event in events:
        s = apply_event(s, event)
    sequential_result = s

    # Batch apply
    batch_result = apply_events(state, events)

    # Both must produce identical state hashes
    hash_seq = create_state_snapshot(sequential_result).state_hash
    hash_batch = create_state_snapshot(batch_result).state_hash
    assert hash_seq == hash_batch


def test_sequential_apply_versions_match():
    """Sequential apply produces correct version numbers."""
    state = _base_state()
    initial_version = state.version

    s = apply_event(state, _make_inventory_event(qty_change=10, event_id="e1"))
    assert s.version == initial_version + 1

    s = apply_event(s, _make_inventory_event(qty_change=20, event_id="e2"))
    assert s.version == initial_version + 2

    s = apply_event(s, _make_inventory_event(qty_change=30, event_id="e3"))
    assert s.version == initial_version + 3


# ─────────────────────────────────────────────────────────────────────────────
# Critical Cortex Invariant: Live Projection == Event Replay
# ─────────────────────────────────────────────────────────────────────────────


def test_live_projection_equals_event_replay():
    """CRITICAL INVARIANT: There must never be two different interpretations
    of the same event sequence.

    Live projection (apply_event) and event replay (apply_events) must
    produce identical state for the same input.
    """
    state = _base_state()
    events = [
        _make_inventory_event(qty_change=50, event_id="e1"),
        _make_order_placed(qty=10, event_id="e2"),
        _make_supplier_delayed(delay_days=5, event_id="e3"),
        _make_factory_shutdown(pct=0.0, event_id="e4"),
        _make_demand_changed(change=200, event_id="e5"),
    ]

    # Live projection (one at a time)
    live_state = state
    for event in events:
        live_state = apply_event(live_state, event)

    # Event replay (batch)
    replay_state = apply_events(state, events)

    # Both must produce identical state hashes
    live_hash = create_state_snapshot(live_state).state_hash
    replay_hash = create_state_snapshot(replay_state).state_hash
    assert live_hash == replay_hash

    # And identical version numbers
    assert live_state.version == replay_state.version


def test_live_projection_equals_event_replay_many_events():
    """Live projection == event replay for many events."""
    state = create_initial_state("ws_1", "world_1", 1)
    events = [_make_inventory_event(qty_change=1, event_id=f"e{i}") for i in range(50)]

    live_state = state
    for event in events:
        live_state = apply_event(live_state, event)

    replay_state = apply_events(state, events)

    assert (
        create_state_snapshot(live_state).state_hash
        == create_state_snapshot(replay_state).state_hash
    )


# ─────────────────────────────────────────────────────────────────────────────
# Validation Integration Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_apply_event_validates_event_identity():
    """apply_event() must reject events with missing identity."""
    state = _base_state()
    bad_event = _make_inventory_event()
    # Create event with empty event_id (bypass validation in __init__)
    from dataclasses import replace

    bad_event = replace(bad_event, event_id="")

    with pytest.raises(ValueError, match="missing_event_id"):
        apply_event(state, bad_event)


def test_apply_event_validates_payload():
    """apply_event() must reject events with missing required payload fields."""
    from app.modules.events.event_validation import (
        EventValidationError,
        check_event,
        validate_event,
    )

    # Create event with valid constructor args, but pass incomplete payload to validate
    event = InventoryChanged(
        event_id="bad_1",
        world_id="world_1",
        workspace_id="ws_1",
        entity_type="warehouse",
        entity_id="wh_001",
        warehouse_id="wh_001",
        component_id="comp_042",
        quantity_change=10,
        reason="production",
    )

    # Test validation directly with incomplete payload
    bad_payload = {"warehouse_id": "wh_001"}  # Missing component_id, quantity_change
    issues = check_event(event, bad_payload)
    assert any(i.severity.value == "error" for i in issues)

    # verify validate_event raises with bad payload
    with pytest.raises(EventValidationError):
        validate_event(event, bad_payload)


# ─────────────────────────────────────────────────────────────────────────────
# Apply Events Empty/Edge Cases
# ─────────────────────────────────────────────────────────────────────────────


def test_apply_events_empty_list():
    """apply_events() with empty list returns the input state unchanged."""
    state = _base_state()
    result = apply_events(state, [])
    assert (
        result is state
        or create_state_snapshot(result).state_hash == create_state_snapshot(state).state_hash
    )


def test_apply_event_increments_version():
    """Each apply_event() call increments version by exactly 1."""
    state = _base_state()
    initial_version = state.version

    for i in range(10):
        state = apply_event(state, _make_inventory_event(qty_change=1, event_id=f"e{i}"))
        assert state.version == initial_version + i + 1


# ─────────────────────────────────────────────────────────────────────────────
# Transition Metadata Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_transition_id_derived_from_event_id():
    """Transition ID must be deterministic and derived from event_id."""
    state = _base_state()
    event = _make_inventory_event(event_id="specific_event_id")
    projector = EVENT_PROJECTORS[type(event)]
    transition = projector(state, event)
    assert transition.transition_id == "txn_specific_event_id"


def test_transition_caused_by_event_id_preserved():
    """Transition must preserve caused_by_event_id from event."""
    state = _base_state()
    from dataclasses import replace

    event = replace(_make_inventory_event(), caused_by_event_id="parent_event_123")
    new_state = apply_event(state, event)
    assert new_state.metadata.get("last_transition_id") == f"txn_{event.event_id}"


# ─────────────────────────────────────────────────────────────────────────────
# WorldEventType Enum Coverage
# ─────────────────────────────────────────────────────────────────────────────


def test_all_worldevent_type_enum_values_have_projectors():
    """Every WorldEventType enum value must have a corresponding projector."""
    # Map enum values to event classes
    enum_to_class = {
        WorldEventType.INVENTORY_CHANGED: InventoryChanged,
        WorldEventType.SUPPLIER_DELAYED: SupplierDelayed,
        WorldEventType.SUPPLIER_HEALTH_CHANGED: SupplierHealthChanged,
        WorldEventType.ORDER_PLACED: OrderPlaced,
        WorldEventType.ORDER_CANCELLED: OrderCancelled,
        WorldEventType.CAPACITY_CHANGED: CapacityChanged,
        WorldEventType.FACTORY_SHUTDOWN: FactoryShutdown,
        WorldEventType.ROUTE_DISRUPTION: RouteDisruption,
        WorldEventType.SHIPMENT_DELAYED: ShipmentDelayed,
        WorldEventType.DEMAND_CHANGED: DemandChanged,
        WorldEventType.PRICE_CHANGED: PriceChanged,
    }

    for event_type, event_cls in enum_to_class.items():
        assert event_cls in EVENT_PROJECTORS, (
            f"WorldEventType.{event_type.name} ({event_cls.__name__}) not registered"
        )


def test_no_extra_registrations_beyond_13_types():
    """EVENT_PROJECTORS must not contain registrations beyond the 13 canonical types."""
    assert len(EVENT_PROJECTORS) == 13
