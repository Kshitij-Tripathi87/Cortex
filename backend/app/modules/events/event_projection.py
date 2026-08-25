"""Event Projection — Compatibility Shim (DEPRECATED).

Program J (World State & Digital Twin) — ADR-016.

This module is DEPRECATED and will be removed after one release cycle.
All projection logic has been consolidated into
`app.modules.world.state_projection` (canonical implementation).

This shim exists only for backward compatibility with existing internal
callers during the transition period. It re-exports the canonical symbols
and emits DeprecationWarning on first use of each public symbol.

NEW CODE MUST IMPORT FROM: app.modules.world.state_projection

    from app.modules.world.state_projection import (
        apply_event,
        apply_transition,
        EVENT_PROJECTORS,
        project_event_to_transition,
        create_initial_state,
        create_state_snapshot,
        validate_state_hash,
        inventory_var_id,
        build_variable_id,
        ensure_variable,
    )

DO NOT ADD NEW LOGIC HERE.
"""

from __future__ import annotations

import warnings
from typing import Any

# Emit module-level deprecation warning on first import (BEFORE any imports from this module)
warnings.warn(
    "app.modules.events.event_projection is deprecated and will be removed. "
    "Use app.modules.world.state_projection instead.",
    DeprecationWarning,
    stacklevel=2,
)

from app.modules.events.event_models import (  # noqa: E402
    CapacityChanged,
    DemandChanged,
    FactoryShutdown,
    InventoryChanged,
    OrderCancelled,
    OrderPlaced,
    PriceChanged,
    RouteDisruption,
    ShipmentDelayed,
    SupplierDelayed,
    SupplierHealthChanged,
)

# Re-export all canonical symbols from the single source of truth
from app.modules.world.state_projection import (  # noqa: E402
    EVENT_PROJECTORS,
    StateTransition,
    WorldState,
    apply_events,
)

# ─────────────────────────────────────────────────────────────────────────────
# Backward-compatible aliases for legacy projector function names
# These emit deprecation warnings and delegate to the canonical implementation
# ─────────────────────────────────────────────────────────────────────────────


def project_inventory_event(state: WorldState, event: Any) -> StateTransition:
    warnings.warn(
        "project_inventory_event is deprecated; use apply_event() from state_projection",
        DeprecationWarning,
        stacklevel=2,
    )
    from app.modules.world.state_projection import _project_inventory_changed

    return _project_inventory_changed(state, event)


def project_supplier_delayed_event(state: WorldState, event: Any) -> StateTransition:
    warnings.warn(
        "project_supplier_delayed_event is deprecated; use apply_event() from state_projection",
        DeprecationWarning,
        stacklevel=2,
    )
    from app.modules.world.state_projection import _project_supplier_delayed

    return _project_supplier_delayed(state, event)


def project_supplier_health_event(state: WorldState, event: Any) -> StateTransition:
    warnings.warn(
        "project_supplier_health_event is deprecated; use apply_event() from state_projection",
        DeprecationWarning,
        stacklevel=2,
    )
    from app.modules.world.state_projection import _project_supplier_health_changed

    return _project_supplier_health_changed(state, event)


def project_order_placed_event(state: WorldState, event: Any) -> StateTransition:
    warnings.warn(
        "project_order_placed_event is deprecated; use apply_event() from state_projection",
        DeprecationWarning,
        stacklevel=2,
    )
    from app.modules.world.state_projection import _project_order_placed

    return _project_order_placed(state, event)


def project_order_cancelled_event(state: WorldState, event: Any) -> StateTransition:
    warnings.warn(
        "project_order_cancelled_event is deprecated; use apply_event() from state_projection",
        DeprecationWarning,
        stacklevel=2,
    )
    from app.modules.world.state_projection import _project_order_cancelled

    return _project_order_cancelled(state, event)


def project_capacity_event(state: WorldState, event: Any) -> StateTransition:
    warnings.warn(
        "project_capacity_event is deprecated; use apply_event() from state_projection",
        DeprecationWarning,
        stacklevel=2,
    )
    from app.modules.world.state_projection import _project_capacity_changed

    return _project_capacity_changed(state, event)


