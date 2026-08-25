"""Constraints — Pre-defined Knowledge Constraints.

Program J (World State & Digital Twin) constraints module:

Provides factory functions for common constraints:
- Inventory floor (must maintain minimum stock)
- Lead time ceiling (must not exceed max days)
- Capacity bounds (factory utilization 0-100%)
- Supplier health (minimum health score)
- Compliance constraints (data residency, etc.)
"""

from __future__ import annotations

from app.common.ids import uuid7
from app.modules.knowledge.knowledge_models import (
    KnowledgeConstraint,
    RuleSeverity,
)


def inventory_floor_constraint(
    workspace_id: str,
    warehouse_id: str,
    component_id: str,
    minimum_units: int,
    severity: RuleSeverity = RuleSeverity.HIGH,
) -> KnowledgeConstraint:
    """Constraint: inventory must be >= minimum_units."""
    var_id = f"inventory.warehouse.{warehouse_id}.{component_id}"
    return KnowledgeConstraint(
        constraint_id=str(uuid7()),
        workspace_id=workspace_id,
        name=f"Inventory Floor: {warehouse_id}/{component_id}",
        description=f"Maintain minimum {minimum_units} units at {warehouse_id} for {component_id}",
        variable_id=var_id,
        operator="ge",
        min_value=minimum_units,
        max_value=None,
        severity=severity,
        violation_message=f"Inventory at {warehouse_id} for {component_id} has fallen below {minimum_units} units",
    )


def lead_time_ceiling_constraint(
    workspace_id: str,
    supplier_id: str,
    max_days: int,
    severity: RuleSeverity = RuleSeverity.MEDIUM,
) -> KnowledgeConstraint:
    """Constraint: supplier lead time must not exceed max_days."""
    var_id = f"lead_time.supplier.{supplier_id}"
    return KnowledgeConstraint(
        constraint_id=str(uuid7()),
        workspace_id=workspace_id,
        name=f"Lead Time Ceiling: {supplier_id}",
        description=f"Supplier {supplier_id} lead time must not exceed {max_days} days",
        variable_id=var_id,
        operator="le",
        min_value=None,
        max_value=max_days,
        severity=severity,
        violation_message=f"Lead time from supplier {supplier_id} has exceeded {max_days} days",
    )


def capacity_range_constraint(
    workspace_id: str,
    factory_id: str,
    min_pct: float,
    max_pct: float,
    severity: RuleSeverity = RuleSeverity.MEDIUM,
) -> KnowledgeConstraint:
    """Constraint: factory capacity utilization must be in [min_pct, max_pct]."""
    var_id = f"capacity.factory.{factory_id}"
    return KnowledgeConstraint(
        constraint_id=str(uuid7()),
        workspace_id=workspace_id,
        name=f"Capacity Range: {factory_id}",
        description=f"Factory {factory_id} capacity must be in [{min_pct}%, {max_pct}%]",
        variable_id=var_id,
        operator="between",
        min_value=min_pct,
        max_value=max_pct,
        severity=severity,
        violation_message=f"Factory {factory_id} capacity is outside acceptable range",
    )


def supplier_health_floor_constraint(
    workspace_id: str,
    supplier_id: str,
    min_health: float,
    severity: RuleSeverity = RuleSeverity.HIGH,
) -> KnowledgeConstraint:
    """Constraint: supplier health score must be >= min_health."""
    var_id = f"supplier_health.supplier.{supplier_id}"
    return KnowledgeConstraint(
        constraint_id=str(uuid7()),
        workspace_id=workspace_id,
        name=f"Supplier Health Floor: {supplier_id}",
        description=f"Supplier {supplier_id} health must be >= {min_health}",
        variable_id=var_id,
        operator="ge",
        min_value=min_health,
        max_value=None,
        severity=severity,
        violation_message=f"Supplier {supplier_id} health has dropped below {min_health}",
    )


def data_residency_constraint(
    workspace_id: str,
    region: str,
    severity: RuleSeverity = RuleSeverity.CRITICAL,
) -> KnowledgeConstraint:
    """Constraint: data must remain in specified region (compliance)."""
    return KnowledgeConstraint(
        constraint_id=str(uuid7()),
        workspace_id=workspace_id,
        name=f"Data Residency: {region}",
        description=f"All data must remain in {region} region",
        variable_id="compliance.data_region",
        operator="eq",
        min_value=region,
        max_value=None,
        severity=severity,
        violation_message=f"Data residency violation: data is not in {region}",
    )
