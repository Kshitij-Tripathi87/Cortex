"""State Projection — Canonical Event-to-State Projection Engine.

Program J (World State & Digital Twin) — ADR-016 single projection path.

This module is the SOLE authoritative implementation of event projection.
All other modules (event_projection.py, event_replay.py, event_store.py)
delegate to this module.

Architecture:
    WorldEvent
         │
         ▼
    validate (event_validation)
         │
         ▼
    EVENT_PROJECTORS  (registry: type[WorldEvent] -> projector function)
         │
         ▼
    apply_transition  (pure: WorldState + StateTransition -> WorldState)
         │
         ▼
    WorldState (immutable, version incremented)

Key invariants:
✓ Pure functions — no DB, no I/O, no clock
✓ Deterministic — same (state, event) always produces same state
✓ Immutable — original state never mutated; new state returned
✓ One registry — EVENT_PROJECTORS is the single source of truth
✓ All 11 WorldEvent subtypes registered
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from app.common.ids import uuid7
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
    WorldEvent,
)
from app.modules.events.event_validation import validate_event
from app.modules.world.state_values import (
    Provenance,
    create_typed_value,
)
from app.modules.world.world_models import (
    StateTransition,
    StateTransitionType,
    StateVariable,
    StateVariableType,
    WorldSnapshot,
    WorldState,
)

# ─────────────────────────────────────────────────────────────────────────────
# Variable ID Builders
# ─────────────────────────────────────────────────────────────────────────────


def build_variable_id(
    variable_type: StateVariableType,
    entity_id: str,
    entity_type: str,
    suffix: str | None = None,
) -> str:
    """Build a deterministic variable ID."""
    parts = [variable_type.value, entity_type, entity_id]
    if suffix:
        parts.append(suffix)
    return ".".join(parts)


def inventory_var_id(warehouse_id: str, component_id: str) -> str:
    return build_variable_id(StateVariableType.INVENTORY, component_id, "warehouse", warehouse_id)


def safety_stock_var_id(warehouse_id: str, component_id: str) -> str:
    return build_variable_id(
        StateVariableType.SAFETY_STOCK, component_id, "warehouse", warehouse_id
    )


def demand_var_id(component_id: str) -> str:
    return build_variable_id(StateVariableType.DEMAND, component_id, "component")


def lead_time_var_id(supplier_id: str) -> str:
    return build_variable_id(StateVariableType.LEAD_TIME, supplier_id, "supplier")


def capacity_var_id(factory_id: str) -> str:
    return build_variable_id(StateVariableType.CAPACITY, factory_id, "factory")


def supplier_health_var_id(supplier_id: str) -> str:
    return build_variable_id(StateVariableType.SUPPLIER_HEALTH, supplier_id, "supplier")


def warehouse_util_var_id(warehouse_id: str) -> str:
    return build_variable_id(StateVariableType.WAREHOUSE_UTILIZATION, warehouse_id, "warehouse")


def transit_delay_var_id(route_id: str) -> str:
    return build_variable_id(StateVariableType.TRANSIT_DELAY, route_id, "route")


def customer_priority_var_id(customer_id: str) -> str:
    return build_variable_id(StateVariableType.CUSTOMER_PRIORITY, customer_id, "customer")


# ─────────────────────────────────────────────────────────────────────────────
# Core Projection Functions
# ─────────────────────────────────────────────────────────────────────────────


def apply_transition(state: WorldState, transition: StateTransition) -> WorldState:
    """Apply a state transition to produce a new world state.

    Pure function: (WorldState, StateTransition) -> WorldState

    ADR-016 §3: This function now creates typed NumericValue instances
    with provenance from the transition's occurred_at.timestamp.

    If a transition references a variable that doesn't exist in the current
    state, the variable is created with the new value (this handles cases
    where the first event for an entity introduces a new state variable).
    """
    new_variables = dict(state.variables)

    # Create provenance from transition
    provenance = Provenance(
        observed_at=transition.occurred_at,
        source_event_id=transition.caused_by_event_id,
        confidence=1.0,
    )

    # Update each affected variable
    for var_id in transition.affected_variables:
        new_raw_value = transition.new_values.get(var_id)
        if new_raw_value is None:
            continue

        old_var = new_variables.get(var_id)
        if old_var:
            # Preserve old provenance's observed_at to maintain determinism
            # Only update if the new event is more recent
            old_provenance = old_var.value.provenance
            if transition.occurred_at >= old_provenance.observed_at:
                new_provenance = provenance
            else:
                new_provenance = old_provenance

            # Create new typed value preserving the old variable's type
            typed_value = create_typed_value(
                variable_type=old_var.variable_type,
                value=new_raw_value,
                provenance=new_provenance,
            )
            new_variables[var_id] = replace(
                old_var,
                value=typed_value,
                metadata={**old_var.metadata, "last_transition": transition.transition_id},
            )
        else:
            # Variable didn't exist before - create it
            var_type_str = var_id.split(".")[0] if "." in var_id else "unknown"
            try:
                var_type = StateVariableType(var_type_str)
            except ValueError:
                var_type = StateVariableType.INVENTORY  # fallback

            parts = var_id.split(".")
            entity_type = parts[1] if len(parts) > 1 else "unknown"
            entity_id = parts[2] if len(parts) > 2 else "unknown"

            typed_value = create_typed_value(
                variable_type=var_type,
                value=new_raw_value,
                provenance=provenance,
            )

            new_variables[var_id] = StateVariable(
                variable_id=var_id,
                variable_type=var_type,
                entity_id=entity_id,
                entity_type=entity_type,
                value=typed_value,
                unit=None,
                metadata={
                    "last_transition": transition.transition_id,
                    "created_by": transition.transition_id,
                },
            )

    next_state = replace(
        state,
        version=state.version + 1,
        created_at=transition.occurred_at,
        variables=new_variables,
        metadata={**state.metadata, "last_transition_id": transition.transition_id},
    )
    # Stamp the deterministic state hash so every materialized state (live,
    # replayed, time-travelled) carries its canonical fingerprint in metadata,
    # matching what store_version persists.
    return replace(
        next_state,
        metadata={**next_state.metadata, "state_hash": compute_state_hash(next_state)},
    )


def apply_transitions(state: WorldState, transitions: list[StateTransition]) -> WorldState:
    """Apply multiple transitions in sequence."""
    current = state
    for transition in transitions:
        current = apply_transition(current, transition)
    return current


# ─────────────────────────────────────────────────────────────────────────────
# Canonical Event Projectors (keyed by WorldEvent subclass)
# ─────────────────────────────────────────────────────────────────────────────
# Each projector is a pure function: (WorldState, TypedWorldEvent) -> StateTransition
# These are the SINGLE authoritative implementations.


def _project_inventory_changed(state: WorldState, event: InventoryChanged) -> StateTransition:
    """Project InventoryChanged to a state transition."""
    var_id = inventory_var_id(event.warehouse_id, event.component_id)
    old_var = state.variables.get(var_id)
    old_value = old_var.raw_value if old_var else 0
    new_value = old_value + event.quantity_change

    return StateTransition(
        transition_id=f"txn_{event.event_id}",
        world_id=event.world_id,
        transition_type=StateTransitionType.INVENTORY_CHANGE,
        affected_variables=[var_id],
        old_values={var_id: old_value},
        new_values={var_id: new_value},
        caused_by_event_id=event.caused_by_event_id,
        occurred_at=event.occurred_at,
        metadata={
            "event_type": event.event_type.value,
            "warehouse_id": event.warehouse_id,
            "component_id": event.component_id,
            "quantity_change": event.quantity_change,
            "reason": event.reason,
        },
    )


def _project_supplier_delayed(state: WorldState, event: SupplierDelayed) -> StateTransition:
    """Project SupplierDelayed to a state transition."""
    var_id = lead_time_var_id(event.entity_id)
    old_var = state.variables.get(var_id)
    old_value = old_var.raw_value if old_var else 0
    new_value = old_value + event.delay_days

    return StateTransition(
        transition_id=f"txn_{event.event_id}",
        world_id=event.world_id,
        transition_type=StateTransitionType.SUPPLIER_DELAY,
        affected_variables=[var_id],
        old_values={var_id: old_value},
        new_values={var_id: new_value},
        caused_by_event_id=event.caused_by_event_id,
        occurred_at=event.occurred_at,
        metadata={
            "event_type": event.event_type.value,
            "supplier_id": event.entity_id,
            "delay_days": event.delay_days,
            "disruption_type": event.disruption_type,
        },
    )


def _project_supplier_health_changed(
    state: WorldState, event: SupplierHealthChanged
) -> StateTransition:
    """Project SupplierHealthChanged to a state transition."""
    var_id = supplier_health_var_id(event.entity_id)
    old_var = state.variables.get(var_id)
    old_value = old_var.raw_value if old_var else 1.0

    return StateTransition(
        transition_id=f"txn_{event.event_id}",
        world_id=event.world_id,
        transition_type=StateTransitionType.SUPPLIER_DELAY,  # reusing closest semantic
        affected_variables=[var_id],
        old_values={var_id: old_value},
        new_values={var_id: event.health_score},
        caused_by_event_id=event.caused_by_event_id,
        occurred_at=event.occurred_at,
        metadata={
            "event_type": event.event_type.value,
            "supplier_id": event.entity_id,
            "health_score": event.health_score,
            "previous_score": event.previous_score,
        },
    )


def _project_order_placed(state: WorldState, event: OrderPlaced) -> StateTransition:
    """Project OrderPlaced to a state transition."""
    var_id = inventory_var_id(event.warehouse_id, event.component_id)
    old_var = state.variables.get(var_id)
    old_value = old_var.raw_value if old_var else 0
    new_value = old_value - event.quantity

    return StateTransition(
        transition_id=f"txn_{event.event_id}",
        world_id=event.world_id,
        transition_type=StateTransitionType.ORDER_PLACED,
        affected_variables=[var_id],
        old_values={var_id: old_value},
        new_values={var_id: new_value},
        caused_by_event_id=event.caused_by_event_id,
        occurred_at=event.occurred_at,
        metadata={
            "event_type": event.event_type.value,
            "warehouse_id": event.warehouse_id,
            "component_id": event.component_id,
            "quantity": event.quantity,
            "customer_id": event.customer_id,
            "priority": event.priority,
        },
    )


def _project_order_cancelled(state: WorldState, event: OrderCancelled) -> StateTransition:
    """Project OrderCancelled to a state transition."""
    var_id = inventory_var_id(event.warehouse_id, event.component_id)
    old_var = state.variables.get(var_id)
    old_value = old_var.raw_value if old_var else 0
    new_value = old_value + event.quantity

    return StateTransition(
        transition_id=f"txn_{event.event_id}",
        world_id=event.world_id,
        transition_type=StateTransitionType.ORDER_CANCELLED,
        affected_variables=[var_id],
        old_values={var_id: old_value},
        new_values={var_id: new_value},
        caused_by_event_id=event.caused_by_event_id,
        occurred_at=event.occurred_at,
        metadata={
            "event_type": event.event_type.value,
            "warehouse_id": event.warehouse_id,
            "component_id": event.component_id,
            "quantity": event.quantity,
            "order_id": event.order_id,
            "reason": event.reason,
        },
    )


def _project_capacity_changed(state: WorldState, event: CapacityChanged) -> StateTransition:
    """Project CapacityChanged to a state transition."""
    var_id = capacity_var_id(event.entity_id)
    old_var = state.variables.get(var_id)
    old_value = old_var.raw_value if old_var else 100.0

    return StateTransition(
        transition_id=f"txn_{event.event_id}",
        world_id=event.world_id,
        transition_type=StateTransitionType.CAPACITY_CHANGE,
        affected_variables=[var_id],
        old_values={var_id: old_value},
        new_values={var_id: event.capacity_pct},
        caused_by_event_id=event.caused_by_event_id,
        occurred_at=event.occurred_at,
        metadata={
            "event_type": event.event_type.value,
            "factory_id": event.entity_id,
            "capacity_pct": event.capacity_pct,
            "reason": event.reason,
        },
    )


def _project_factory_shutdown(state: WorldState, event: FactoryShutdown) -> StateTransition:
    """Project FactoryShutdown to a state transition."""
    var_id = capacity_var_id(event.entity_id)
    old_var = state.variables.get(var_id)
    old_value = old_var.raw_value if old_var else 100.0

    return StateTransition(
        transition_id=f"txn_{event.event_id}",
        world_id=event.world_id,
        transition_type=StateTransitionType.FACTORY_SHUTDOWN,
        affected_variables=[var_id],
        old_values={var_id: old_value},
        new_values={var_id: event.capacity_pct},
        caused_by_event_id=event.caused_by_event_id,
        occurred_at=event.occurred_at,
        metadata={
            "event_type": event.event_type.value,
            "factory_id": event.entity_id,
            "capacity_pct": event.capacity_pct,
            "estimated_recovery_days": event.estimated_recovery_days,
            "cause": event.cause,
        },
    )


def _project_route_disruption(state: WorldState, event: RouteDisruption) -> StateTransition:
    """Project RouteDisruption to a state transition."""
    var_id = transit_delay_var_id(event.entity_id)
    old_var = state.variables.get(var_id)
    old_value = old_var.raw_value if old_var else 0
    new_value = old_value + event.delay_days

    return StateTransition(
        transition_id=f"txn_{event.event_id}",
        world_id=event.world_id,
        transition_type=StateTransitionType.ROUTE_DISRUPTION,
        affected_variables=[var_id],
        old_values={var_id: old_value},
        new_values={var_id: new_value},
        caused_by_event_id=event.caused_by_event_id,
        occurred_at=event.occurred_at,
        metadata={
            "event_type": event.event_type.value,
            "route_id": event.entity_id,
            "delay_days": event.delay_days,
            "disruption_type": event.disruption_type,
        },
    )


def _project_shipment_delayed(state: WorldState, event: ShipmentDelayed) -> StateTransition:
    """Project ShipmentDelayed to a state transition."""
    var_id = transit_delay_var_id(event.entity_id)
    old_var = state.variables.get(var_id)
    old_value = old_var.raw_value if old_var else 0
    new_value = old_value + event.delay_days

    return StateTransition(
        transition_id=f"txn_{event.event_id}",
        world_id=event.world_id,
        transition_type=StateTransitionType.SHIPMENT_DELAYED,
        affected_variables=[var_id],
        old_values={var_id: old_value},
        new_values={var_id: new_value},
        caused_by_event_id=event.caused_by_event_id,
        occurred_at=event.occurred_at,
        metadata={
            "event_type": event.event_type.value,
            "route_id": event.entity_id,
            "delay_days": event.delay_days,
            "shipment_id": event.shipment_id,
            "cause": event.cause,
        },
    )


def _project_demand_changed(state: WorldState, event: DemandChanged) -> StateTransition:
    """Project DemandChanged to a state transition."""
    var_id = demand_var_id(event.entity_id)
    old_var = state.variables.get(var_id)
    old_value = old_var.raw_value if old_var else 0
    new_value = old_value + event.demand_change

    return StateTransition(
        transition_id=f"txn_{event.event_id}",
        world_id=event.world_id,
        transition_type=StateTransitionType.DEMAND_CHANGE,
        affected_variables=[var_id],
        old_values={var_id: old_value},
        new_values={var_id: new_value},
        caused_by_event_id=event.caused_by_event_id,
        occurred_at=event.occurred_at,
        metadata={
            "event_type": event.event_type.value,
            "component_id": event.entity_id,
            "demand_change": event.demand_change,
            "confidence": event.confidence,
            "source": event.source,
        },
    )


def _project_price_changed(state: WorldState, event: PriceChanged) -> StateTransition:
    """Project PriceChanged to a state transition (revenue/margin variables)."""
    revenue_var_id = build_variable_id(StateVariableType.REVENUE, event.entity_id, "component")
    margin_var_id = build_variable_id(StateVariableType.MARGIN, event.entity_id, "component")

    old_revenue = state.variables.get(revenue_var_id)
    old_margin = state.variables.get(margin_var_id)
    old_revenue_val = old_revenue.raw_value if old_revenue else 0.0
    old_margin_val = old_margin.raw_value if old_margin else 0.0

    multiplier = event.new_price / max(event.previous_price or event.new_price, 0.01)
    new_revenue = old_revenue_val * multiplier
    new_margin = old_margin_val * multiplier

    return StateTransition(
        transition_id=f"txn_{event.event_id}",
        world_id=event.world_id,
        transition_type=StateTransitionType.PRICE_CHANGE,
        affected_variables=[revenue_var_id, margin_var_id],
        old_values={revenue_var_id: old_revenue_val, margin_var_id: old_margin_val},
        new_values={revenue_var_id: new_revenue, margin_var_id: new_margin},
        caused_by_event_id=event.caused_by_event_id,
        occurred_at=event.occurred_at,
        metadata={
            "event_type": event.event_type.value,
            "component_id": event.entity_id,
            "new_price": event.new_price,
            "previous_price": event.previous_price,
            "currency": event.currency,
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# EVENT_PROJECTORS Registry — Single Source of Truth
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# Audit-Only Projectors (V2 Phase 1 — Spine Ingestion & Execution)
# ─────────────────────────────────────────────────────────────────────────────
# These events are appended to the immutable log for provenance and version
# tracking. They produce empty transitions — no StateVariable mutations.


def _project_entity_ingested(state: WorldState, event: EntityIngested) -> StateTransition:
    """Project EntityIngested to a no-op state transition.

    Records the ingestion event in the log and bumps the world version,
    but does not alter any StateVariable values. Entities live in the
    Operational Graph, not in World State variables.
    """
    return StateTransition(
        transition_id=f"txn_{event.event_id}",
        world_id=event.world_id,
        transition_type=StateTransitionType.ORDER_PLACED,  # closest existing type; no-op anyway
        affected_variables=[],
        old_values={},
        new_values={},
        caused_by_event_id=event.caused_by_event_id,
        occurred_at=event.occurred_at,
        metadata={
            "event_type": event.event_type.value,
            "entity_type": event.entity_type,
            "entity_id": event.entity_id,
            "audit_only": True,
        },
    )


def _project_execution_outcome(state: WorldState, event: ExecutionOutcome) -> StateTransition:
    """Project ExecutionOutcome to a no-op state transition.

    Records the execution result in the log and bumps the world version,
    but does not alter any StateVariable values.
    """
    return StateTransition(
        transition_id=f"txn_{event.event_id}",
        world_id=event.world_id,
        transition_type=StateTransitionType.ORDER_PLACED,  # closest existing type; no-op anyway
        affected_variables=[],
        old_values={},
        new_values={},
        caused_by_event_id=event.caused_by_event_id,
        occurred_at=event.occurred_at,
        metadata={
            "event_type": event.event_type.value,
            "plan_id": event.plan_id,
            "action": event.action,
            "result_status": event.result_status,
            "audit_only": True,
        },
    )


EVENT_PROJECTORS: dict[type[WorldEvent], Any] = {
    InventoryChanged: _project_inventory_changed,
    SupplierDelayed: _project_supplier_delayed,
    SupplierHealthChanged: _project_supplier_health_changed,
    OrderPlaced: _project_order_placed,
    OrderCancelled: _project_order_cancelled,
    CapacityChanged: _project_capacity_changed,
    FactoryShutdown: _project_factory_shutdown,
    RouteDisruption: _project_route_disruption,
    ShipmentDelayed: _project_shipment_delayed,
    DemandChanged: _project_demand_changed,
    PriceChanged: _project_price_changed,
    EntityIngested: _project_entity_ingested,
    ExecutionOutcome: _project_execution_outcome,
}


# Verify all WorldEvent subtypes are registered at import time
_ALL_WORLDEVENT_SUBTYPES = (
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

for _cls in _ALL_WORLDEVENT_SUBTYPES:
    if _cls not in EVENT_PROJECTORS:
        raise RuntimeError(
            f"Missing projector registration for {_cls.__name__} in EVENT_PROJECTORS"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Public API: apply_event — Validate → Project → Apply
# ─────────────────────────────────────────────────────────────────────────────


def apply_event(state: WorldState, event: WorldEvent) -> WorldState:
    """Validate an event, project it to a transition, and apply to state.

    This is the canonical single operation for advancing world state:
        apply_event(current_state, new_event) -> new_state

    Steps:
    1. Validate event identity and payload (structural validation)
    2. Look up projector in EVENT_PROJECTORS
    3. Project event to StateTransition
    4. Apply transition to produce new WorldState

    Returns the new WorldState (original unchanged — immutability guaranteed).
    Raises ValueError if event type has no projector or validation fails.
    """
    # Step 1: Structural validation (identity + payload shape)
    validate_event(event)

    # Step 2: Resolve projector
    projector = EVENT_PROJECTORS.get(type(event))
    if projector is None:
        raise ValueError(f"No projector registered for event type: {type(event).__name__}")

    # Step 3: Project to transition
    transition = projector(state, event)

    # Step 4: Apply transition
    return apply_transition(state, transition)


def apply_events(state: WorldState, events: list[WorldEvent]) -> WorldState:
    """Apply a sequence of events in order, returning the final state."""
    current = state
    for event in events:
        current = apply_event(current, event)
    return current


# ─────────────────────────────────────────────────────────────────────────────
# State Initialization & Factory Functions
# ─────────────────────────────────────────────────────────────────────────────


def create_initial_state(
    workspace_id: str,
    world_id: str,
    graph_version: int,
    initial_variables: dict[str, StateVariable] | None = None,
) -> WorldState:
    """Create an initial world state for a workspace."""
    state = WorldState(
        world_id=world_id,
        workspace_id=workspace_id,
        version=1,
        variables=initial_variables or {},
        graph_version=graph_version,
    )
    return replace(state, metadata={"state_hash": compute_state_hash(state)})


def compute_state_hash(state: WorldState) -> str:
    """Compute the deterministic SHA-256 hash of a world state.

    ADR-016 §3: The hash is computed from RAW VALUES ONLY (not provenance
    timestamps), so that two states with identical values produce identical
    hashes regardless of when their provenance was recorded. This is the
    single canonical implementation; snapshots, validation, and persisted
    state rows all derive their hashes from it.
    """
    import hashlib
    import json

    canonical_vars = {}
    for vid in sorted(state.variables.keys()):
        var = state.variables[vid]
        canonical_vars[vid] = {
            "variable_id": var.variable_id,
            "variable_type": var.variable_type.value,
            "entity_id": var.entity_id,
            "entity_type": var.entity_type,
            "value": var.raw_value,
            "unit": var.unit,
        }

    canonical = json.dumps(
        {
            "world_id": state.world_id,
            "workspace_id": state.workspace_id,
            "version": state.version,
            "variables": canonical_vars,
            "graph_version": state.graph_version,
        },
        sort_keys=True,
    ).encode()

    return hashlib.sha256(canonical).hexdigest()[:64]


def create_state_snapshot(state: WorldState, created_by: str | None = None) -> WorldSnapshot:
    """Create a deterministic snapshot of a world state.

    The hash is computed via :func:`compute_state_hash` (raw values only),
    so two states with identical values produce identical hashes regardless
    of when their provenance was recorded.
    """
    state_hash = compute_state_hash(state)

    return WorldSnapshot(
        snapshot_id=str(uuid7()),
        world_id=state.world_id,
        workspace_id=state.workspace_id,
        version=state.version,
        graph_version=state.graph_version,
        state_hash=state_hash,
        variable_count=len(state.variables),
        created_by=created_by,
    )


def validate_state_hash(state: WorldState, expected_hash: str) -> bool:
    """Verify a state matches its expected hash (tamper detection)."""
    return compute_state_hash(state) == expected_hash


# ─────────────────────────────────────────────────────────────────────────────
# State Reconstruction from Events (Replay)
# ─────────────────────────────────────────────────────────────────────────────


def reconstruct_state(
    workspace_id: str,
    world_id: str,
    graph_version: int,
    initial_variables: dict[str, StateVariable] | None,
    transitions: list[StateTransition],
) -> WorldState:
    """Reconstruct world state by replaying transitions from genesis.

    This is the core replay function - given a sequence of transitions,
    apply them in order to reconstruct the state at any point in time.
    """
    state = create_initial_state(workspace_id, world_id, graph_version, initial_variables)
    for transition in transitions:
        state = apply_transition(state, transition)
    return state


def replay_from_snapshot(
    snapshot: WorldSnapshot,
    transitions: list[StateTransition],
    initial_variables: dict[str, StateVariable] | None = None,
) -> WorldState:
    """Reconstruct state from a snapshot + subsequent transitions.

    Faster than full replay - starts from a checkpoint snapshot.
    """
    state = create_initial_state(
        snapshot.workspace_id,
        snapshot.world_id,
        snapshot.graph_version,
        initial_variables,
    )

    # Apply only transitions after the snapshot version
    relevant_transitions = [t for t in transitions if t.version > snapshot.version]

    for transition in relevant_transitions:
        state = apply_transition(state, transition)

    return state


# ─────────────────────────────────────────────────────────────────────────────
# Legacy Event-to-Transition Projection (for DB replay compatibility)
# ─────────────────────────────────────────────────────────────────────────────
# These functions handle the DB row format (string event_type) for replay.
# They delegate to the canonical EVENT_PROJECTORS via typed event deserialization.


_LEGACY_EVENT_TYPE_MAP: dict[str, type[WorldEvent]] = {
    "inventory_changed": InventoryChanged,
    "supplier_delayed": SupplierDelayed,
    "supplier_health_changed": SupplierHealthChanged,
    "order_placed": OrderPlaced,
    "order_cancelled": OrderCancelled,
    "capacity_changed": CapacityChanged,
    "factory_shutdown": FactoryShutdown,
    "route_disruption": RouteDisruption,
    "shipment_delayed": ShipmentDelayed,
    "demand_change": DemandChanged,
    "demand_changed": DemandChanged,
    "price_change": PriceChanged,
    "price_changed": PriceChanged,
    "entity_ingested": EntityIngested,
    "execution_outcome": ExecutionOutcome,
}


def project_event_to_transition(
    state: WorldState,
    event: Any,  # WorldEvent or WorldStateEventDB — avoid circular import
) -> StateTransition | None:
    """Convert an event (typed WorldEvent or DB row) into a StateTransition for projection/replay.

    This bridges the event store (source of truth, string event_type) and live typed events to
    the canonical projection engine (EVENT_PROJECTORS keyed by typed class).

    Returns None if the event type is not recognized (e.g., unknown event_type).
    The resulting transition_id is derived from the event_id so that replay
    is deterministic: same events always produce same transitions/state hashes.
    """
    from dataclasses import replace as dc_replace

    if isinstance(event, WorldEvent):
        validate_event(event)
        projector = EVENT_PROJECTORS.get(type(event))
        if projector is None:
            return None
        transition = projector(state, event)
        return dc_replace(transition, transition_id=f"txn_{event.event_id}")

    payload = getattr(event, "payload", None) or {}
    event_type_str = (
        event.event_type if isinstance(event.event_type, str) else event.event_type.value
    )
    event_metadata = getattr(event, "extra_metadata", None)
    if not isinstance(event_metadata, dict):
        raw_meta = getattr(event, "metadata", None)
        event_metadata = raw_meta if isinstance(raw_meta, dict) else {}

    event_cls = _LEGACY_EVENT_TYPE_MAP.get(event_type_str)
    if event_cls is None:
        return None

    # Build a typed event instance from DB row
    if event_cls is InventoryChanged:
        typed_event = InventoryChanged(
            event_id=event.event_id,
            world_id=event.world_id,
            workspace_id=event.workspace_id,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            warehouse_id=payload["warehouse_id"],
            component_id=payload["component_id"],
            quantity_change=payload["quantity_change"],
            reason=payload.get("reason", "production"),
            caused_by_event_id=event.caused_by_event_id,
            occurred_at=event.occurred_at,
            metadata=event_metadata,
        )
    elif event_cls is SupplierDelayed:
        typed_event = SupplierDelayed(
            event_id=event.event_id,
            world_id=event.world_id,
            workspace_id=event.workspace_id,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            delay_days=payload["delay_days"],
            disruption_type=payload.get("disruption_type", "unknown"),
            caused_by_event_id=event.caused_by_event_id,
            occurred_at=event.occurred_at,
            metadata=event_metadata,
        )
    elif event_cls is SupplierHealthChanged:
        typed_event = SupplierHealthChanged(
            event_id=event.event_id,
            world_id=event.world_id,
            workspace_id=event.workspace_id,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            health_score=payload["health_score"],
            previous_score=payload.get("previous_score"),
            caused_by_event_id=event.caused_by_event_id,
            occurred_at=event.occurred_at,
            metadata=event_metadata,
        )
    elif event_cls is OrderPlaced:
        typed_event = OrderPlaced(
            event_id=event.event_id,
            world_id=event.world_id,
            workspace_id=event.workspace_id,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            warehouse_id=payload["warehouse_id"],
            component_id=payload["component_id"],
            quantity=payload["quantity"],
            customer_id=payload.get("customer_id"),
            priority=payload.get("priority", "standard"),
            caused_by_event_id=event.caused_by_event_id,
            occurred_at=event.occurred_at,
            metadata=event_metadata,
        )
    elif event_cls is OrderCancelled:
        typed_event = OrderCancelled(
            event_id=event.event_id,
            world_id=event.world_id,
            workspace_id=event.workspace_id,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            warehouse_id=payload["warehouse_id"],
            component_id=payload["component_id"],
            quantity=payload["quantity"],
            order_id=payload["order_id"],
            reason=payload.get("reason", ""),
            caused_by_event_id=event.caused_by_event_id,
            occurred_at=event.occurred_at,
            metadata=event_metadata,
        )
    elif event_cls is CapacityChanged:
        typed_event = CapacityChanged(
            event_id=event.event_id,
            world_id=event.world_id,
            workspace_id=event.workspace_id,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            capacity_pct=payload["capacity_pct"],
            reason=payload.get("reason", ""),
            caused_by_event_id=event.caused_by_event_id,
            occurred_at=event.occurred_at,
            metadata=event_metadata,
        )
    elif event_cls is FactoryShutdown:
        typed_event = FactoryShutdown(
            event_id=event.event_id,
            world_id=event.world_id,
            workspace_id=event.workspace_id,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            capacity_pct=payload["capacity_pct"],
            estimated_recovery_days=payload.get("estimated_recovery_days"),
            cause=payload.get("cause", ""),
            caused_by_event_id=event.caused_by_event_id,
            occurred_at=event.occurred_at,
            metadata=event_metadata,
        )
    elif event_cls is RouteDisruption:
        typed_event = RouteDisruption(
            event_id=event.event_id,
            world_id=event.world_id,
            workspace_id=event.workspace_id,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            delay_days=payload["delay_days"],
            disruption_type=payload.get("disruption_type", "unknown"),
            caused_by_event_id=event.caused_by_event_id,
            occurred_at=event.occurred_at,
            metadata=event_metadata,
        )
    elif event_cls is ShipmentDelayed:
        typed_event = ShipmentDelayed(
            event_id=event.event_id,
            world_id=event.world_id,
            workspace_id=event.workspace_id,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            delay_days=payload["delay_days"],
            shipment_id=payload["shipment_id"],
            cause=payload.get("cause", ""),
            caused_by_event_id=event.caused_by_event_id,
            occurred_at=event.occurred_at,
            metadata=event_metadata,
        )
    elif event_cls is DemandChanged:
        typed_event = DemandChanged(
            event_id=event.event_id,
            world_id=event.world_id,
            workspace_id=event.workspace_id,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            demand_change=payload["demand_change"],
            confidence=payload.get("confidence", 1.0),
            source=payload.get("source", "actual"),
            caused_by_event_id=event.caused_by_event_id,
            occurred_at=event.occurred_at,
            metadata=event_metadata,
        )
    elif event_cls is PriceChanged:
        typed_event = PriceChanged(
            event_id=event.event_id,
            world_id=event.world_id,
            workspace_id=event.workspace_id,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            new_price=payload["new_price"],
            previous_price=payload.get("previous_price"),
            currency=payload.get("currency", "USD"),
            caused_by_event_id=event.caused_by_event_id,
            occurred_at=event.occurred_at,
            metadata=event_metadata,
        )
    elif event_cls is EntityIngested:
        typed_event = EntityIngested(
            event_id=event.event_id,
            world_id=event.world_id,
            workspace_id=event.workspace_id,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            attributes=payload.get("attributes", {}),
            source_file=payload.get("source_file", ""),
            caused_by_event_id=event.caused_by_event_id,
            occurred_at=event.occurred_at,
            metadata=event_metadata,
        )
    elif event_cls is ExecutionOutcome:
        typed_event = ExecutionOutcome(
            event_id=event.event_id,
            world_id=event.world_id,
            workspace_id=event.workspace_id,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            plan_id=payload.get("plan_id", ""),
            action=payload.get("action", ""),
            result_status=payload.get("result_status", ""),
            caused_by_event_id=event.caused_by_event_id,
            occurred_at=event.occurred_at,
            metadata=event_metadata,
        )
    else:
        return None

    # Validate the typed event before projecting
    validate_event(typed_event)

    # Project using the canonical registry
    projector = EVENT_PROJECTORS[event_cls]
    transition = projector(state, typed_event)

    # Override transition_id to be derived from event_id for deterministic replay
    return dc_replace(transition, transition_id=f"txn_{event.event_id}")


# ─────────────────────────────────────────────────────────────────────────────
# Legacy String-Keyed Projectors (for replay compatibility)
# ─────────────────────────────────────────────────────────────────────────────
# These functions match the signatures expected by project_event_to_transition
# and the world/__init__.py re-exports. They delegate to the canonical
# EVENT_PROJECTORS registry via typed event construction.


def project_inventory_change(
    state: WorldState,
    warehouse_id: str,
    component_id: str,
    quantity_change: int,
    caused_by_event_id: str | None = None,
) -> StateTransition:
    """Legacy projector for inventory_change events (string-keyed)."""
    return _project_inventory_changed(
        state,
        InventoryChanged(
            event_id="legacy",
            world_id=state.world_id,
            workspace_id=state.workspace_id,
            entity_type="warehouse",
            entity_id=warehouse_id,
            warehouse_id=warehouse_id,
            component_id=component_id,
            quantity_change=quantity_change,
            reason="legacy",
        ),
    )


def project_supplier_delay(
    state: WorldState,
    supplier_id: str,
    delay_days: int,
    caused_by_event_id: str | None = None,
) -> StateTransition:
    """Legacy projector for supplier_delayed events (string-keyed)."""
    return _project_supplier_delayed(
        state,
        SupplierDelayed(
            event_id="legacy",
            world_id=state.world_id,
            workspace_id=state.workspace_id,
            entity_type="supplier",
            entity_id=supplier_id,
            delay_days=delay_days,
            disruption_type="legacy",
        ),
    )


def project_factory_shutdown(
    state: WorldState,
    factory_id: str,
    capacity_pct: float,
    caused_by_event_id: str | None = None,
) -> StateTransition:
    """Legacy projector for factory_shutdown events (string-keyed)."""
    return _project_factory_shutdown(
        state,
        FactoryShutdown(
            event_id="legacy",
            world_id=state.world_id,
            workspace_id=state.workspace_id,
            entity_type="factory",
            entity_id=factory_id,
            capacity_pct=capacity_pct,
            estimated_recovery_days=None,
            cause="legacy",
        ),
    )


def project_route_disruption(
    state: WorldState,
    route_id: str,
    delay_days: int,
    caused_by_event_id: str | None = None,
) -> StateTransition:
    """Legacy projector for route_disruption events (string-keyed)."""
    return _project_route_disruption(
        state,
        RouteDisruption(
            event_id="legacy",
            world_id=state.world_id,
            workspace_id=state.workspace_id,
            entity_type="route",
            entity_id=route_id,
            delay_days=delay_days,
            disruption_type="legacy",
        ),
    )


def project_order_placed(
    state: WorldState,
    warehouse_id: str,
    component_id: str,
    quantity: int,
    caused_by_event_id: str | None = None,
) -> StateTransition:
    """Legacy projector for order_placed events (string-keyed)."""
    return _project_order_placed(
        state,
        OrderPlaced(
            event_id="legacy",
            world_id=state.world_id,
            workspace_id=state.workspace_id,
            entity_type="warehouse",
            entity_id=warehouse_id,
            warehouse_id=warehouse_id,
            component_id=component_id,
            quantity=quantity,
            customer_id=None,
            priority="standard",
        ),
    )


def project_demand_change(
    state: WorldState,
    component_id: str,
    demand_change: int,
    caused_by_event_id: str | None = None,
) -> StateTransition:
    """Legacy projector for demand_change events (string-keyed)."""
    return _project_demand_changed(
        state,
        DemandChanged(
            event_id="legacy",
            world_id=state.world_id,
            workspace_id=state.workspace_id,
            entity_type="component",
            entity_id=component_id,
            demand_change=demand_change,
            confidence=1.0,
            source="legacy",
        ),
    )


def project_capacity_change(
    state: WorldState,
    factory_id: str,
    capacity_pct: float,
    caused_by_event_id: str | None = None,
) -> StateTransition:
    """Legacy projector for capacity_change events (string-keyed)."""
    return _project_capacity_changed(
        state,
        CapacityChanged(
            event_id="legacy",
            world_id=state.world_id,
            workspace_id=state.workspace_id,
            entity_type="factory",
            entity_id=factory_id,
            capacity_pct=capacity_pct,
            reason="legacy",
        ),
    )


def project_shipment_delayed(
    state: WorldState,
    route_id: str,
    delay_days: int,
    caused_by_event_id: str | None = None,
) -> StateTransition:
    """Legacy projector for shipment_delayed events (string-keyed)."""
    return _project_shipment_delayed(
        state,
        ShipmentDelayed(
            event_id="legacy",
            world_id=state.world_id,
            workspace_id=state.workspace_id,
            entity_type="route",
            entity_id=route_id,
            delay_days=delay_days,
            shipment_id="legacy",
            cause="legacy",
        ),
    )


def project_price_change(
    state: WorldState,
    component_id: str,
    new_price: float,
    caused_by_event_id: str | None = None,
) -> StateTransition:
    """Legacy projector for price_change events (string-keyed)."""
    return _project_price_changed(
        state,
        PriceChanged(
            event_id="legacy",
            world_id=state.world_id,
            workspace_id=state.workspace_id,
            entity_type="component",
            entity_id=component_id,
            new_price=new_price,
            previous_price=None,
            currency="USD",
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Variable Initialization Helper
# ─────────────────────────────────────────────────────────────────────────────


def ensure_variable(
    state: WorldState,
    variable_type: StateVariableType,
    entity_id: str,
    entity_type: str,
    initial_value: float | int | str | bool = 0,
    unit: str | None = None,
) -> WorldState:
    """Ensure a state variable exists, creating it with initial_value if not.

    Used when an event references a variable that hasn't been seen yet
    (e.g., a new supplier's first lead time event).
    """
    var_id = build_variable_id(variable_type, entity_id, entity_type)
    if var_id in state.variables:
        return state

    new_var = StateVariable(
        variable_id=var_id,
        variable_type=variable_type,
        entity_id=entity_id,
        entity_type=entity_type,
        value=initial_value,  # type: ignore[arg-type]  # auto-wrapped by __post_init__
        unit=unit,
    )
    return replace(state, variables={**state.variables, var_id: new_var})
