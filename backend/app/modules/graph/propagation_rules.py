"""Propagation Rules — deterministic supply-chain propagation specifications.

Rules are NOT algorithms. They are specifications consumed by the
PropagationEngine runtime. Each rule defines:

  - source signal categories that activate it
  - traversal direction (downstream, upstream, both)
  - relationship types the rule follows
  - hop limits
  - attenuation per hop (0..1, multiplicative)
  - confidence decay per hop (0..1, multiplicative)
  - stop conditions (entity types that terminate propagation)
  - impact type and severity mapping

The runtime selects the matching rule for a given signal and walks
the graph accordingly. Multiple signals of the same category reuse
the same rule — guaranteeing determinism.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.modules.graph.propagation_models import (
    ImpactType,
    PropagationDirection,
    Severity,
)

# ─────────────────────────────────────────────────────────────────────────────
# Rule contract
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PropagationRule:
    """Specification for one propagation behavior.

    Versioned and frozen — modifications require a new version.
    """

    name: str  # unique rule name
    version: str  # semver, e.g. "1.0.0"
    description: str

    # What activates this rule
    applies_to_signals: list[str]  # signal_name(s) that trigger this rule

    # Graph traversal
    direction: PropagationDirection
    relationship_types: list[str]  # edge types to follow (empty = all)
    max_depth: int  # hop limit (independent of request cap)

    # Scoring formulas (deterministic)
    attenuation_per_hop: float  # 0..1, multiplicative per hop
    confidence_decay_per_hop: float  # 0..1, multiplicative per hop

    # Stop conditions
    stop_at_entity_types: list[str]  # terminate when reaching these types
    skip_relationships: list[str]  # never follow these edge types

    # Impact mapping
    default_impact_type: ImpactType
    severity_by_hop: dict[int, Severity] = field(default_factory=dict)
    entity_type_impact_map: dict[str, ImpactType] = field(default_factory=dict)

    # Explanation template
    explanation_template: str = "Propagated from {source_entity} via {relationship} to {affected_entity} (hop {hop}, confidence {confidence:.2f})."

    def impact_type_for(self, entity_type: str) -> ImpactType:
        """Get impact type for an entity type, falling back to default."""
        return self.entity_type_impact_map.get(entity_type, self.default_impact_type)

    def severity_for_hop(self, hop: int, source_severity: Severity) -> Severity:
        """Determine severity at a given hop.

        If severity_by_hop defines a specific severity for this hop, use it.
        Otherwise degrade by one level per hop from source severity.
        """
        if hop in self.severity_by_hop:
            return self.severity_by_hop[hop]

        # Degrade severity per hop
        levels = [Severity.BLOCKING, Severity.CRITICAL, Severity.WARNING, Severity.INFO]
        order = {s: i for i, s in enumerate(levels)}
        source_level = order.get(source_severity, 3)
        degraded = min(3, source_level + hop)
        return levels[degraded]

    def attenuation_at_hop(self, hop: int) -> float:
        """Total attenuation at a given hop (attenuation_per_hop ** hop)."""
        if hop <= 0:
            return 1.0
        return self.attenuation_per_hop**hop

    def confidence_at_hop(self, hop: int, source_confidence: float) -> float:
        """Confidence at a given hop, decaying from source."""
        if hop <= 0:
            return source_confidence
        return source_confidence * (self.confidence_decay_per_hop**hop)

    def should_stop(self, entity_type: str) -> bool:
        """Check if propagation should stop at this entity type."""
        return entity_type in self.stop_at_entity_types

    def follows_relationship(self, rel_type: str) -> bool:
        """Check if this rule follows a given relationship type."""
        if rel_type in self.skip_relationships:
            return False
        if not self.relationship_types:
            return True
        return rel_type in self.relationship_types

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "applies_to_signals": list(self.applies_to_signals),
            "direction": self.direction.value,
            "relationship_types": list(self.relationship_types),
            "max_depth": self.max_depth,
            "attenuation_per_hop": round(self.attenuation_per_hop, 4),
            "confidence_decay_per_hop": round(self.confidence_decay_per_hop, 4),
            "stop_at_entity_types": list(self.stop_at_entity_types),
            "skip_relationships": list(self.skip_relationships),
            "default_impact_type": self.default_impact_type.value,
            "severity_by_hop": {k: v.value for k, v in self.severity_by_hop.items()},
            "entity_type_impact_map": {k: v.value for k, v in self.entity_type_impact_map.items()},
            "explanation_template": self.explanation_template,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Frozen Rule Registry — supply-chain native rules
# ─────────────────────────────────────────────────────────────────────────────


# Default severity and confidence decay rates
# Enterprise supply chain research suggests confidence decays roughly 10-15% per hop
# and operational impact attenuates ~20% per hop in well-connected networks

PROPAGATION_RULES: dict[str, PropagationRule] = {
    "supplier_failure": PropagationRule(
        name="supplier_failure",
        version="1.0.0",
        description=(
            "Supplier failure propagates downstream: Supplier → Plant → "
            "Inventory → Orders → Customers."
        ),
        applies_to_signals=[
            "single_point_of_failure_alert",
            "criticality_alert",
            "isolation_alert",
        ],
        direction=PropagationDirection.UPSTREAM,
        relationship_types=[
            "ORDERS_FROM",  # PurchaseOrder → Supplier (reverse: who buys from us)
            "SHIPS_TO",  # PO → Facility
            "ORIGINATES_FROM",  # Shipment → Facility/Supplier
            "STORED_AT",  # Inventory → Facility
            "IS_PRODUCT",  # Inventory → Product
            "SHIPS_FROM",  # SalesOrder → Facility
            "ORDERED_BY",  # SalesOrder → Customer
            "DESTINED_TO",  # Shipment → Customer/Facility
            "SUPPLIED_BY",  # Inventory → Supplier
            "USES_ROUTE",  # Shipment → Route
            "CARRIED_BY",  # Shipment → Carrier
        ],
        max_depth=8,
        attenuation_per_hop=0.85,
        confidence_decay_per_hop=0.90,
        stop_at_entity_types=["Customer"],
        skip_relationships=["PARENT_OF", "COMPONENT_OF", "HAS_COMPONENT", "LOCATED_IN"],
        default_impact_type=ImpactType.SUPPLIER,
        severity_by_hop={
            0: Severity.CRITICAL,
            1: Severity.CRITICAL,
            2: Severity.WARNING,
            3: Severity.WARNING,
        },
        entity_type_impact_map={
            "Supplier": ImpactType.SUPPLIER,
            "Facility": ImpactType.FACILITY,
            "InventoryItem": ImpactType.INVENTORY,
            "Product": ImpactType.INVENTORY,
            "PurchaseOrder": ImpactType.ORDER,
            "SalesOrder": ImpactType.ORDER,
            "Customer": ImpactType.CUSTOMER,
            "Shipment": ImpactType.LOGISTICS,
            "Route": ImpactType.LOGISTICS,
            "Carrier": ImpactType.LOGISTICS,
        },
        explanation_template=(
            "Supplier disruption at {source_entity} propagated via {relationship} "
            "to {affected_entity} (hop {hop}, severity {severity}, confidence {confidence:.2f})."
        ),
    ),
    "warehouse_outage": PropagationRule(
        name="warehouse_outage",
        version="1.0.0",
        description=(
            "Facility/warehouse outage propagates downstream: Facility → "
            "Inventory → Orders → Customers."
        ),
        applies_to_signals=[
            "single_point_of_failure_alert",
            "criticality_alert",
            "concentration_risk_alert",
            "bottleneck_alert",
        ],
        direction=PropagationDirection.DOWNSTREAM,
        relationship_types=[
            "STORED_AT",
            "SHIPS_FROM",
            "SHIPS_TO",
            "ORIGINATES_FROM",
            "ORDERED_BY",
            "DESTINED_TO",
            "IS_PRODUCT",
        ],
        max_depth=6,
        attenuation_per_hop=0.80,
        confidence_decay_per_hop=0.88,
        stop_at_entity_types=["Customer"],
        skip_relationships=["PARENT_OF", "COMPONENT_OF", "HAS_COMPONENT", "LOCATED_IN"],
        default_impact_type=ImpactType.FACILITY,
        severity_by_hop={
            0: Severity.CRITICAL,
            1: Severity.CRITICAL,
            2: Severity.WARNING,
            3: Severity.WARNING,
        },
        entity_type_impact_map={
            "Facility": ImpactType.FACILITY,
            "InventoryItem": ImpactType.INVENTORY,
            "Product": ImpactType.INVENTORY,
            "SalesOrder": ImpactType.ORDER,
            "PurchaseOrder": ImpactType.ORDER,
            "Customer": ImpactType.CUSTOMER,
            "Shipment": ImpactType.LOGISTICS,
        },
        explanation_template=(
            "Facility outage at {source_entity} propagated via {relationship} "
            "to {affected_entity} (hop {hop}, severity {severity}, confidence {confidence:.2f})."
        ),
    ),
    "route_closure": PropagationRule(
        name="route_closure",
        version="1.0.0",
        description=("Route closure propagates: Route → Shipments → Facilities → Orders."),
        applies_to_signals=[
            "bottleneck_alert",
            "criticality_alert",
        ],
        direction=PropagationDirection.BOTH,
        relationship_types=[
            "USES_ROUTE",
            "ORIGINATES_FROM",
            "DESTINED_TO",
            "CONNECTS_FROM",
            "CONNECTS_TO",
            "CARRIED_BY",
            "SHIPS_FROM",
            "SHIPS_TO",
            "ORDERED_BY",
            "STORED_AT",
        ],
        max_depth=5,
        attenuation_per_hop=0.85,
        confidence_decay_per_hop=0.90,
        stop_at_entity_types=["Customer"],
        skip_relationships=["PARENT_OF", "COMPONENT_OF", "HAS_COMPONENT", "LOCATED_IN"],
        default_impact_type=ImpactType.LOGISTICS,
        severity_by_hop={
            0: Severity.CRITICAL,
            1: Severity.CRITICAL,
            2: Severity.WARNING,
            3: Severity.WARNING,
        },
        entity_type_impact_map={
            "Route": ImpactType.LOGISTICS,
            "Shipment": ImpactType.LOGISTICS,
            "Facility": ImpactType.FACILITY,
            "Carrier": ImpactType.LOGISTICS,
            "SalesOrder": ImpactType.ORDER,
            "PurchaseOrder": ImpactType.ORDER,
            "Customer": ImpactType.CUSTOMER,
        },
        explanation_template=(
            "Route disruption at {source_entity} propagated via {relationship} "
            "to {affected_entity} (hop {hop}, severity {severity}, confidence {confidence:.2f})."
        ),
    ),
    "shipment_delay": PropagationRule(
        name="shipment_delay",
        version="1.0.0",
        description=("Shipment delay propagates: Shipment → Facilities → Orders → Customers."),
        applies_to_signals=[
            "bottleneck_alert",
            "criticality_alert",
        ],
        direction=PropagationDirection.DOWNSTREAM,
        relationship_types=[
            "ORIGINATES_FROM",
            "DESTINED_TO",
            "SHIPS_FROM",
            "SHIPS_TO",
            "ORDERED_BY",
            "STORED_AT",
        ],
        max_depth=5,
        attenuation_per_hop=0.88,
        confidence_decay_per_hop=0.92,
        stop_at_entity_types=["Customer"],
        skip_relationships=[
            "PARENT_OF",
            "COMPONENT_OF",
            "HAS_COMPONENT",
            "LOCATED_IN",
            "USES_ROUTE",
        ],
        default_impact_type=ImpactType.LOGISTICS,
        severity_by_hop={
            0: Severity.WARNING,
            1: Severity.WARNING,
            2: Severity.INFO,
            3: Severity.INFO,
        },
        entity_type_impact_map={
            "Shipment": ImpactType.LOGISTICS,
            "Facility": ImpactType.FACILITY,
            "SalesOrder": ImpactType.ORDER,
            "PurchaseOrder": ImpactType.ORDER,
            "Customer": ImpactType.CUSTOMER,
        },
        explanation_template=(
            "Shipment delay at {source_entity} propagated via {relationship} "
            "to {affected_entity} (hop {hop}, severity {severity}, confidence {confidence:.2f})."
        ),
    ),
    "demand_spike": PropagationRule(
        name="demand_spike",
        version="1.0.0",
        description=(
            "Demand spike propagates upstream: Customer → Orders → Facilities → "
            "Inventory → Suppliers."
        ),
        applies_to_signals=[
            "concentration_risk_alert",
            "criticality_alert",
        ],
        direction=PropagationDirection.UPSTREAM,
        relationship_types=[
            "ORDERED_BY",
            "SHIPS_FROM",
            "STORED_AT",
            "IS_PRODUCT",
            "SUPPLIED_BY",
            "ORDERS_FROM",
            "SHIPS_TO",
        ],
        max_depth=7,
        attenuation_per_hop=0.85,
        confidence_decay_per_hop=0.90,
        stop_at_entity_types=["Supplier"],
        skip_relationships=[
            "PARENT_OF",
            "COMPONENT_OF",
            "HAS_COMPONENT",
            "LOCATED_IN",
            "USES_ROUTE",
        ],
        default_impact_type=ImpactType.CUSTOMER,
        severity_by_hop={
            0: Severity.CRITICAL,
            1: Severity.WARNING,
            2: Severity.WARNING,
            3: Severity.INFO,
        },
        entity_type_impact_map={
            "Customer": ImpactType.CUSTOMER,
            "SalesOrder": ImpactType.ORDER,
            "Facility": ImpactType.FACILITY,
            "InventoryItem": ImpactType.INVENTORY,
            "Product": ImpactType.INVENTORY,
            "Supplier": ImpactType.SUPPLIER,
            "PurchaseOrder": ImpactType.ORDER,
        },
        explanation_template=(
            "Demand spike from {source_entity} propagated via {relationship} "
            "to {affected_entity} (hop {hop}, severity {severity}, confidence {confidence:.2f})."
        ),
    ),
    "inventory_shortage": PropagationRule(
        name="inventory_shortage",
        version="1.0.0",
        description=("Inventory shortage propagates: Inventory → Orders → Customers."),
        applies_to_signals=[
            "single_point_of_failure_alert",
            "concentration_risk_alert",
            "criticality_alert",
        ],
        direction=PropagationDirection.DOWNSTREAM,
        relationship_types=[
            "IS_PRODUCT",
            "SHIPS_FROM",
            "ORDERED_BY",
            "STORED_AT",
        ],
        max_depth=4,
        attenuation_per_hop=0.90,
        confidence_decay_per_hop=0.93,
        stop_at_entity_types=["Customer"],
        skip_relationships=[
            "PARENT_OF",
            "COMPONENT_OF",
            "HAS_COMPONENT",
            "LOCATED_IN",
            "USES_ROUTE",
        ],
        default_impact_type=ImpactType.INVENTORY,
        severity_by_hop={
            0: Severity.CRITICAL,
            1: Severity.WARNING,
            2: Severity.WARNING,
            3: Severity.INFO,
        },
        entity_type_impact_map={
            "InventoryItem": ImpactType.INVENTORY,
            "Product": ImpactType.INVENTORY,
            "SalesOrder": ImpactType.ORDER,
            "Facility": ImpactType.FACILITY,
            "Customer": ImpactType.CUSTOMER,
        },
        explanation_template=(
            "Inventory shortage at {source_entity} propagated via {relationship} "
            "to {affected_entity} (hop {hop}, severity {severity}, confidence {confidence:.2f})."
        ),
    ),
    "generic_downstream": PropagationRule(
        name="generic_downstream",
        version="1.0.0",
        description=(
            "Fallback rule: propagates downstream impact from any node "
            "through any edge type. Used when no specific rule matches."
        ),
        applies_to_signals=[],  # Fallback — never directly keyed
        direction=PropagationDirection.DOWNSTREAM,
        relationship_types=[],  # All edges
        max_depth=5,
        attenuation_per_hop=0.85,
        confidence_decay_per_hop=0.90,
        stop_at_entity_types=[],
        skip_relationships=["PARENT_OF", "LOCATED_IN", "COMPONENT_OF", "HAS_COMPONENT"],
        default_impact_type=ImpactType.UNKNOWN,
        severity_by_hop={},
        entity_type_impact_map={},
        explanation_template=(
            "Impact from {source_entity} propagated via {relationship} "
            "to {affected_entity} (hop {hop}, confidence {confidence:.2f})."
        ),
    ),
}


def get_rule(signal_name: str) -> PropagationRule:
    """Get the propagation rule for a signal name.

    Returns the first matching rule. Falls back to 'generic_downstream'
    if no specific rule matches the signal name.
    """
    for _rule_name, rule in PROPAGATION_RULES.items():
        if signal_name in rule.applies_to_signals:
            return rule
    return PROPAGATION_RULES["generic_downstream"]


def list_rules() -> list[PropagationRule]:
    """List all propagation rules."""
    return list(PROPAGATION_RULES.values())