def project_factory_shutdown_event(state: WorldState, event: Any) -> StateTransition:
    warnings.warn(
        "project_factory_shutdown_event is deprecated; use apply_event() from state_projection",
        DeprecationWarning,
        stacklevel=2,
    )
    from app.modules.world.state_projection import _project_factory_shutdown

    return _project_factory_shutdown(state, event)


def project_route_disruption_event(state: WorldState, event: Any) -> StateTransition:
    warnings.warn(
        "project_route_disruption_event is deprecated; use apply_event() from state_projection",
        DeprecationWarning,
        stacklevel=2,
    )
    from app.modules.world.state_projection import _project_route_disruption

    return _project_route_disruption(state, event)


def project_shipment_delayed_event(state: WorldState, event: Any) -> StateTransition:
    warnings.warn(
        "project_shipment_delayed_event is deprecated; use apply_event() from state_projection",
        DeprecationWarning,
        stacklevel=2,
    )
    from app.modules.world.state_projection import _project_shipment_delayed

    return _project_shipment_delayed(state, event)


def project_demand_event(state: WorldState, event: Any) -> StateTransition:
    warnings.warn(
        "project_demand_event is deprecated; use apply_event() from state_projection",
        DeprecationWarning,
        stacklevel=2,
    )
    from app.modules.world.state_projection import _project_demand_changed

    return _project_demand_changed(state, event)


def project_price_event(state: WorldState, event: Any) -> StateTransition:
    warnings.warn(
        "project_price_event is deprecated; use apply_event() from state_projection",
        DeprecationWarning,
        stacklevel=2,
    )
    from app.modules.world.state_projection import _project_price_changed

    return _project_price_changed(state, event)


# Legacy projector registry for backward compatibility
# Populated at import time from canonical EVENT_PROJECTORS
_PROJECTORS: dict[type, Any] = dict(EVENT_PROJECTORS)


def _get_legacy_projectors() -> dict[type, Any]:
    warnings.warn(
        "_PROJECTORS from event_projection is deprecated; use EVENT_PROJECTORS from state_projection",
        DeprecationWarning,
        stacklevel=2,
    )
    return _PROJECTORS


def project_event(state: WorldState, event: Any) -> StateTransition:
    """Legacy route function — projects event to transition (not apply)."""
    warnings.warn(
        "project_event() is deprecated; use apply_event() from state_projection",
        DeprecationWarning,
        stacklevel=2,
    )
    projector = EVENT_PROJECTORS.get(type(event))
    if projector is None:
        raise ValueError(f"No projector for event type: {type(event).__name__}")
    return projector(state, event)


def project_events(state: WorldState, events: list[Any]) -> WorldState:
    """Legacy batch projection — delegates to canonical apply_events()."""
    warnings.warn(
        "project_events() is deprecated; use apply_events() from state_projection",
        DeprecationWarning,
        stacklevel=2,
    )
    return apply_events(state, events)


# ─────────────────────────────────────────────────────────────────────────────
# Variable Initialization Helper (re-exported)
# ─────────────────────────────────────────────────────────────────────────────

# ensure_variable is already re-exported above


_LEGACY_PROJECTOR_MAP = {
    InventoryChanged: project_inventory_event,
    SupplierDelayed: project_supplier_delayed_event,
    SupplierHealthChanged: project_supplier_health_event,
    OrderPlaced: project_order_placed_event,
    OrderCancelled: project_order_cancelled_event,
    CapacityChanged: project_capacity_event,
    FactoryShutdown: project_factory_shutdown_event,
    RouteDisruption: project_route_disruption_event,
    ShipmentDelayed: project_shipment_delayed_event,
    DemandChanged: project_demand_event,
    PriceChanged: project_price_event,
}

# Verify coverage at import time
for cls in (
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
):
    if cls not in _LEGACY_PROJECTOR_MAP:
        raise RuntimeError(f"Missing legacy projector for {cls.__name__}")
