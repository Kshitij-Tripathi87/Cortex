"""Recommendation Rules — deterministic candidate generation for Program G.

This module defines:
  - Recommendation type specifications (closed taxonomy)
  - Candidate generation rules per scenario type
  - Required evidence validation
  - Policy classifications

All rules are deterministic and testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.modules.graph.recommendation_models import (
    PolicyClassification,
    RecommendationCategory,
    RecommendationType,
    ReversibilityLevel,
)
from app.modules.graph.scenario_models import ScenarioType


@dataclass(frozen=True)
class RecommendationTypeSpec:
    """Specification for a recommendation type in the closed taxonomy.

    Each type defines:
      - human-readable name
      - allowed scenario types
      - required evidence inputs
      - expected trade-offs
      - reversibility expectation
      - policy classification
    """

    recommendation_type: RecommendationType
    category: RecommendationCategory
    name: str
    description: str
    allowed_scenario_types: list[ScenarioType]
    required_evidence: list[str]  # entity types that must be present
    typical_trade_offs: list[str]  # dimensions of trade-offs
    reversibility: ReversibilityLevel
    policy_classification: PolicyClassification
    estimated_cost_range: tuple[float, float] | None = None  # (min, max) USD
    estimated_time_range: tuple[float, float] | None = None  # (min, max) hours

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommendation_type": self.recommendation_type.value,
            "category": self.category.value,
            "name": self.name,
            "description": self.description,
            "allowed_scenario_types": [s.value for s in self.allowed_scenario_types],
            "required_evidence": list(self.required_evidence),
            "typical_trade_offs": list(self.typical_trade_offs),
            "reversibility": self.reversibility.value,
            "policy_classification": self.policy_classification.value,
            "estimated_cost_range": list(self.estimated_cost_range)
            if self.estimated_cost_range
            else None,
            "estimated_time_range": list(self.estimated_time_range)
            if self.estimated_time_range
            else None,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Recommendation Type Specifications (Closed Taxonomy)
# ─────────────────────────────────────────────────────────────────────────────

RECOMMENDATION_TAXONOMY: dict[RecommendationType, RecommendationTypeSpec] = {
    # Supply-side actions
    RecommendationType.EXPEDITE_SHIPMENT: RecommendationTypeSpec(
        recommendation_type=RecommendationType.EXPEDITE_SHIPMENT,
        category=RecommendationCategory.SUPPLY_SIDE,
        name="Expedite Shipment",
        description="Accelerate existing inbound shipment to reduce lead time",
        allowed_scenario_types=[
            ScenarioType.SUPPLIER_FAILURE,
            ScenarioType.INVENTORY_SHORTAGE,
            ScenarioType.DEMAND_SPIKE,
        ],
        required_evidence=["Shipment", "InventoryItem"],
        typical_trade_offs=["cost", "speed", "risk"],
        reversibility=ReversibilityLevel.PARTIALLY_REVERSIBLE,
        policy_classification=PolicyClassification.REVIEW_REQUIRED,
        estimated_cost_range=(500.0, 5000.0),
        estimated_time_range=(4.0, 24.0),
    ),
    RecommendationType.USE_ALTERNATE_SUPPLIER: RecommendationTypeSpec(
        recommendation_type=RecommendationType.USE_ALTERNATE_SUPPLIER,
        category=RecommendationCategory.SUPPLY_SIDE,
        name="Use Alternate Supplier",
        description="Switch to alternative supplier to maintain supply continuity",
        allowed_scenario_types=[
            ScenarioType.SUPPLIER_FAILURE,
            ScenarioType.CAPACITY_CONSTRAINT,
        ],
        required_evidence=["Supplier", "Product"],
        typical_trade_offs=["cost", "quality", "lead_time", "risk"],
        reversibility=ReversibilityLevel.PARTIALLY_REVERSIBLE,
        policy_classification=PolicyClassification.REVIEW_REQUIRED,
        estimated_cost_range=(1000.0, 10000.0),
        estimated_time_range=(24.0, 168.0),
    ),
    RecommendationType.TRANSFER_INVENTORY: RecommendationTypeSpec(
        recommendation_type=RecommendationType.TRANSFER_INVENTORY,
        category=RecommendationCategory.SUPPLY_SIDE,
        name="Transfer Inventory",
        description="Move inventory from another warehouse to cover shortage",
        allowed_scenario_types=[
            ScenarioType.INVENTORY_SHORTAGE,
            ScenarioType.WAREHOUSE_OUTAGE,
            ScenarioType.DEMAND_SPIKE,
        ],
        required_evidence=["InventoryItem", "Facility"],
        typical_trade_offs=["cost", "speed", "service_level"],
        reversibility=ReversibilityLevel.FULLY_REVERSIBLE,
        policy_classification=PolicyClassification.AUTO_APPROVED,
        estimated_cost_range=(200.0, 3000.0),
        estimated_time_range=(12.0, 72.0),
    ),
    RecommendationType.REBALANCE_STOCK: RecommendationTypeSpec(
        recommendation_type=RecommendationType.REBALANCE_STOCK,
        category=RecommendationCategory.SUPPLY_SIDE,
        name="Rebalance Stock",
        description="Redistribute inventory across warehouses to optimize coverage",
        allowed_scenario_types=[
            ScenarioType.INVENTORY_SHORTAGE,
            ScenarioType.DEMAND_SPIKE,
            ScenarioType.DEMAND_DROP,
        ],
        required_evidence=["InventoryItem", "Facility"],
        typical_trade_offs=["cost", "service_level", "complexity"],
        reversibility=ReversibilityLevel.FULLY_REVERSIBLE,
        policy_classification=PolicyClassification.AUTO_APPROVED,
        estimated_cost_range=(500.0, 5000.0),
        estimated_time_range=(24.0, 96.0),
    ),
    # Demand-side actions
    RecommendationType.PRIORITIZE_CRITICAL_ORDERS: RecommendationTypeSpec(
        recommendation_type=RecommendationType.PRIORITIZE_CRITICAL_ORDERS,
        category=RecommendationCategory.DEMAND_SIDE,
        name="Prioritize Critical Orders",
        description="Allocate limited inventory to critical customer orders first",
        allowed_scenario_types=[
            ScenarioType.INVENTORY_SHORTAGE,
            ScenarioType.DEMAND_SPIKE,
            ScenarioType.CAPACITY_CONSTRAINT,
        ],
        required_evidence=["Order", "Customer"],
        typical_trade_offs=["service_level", "customer_satisfaction", "revenue"],
        reversibility=ReversibilityLevel.PARTIALLY_REVERSIBLE,
        policy_classification=PolicyClassification.REVIEW_REQUIRED,
        estimated_cost_range=(0.0, 1000.0),
        estimated_time_range=(1.0, 8.0),
    ),
    RecommendationType.DELAY_LOW_PRIORITY_ORDERS: RecommendationTypeSpec(
        recommendation_type=RecommendationType.DELAY_LOW_PRIORITY_ORDERS,
        category=RecommendationCategory.DEMAND_SIDE,
        name="Delay Low-Priority Orders",
        description="Postpone fulfillment of lower-priority orders to preserve inventory",
        allowed_scenario_types=[
            ScenarioType.INVENTORY_SHORTAGE,
            ScenarioType.CAPACITY_CONSTRAINT,
            ScenarioType.WAREHOUSE_OUTAGE,
        ],
        required_evidence=["Order"],
        typical_trade_offs=["service_level", "customer_satisfaction", "penalty_costs"],
        reversibility=ReversibilityLevel.PARTIALLY_REVERSIBLE,
        policy_classification=PolicyClassification.REVIEW_REQUIRED,
        estimated_cost_range=(0.0, 2000.0),
        estimated_time_range=(1.0, 4.0),
    ),
    RecommendationType.SPLIT_FULFILLMENT: RecommendationTypeSpec(
        recommendation_type=RecommendationType.SPLIT_FULFILLMENT,
        category=RecommendationCategory.DEMAND_SIDE,
        name="Split Fulfillment",
        description="Fulfill order from multiple warehouses to meet demand",
        allowed_scenario_types=[
            ScenarioType.INVENTORY_SHORTAGE,
            ScenarioType.WAREHOUSE_OUTAGE,
        ],
        required_evidence=["Order", "Facility", "InventoryItem"],
        typical_trade_offs=["cost", "speed", "complexity"],
        reversibility=ReversibilityLevel.FULLY_REVERSIBLE,
        policy_classification=PolicyClassification.AUTO_APPROVED,
        estimated_cost_range=(300.0, 2000.0),
        estimated_time_range=(12.0, 48.0),
    ),
    # Logistics actions
    RecommendationType.REROUTE_SHIPMENT: RecommendationTypeSpec(
        recommendation_type=RecommendationType.REROUTE_SHIPMENT,
        category=RecommendationCategory.LOGISTICS,
        name="Reroute Shipment",
        description="Change shipment route to avoid disruption",
        allowed_scenario_types=[
            ScenarioType.ROUTE_CLOSURE,
            ScenarioType.SHIPMENT_DELAY,
        ],
        required_evidence=["Shipment", "LogisticsRoute"],
        typical_trade_offs=["cost", "speed", "risk"],
        reversibility=ReversibilityLevel.PARTIALLY_REVERSIBLE,
        policy_classification=PolicyClassification.REVIEW_REQUIRED,
        estimated_cost_range=(500.0, 8000.0),
        estimated_time_range=(4.0, 48.0),
    ),
    RecommendationType.EXPEDITE_ALTERNATIVE_CARRIER: RecommendationTypeSpec(
        recommendation_type=RecommendationType.EXPEDITE_ALTERNATIVE_CARRIER,
        category=RecommendationCategory.LOGISTICS,
        name="Expedite Alternative Carrier",
        description="Switch to faster carrier or logistics provider",
        allowed_scenario_types=[
            ScenarioType.SHIPMENT_DELAY,
            ScenarioType.ROUTE_CLOSURE,
        ],
        required_evidence=["Shipment", "Carrier"],
        typical_trade_offs=["cost", "speed", "reliability"],
        reversibility=ReversibilityLevel.PARTIALLY_REVERSIBLE,
        policy_classification=PolicyClassification.REVIEW_REQUIRED,
        estimated_cost_range=(1000.0, 10000.0),
        estimated_time_range=(4.0, 24.0),
    ),
    # Operational actions
    RecommendationType.HOLD_SHIPMENT_PENDING_REVIEW: RecommendationTypeSpec(
        recommendation_type=RecommendationType.HOLD_SHIPMENT_PENDING_REVIEW,
        category=RecommendationCategory.OPERATIONAL,
        name="Hold Shipment Pending Review",
        description="Pause shipment execution pending human review of situation",
        allowed_scenario_types=[
            ScenarioType.SUPPLIER_FAILURE,
            ScenarioType.WAREHOUSE_OUTAGE,
            ScenarioType.ROUTE_CLOSURE,
        ],
        required_evidence=["Shipment"],
        typical_trade_offs=["speed", "risk", "control"],
        reversibility=ReversibilityLevel.FULLY_REVERSIBLE,
        policy_classification=PolicyClassification.AUTO_APPROVED,
        estimated_cost_range=(0.0, 500.0),
        estimated_time_range=(1.0, 8.0),
    ),
    RecommendationType.REALLOCATE_TO_CRITICAL_CUSTOMERS: RecommendationTypeSpec(
        recommendation_type=RecommendationType.REALLOCATE_TO_CRITICAL_CUSTOMERS,
        category=RecommendationCategory.OPERATIONAL,
        name="Reallocate to Critical Customers",
        description="Redirect inventory allocation to protect critical customer relationships",
        allowed_scenario_types=[
            ScenarioType.INVENTORY_SHORTAGE,
            ScenarioType.DEMAND_SPIKE,
        ],
        required_evidence=["Customer", "InventoryItem", "Order"],
        typical_trade_offs=["service_level", "revenue", "customer_satisfaction"],
        reversibility=ReversibilityLevel.PARTIALLY_REVERSIBLE,
        policy_classification=PolicyClassification.REVIEW_REQUIRED,
        estimated_cost_range=(0.0, 3000.0),
        estimated_time_range=(2.0, 12.0),
    ),
    # Monitoring / no-action
    RecommendationType.NO_ACTION_MONITOR: RecommendationTypeSpec(
        recommendation_type=RecommendationType.NO_ACTION_MONITOR,
        category=RecommendationCategory.MONITORING,
        name="No Action - Monitor",
        description="Continue monitoring - current impact is within acceptable tolerance",
        allowed_scenario_types=[
            ScenarioType.SUPPLIER_FAILURE,
            ScenarioType.WAREHOUSE_OUTAGE,
            ScenarioType.ROUTE_CLOSURE,
            ScenarioType.SHIPMENT_DELAY,
            ScenarioType.DEMAND_SPIKE,
            ScenarioType.DEMAND_DROP,
            ScenarioType.INVENTORY_SHORTAGE,
            ScenarioType.CAPACITY_CONSTRAINT,
        ],
        required_evidence=[],
        typical_trade_offs=["risk", "proactivity"],
        reversibility=ReversibilityLevel.FULLY_REVERSIBLE,
        policy_classification=PolicyClassification.AUTO_APPROVED,
        estimated_cost_range=(0.0, 100.0),
        estimated_time_range=(0.0, 1.0),
    ),
    RecommendationType.CUSTOM: RecommendationTypeSpec(
        recommendation_type=RecommendationType.CUSTOM,
        category=RecommendationCategory.OPERATIONAL,
        name="Custom Recommendation",
        description="Custom recommendation requiring explicit policy approval",
        allowed_scenario_types=list(ScenarioType),
        required_evidence=[],
        typical_trade_offs=["varies"],
        reversibility=ReversibilityLevel.UNKNOWN,
        policy_classification=PolicyClassification.POLICY_RESTRICTED,
        estimated_cost_range=None,
        estimated_time_range=None,
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
# Scenario → Recommendation Mapping Rules
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ScenarioRecommendationRule:
    """Rule defining which recommendations to generate for a scenario type.

    Each scenario type has a set of candidate recommendations that should
    be considered based on the scenario characteristics.
    """

    scenario_type: ScenarioType
    candidate_types: list[RecommendationType]
    conditions: dict[str, Any]  # conditions that must be met
    priority_weights: dict[RecommendationType, float]  # initial priority weights

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_type": self.scenario_type.value,
            "candidate_types": [t.value for t in self.candidate_types],
            "conditions": dict(self.conditions),
            "priority_weights": {t.value: w for t, w in self.priority_weights.items()},
        }


# Rules for each scenario type
SCENARIO_RECOMMENDATION_RULES: dict[ScenarioType, ScenarioRecommendationRule] = {
    ScenarioType.SUPPLIER_FAILURE: ScenarioRecommendationRule(
        scenario_type=ScenarioType.SUPPLIER_FAILURE,
        candidate_types=[
            RecommendationType.USE_ALTERNATE_SUPPLIER,
            RecommendationType.EXPEDITE_SHIPMENT,
            RecommendationType.TRANSFER_INVENTORY,
            RecommendationType.DELAY_LOW_PRIORITY_ORDERS,
            RecommendationType.HOLD_SHIPMENT_PENDING_REVIEW,
            RecommendationType.NO_ACTION_MONITOR,
        ],
        conditions={
            "min_severity": "warning",
            "requires_alternate_supplier": True,
        },
        priority_weights={
            RecommendationType.USE_ALTERNATE_SUPPLIER: 0.9,
            RecommendationType.EXPEDITE_SHIPMENT: 0.7,
            RecommendationType.TRANSFER_INVENTORY: 0.6,
            RecommendationType.DELAY_LOW_PRIORITY_ORDERS: 0.4,
            RecommendationType.HOLD_SHIPMENT_PENDING_REVIEW: 0.3,
            RecommendationType.NO_ACTION_MONITOR: 0.1,
        },
    ),
    ScenarioType.WAREHOUSE_OUTAGE: ScenarioRecommendationRule(
        scenario_type=ScenarioType.WAREHOUSE_OUTAGE,
        candidate_types=[
            RecommendationType.TRANSFER_INVENTORY,
            RecommendationType.SPLIT_FULFILLMENT,
            RecommendationType.REROUTE_SHIPMENT,
            RecommendationType.DELAY_LOW_PRIORITY_ORDERS,
            RecommendationType.HOLD_SHIPMENT_PENDING_REVIEW,
            RecommendationType.NO_ACTION_MONITOR,
        ],
        conditions={
            "min_severity": "warning",
            "requires_alternate_facility": True,
        },
        priority_weights={
            RecommendationType.TRANSFER_INVENTORY: 0.9,
            RecommendationType.SPLIT_FULFILLMENT: 0.7,
            RecommendationType.REROUTE_SHIPMENT: 0.6,
            RecommendationType.DELAY_LOW_PRIORITY_ORDERS: 0.4,
            RecommendationType.HOLD_SHIPMENT_PENDING_REVIEW: 0.3,
            RecommendationType.NO_ACTION_MONITOR: 0.1,
        },
    ),
    ScenarioType.ROUTE_CLOSURE: ScenarioRecommendationRule(
        scenario_type=ScenarioType.ROUTE_CLOSURE,
        candidate_types=[
            RecommendationType.REROUTE_SHIPMENT,
            RecommendationType.EXPEDITE_ALTERNATIVE_CARRIER,
            RecommendationType.DELAY_LOW_PRIORITY_ORDERS,
            RecommendationType.HOLD_SHIPMENT_PENDING_REVIEW,
            RecommendationType.NO_ACTION_MONITOR,
        ],
        conditions={
            "min_severity": "warning",
            "requires_alternate_route": True,
        },
        priority_weights={
            RecommendationType.REROUTE_SHIPMENT: 0.9,
            RecommendationType.EXPEDITE_ALTERNATIVE_CARRIER: 0.7,
            RecommendationType.DELAY_LOW_PRIORITY_ORDERS: 0.4,
            RecommendationType.HOLD_SHIPMENT_PENDING_REVIEW: 0.3,
            RecommendationType.NO_ACTION_MONITOR: 0.1,
        },
    ),
    ScenarioType.SHIPMENT_DELAY: ScenarioRecommendationRule(
        scenario_type=ScenarioType.SHIPMENT_DELAY,
        candidate_types=[
            RecommendationType.EXPEDITE_SHIPMENT,
            RecommendationType.EXPEDITE_ALTERNATIVE_CARRIER,
            RecommendationType.REROUTE_SHIPMENT,
            RecommendationType.HOLD_SHIPMENT_PENDING_REVIEW,
            RecommendationType.NO_ACTION_MONITOR,
        ],
        conditions={
            "min_severity": "info",
            "delay_threshold_hours": 24.0,
        },
        priority_weights={
            RecommendationType.EXPEDITE_SHIPMENT: 0.8,
            RecommendationType.EXPEDITE_ALTERNATIVE_CARRIER: 0.7,
            RecommendationType.REROUTE_SHIPMENT: 0.6,
            RecommendationType.HOLD_SHIPMENT_PENDING_REVIEW: 0.3,
            RecommendationType.NO_ACTION_MONITOR: 0.2,
        },
    ),
    ScenarioType.DEMAND_SPIKE: ScenarioRecommendationRule(
        scenario_type=ScenarioType.DEMAND_SPIKE,
        candidate_types=[
            RecommendationType.TRANSFER_INVENTORY,
            RecommendationType.REBALANCE_STOCK,
            RecommendationType.PRIORITIZE_CRITICAL_ORDERS,
            RecommendationType.EXPEDITE_SHIPMENT,
            RecommendationType.REALLOCATE_TO_CRITICAL_CUSTOMERS,
            RecommendationType.NO_ACTION_MONITOR,
        ],
        conditions={
            "min_severity": "warning",
            "spike_threshold_pct": 20.0,
        },
        priority_weights={
            RecommendationType.TRANSFER_INVENTORY: 0.8,
            RecommendationType.REBALANCE_STOCK: 0.7,
            RecommendationType.PRIORITIZE_CRITICAL_ORDERS: 0.7,
            RecommendationType.EXPEDITE_SHIPMENT: 0.6,
            RecommendationType.REALLOCATE_TO_CRITICAL_CUSTOMERS: 0.6,
            RecommendationType.NO_ACTION_MONITOR: 0.1,
        },
    ),
    ScenarioType.DEMAND_DROP: ScenarioRecommendationRule(
        scenario_type=ScenarioType.DEMAND_DROP,
        candidate_types=[
            RecommendationType.REBALANCE_STOCK,
            RecommendationType.DELAY_LOW_PRIORITY_ORDERS,
            RecommendationType.NO_ACTION_MONITOR,
        ],
        conditions={
            "min_severity": "info",
            "drop_threshold_pct": 20.0,
        },
        priority_weights={
            RecommendationType.REBALANCE_STOCK: 0.7,
            RecommendationType.DELAY_LOW_PRIORITY_ORDERS: 0.4,
            RecommendationType.NO_ACTION_MONITOR: 0.5,
        },
    ),
    ScenarioType.INVENTORY_SHORTAGE: ScenarioRecommendationRule(
        scenario_type=ScenarioType.INVENTORY_SHORTAGE,
        candidate_types=[
            RecommendationType.TRANSFER_INVENTORY,
            RecommendationType.EXPEDITE_SHIPMENT,
            RecommendationType.USE_ALTERNATE_SUPPLIER,
            RecommendationType.PRIORITIZE_CRITICAL_ORDERS,
            RecommendationType.REALLOCATE_TO_CRITICAL_CUSTOMERS,
            RecommendationType.SPLIT_FULFILLMENT,
            RecommendationType.NO_ACTION_MONITOR,
        ],
        conditions={
            "min_severity": "warning",
            "shortage_threshold_days": 7,
        },
        priority_weights={
            RecommendationType.TRANSFER_INVENTORY: 0.9,
            RecommendationType.EXPEDITE_SHIPMENT: 0.8,
            RecommendationType.USE_ALTERNATE_SUPPLIER: 0.7,
            RecommendationType.PRIORITIZE_CRITICAL_ORDERS: 0.6,
            RecommendationType.REALLOCATE_TO_CRITICAL_CUSTOMERS: 0.6,
            RecommendationType.SPLIT_FULFILLMENT: 0.5,
            RecommendationType.NO_ACTION_MONITOR: 0.1,
        },
    ),
    ScenarioType.CAPACITY_CONSTRAINT: ScenarioRecommendationRule(
        scenario_type=ScenarioType.CAPACITY_CONSTRAINT,
        candidate_types=[
            RecommendationType.USE_ALTERNATE_SUPPLIER,
            RecommendationType.PRIORITIZE_CRITICAL_ORDERS,
            RecommendationType.DELAY_LOW_PRIORITY_ORDERS,
            RecommendationType.REBALANCE_STOCK,
            RecommendationType.NO_ACTION_MONITOR,
        ],
        conditions={
            "min_severity": "warning",
            "capacity_threshold_pct": 80.0,
        },
        priority_weights={
            RecommendationType.USE_ALTERNATE_SUPPLIER: 0.8,
            RecommendationType.PRIORITIZE_CRITICAL_ORDERS: 0.7,
            RecommendationType.DELAY_LOW_PRIORITY_ORDERS: 0.6,
            RecommendationType.REBALANCE_STOCK: 0.5,
            RecommendationType.NO_ACTION_MONITOR: 0.2,
        },
    ),
}


def get_recommendation_type_spec(
    recommendation_type: RecommendationType,
) -> RecommendationTypeSpec | None:
    """Get specification for a recommendation type."""
    return RECOMMENDATION_TAXONOMY.get(recommendation_type)


def get_scenario_recommendation_rule(
    scenario_type: ScenarioType,
) -> ScenarioRecommendationRule | None:
    """Get recommendation rule for a scenario type."""
    return SCENARIO_RECOMMENDATION_RULES.get(scenario_type)


def get_allowed_recommendation_types(
    scenario_type: ScenarioType,
) -> list[RecommendationType]:
    """Get list of recommendation types allowed for a scenario type."""
    rule = SCENARIO_RECOMMENDATION_RULES.get(scenario_type)
    if rule:
        return list(rule.candidate_types)
    return []


def is_recommendation_allowed(
    scenario_type: ScenarioType,
    recommendation_type: RecommendationType,
) -> bool:
    """Check if a recommendation type is allowed for a scenario type."""
    allowed = get_allowed_recommendation_types(scenario_type)
    return recommendation_type in allowed
