"""Operational State Models — immutable snapshots of enterprise operational data.

These dataclasses represent the current state of the enterprise at a point in time.
They are NOT graph-derived — they come from ERP, WMS, TMS, MES, and other systems.

Every operational state object includes:
  - current value(s)
  - timestamp (when observed)
  - source (which system provided it)
  - freshness (age in seconds)
  - confidence (0..1, based on source reliability and freshness)
  - provenance (audit trail)
  - version (for replay and caching)

All objects are frozen (immutable) to ensure deterministic reasoning downstream.
Program E (Propagation), F (Scenario), and G (Recommendation) consume these.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class Provenance:
    """Audit trail for an operational state value."""

    source_system: str  # e.g., "SAP", "Oracle WMS", "Manhattan TMS"
    source_table: str | None  # e.g., "MARA", "inventory_snapshot"
    source_field: str | None  # e.g., "labst", "coverage_days"
    extracted_at: datetime  # when data was extracted from source
    transformed_at: datetime | None  # when transformation was applied
    loaded_at: datetime  # when loaded into Cortex operational state
    transformation_logic: str | None = None  # e.g., "labst / daily_demand"
    quality_checks: list[str] = field(default_factory=list)  # passed checks


@dataclass(frozen=True)
class FreshnessPolicy:
    """Freshness requirements for an operational state value."""

    max_age_seconds: float  # e.g., 86400 for 24 hours
    degraded_age_seconds: float  # e.g., 43200 for 12 hours (confidence degrades after this)
    stale_age_seconds: float  # e.g., 172800 for 48 hours (value considered stale)
    expiration_policy: str  # "block" | "degrade" | "ignore"
    required_for_signal: bool  # if True, missing/stale blocks signal generation


@dataclass(frozen=True)
class InventoryOperationalState:
    """Inventory metrics for a node (Part, Product, etc.)."""

    node_id: str
    entity_id: str
    entity_type: str

    # Metadata (required fields first)
    timestamp: datetime
    source: str
    freshness_seconds: float

    # Current values (all optional with defaults)
    coverage_days: float | None = None  # days of supply remaining
    safety_stock_units: float | None = None  # safety stock level
    days_of_supply: float | None = None  # alternative coverage metric
    on_hand_units: float | None = None  # current inventory
    on_order_units: float | None = None  # units in transit/ordered
    daily_demand_units: float | None = None  # average daily demand

    # Metadata (optional)
    confidence: float = 1.0
    provenance: Provenance | None = None
    freshness_policy: FreshnessPolicy | None = None

    def is_fresh(self, as_of: datetime | None = None) -> bool:
        """Check if value is within freshness threshold."""
        if as_of is None:
            as_of = datetime.now(UTC)
        age = as_of.timestamp() - self.timestamp.timestamp()
        policy = self.freshness_policy
        if policy is None:
            return age <= 86400  # default 24h
        return age <= policy.max_age_seconds

    def is_stale(self, as_of: datetime | None = None) -> bool:
        """Check if value is stale (beyond acceptable age)."""
        if as_of is None:
            as_of = datetime.now(UTC)
        age = as_of.timestamp() - self.timestamp.timestamp()
        policy = self.freshness_policy
        if policy is None:
            return age > 172800  # default 48h
        return age > policy.stale_age_seconds

    def is_degraded(self, as_of: datetime | None = None) -> bool:
        """Check if value is in degraded freshness zone."""
        if as_of is None:
            as_of = datetime.now(UTC)
        age = as_of.timestamp() - self.timestamp.timestamp()
        policy = self.freshness_policy
        if policy is None:
            return age > 86400 and age <= 172800
        return age > policy.degraded_age_seconds and age <= policy.stale_age_seconds


@dataclass(frozen=True)
class OrderOperationalState:
    """Order metrics for a node (Purchase Order, Sales Order, etc.)."""

    node_id: str
    entity_id: str
    entity_type: str

    # Metadata (required fields first)
    timestamp: datetime
    source: str
    freshness_seconds: float

    # Current values (all optional with defaults)
    open_orders_count: int | None = None  # number of open orders
    critical_orders_count: int | None = None  # orders marked critical
    priority_orders_count: int | None = None  # orders marked priority
    total_order_value: float | None = None  # total value of open orders
    overdue_orders_count: int | None = None  # orders past due date
    average_lead_time_days: float | None = None  # avg lead time for this node

    # Metadata (optional)
    confidence: float = 1.0
    provenance: Provenance | None = None
    freshness_policy: FreshnessPolicy | None = None

    def is_fresh(self, as_of: datetime | None = None) -> bool:
        if as_of is None:
            as_of = datetime.now(UTC)
        age = as_of.timestamp() - self.timestamp.timestamp()
        policy = self.freshness_policy
        if policy is None:
            return age <= 21600  # default 6h for orders
        return age <= policy.max_age_seconds

    def is_stale(self, as_of: datetime | None = None) -> bool:
        if as_of is None:
            as_of = datetime.now(UTC)
        age = as_of.timestamp() - self.timestamp.timestamp()
        policy = self.freshness_policy
        if policy is None:
            return age > 43200  # default 12h
        return age > policy.stale_age_seconds


@dataclass(frozen=True)
class LogisticsOperationalState:
    """Logistics metrics for a node (Shipment, Route, Carrier, etc.)."""

    node_id: str
    entity_id: str
    entity_type: str

    # Metadata (required fields first)
    timestamp: datetime
    source: str
    freshness_seconds: float

    # Current values (all optional with defaults)
    route_availability: float | None = None  # 0..1, route usability
    transit_delay_days: float | None = None  # average delay in days
    carrier_status: str | None = None  # e.g., "active", "delayed", "suspended"
    on_time_delivery_rate: float | None = None  # 0..1 OTD rate
    average_transit_time_days: float | None = None
    shipments_in_transit: int | None = None

    # Metadata (optional)
    confidence: float = 1.0
    provenance: Provenance | None = None
    freshness_policy: FreshnessPolicy | None = None

    def is_fresh(self, as_of: datetime | None = None) -> bool:
        if as_of is None:
            as_of = datetime.now(UTC)
        age = as_of.timestamp() - self.timestamp.timestamp()
        policy = self.freshness_policy
        if policy is None:
            return age <= 21600  # default 6h for logistics
        return age <= policy.max_age_seconds

    def is_stale(self, as_of: datetime | None = None) -> bool:
        if as_of is None:
            as_of = datetime.now(UTC)
        age = as_of.timestamp() - self.timestamp.timestamp()
        policy = self.freshness_policy
        if policy is None:
            return age > 86400  # default 24h
        return age > policy.stale_age_seconds


@dataclass(frozen=True)
class ProductionOperationalState:
    """Production metrics for a node (Facility, Production Order, etc.)."""

    node_id: str
    entity_id: str
    entity_type: str

    # Metadata (required fields first)
    timestamp: datetime
    source: str
    freshness_seconds: float

    # Current values (all optional with defaults)
    utilization_pct: float | None = None  # 0..1 capacity utilization
    capacity_pct: float | None = None  # available capacity
    maintenance_flag: bool | None = None  # True if under maintenance
    output_units_per_day: float | None = None
    quality_yield_pct: float | None = None  # 0..1 good units / total
    downtime_hours: float | None = None  # hours of downtime

    # Metadata (optional)
    confidence: float = 1.0
    provenance: Provenance | None = None
    freshness_policy: FreshnessPolicy | None = None

    def is_fresh(self, as_of: datetime | None = None) -> bool:
        if as_of is None:
            as_of = datetime.now(UTC)
        age = as_of.timestamp() - self.timestamp.timestamp()
        policy = self.freshness_policy
        if policy is None:
            return age <= 43200  # default 12h for production
        return age <= policy.max_age_seconds

    def is_stale(self, as_of: datetime | None = None) -> bool:
        if as_of is None:
            as_of = datetime.now(UTC)
        age = as_of.timestamp() - self.timestamp.timestamp()
        policy = self.freshness_policy
        if policy is None:
            return age > 86400  # default 24h
        return age > policy.stale_age_seconds


@dataclass(frozen=True)
class BusinessOperationalState:
    """Business metrics for a node (Customer, Product, etc.)."""

    node_id: str
    entity_id: str
    entity_type: str

    # Metadata (required fields first)
    timestamp: datetime
    source: str
    freshness_seconds: float

    # Current values (all optional with defaults)
    revenue_at_risk: float | None = None  # revenue impacted by disruption
    critical_customer_flag: bool | None = None  # True if strategic customer
    sla_penalty: float | None = None  # penalty for SLA breach
    contract_value: float | None = None
    customer_lifetime_value: float | None = None
    strategic_importance: str | None = None  # "low", "medium", "high", "critical"

    # Metadata (optional)
    confidence: float = 1.0
    provenance: Provenance | None = None
    freshness_policy: FreshnessPolicy | None = None

    def is_fresh(self, as_of: datetime | None = None) -> bool:
        if as_of is None:
            as_of = datetime.now(UTC)
        age = as_of.timestamp() - self.timestamp.timestamp()
        policy = self.freshness_policy
        if policy is None:
            return age <= 86400  # default 24h for business
        return age <= policy.max_age_seconds

    def is_stale(self, as_of: datetime | None = None) -> bool:
        if as_of is None:
            as_of = datetime.now(UTC)
        age = as_of.timestamp() - self.timestamp.timestamp()
        policy = self.freshness_policy
        if policy is None:
            return age > 604800  # default 7 days for business metrics
        return age > policy.stale_age_seconds


# Type alias for any operational state
NodeOperationalState = (
    InventoryOperationalState
    | OrderOperationalState
    | LogisticsOperationalState
    | ProductionOperationalState
    | BusinessOperationalState
)


@dataclass(frozen=True)
class OperationalContextSnapshot:
    """Complete operational state snapshot for a workspace.

    This is the immutable snapshot returned by the OperationalStateEngine.
    It contains all operational state values for all nodes in the workspace.
    """

    workspace_id: str
    snapshot_id: str | None
    snapshot_version: int | None
    snapshot_hash: str | None

    # Per-node operational state (keyed by node_id)
    by_node: dict[str, NodeOperationalState] = field(default_factory=dict)

    # Aggregates (optional, computed by engine)
    total_inventory_value: float | None = None
    total_open_orders: int | None = None
    total_shipments_in_transit: int | None = None
    avg_utilization_pct: float | None = None

    # Metadata
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def get_inventory_state(self, node_id: str) -> InventoryOperationalState | None:
        """Get inventory state for a node, if available."""
        state = self.by_node.get(node_id)
        if isinstance(state, InventoryOperationalState):
            return state
        return None

    def get_order_state(self, node_id: str) -> OrderOperationalState | None:
        """Get order state for a node, if available."""
        state = self.by_node.get(node_id)
        if isinstance(state, OrderOperationalState):
            return state
        return None

    def get_logistics_state(self, node_id: str) -> LogisticsOperationalState | None:
        """Get logistics state for a node, if available."""
        state = self.by_node.get(node_id)
        if isinstance(state, LogisticsOperationalState):
            return state
        return None

    def get_production_state(self, node_id: str) -> ProductionOperationalState | None:
        """Get production state for a node, if available."""
        state = self.by_node.get(node_id)
        if isinstance(state, ProductionOperationalState):
            return state
        return None

    def get_business_state(self, node_id: str) -> BusinessOperationalState | None:
        """Get business state for a node, if available."""
        state = self.by_node.get(node_id)
        if isinstance(state, BusinessOperationalState):
            return state
        return None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for API response or caching."""
        return {
            "workspace_id": self.workspace_id,
            "snapshot_id": self.snapshot_id,
            "snapshot_version": self.snapshot_version,
            "snapshot_hash": self.snapshot_hash,
            "timestamp": self.timestamp.isoformat(),
            "by_node": {nid: _state_to_dict(state) for nid, state in self.by_node.items()},
            "metadata": self.metadata,
        }


def _state_to_dict(state: NodeOperationalState) -> dict[str, Any]:
    """Convert any operational state to dict."""
    return {
        "node_id": state.node_id,
        "entity_id": state.entity_id,
        "entity_type": state.entity_type,
        "timestamp": state.timestamp.isoformat(),
        "source": state.source,
        "freshness_seconds": state.freshness_seconds,
        "confidence": state.confidence,
        # Include type-specific fields
        **{
            k: v
            for k, v in state.__dict__.items()
            if k
            not in (
                "node_id",
                "entity_id",
                "entity_type",
                "timestamp",
                "source",
                "freshness_seconds",
                "confidence",
                "provenance",
                "freshness_policy",
            )
        },
    }
