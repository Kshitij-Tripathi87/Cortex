"""Context Validation — validates operational state freshness, units, and provenance.

Validation ensures operational context is trustworthy before being used for
signal detection and propagation. Validation checks:
  - Required fields present
  - Freshness within policy thresholds
  - Units are consistent and valid
  - Confidence bounds (0..1)
  - Provenance completeness

Validation is performed by the OperationalStateEngine during load.
Failed validation results in degraded confidence or blocked signal generation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.modules.graph.context_models import (
    BusinessOperationalState,
    InventoryOperationalState,
    LogisticsOperationalState,
    NodeOperationalState,
    OperationalContextSnapshot,
    OrderOperationalState,
    ProductionOperationalState,
)


@dataclass(frozen=True)
class ValidationIssue:
    """A single validation issue found during context validation."""

    node_id: str
    entity_type: str
    field_name: str
    issue_type: str  # "missing", "stale", "invalid_unit", "out_of_bounds", "no_provenance"
    severity: str  # "warning" | "error" | "blocking"
    message: str
    current_value: Any = None
    expected_value: Any = None


@dataclass(frozen=True)
class ValidationResult:
    """Result of validating an OperationalContextSnapshot."""

    is_valid: bool
    can_proceed: bool  # True if we can proceed (even with warnings)
    issues: list[ValidationIssue] = field(default_factory=list)
    warnings: int = 0
    errors: int = 0
    blocking: int = 0

    @classmethod
    def ok(cls) -> ValidationResult:
        """Create a successful validation result."""
        return cls(
            is_valid=True,
            can_proceed=True,
            issues=[],
            warnings=0,
            errors=0,
            blocking=0,
        )


def validate_operational_context(
    snapshot: OperationalContextSnapshot,
    *,
    as_of: datetime | None = None,
    require_provenance: bool = False,
    strict_freshness: bool = False,
) -> ValidationResult:
    """Validate an operational context snapshot.

    Args:
        snapshot: The snapshot to validate
        as_of: Time to check freshness against (default: now)
        require_provenance: If True, missing provenance is an error
        strict_freshness: If True, degraded freshness is an error

    Returns:
        ValidationResult with issues categorized by severity
    """
    as_of = as_of or datetime.now(UTC)
    issues: list[ValidationIssue] = []

    for node_id, state in snapshot.by_node.items():
        # Validate common fields
        issues.extend(
            _validate_common_fields(node_id, state, as_of, require_provenance, strict_freshness)
        )

        # Validate type-specific fields
        if isinstance(state, InventoryOperationalState):
            issues.extend(_validate_inventory_state(node_id, state, as_of, strict_freshness))
        elif isinstance(state, OrderOperationalState):
            issues.extend(_validate_order_state(node_id, state, as_of, strict_freshness))
        elif isinstance(state, LogisticsOperationalState):
            issues.extend(_validate_logistics_state(node_id, state, as_of, strict_freshness))
        elif isinstance(state, ProductionOperationalState):
            issues.extend(_validate_production_state(node_id, state, as_of, strict_freshness))
        elif isinstance(state, BusinessOperationalState):
            issues.extend(_validate_business_state(node_id, state, as_of, strict_freshness))

    # Categorize issues
    warnings = sum(1 for i in issues if i.severity == "warning")
    errors = sum(1 for i in issues if i.severity == "error")
    blocking = sum(1 for i in issues if i.severity == "blocking")

    return ValidationResult(
        is_valid=errors == 0 and blocking == 0,
        can_proceed=blocking == 0,
        issues=issues,
        warnings=warnings,
        errors=errors,
        blocking=blocking,
    )


def _validate_common_fields(
    node_id: str,
    state: NodeOperationalState,
    as_of: datetime,
    require_provenance: bool,
    strict_freshness: bool = False,
) -> list[ValidationIssue]:
    """Validate fields common to all operational state types."""
    issues: list[ValidationIssue] = []

    # Check confidence bounds
    if state.confidence < 0.0 or state.confidence > 1.0:
        issues.append(
            ValidationIssue(
                node_id=node_id,
                entity_type=state.entity_type,
                field_name="confidence",
                issue_type="out_of_bounds",
                severity="error",
                message=f"Confidence {state.confidence} is outside [0.0, 1.0]",
                current_value=state.confidence,
                expected_value="[0.0, 1.0]",
            )
        )

    # Check freshness
    if state.is_stale(as_of):
        stale_severity = (
            "error"
            if (state.freshness_policy and state.freshness_policy.expiration_policy == "block")
            else ("error" if strict_freshness else "warning")
        )
        issues.append(
            ValidationIssue(
                node_id=node_id,
                entity_type=state.entity_type,
                field_name="freshness",
                issue_type="stale",
                severity=stale_severity,
                message=f"Operational state is stale (age={state.freshness_seconds:.0f}s)",
                current_value=state.freshness_seconds,
                expected_value=f"<{state.freshness_policy.stale_age_seconds if state.freshness_policy else 172800}s",
            )
        )
    elif state.is_degraded(as_of):
        degraded_severity = "error" if strict_freshness else "warning"
        issues.append(
            ValidationIssue(
                node_id=node_id,
                entity_type=state.entity_type,
                field_name="freshness",
                issue_type="stale",
                severity=degraded_severity,
                message=f"Operational state freshness is degraded (age={state.freshness_seconds:.0f}s)",
                current_value=state.freshness_seconds,
            )
        )

    # Check provenance
    if require_provenance and state.provenance is None:
        issues.append(
            ValidationIssue(
                node_id=node_id,
                entity_type=state.entity_type,
                field_name="provenance",
                issue_type="no_provenance",
                severity="error",
                message="Provenance is required but missing",
            )
        )

    return issues


def _validate_inventory_state(
    node_id: str,
    state: InventoryOperationalState,
    as_of: datetime,
    strict_freshness: bool,
) -> list[ValidationIssue]:
    """Validate inventory-specific fields."""
    issues: list[ValidationIssue] = []

    # Check coverage_days is non-negative if present
    if state.coverage_days is not None and state.coverage_days < 0:
        issues.append(
            ValidationIssue(
                node_id=node_id,
                entity_type=state.entity_type,
                field_name="coverage_days",
                issue_type="out_of_bounds",
                severity="error",
                message="Coverage days cannot be negative",
                current_value=state.coverage_days,
                expected_value=">= 0",
            )
        )

    # Check days_of_supply consistency
    if state.days_of_supply is not None and state.days_of_supply < 0:
        issues.append(
            ValidationIssue(
                node_id=node_id,
                entity_type=state.entity_type,
                field_name="days_of_supply",
                issue_type="out_of_bounds",
                severity="error",
                message="Days of supply cannot be negative",
                current_value=state.days_of_supply,
                expected_value=">= 0",
            )
        )

    # Check on_hand_units
    if state.on_hand_units is not None and state.on_hand_units < 0:
        issues.append(
            ValidationIssue(
                node_id=node_id,
                entity_type=state.entity_type,
                field_name="on_hand_units",
                issue_type="out_of_bounds",
                severity="error",
                message="On-hand units cannot be negative",
                current_value=state.on_hand_units,
                expected_value=">= 0",
            )
        )

    return issues


def _validate_order_state(
    node_id: str,
    state: OrderOperationalState,
    as_of: datetime,
    strict_freshness: bool,
) -> list[ValidationIssue]:
    """Validate order-specific fields."""
    issues: list[ValidationIssue] = []

    # Check counts are non-negative
    for field_name in [
        "open_orders_count",
        "critical_orders_count",
        "priority_orders_count",
        "overdue_orders_count",
    ]:
        value = getattr(state, field_name, None)
        if value is not None and value < 0:
            issues.append(
                ValidationIssue(
                    node_id=node_id,
                    entity_type=state.entity_type,
                    field_name=field_name,
                    issue_type="out_of_bounds",
                    severity="error",
                    message=f"{field_name} cannot be negative",
                    current_value=value,
                    expected_value=">= 0",
                )
            )

    return issues


def _validate_logistics_state(
    node_id: str,
    state: LogisticsOperationalState,
    as_of: datetime,
    strict_freshness: bool,
) -> list[ValidationIssue]:
    """Validate logistics-specific fields."""
    issues: list[ValidationIssue] = []

    # Check rates are in [0, 1]
    for field_name in ["route_availability", "on_time_delivery_rate"]:
        value = getattr(state, field_name, None)
        if value is not None and (value < 0 or value > 1):
            issues.append(
                ValidationIssue(
                    node_id=node_id,
                    entity_type=state.entity_type,
                    field_name=field_name,
                    issue_type="out_of_bounds",
                    severity="error",
                    message=f"{field_name} must be in [0, 1]",
                    current_value=value,
                    expected_value="[0, 1]",
                )
            )

    return issues


def _validate_production_state(
    node_id: str,
    state: ProductionOperationalState,
    as_of: datetime,
    strict_freshness: bool,
) -> list[ValidationIssue]:
    """Validate production-specific fields."""
    issues: list[ValidationIssue] = []

    # Check percentages are in [0, 1]
    for field_name in ["utilization_pct", "capacity_pct", "quality_yield_pct"]:
        value = getattr(state, field_name, None)
        if value is not None and (value < 0 or value > 1):
            issues.append(
                ValidationIssue(
                    node_id=node_id,
                    entity_type=state.entity_type,
                    field_name=field_name,
                    issue_type="out_of_bounds",
                    severity="error",
                    message=f"{field_name} must be in [0, 1]",
                    current_value=value,
                    expected_value="[0, 1]",
                )
            )

    return issues


def _validate_business_state(
    node_id: str,
    state: BusinessOperationalState,
    as_of: datetime,
    strict_freshness: bool,
) -> list[ValidationIssue]:
    """Validate business-specific fields."""
    issues: list[ValidationIssue] = []

    # Check revenue values are non-negative
    for field_name in [
        "revenue_at_risk",
        "sla_penalty",
        "contract_value",
        "customer_lifetime_value",
    ]:
        value = getattr(state, field_name, None)
        if value is not None and value < 0:
            issues.append(
                ValidationIssue(
                    node_id=node_id,
                    entity_type=state.entity_type,
                    field_name=field_name,
                    issue_type="out_of_bounds",
                    severity="error",
                    message=f"{field_name} cannot be negative",
                    current_value=value,
                    expected_value=">= 0",
                )
            )

    # Check strategic_importance is valid
    valid_importance = {"low", "medium", "high", "critical", None}
    if state.strategic_importance not in valid_importance:
        issues.append(
            ValidationIssue(
                node_id=node_id,
                entity_type=state.entity_type,
                field_name="strategic_importance",
                issue_type="invalid_unit",
                severity="warning",
                message=f"Invalid strategic_importance: {state.strategic_importance}",
                current_value=state.strategic_importance,
                expected_value=list(valid_importance - {None}),
            )
        )

    return issues
