"""Scenario Rules — deterministic specifications for scenario execution.

Rules are NOT algorithms. They are specifications consumed by the
ScenarioEngine runtime. Each rule defines:

  - scenario type it applies to
  - required parameters and their validation
  - assumptions to record
  - how to map propagation impacts to scenario impacts
  - recovery time estimation formulas
  - financial impact estimation formulas
  - service level impact formulas

The runtime selects the matching rule for a scenario type and applies
it to the source propagation snapshot. Same inputs → same outputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.modules.graph.scenario_models import (
    ScenarioAssumption,
    ScenarioDefinition,
    ScenarioParameter,
    ScenarioType,
)

# ─────────────────────────────────────────────────────────────────────────────
# Rule Contract
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ScenarioRule:
    """Specification for one scenario behavior.

    Versioned and frozen — modifications require a new version.
    """

    name: str
    version: str
    scenario_type: ScenarioType
    description: str

    # Required parameters (name, required, default, unit, validator)
    parameters: list[dict[str, Any]] = field(default_factory=list)

    # Default assumptions to record
    default_assumptions: list[dict[str, Any]] = field(default_factory=list)

    # Impact mapping: how to transform propagation impacts
    impact_category_map: dict[str, str] = field(default_factory=dict)
    severity_map: dict[str, str] = field(default_factory=dict)
    default_impact_type: str = "business"

    # Estimation formulas (deterministic)
    recovery_hours_base: float = 24.0
    recovery_hours_per_hop: float = 12.0
    recovery_hours_per_severity: dict[str, float] = field(default_factory=dict)

    financial_impact_base: float = 10000.0
    financial_impact_per_severity: dict[str, float] = field(default_factory=dict)
    financial_impact_per_entity_type: dict[str, float] = field(default_factory=dict)

    service_level_impact_base: float = 5.0  # percentage
    service_level_impact_per_severity: dict[str, float] = field(default_factory=dict)
    service_level_impact_per_hop: float = 2.0

    def validate_parameters(self, params: list[ScenarioParameter]) -> list[str]:
        """Validate scenario parameters. Returns list of errors (empty if valid)."""
        errors = []
        provided = {p.name: p for p in params}
        for p_def in self.parameters:
            name = p_def["name"]
            required = p_def.get("required", False)
            if required and name not in provided:
                errors.append(f"Missing required parameter: {name}")
            if name in provided:
                value = provided[name].value
                # Type validation
                expected_type = p_def.get("type")
                if expected_type and not isinstance(value, expected_type):
                    errors.append(
                        f"Parameter {name}: expected {expected_type}, got {type(value).__name__}"
                    )
                # Range validation
                if "min" in p_def and value < p_def["min"]:
                    errors.append(f"Parameter {name}: value {value} below minimum {p_def['min']}")
                if "max" in p_def and value > p_def["max"]:
                    errors.append(f"Parameter {name}: value {value} above maximum {p_def['max']}")
        return errors

    def build_assumptions(self, definition: ScenarioDefinition) -> list[ScenarioAssumption]:
        """Build assumptions from defaults + scenario parameters."""
        from app.common.ids import uuid7

        assumptions = []
        for a_def in self.default_assumptions:
            assumptions.append(
                ScenarioAssumption(
                    assumption_id=str(uuid7()),
                    scenario_id=definition.scenario_id,
                    description=a_def.get("description", ""),
                    category=a_def.get("category", "business"),
                    confidence=a_def.get("confidence", 0.8),
                    source=a_def.get("source", "default"),
                    metadata=a_def.get("metadata", {}),
                )
            )
        return assumptions

    def estimate_recovery_hours(
        self,
        hop: int,
        severity: str,
        entity_type: str,
    ) -> float:
        """Estimate recovery time in hours."""
        hours = self.recovery_hours_base
        hours += hop * self.recovery_hours_per_hop
        hours += self.recovery_hours_per_severity.get(severity, 0.0)
        return round(hours, 1)

    def estimate_financial_impact(
        self,
        severity: str,
        entity_type: str,
        hop: int,
    ) -> float:
        """Estimate financial impact in dollars."""
        impact = self.financial_impact_base
        impact *= self.financial_impact_per_severity.get(severity, 1.0)
        impact *= self.financial_impact_per_entity_type.get(entity_type, 1.0)
        # Attenuate by hop distance
        impact *= max(0.1, 1.0 - (hop * 0.1))
        return round(impact, 2)

    def estimate_service_level_impact(
        self,
        severity: str,
        hop: int,
    ) -> float:
        """Estimate service level impact as percentage."""
        impact = self.service_level_impact_base
        impact += self.service_level_impact_per_severity.get(severity, 0.0)
        impact += hop * self.service_level_impact_per_hop
        return round(min(100.0, impact), 1)


# ─────────────────────────────────────────────────────────────────────────────
# Frozen Rule Registry — supply-chain native scenario rules
# ─────────────────────────────────────────────────────────────────────────────


SCENARIO_RULES: dict[ScenarioType, ScenarioRule] = {
    ScenarioType.SUPPLIER_FAILURE: ScenarioRule(
        name="supplier_failure",
        version="1.0.0",
        scenario_type=ScenarioType.SUPPLIER_FAILURE,
        description="Simulate complete supplier failure: no deliveries, no capacity.",
        parameters=[
            {
                "name": "failure_duration_days",
                "required": True,
                "type": int,
                "min": 1,
                "max": 365,
                "unit": "days",
            },
            {
                "name": "alternative_supplier_available",
                "required": False,
                "type": bool,
                "default": False,
            },
            {
                "name": "inventory_buffer_days",
                "required": False,
                "type": int,
                "min": 0,
                "default": 0,
                "unit": "days",
            },
        ],
        default_assumptions=[
            {
                "description": "No incoming shipments from failed supplier",
                "category": "graph",
                "confidence": 1.0,
                "source": "scenario_definition",
            },
            {
                "description": "Alternative suppliers not available unless specified",
                "category": "business",
                "confidence": 0.7,
                "source": "default",
            },
            {
                "description": "Propagation follows existing dependency graph",
                "category": "propagation",
                "confidence": 0.9,
                "source": "derived_from_context",
            },
        ],
        impact_category_map={
            "Supplier": "supplier",
            "Facility": "production",
            "InventoryItem": "inventory",
            "Product": "inventory",
            "PurchaseOrder": "order",
            "SalesOrder": "order",
            "Customer": "customer",
            "Shipment": "logistics",
            "Route": "logistics",
            "Carrier": "logistics",
        },
        severity_map={
            "blocking": "critical",
            "critical": "critical",
            "warning": "warning",
            "info": "info",
        },
        recovery_hours_base=48.0,
        recovery_hours_per_hop=24.0,
        recovery_hours_per_severity={
            "critical": 72.0,
            "warning": 24.0,
            "info": 8.0,
        },
        financial_impact_base=50000.0,
        financial_impact_per_severity={
            "critical": 10.0,
            "warning": 3.0,
            "info": 0.5,
        },
        financial_impact_per_entity_type={
            "Customer": 5.0,
            "SalesOrder": 3.0,
            "Facility": 2.0,
            "InventoryItem": 1.5,
        },
        service_level_impact_base=10.0,
        service_level_impact_per_severity={
            "critical": 25.0,
            "warning": 10.0,
            "info": 2.0,
        },
        service_level_impact_per_hop=5.0,
    ),
    ScenarioType.WAREHOUSE_OUTAGE: ScenarioRule(
        name="warehouse_outage",
        version="1.0.0",
        scenario_type=ScenarioType.WAREHOUSE_OUTAGE,
        description="Simulate warehouse/facility outage: no storage, no fulfillment.",
        parameters=[
            {
                "name": "outage_duration_days",
                "required": True,
                "type": int,
                "min": 1,
                "max": 365,
                "unit": "days",
            },
            {
                "name": "backup_facility_available",
                "required": False,
                "type": bool,
                "default": False,
            },
            {"name": "cross_dock_capability", "required": False, "type": bool, "default": False},
        ],
        default_assumptions=[
            {
                "description": "No inventory accessible at affected facility",
                "category": "graph",
                "confidence": 1.0,
                "source": "scenario_definition",
            },
            {
                "description": "In-transit shipments rerouted if backup exists",
                "category": "logistics",
                "confidence": 0.6,
                "source": "default",
            },
        ],
        impact_category_map={
            "Facility": "production",
            "InventoryItem": "inventory",
            "Product": "inventory",
            "SalesOrder": "order",
            "Customer": "customer",
            "Shipment": "logistics",
        },
        severity_map={
            "blocking": "critical",
            "critical": "critical",
            "warning": "warning",
            "info": "info",
        },
        recovery_hours_base=24.0,
        recovery_hours_per_hop=12.0,
        recovery_hours_per_severity={
            "critical": 48.0,
            "warning": 12.0,
            "info": 4.0,
        },
        financial_impact_base=25000.0,
        financial_impact_per_severity={
            "critical": 8.0,
            "warning": 2.5,
            "info": 0.3,
        },
        financial_impact_per_entity_type={
            "Customer": 4.0,
            "SalesOrder": 2.5,
            "InventoryItem": 2.0,
        },
        service_level_impact_base=15.0,
        service_level_impact_per_severity={
            "critical": 30.0,
            "warning": 15.0,
            "info": 3.0,
        },
        service_level_impact_per_hop=8.0,
    ),
    ScenarioType.ROUTE_CLOSURE: ScenarioRule(
        name="route_closure",
        version="1.0.0",
        scenario_type=ScenarioType.ROUTE_CLOSURE,
        description="Simulate route/transport corridor closure: no shipments via this route.",
        parameters=[
            {
                "name": "closure_duration_days",
                "required": True,
                "type": int,
                "min": 1,
                "max": 180,
                "unit": "days",
            },
            {
                "name": "alternate_routes_available",
                "required": False,
                "type": bool,
                "default": False,
            },
            {
                "name": "carrier_flexibility",
                "required": False,
                "type": str,
                "default": "medium",
                "enum": ["low", "medium", "high"],
            },
        ],
        default_assumptions=[
            {
                "description": "All shipments on closed route delayed",
                "category": "graph",
                "confidence": 1.0,
                "source": "scenario_definition",
            },
            {
                "description": "Alternate routes add transit time based on carrier flexibility",
                "category": "logistics",
                "confidence": 0.7,
                "source": "default",
            },
        ],
        impact_category_map={
            "Route": "logistics",
            "Shipment": "logistics",
            "Facility": "production",
            "SalesOrder": "order",
            "Customer": "customer",
        },
        severity_map={
            "blocking": "critical",
            "critical": "critical",
            "warning": "warning",
            "info": "info",
        },
        recovery_hours_base=12.0,
        recovery_hours_per_hop=6.0,
        recovery_hours_per_severity={
            "critical": 24.0,
            "warning": 8.0,
            "info": 2.0,
        },
        financial_impact_base=15000.0,
        financial_impact_per_severity={
            "critical": 5.0,
            "warning": 2.0,
            "info": 0.4,
        },
        financial_impact_per_entity_type={
            "Customer": 3.0,
            "SalesOrder": 2.0,
            "Shipment": 1.5,
        },
        service_level_impact_base=8.0,
        service_level_impact_per_severity={
            "critical": 20.0,
            "warning": 8.0,
            "info": 1.5,
        },
        service_level_impact_per_hop=3.0,
    ),
    ScenarioType.SHIPMENT_DELAY: ScenarioRule(
        name="shipment_delay",
        version="1.0.0",
        scenario_type=ScenarioType.SHIPMENT_DELAY,
        description="Simulate specific shipment delay: late delivery to facility/customer.",
        parameters=[
            {
                "name": "delay_days",
                "required": True,
                "type": int,
                "min": 1,
                "max": 60,
                "unit": "days",
            },
            {
                "name": "shipment_priority",
                "required": False,
                "type": str,
                "default": "standard",
                "enum": ["standard", "expedited", "critical"],
            },
        ],
        default_assumptions=[
            {
                "description": "Single shipment delayed, no systemic impact unless critical",
                "category": "logistics",
                "confidence": 0.8,
                "source": "scenario_definition",
            },
        ],
        impact_category_map={
            "Shipment": "logistics",
            "Facility": "production",
            "SalesOrder": "order",
            "Customer": "customer",
        },
        severity_map={
            "blocking": "critical",
            "critical": "critical",
            "warning": "warning",
            "info": "info",
        },
        recovery_hours_base=8.0,
        recovery_hours_per_hop=4.0,
        recovery_hours_per_severity={
            "critical": 16.0,
            "warning": 4.0,
            "info": 1.0,
        },
        financial_impact_base=5000.0,
        financial_impact_per_severity={
            "critical": 4.0,
            "warning": 1.5,
            "info": 0.2,
        },
        financial_impact_per_entity_type={
            "Customer": 2.0,
            "SalesOrder": 1.5,
        },
        service_level_impact_base=5.0,
        service_level_impact_per_severity={
            "critical": 15.0,
            "warning": 5.0,
            "info": 1.0,
        },
        service_level_impact_per_hop=2.0,
    ),
    ScenarioType.DEMAND_SPIKE: ScenarioRule(
        name="demand_spike",
        version="1.0.0",
        scenario_type=ScenarioType.DEMAND_SPIKE,
        description="Simulate sudden demand increase: capacity strain, inventory drawdown.",
        parameters=[
            {
                "name": "spike_magnitude_pct",
                "required": True,
                "type": int,
                "min": 10,
                "max": 500,
                "unit": "percent",
            },
            {
                "name": "duration_weeks",
                "required": True,
                "type": int,
                "min": 1,
                "max": 52,
                "unit": "weeks",
            },
            {
                "name": "capacity_flexibility",
                "required": False,
                "type": str,
                "default": "medium",
                "enum": ["low", "medium", "high"],
            },
        ],
        default_assumptions=[
            {
                "description": "Demand spike propagates upstream through orders",
                "category": "graph",
                "confidence": 0.9,
                "source": "derived_from_context",
            },
            {
                "description": "Capacity cannot instantly expand beyond flexibility factor",
                "category": "production",
                "confidence": 0.7,
                "source": "default",
            },
        ],
        impact_category_map={
            "Customer": "customer",
            "SalesOrder": "order",
            "Facility": "production",
            "InventoryItem": "inventory",
            "Supplier": "supplier",
        },
        severity_map={
            "blocking": "critical",
            "critical": "critical",
            "warning": "warning",
            "info": "info",
        },
        recovery_hours_base=72.0,
        recovery_hours_per_hop=16.0,
        recovery_hours_per_severity={
            "critical": 96.0,
            "warning": 32.0,
            "info": 8.0,
        },
        financial_impact_base=20000.0,
        financial_impact_per_severity={
            "critical": 6.0,
            "warning": 2.0,
            "info": 0.4,
        },
        financial_impact_per_entity_type={
            "Customer": 4.0,
            "Facility": 3.0,
            "SalesOrder": 2.0,
            "InventoryItem": 1.5,
        },
        service_level_impact_base=12.0,
        service_level_impact_per_severity={
            "critical": 25.0,
            "warning": 12.0,
            "info": 2.0,
        },
        service_level_impact_per_hop=6.0,
    ),
    ScenarioType.DEMAND_DROP: ScenarioRule(
        name="demand_drop",
        version="1.0.0",
        scenario_type=ScenarioType.DEMAND_DROP,
        description="Simulate demand decrease: excess inventory, underutilized capacity.",
        parameters=[
            {
                "name": "drop_magnitude_pct",
                "required": True,
                "type": int,
                "min": 10,
                "max": 90,
                "unit": "percent",
            },
            {
                "name": "duration_weeks",
                "required": True,
                "type": int,
                "min": 1,
                "max": 52,
                "unit": "weeks",
            },
        ],
        default_assumptions=[
            {
                "description": "Reduced orders propagate upstream",
                "category": "graph",
                "confidence": 0.9,
                "source": "derived_from_context",
            },
            {
                "description": "Inventory carrying costs increase",
                "category": "business",
                "confidence": 0.8,
                "source": "default",
            },
        ],
        impact_category_map={
            "customer": "customer",
            "sales_order": "order",
            "facility": "production",
            "inventory_item": "inventory",
            "supplier": "supplier",
        },
        severity_map={
            "blocking": "critical",
            "critical": "critical",
            "warning": "warning",
            "info": "info",
        },
        recovery_hours_base=48.0,
        recovery_hours_per_hop=12.0,
        recovery_hours_per_severity={
            "critical": 72.0,
            "warning": 24.0,
            "info": 8.0,
        },
        financial_impact_base=15000.0,
        financial_impact_per_severity={
            "critical": 5.0,
            "warning": 1.5,
            "info": 0.3,
        },
        financial_impact_per_entity_type={
            "Facility": 3.0,
            "InventoryItem": 2.5,
            "Supplier": 1.5,
        },
        service_level_impact_base=5.0,
        service_level_impact_per_severity={
            "critical": 10.0,
            "warning": 5.0,
            "info": 1.0,
        },
        service_level_impact_per_hop=2.0,
    ),
    ScenarioType.INVENTORY_SHORTAGE: ScenarioRule(
        name="inventory_shortage",
        version="1.0.0",
        scenario_type=ScenarioType.INVENTORY_SHORTAGE,
        description="Simulate inventory shortage at a facility: stockouts, backorders.",
        parameters=[
            {
                "name": "shortage_severity_pct",
                "required": True,
                "type": int,
                "min": 10,
                "max": 100,
                "unit": "percent",
            },
            {"name": "affected_skus", "required": False, "type": list, "default": []},
            {
                "name": "replenishment_lead_time_days",
                "required": False,
                "type": int,
                "min": 1,
                "default": 7,
                "unit": "days",
            },
        ],
        default_assumptions=[
            {
                "description": "Shortage propagates to dependent orders",
                "category": "graph",
                "confidence": 1.0,
                "source": "scenario_definition",
            },
            {
                "description": "No emergency replenishment unless specified",
                "category": "business",
                "confidence": 0.7,
                "source": "default",
            },
        ],
        impact_category_map={
            "inventory_item": "inventory",
            "product": "inventory",
            "sales_order": "order",
            "customer": "customer",
            "facility": "production",
        },
        severity_map={
            "blocking": "critical",
            "critical": "critical",
            "warning": "warning",
            "info": "info",
        },
        recovery_hours_base=24.0,
        recovery_hours_per_hop=12.0,
        recovery_hours_per_severity={
            "critical": 48.0,
            "warning": 16.0,
            "info": 4.0,
        },
        financial_impact_base=20000.0,
        financial_impact_per_severity={
            "critical": 7.0,
            "warning": 2.5,
            "info": 0.5,
        },
        financial_impact_per_entity_type={
            "Customer": 4.0,
            "SalesOrder": 2.5,
            "InventoryItem": 2.0,
        },
        service_level_impact_base=10.0,
        service_level_impact_per_severity={
            "critical": 25.0,
            "warning": 12.0,
            "info": 2.0,
        },
        service_level_impact_per_hop=6.0,
    ),
    ScenarioType.CAPACITY_CONSTRAINT: ScenarioRule(
        name="capacity_constraint",
        version="1.0.0",
        scenario_type=ScenarioType.CAPACITY_CONSTRAINT,
        description="Simulate production capacity constraint: bottleneck, reduced throughput.",
        parameters=[
            {
                "name": "capacity_reduction_pct",
                "required": True,
                "type": int,
                "min": 10,
                "max": 90,
                "unit": "percent",
            },
            {"name": "affected_facilities", "required": False, "type": list, "default": []},
            {"name": "overtime_available", "required": False, "type": bool, "default": True},
        ],
        default_assumptions=[
            {
                "description": "Capacity constraint propagates to downstream orders",
                "category": "graph",
                "confidence": 0.9,
                "source": "derived_from_context",
            },
            {
                "description": "Overtime can partially offset but at higher cost",
                "category": "production",
                "confidence": 0.7,
                "source": "default",
            },
        ],
        impact_category_map={
            "facility": "production",
            "sales_order": "order",
            "inventory_item": "inventory",
            "customer": "customer",
        },
        severity_map={
            "blocking": "critical",
            "critical": "critical",
            "warning": "warning",
            "info": "info",
        },
        recovery_hours_base=36.0,
        recovery_hours_per_hop=16.0,
        recovery_hours_per_severity={
            "critical": 72.0,
            "warning": 24.0,
            "info": 8.0,
        },
        financial_impact_base=30000.0,
        financial_impact_per_severity={
            "critical": 8.0,
            "warning": 3.0,
            "info": 0.5,
        },
        financial_impact_per_entity_type={
            "Facility": 4.0,
            "SalesOrder": 2.0,
            "Customer": 3.0,
        },
        service_level_impact_base=8.0,
        service_level_impact_per_severity={
            "critical": 20.0,
            "warning": 10.0,
            "info": 2.0,
        },
        service_level_impact_per_hop=4.0,
    ),
    ScenarioType.CUSTOM: ScenarioRule(
        name="custom",
        version="1.0.0",
        scenario_type=ScenarioType.CUSTOM,
        description="Generic custom scenario with default parameters.",
        parameters=[],
        default_assumptions=[
            {
                "description": "Custom scenario with user-defined parameters",
                "category": "parameter",
                "confidence": 0.9,
                "source": "user_defined",
            },
        ],
        impact_category_map={
            "Supplier": "supplier",
            "Facility": "production",
            "InventoryItem": "inventory",
            "Product": "inventory",
            "PurchaseOrder": "order",
            "SalesOrder": "order",
            "Customer": "customer",
            "Shipment": "logistics",
            "Route": "logistics",
            "Carrier": "logistics",
        },
        severity_map={
            "blocking": "critical",
            "critical": "critical",
            "warning": "warning",
            "info": "info",
        },
        recovery_hours_base=48.0,
        recovery_hours_per_hop=12.0,
        recovery_hours_per_severity={
            "critical": 72.0,
            "warning": 24.0,
            "info": 8.0,
        },
        financial_impact_base=10000.0,
        financial_impact_per_severity={
            "critical": 3.0,
            "warning": 1.0,
            "info": 0.2,
        },
        financial_impact_per_entity_type={},
        service_level_impact_base=5.0,
        service_level_impact_per_severity={
            "critical": 10.0,
            "warning": 5.0,
            "info": 1.0,
        },
        service_level_impact_per_hop=2.0,
    ),
}


def get_rule(scenario_type: ScenarioType) -> ScenarioRule:
    """Get the scenario rule for a scenario type."""
    return SCENARIO_RULES.get(scenario_type, SCENARIO_RULES[ScenarioType.CUSTOM])


def list_rules() -> list[ScenarioRule]:
    """List all scenario rules."""
    return list(SCENARIO_RULES.values())
