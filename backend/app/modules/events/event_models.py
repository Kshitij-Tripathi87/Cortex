"""Event Models — Typed Domain Events for World State Sourcing.

Program J (World State & Digital Twin) event taxonomy:

These are the canonical domain events that the World State Engine
subscribes to. Every event produces a state transition via projection.

Events are immutable records of facts about the operational world.
They are:
- Typed (each has a specific event_type)
- Frozen (cannot be modified after creation)
- Serializable (to_dict for storage)
- Hashable (deterministic for verification)

Event Categories:
- Inventory: InventoryChanged
- Supplier: SupplierDelayed, SupplierHealthChanged
- Orders: OrderPlaced, OrderCancelled
- Capacity: CapacityChanged, FactoryShutdown
- Routes: RouteDisruption, ShipmentDelayed
- Demand: DemandChanged

Each event carries enough context to derive the state transition
without consulting external systems (closed-world assumption).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, ClassVar


class EventCategory(StrEnum):
    """Categories of world state events."""

    INVENTORY = "inventory"
    SUPPLIER = "supplier"
    ORDER = "order"
    CAPACITY = "capacity"
    ROUTE = "route"
    DEMAND = "demand"
    PRICE = "price"


# ─────────────────────────────────────────────────────────────────────────────
# Event Type Enum (matches event_type column in world_state_events table)
# ─────────────────────────────────────────────────────────────────────────────


class WorldEventType(StrEnum):
    """All event types recognized by the World State Engine."""

    INVENTORY_CHANGED = "inventory_changed"
    SUPPLIER_DELAYED = "supplier_delayed"
    SUPPLIER_HEALTH_CHANGED = "supplier_health_changed"
    ORDER_PLACED = "order_placed"
    ORDER_CANCELLED = "order_cancelled"
    CAPACITY_CHANGED = "capacity_changed"
    FACTORY_SHUTDOWN = "factory_shutdown"
    ROUTE_DISRUPTION = "route_disruption"
    SHIPMENT_DELAYED = "shipment_delayed"
    DEMAND_CHANGED = "demand_change"
    PRICE_CHANGED = "price_change"
    ENTITY_INGESTED = "entity_ingested"
    EXECUTION_OUTCOME = "execution_outcome"


# ─────────────────────────────────────────────────────────────────────────────
# Forward-compatibility metadata keys (ADR-015 invariant I10)
#
# Programs K (GNN), L (RL), M (Multi-Agent), N (Execution Plane) will write
# these keys. Program J does not consume them — they are reserved names only.
# Any other metadata key triggers a WARNING (not an error) from
# event_validation.check_event.
# ─────────────────────────────────────────────────────────────────────────────


METADATA_KEYS: frozenset[str] = frozenset(
    {
        "experiment_id",
        "policy_version",
        "decision_source",
        "shadow_model_version",
        "feature_vector_hash",
        "training_tags",
    }
)


# ─────────────────────────────────────────────────────────────────────────────
# Base Event
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class WorldEvent:
    """Base class for all world state events.

    Every event has:
    - event_id: unique identifier
    - world_id: world this event belongs to
    - workspace_id: workspace scope for multi-tenancy
    - entity_type: warehouse, supplier, factory, route, etc.
    - entity_id: ID of the affected entity
    - event_type: WorldEventType — set automatically by subclasses
    - occurred_at: when the event happened (not when it was recorded)
    - metadata: optional context (source, batch_id, etc.)

    Subclasses set EVENT_TYPE as a class attribute and it is used as
    the default for the event_type field, so callers never need to
    pass it explicitly.
    """

    EVENT_TYPE: ClassVar[WorldEventType]

    event_id: str
    world_id: str
    workspace_id: str
    entity_type: str
    entity_id: str
    event_type: WorldEventType = field(default=None)  # type: ignore[assignment]
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    caused_by_event_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # If event_type wasn't provided, use the class-level EVENT_TYPE
        if self.event_type is None:
            object.__setattr__(self, "event_type", self.EVENT_TYPE)

    def to_payload(self) -> dict[str, Any]:
        """Serialize event-specific fields for storage in event.payload."""
        raise NotImplementedError("Subclasses must implement to_payload()")

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "world_id": self.world_id,
            "workspace_id": self.workspace_id,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "event_type": self.event_type.value,
            "occurred_at": self.occurred_at.isoformat(),
            "caused_by_event_id": self.caused_by_event_id,
            "metadata": dict(self.metadata),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Inventory Events
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class InventoryChanged(WorldEvent):
    """Inventory level changed (production, receipt, write-off, transfer).

    Payload:
        warehouse_id: str
        component_id: str
        quantity_change: int  (positive = increase, negative = decrease)
        reason: str          # production, receipt, consumption, write_off
    """

    EVENT_TYPE: ClassVar[WorldEventType] = WorldEventType.INVENTORY_CHANGED

    warehouse_id: str = ""
    component_id: str = ""
    quantity_change: int = 0
    reason: str = "production"

    def to_payload(self) -> dict[str, Any]:
        return {
            "warehouse_id": self.warehouse_id,
            "component_id": self.component_id,
            "quantity_change": self.quantity_change,
            "reason": self.reason,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Supplier Events
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SupplierDelayed(WorldEvent):
    """A supplier's lead time increased due to disruption.

    Payload:
        delay_days: int
        disruption_type: str  # port_closure, weather, labor, financial
    """

    EVENT_TYPE: ClassVar[WorldEventType] = WorldEventType.SUPPLIER_DELAYED

    delay_days: int = 0
    disruption_type: str = "unknown"

    def to_payload(self) -> dict[str, Any]:
        return {
            "delay_days": self.delay_days,
            "disruption_type": self.disruption_type,
        }


@dataclass(frozen=True)
class SupplierHealthChanged(WorldEvent):
    """A supplier's overall health/risk score changed.

    Payload:
        health_score: float  # 0.0 (failed) to 1.0 (healthy)
        previous_score: float | None
    """

    EVENT_TYPE: ClassVar[WorldEventType] = WorldEventType.SUPPLIER_HEALTH_CHANGED

    health_score: float = 1.0
    previous_score: float | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "health_score": self.health_score,
            "previous_score": self.previous_score,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Order Events
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class OrderPlaced(WorldEvent):
    """An order was placed (consumes inventory).

    Payload:
        warehouse_id: str
        component_id: str
        quantity: int
        customer_id: str | None
        priority: str  # standard, expedited, critical
    """

    EVENT_TYPE: ClassVar[WorldEventType] = WorldEventType.ORDER_PLACED

    warehouse_id: str = ""
    component_id: str = ""
    quantity: int = 0
    customer_id: str | None = None
    priority: str = "standard"

    def to_payload(self) -> dict[str, Any]:
        return {
            "warehouse_id": self.warehouse_id,
            "component_id": self.component_id,
            "quantity": self.quantity,
            "customer_id": self.customer_id,
            "priority": self.priority,
        }


@dataclass(frozen=True)
class OrderCancelled(WorldEvent):
    """An order was cancelled (returns inventory to available).

    Payload:
        warehouse_id: str
        component_id: str
        quantity: int
        order_id: str
        reason: str
    """

    EVENT_TYPE: ClassVar[WorldEventType] = WorldEventType.ORDER_CANCELLED

    warehouse_id: str = ""
    component_id: str = ""
    quantity: int = 0
    order_id: str = ""
    reason: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "warehouse_id": self.warehouse_id,
            "component_id": self.component_id,
            "quantity": self.quantity,
            "order_id": self.order_id,
            "reason": self.reason,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Capacity Events
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CapacityChanged(WorldEvent):
    """A factory's capacity utilization changed.

    Payload:
        capacity_pct: float  # 0-100
        reason: str          # maintenance, expansion, ramp_up, ramp_down
    """

    EVENT_TYPE: ClassVar[WorldEventType] = WorldEventType.CAPACITY_CHANGED

    capacity_pct: float = 100.0
    reason: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "capacity_pct": self.capacity_pct,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class FactoryShutdown(WorldEvent):
    """A factory was fully or partially shut down.

    Payload:
        capacity_pct: float    # resulting capacity (0 = full shutdown)
        estimated_recovery_days: int | None
        cause: str
    """

    EVENT_TYPE: ClassVar[WorldEventType] = WorldEventType.FACTORY_SHUTDOWN

    capacity_pct: float = 0.0
    estimated_recovery_days: int | None = None
    cause: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "capacity_pct": self.capacity_pct,
            "estimated_recovery_days": self.estimated_recovery_days,
            "cause": self.cause,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Route Events
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RouteDisruption(WorldEvent):
    """A shipping route was disrupted.

    Payload:
        delay_days: int
        disruption_type: str  # port_closure, weather, customs, capacity
    """

    EVENT_TYPE: ClassVar[WorldEventType] = WorldEventType.ROUTE_DISRUPTION

    delay_days: int = 0
    disruption_type: str = "unknown"

    def to_payload(self) -> dict[str, Any]:
        return {
            "delay_days": self.delay_days,
            "disruption_type": self.disruption_type,
        }


@dataclass(frozen=True)
class ShipmentDelayed(WorldEvent):
    """A specific shipment was delayed.

    Payload:
        delay_days: int
        shipment_id: str
        cause: str
    """

    EVENT_TYPE: ClassVar[WorldEventType] = WorldEventType.SHIPMENT_DELAYED

    delay_days: int = 0
    shipment_id: str = ""
    cause: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "delay_days": self.delay_days,
            "shipment_id": self.shipment_id,
            "cause": self.cause,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Demand Events
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DemandChanged(WorldEvent):
    """Demand for a component changed.

    Payload:
        demand_change: int  # positive = increase, negative = decrease
        confidence: float   # 0-1, how confident we are in the change
        source: str         # forecast, actual, manual
    """

    EVENT_TYPE: ClassVar[WorldEventType] = WorldEventType.DEMAND_CHANGED

    demand_change: int = 0
    confidence: float = 1.0
    source: str = "actual"

    def to_payload(self) -> dict[str, Any]:
        return {
            "demand_change": self.demand_change,
            "confidence": self.confidence,
            "source": self.source,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Price Events
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PriceChanged(WorldEvent):
    """Market price for a component changed.

    Payload:
        new_price: float
        previous_price: float | None
        currency: str
    """

    EVENT_TYPE: ClassVar[WorldEventType] = WorldEventType.PRICE_CHANGED

    new_price: float = 0.0
    previous_price: float | None = None
    currency: str = "USD"

    def to_payload(self) -> dict[str, Any]:
        return {
            "new_price": self.new_price,
            "previous_price": self.previous_price,
            "currency": self.currency,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Spine Ingestion & Execution Events (V2 Phase 1)
# ─────────────────────────────────────────────────────────────────────────────
# Audit-only events: appended to the immutable log for provenance and version
# tracking, but produce no-op projections (no StateVariable mutations).
# Entities live in the Operational Graph, not in World State variables.


@dataclass(frozen=True)
class EntityIngested(WorldEvent):
    """An entity was ingested from uploaded data into the operational graph.

    Audit-only event — records the fact of ingestion and bumps the world
    version without altering any StateVariable values.

    Payload:
        attributes: dict[str, Any]  — canonical entity attributes
        source_file: str            — originating file name
    """

    EVENT_TYPE: ClassVar[WorldEventType] = WorldEventType.ENTITY_INGESTED

    attributes: dict[str, Any] = field(default_factory=dict)
    source_file: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes,
            "source_file": self.source_file,
        }


@dataclass(frozen=True)
class ExecutionOutcome(WorldEvent):
    """An execution plan produced an outcome (success or failure).

    Audit-only event — records the execution result and bumps the world
    version without altering any StateVariable values.

    Payload:
        plan_id: str         — execution plan identifier
        action: str          — canonical action verb
        result_status: str   — EXECUTED | FAILED | DENIED
    """

    EVENT_TYPE: ClassVar[WorldEventType] = WorldEventType.EXECUTION_OUTCOME

    plan_id: str = ""
    action: str = ""
    result_status: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "action": self.action,
            "result_status": self.result_status,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Factory function — convert (event_type, payload) -> typed WorldEvent
# ─────────────────────────────────────────────────────────────────────────────


_EVENT_CLASS_MAP: dict[WorldEventType, type[WorldEvent]] = {
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
    WorldEventType.ENTITY_INGESTED: EntityIngested,
    WorldEventType.EXECUTION_OUTCOME: ExecutionOutcome,
}


def deserialize_event(
    event_id: str,
    world_id: str,
    workspace_id: str,
    entity_type: str,
    entity_id: str,
    event_type: str,
    payload: dict[str, Any],
    occurred_at: datetime,
    caused_by_event_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> WorldEvent:
    """Deserialize a stored event (DB row) into a typed WorldEvent instance.

    Used by replay to reconstruct typed events from the event log.
    """
    et = WorldEventType(event_type)
    cls = _EVENT_CLASS_MAP.get(et)
    if cls is None:
        raise ValueError(f"Unknown event_type: {event_type}")

    base = {
        "event_id": event_id,
        "world_id": world_id,
        "workspace_id": workspace_id,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "event_type": et,
        "occurred_at": occurred_at,
        "caused_by_event_id": caused_by_event_id,
        "metadata": metadata or {},
    }
    return cls(**base, **payload)
