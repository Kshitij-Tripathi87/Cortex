"""World State Models — Immutable Contracts for the World State Engine.

Program J (World State & Digital Twin) defines the separation between:
- Operational Graph: Structural entities (suppliers, warehouses, products) — rarely changes
- World State: Mutable operational variables (inventory, demand, capacity) — changes constantly

All models in this module are:
✓ Immutable (frozen dataclasses)
✓ Versioned (every state has a version number)
✓ Serializable (to_dict/from_dict)
✓ Hashable (deterministic state hashes for verification)

This separation is the foundation for:
- Event sourcing (events change state variables)
- Digital twins (clone state variables, not graph structure)
- Simulation (manipulate state variables safely in isolation)
- Knowledge layer (rules constrain valid state transitions)

ADR-016 §3: State values are typed (per-domain wrappers) with provenance
and freshness split from the value itself. See `state_values.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.modules.world.state_values import NumericValue

# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────


class StateVariableType(StrEnum):
    """Types of mutable state variables in the world."""

    INVENTORY = "inventory"
    SAFETY_STOCK = "safety_stock"
    DEMAND = "demand"
    LEAD_TIME = "lead_time"
    CAPACITY = "capacity"
    SUPPLIER_HEALTH = "supplier_health"
    WAREHOUSE_UTILIZATION = "warehouse_utilization"
    TRANSIT_DELAY = "transit_delay"
    CUSTOMER_PRIORITY = "customer_priority"
    REVENUE = "revenue"
    MARGIN = "margin"
    WORKING_CAPITAL = "working_capital"


class StateTransitionType(StrEnum):
    """Types of state transitions."""

    INVENTORY_CHANGE = "inventory_change"
    SUPPLIER_DELAY = "supplier_delay"
    FACTORY_SHUTDOWN = "factory_shutdown"
    ROUTE_DISRUPTION = "route_disruption"
    ORDER_PLACED = "order_placed"
    ORDER_CANCELLED = "order_cancelled"
    CAPACITY_CHANGE = "capacity_change"
    DEMAND_CHANGE = "demand_change"
    SHIPMENT_DELAYED = "shipment_delayed"
    PRICE_CHANGE = "price_change"


# ─────────────────────────────────────────────────────────────────────────────
# State Variables
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StateVariable:
    """A single mutable state variable in the world.

    ADR-016 §3: The `value` field is a typed `NumericValue` (not raw float/int/str).
    Provenance and freshness are part of the value object, not separate metadata.

    Examples:
        - inventory[warehouse_X][component_Y] = InventoryQuantity(value=200, ...)
        - lead_time[supplier_Z] = LeadTime(value=14, ...)
        - capacity[factory_W] = Capacity(value=75.0, ...)
    """

    variable_id: str  # Unique within world (e.g., "inventory.wh_001.comp_042")
    variable_type: StateVariableType
    entity_id: str  # ID of the entity this variable belongs to
    entity_type: str  # Type of entity (warehouse, supplier, factory, etc.)
    value: NumericValue  # Typed value with provenance
    unit: str | None = None  # "units", "days", "percent", "USD" (sourced from value)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Lazy import to avoid circular dependency at module load time.
        from app.modules.world.state_values import NumericValue, Provenance, create_typed_value

        # Auto-wrap raw values into typed NumericValue for backward compatibility.
        # New code should pass a typed value directly; this wrapping exists so
        # legacy test code and migration paths keep working.
        if not isinstance(self.value, NumericValue):
            provenance = Provenance(
                observed_at=datetime.now(UTC),
                confidence=1.0,
            )
            typed_value = create_typed_value(
                variable_type=self.variable_type,
                value=self.value,
                provenance=provenance,
                unit=self.unit,
            )
            object.__setattr__(self, "value", typed_value)

        # Auto-populate unit from value if not specified
        if self.unit is None and self.value is not None:
            object.__setattr__(self, "unit", self.value.unit)

    @property
    def raw_value(self) -> float | int | str:
        """Extract the raw numeric/string value from the typed value.

        For backward compatibility with code that expects raw values.
        """
        return self.value.value

    @classmethod
    def from_raw_value(
        cls,
        variable_id: str,
        variable_type: StateVariableType,
        entity_id: str,
        entity_type: str,
        raw_value: float | int | str,
        unit: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> StateVariable:
        """Convenience constructor: create a StateVariable from a raw numeric value.

        Auto-wraps the raw value in the appropriate typed NumericValue.
        Used by test code and migration paths where raw values are stored.
        """
        from app.modules.world.state_values import Provenance, create_typed_value

        provenance = Provenance(
            observed_at=datetime.now(UTC),
            confidence=1.0,
        )
        typed_value = create_typed_value(
            variable_type=variable_type,
            value=raw_value,
            provenance=provenance,
            unit=unit,
        )
        return cls(
            variable_id=variable_id,
            variable_type=variable_type,
            entity_id=entity_id,
            entity_type=entity_type,
            value=typed_value,
            unit=unit,
            metadata=metadata or {},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "variable_id": self.variable_id,
            "variable_type": self.variable_type.value,
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "value": self.value.value if hasattr(self.value, "value") else self.value,
            "unit": self.unit,
            "metadata": dict(self.metadata),
        }


# ─────────────────────────────────────────────────────────────────────────────
# State Transitions
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StateTransition:
    """A change to one or more state variables.

    Immutable record of a state change. Transitions are produced by events
    (InventoryChanged, SupplierDelayed, etc.) and applied via state_projection.

    ADR-016 §3: old_values and new_values carry raw numeric values for
    serialization and diff purposes. The typed NumericValue lives in the
    StateVariable itself.
    """

    transition_id: str
    world_id: str
    transition_type: StateTransitionType
    affected_variables: list[str]  # List of variable_ids that changed
    old_values: dict[str, float | int | str]
    new_values: dict[str, float | int | str]
    caused_by_event_id: str | None = None
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "transition_id": self.transition_id,
            "world_id": self.world_id,
            "transition_type": self.transition_type.value,
            "affected_variables": list(self.affected_variables),
            "old_values": dict(self.old_values),
            "new_values": dict(self.new_values),
            "caused_by_event_id": self.caused_by_event_id,
            "occurred_at": self.occurred_at.isoformat(),
            "metadata": dict(self.metadata),
        }


# ─────────────────────────────────────────────────────────────────────────────
# World State
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class WorldState:
    """Complete mutable state of the world at a point in time.

    Contains all state variables for a workspace. The operational graph
    (structural entities and relationships) lives separately and is referenced
    by entity_id. This separation allows:
    - Fast state queries (no graph traversal needed)
    - Easy state cloning (just copy variables)
    - Simple state validation (check variables, not graph structure)
    """

    world_id: str
    workspace_id: str
    version: int
    variables: dict[str, StateVariable]  # variable_id -> StateVariable
    graph_version: int  # Reference to operational graph version
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def get_variable(self, variable_id: str) -> StateVariable | None:
        """Get a specific state variable."""
        return self.variables.get(variable_id)

    def get_variables_by_type(self, variable_type: StateVariableType) -> list[StateVariable]:
        """Get all variables of a specific type."""
        return [v for v in self.variables.values() if v.variable_type == variable_type]

    def get_variables_by_entity(self, entity_id: str) -> list[StateVariable]:
        """Get all variables belonging to a specific entity."""
        return [v for v in self.variables.values() if v.entity_id == entity_id]

    def to_dict(self) -> dict[str, Any]:
        return {
            "world_id": self.world_id,
            "workspace_id": self.workspace_id,
            "version": self.version,
            "variables": {vid: v.to_dict() for vid, v in self.variables.items()},
            "graph_version": self.graph_version,
            "created_at": self.created_at.isoformat(),
            "metadata": dict(self.metadata),
        }


# ─────────────────────────────────────────────────────────────────────────────
# World Snapshot
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class WorldSnapshot:
    """An immutable, versioned snapshot of the world state.

    Snapshots are created periodically and serve as checkpoints for:
    - Fast state reconstruction (no need to replay from genesis)
    - Digital twin cloning (copy from a specific snapshot)
    - Time travel (reconstruct state at any historical point)
    - Verification (detect state drift by comparing snapshots)
    """

    snapshot_id: str
    world_id: str
    workspace_id: str
    version: int
    graph_version: int
    state_hash: str  # SHA256 of canonical state representation
    variable_count: int
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str | None = None  # "system", "user_id", "twin_id"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "world_id": self.world_id,
            "workspace_id": self.workspace_id,
            "version": self.version,
            "graph_version": self.graph_version,
            "state_hash": self.state_hash,
            "variable_count": self.variable_count,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "metadata": dict(self.metadata),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Metadata & Summary
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StateMetadata:
    """Metadata about a world state (provenance, lineage, context)."""

    workspace_id: str
    world_id: str
    version: int
    graph_version: int
    source: str  # "production", "twin_id", "simulation_id"
    parent_world_id: str | None = None  # For twins: ID of the parent world
    parent_version: int | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "world_id": self.world_id,
            "version": self.version,
            "graph_version": self.graph_version,
            "source": self.source,
            "parent_world_id": self.parent_world_id,
            "parent_version": self.parent_version,
            "created_at": self.created_at.isoformat(),
            "tags": list(self.tags),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class StateSummary:
    """Lightweight summary of world state for quick queries."""

    workspace_id: str
    world_id: str
    version: int
    graph_version: int
    variable_count: int
    variables_by_type: dict[str, int]  # variable_type -> count
    entities_with_state: int
    last_transition_at: datetime | None = None
    snapshot_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "world_id": self.world_id,
            "version": self.version,
            "graph_version": self.graph_version,
            "variable_count": self.variable_count,
            "variables_by_type": dict(self.variables_by_type),
            "entities_with_state": self.entities_with_state,
            "last_transition_at": self.last_transition_at.isoformat()
            if self.last_transition_at
            else None,
            "snapshot_count": self.snapshot_count,
            "metadata": dict(self.metadata),
        }
