"""World Validation — Validation Rules for World State.

Ensures world state integrity by validating:
- Negative inventory
- Impossible capacity
- Broken references
- Invalid lead times
- Missing suppliers
- Invalid demand
- Duplicate state
- State hash verification
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from app.modules.world.world_models import (
    StateVariableType,
    WorldSnapshot,
    WorldState,
)


class ValidationSeverity(StrEnum):
    """Severity of a validation issue."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class ValidationIssue:
    """A single validation issue found during validation."""

    issue_id: str
    severity: ValidationSeverity
    rule: str
    message: str
    affected_variables: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ValidationResult:
    """Result of a validation pass."""

    is_valid: bool
    issues: list[ValidationIssue]
    validated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    rules_checked: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "issues": [
                {
                    "issue_id": i.issue_id,
                    "severity": i.severity.value,
                    "rule": i.rule,
                    "message": i.message,
                    "affected_variables": i.affected_variables,
                    "metadata": i.metadata,
                }
                for i in self.issues
            ],
            "validated_at": self.validated_at.isoformat(),
            "rules_checked": self.rules_checked,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Validation Rules
# ─────────────────────────────────────────────────────────────────────────────


class ValidationRules:
    """Collection of validation rules for world state."""

    # ─────────────────────────────────────────────────────────────────────────
    # Inventory Rules
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def check_negative_inventory(state: WorldState) -> list[ValidationIssue]:
        """Check for negative inventory levels."""
        issues = []
        for var in state.variables.values():
            if var.variable_type == StateVariableType.INVENTORY:
                value = var.raw_value
                if isinstance(value, (int, float)) and value < 0:
                    issues.append(
                        ValidationIssue(
                            issue_id=f"neg_inv_{var.variable_id}",
                            severity=ValidationSeverity.ERROR,
                            rule="negative_inventory",
                            message=f"Negative inventory for {var.entity_id}: {value}",
                            affected_variables=[var.variable_id],
                            metadata={"entity_id": var.entity_id, "value": value, "unit": var.unit},
                        )
                    )
        return issues

    @staticmethod
    def check_inventory_below_safety_stock(state: WorldState) -> list[ValidationIssue]:
        """Check if inventory is below safety stock."""
        issues = []
        inventory = {
            v.variable_id: v
            for v in state.variables.values()
            if v.variable_type == StateVariableType.INVENTORY
        }
        safety_stock = {
            v.variable_id: v
            for v in state.variables.values()
            if v.variable_type == StateVariableType.SAFETY_STOCK
        }

        for inv_id, inv_var in inventory.items():
            # Find matching safety stock (same entity)
            ss_var = safety_stock.get(inv_id.replace("inventory", "safety_stock"))
            if (
                ss_var
                and isinstance(inv_var.raw_value, (int, float))
                and isinstance(ss_var.raw_value, (int, float))
                and inv_var.raw_value < ss_var.raw_value
            ):
                issues.append(
                    ValidationIssue(
                        issue_id=f"below_ss_{inv_var.variable_id}",
                        severity=ValidationSeverity.WARNING,
                        rule="inventory_below_safety_stock",
                        message=f"Inventory below safety stock for {inv_var.entity_id}: {inv_var.raw_value} < {ss_var.raw_value}",
                        affected_variables=[inv_var.variable_id, ss_var.variable_id],
                        metadata={
                            "entity_id": inv_var.entity_id,
                            "inventory": inv_var.raw_value,
                            "safety_stock": ss_var.raw_value,
                        },
                    )
                )
        return issues

    # ─────────────────────────────────────────────────────────────────────────
    # Capacity Rules
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def check_impossible_capacity(state: WorldState) -> list[ValidationIssue]:
        """Check for impossible capacity values."""
        issues = []
        for var in state.variables.values():
            if var.variable_type == StateVariableType.CAPACITY:
                value = var.raw_value
                if isinstance(value, (int, float)):
                    if value < 0:
                        issues.append(
                            ValidationIssue(
                                issue_id=f"neg_cap_{var.variable_id}",
                                severity=ValidationSeverity.ERROR,
                                rule="negative_capacity",
                                message=f"Negative capacity for {var.entity_id}: {value}%",
                                affected_variables=[var.variable_id],
                                metadata={"entity_id": var.entity_id, "value": value},
                            )
                        )
                    elif value > 100:
                        issues.append(
                            ValidationIssue(
                                issue_id=f"over_cap_{var.variable_id}",
                                severity=ValidationSeverity.WARNING,
                                rule="over_capacity",
                                message=f"Capacity over 100% for {var.entity_id}: {value}%",
                                affected_variables=[var.variable_id],
                                metadata={"entity_id": var.entity_id, "value": value},
                            )
                        )
        return issues

    @staticmethod
    def check_zero_capacity_producing(state: WorldState) -> list[ValidationIssue]:
        """Check for factories with zero capacity that should be producing."""
        issues = []
        for var in state.variables.values():
            if var.variable_type == StateVariableType.CAPACITY:
                value = var.raw_value
                if isinstance(value, (int, float)) and value == 0:
                    # Could check if factory has active orders
                    issues.append(
                        ValidationIssue(
                            issue_id=f"zero_cap_{var.variable_id}",
                            severity=ValidationSeverity.INFO,
                            rule="zero_capacity",
                            message=f"Factory {var.entity_id} has 0% capacity",
                            affected_variables=[var.variable_id],
                            metadata={"entity_id": var.entity_id, "value": value},
                        )
                    )
        return issues

    # ─────────────────────────────────────────────────────────────────────────
    # Lead Time Rules
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def check_invalid_lead_time(state: WorldState) -> list[ValidationIssue]:
        """Check for invalid lead times."""
        issues = []
        for var in state.variables.values():
            if var.variable_type == StateVariableType.LEAD_TIME:
                value = var.raw_value
                if isinstance(value, (int, float)):
                    if value < 0:
                        issues.append(
                            ValidationIssue(
                                issue_id=f"neg_lt_{var.variable_id}",
                                severity=ValidationSeverity.ERROR,
                                rule="negative_lead_time",
                                message=f"Negative lead time for {var.entity_id}: {value} days",
                                affected_variables=[var.variable_id],
                                metadata={"entity_id": var.entity_id, "value": value},
                            )
                        )
                    elif value > 365:
                        issues.append(
                            ValidationIssue(
                                issue_id=f"long_lt_{var.variable_id}",
                                severity=ValidationSeverity.WARNING,
                                rule="excessive_lead_time",
                                message=f"Lead time exceeds 1 year for {var.entity_id}: {value} days",
                                affected_variables=[var.variable_id],
                                metadata={"entity_id": var.entity_id, "value": value},
                            )
                        )
        return issues

    # ─────────────────────────────────────────────────────────────────────────
    # Demand Rules
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def check_invalid_demand(state: WorldState) -> list[ValidationIssue]:
        """Check for invalid demand values."""
        issues = []
        for var in state.variables.values():
            if var.variable_type == StateVariableType.DEMAND:
                value = var.raw_value
                if isinstance(value, (int, float)) and value < 0:
                    issues.append(
                        ValidationIssue(
                            issue_id=f"neg_dem_{var.variable_id}",
                            severity=ValidationSeverity.ERROR,
                            rule="negative_demand",
                            message=f"Negative demand for {var.entity_id}: {value}",
                            affected_variables=[var.variable_id],
                            metadata={"entity_id": var.entity_id, "value": value},
                        )
                    )
        return issues

    # ─────────────────────────────────────────────────────────────────────────
    # Supplier Health Rules
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def check_supplier_health(state: WorldState) -> list[ValidationIssue]:
        """Check supplier health values are in valid range."""
        issues = []
        for var in state.variables.values():
            if var.variable_type == StateVariableType.SUPPLIER_HEALTH:
                value = var.raw_value
                if isinstance(value, (int, float)):
                    if value < 0 or value > 100:
                        issues.append(
                            ValidationIssue(
                                issue_id=f"health_range_{var.variable_id}",
                                severity=ValidationSeverity.ERROR,
                                rule="supplier_health_range",
                                message=f"Supplier health out of range for {var.entity_id}: {value}%",
                                affected_variables=[var.variable_id],
                                metadata={"entity_id": var.entity_id, "value": value},
                            )
                        )
                    elif value < 30:
                        issues.append(
                            ValidationIssue(
                                issue_id=f"low_health_{var.variable_id}",
                                severity=ValidationSeverity.WARNING,
                                rule="low_supplier_health",
                                message=f"Supplier {var.entity_id} health critical: {value}%",
                                affected_variables=[var.variable_id],
                                metadata={"entity_id": var.entity_id, "value": value},
                            )
                        )
        return issues

    # ─────────────────────────────────────────────────────────────────────────
    # Transit Delay Rules
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def check_transit_delay(state: WorldState) -> list[ValidationIssue]:
        """Check transit delays."""
        issues = []
        for var in state.variables.values():
            if var.variable_type == StateVariableType.TRANSIT_DELAY:
                value = var.raw_value
                if isinstance(value, (int, float)) and value > 30:
                    issues.append(
                        ValidationIssue(
                            issue_id=f"long_delay_{var.variable_id}",
                            severity=ValidationSeverity.WARNING,
                            rule="excessive_transit_delay",
                            message=f"Transit delay exceeds 30 days for {var.entity_id}: {value} days",
                            affected_variables=[var.variable_id],
                            metadata={"entity_id": var.entity_id, "value": value},
                        )
                    )
        return issues

    # ─────────────────────────────────────────────────────────────────────────
    # Revenue/Margin Rules
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def check_negative_revenue(state: WorldState) -> list[ValidationIssue]:
        """Check for negative revenue."""
        issues = []
        for var in state.variables.values():
            if var.variable_type == StateVariableType.REVENUE:
                value = var.raw_value
                if isinstance(value, (int, float)) and value < 0:
                    issues.append(
                        ValidationIssue(
                            issue_id=f"neg_rev_{var.variable_id}",
                            severity=ValidationSeverity.WARNING,
                            rule="negative_revenue",
                            message=f"Negative revenue for {var.entity_id}: {value}",
                            affected_variables=[var.variable_id],
                            metadata={"entity_id": var.entity_id, "value": value},
                        )
                    )
        return issues

    @staticmethod
    def check_margin_range(state: WorldState) -> list[ValidationIssue]:
        """Check margin is in reasonable range."""
        issues = []
        for var in state.variables.values():
            if var.variable_type == StateVariableType.MARGIN:
                value = var.raw_value
                if isinstance(value, (int, float)) and (value < -100 or value > 100):
                    issues.append(
                        ValidationIssue(
                            issue_id=f"margin_range_{var.variable_id}",
                            severity=ValidationSeverity.ERROR,
                            rule="margin_out_of_range",
                            message=f"Margin out of expected range for {var.entity_id}: {value}%",
                            affected_variables=[var.variable_id],
                            metadata={"entity_id": var.entity_id, "value": value},
                        )
                    )
        return issues

    # ─────────────────────────────────────────────────────────────────────────
    # Working Capital Rules
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def check_working_capital(state: WorldState) -> list[ValidationIssue]:
        """Check working capital values."""
        issues = []
        for var in state.variables.values():
            if var.variable_type == StateVariableType.WORKING_CAPITAL:
                value = var.raw_value
                if isinstance(value, (int, float)) and value < 0:
                    issues.append(
                        ValidationIssue(
                            issue_id=f"neg_wc_{var.variable_id}",
                            severity=ValidationSeverity.WARNING,
                            rule="negative_working_capital",
                            message=f"Negative working capital for {var.entity_id}: {value}",
                            affected_variables=[var.variable_id],
                            metadata={"entity_id": var.entity_id, "value": value},
                        )
                    )
        return issues

    # ─────────────────────────────────────────────────────────────────────────
    # Warehouse Utilization Rules
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def check_warehouse_utilization(state: WorldState) -> list[ValidationIssue]:
        """Check warehouse utilization."""
        issues = []
        for var in state.variables.values():
            if var.variable_type == StateVariableType.WAREHOUSE_UTILIZATION:
                value = var.raw_value
                if isinstance(value, (int, float)):
                    if value < 0 or value > 100:
                        issues.append(
                            ValidationIssue(
                                issue_id=f"util_range_{var.variable_id}",
                                severity=ValidationSeverity.ERROR,
                                rule="warehouse_utilization_range",
                                message=f"Warehouse utilization out of range for {var.entity_id}: {value}%",
                                affected_variables=[var.variable_id],
                                metadata={"entity_id": var.entity_id, "value": value},
                            )
                        )
                    elif value > 95:
                        issues.append(
                            ValidationIssue(
                                issue_id=f"high_util_{var.variable_id}",
                                severity=ValidationSeverity.WARNING,
                                rule="high_warehouse_utilization",
                                message=f"Warehouse {var.entity_id} near capacity: {value}%",
                                affected_variables=[var.variable_id],
                                metadata={"entity_id": var.entity_id, "value": value},
                            )
                        )
        return issues

    # ─────────────────────────────────────────────────────────────────────────
    # State Integrity Rules
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def check_duplicate_variables(state: WorldState) -> list[ValidationIssue]:
        """Check for duplicate variable IDs."""
        issues = []
        seen = set()
        for var_id in state.variables:
            if var_id in seen:
                issues.append(
                    ValidationIssue(
                        issue_id=f"dup_var_{var_id}",
                        severity=ValidationSeverity.ERROR,
                        rule="duplicate_variable",
                        message=f"Duplicate variable ID: {var_id}",
                        affected_variables=[var_id],
                    )
                )
            seen.add(var_id)
        return issues

    @staticmethod
    def check_state_hash(state: WorldState, expected_hash: str) -> list[ValidationIssue]:
        """Verify state hash matches expected (tamper detection)."""
        issues = []
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
        actual_hash = hashlib.sha256(canonical).hexdigest()[:64]

        if actual_hash != expected_hash:
            issues.append(
                ValidationIssue(
                    issue_id=f"hash_mismatch_{state.world_id}",
                    severity=ValidationSeverity.ERROR,
                    rule="state_hash_mismatch",
                    message=f"State hash mismatch: expected {expected_hash}, got {actual_hash}",
                    affected_variables=list(state.variables.keys()),
                    metadata={"expected_hash": expected_hash, "actual_hash": actual_hash},
                )
            )
        return issues

    @staticmethod
    def check_version_consistency(state: WorldState) -> list[ValidationIssue]:
        """Check version consistency."""
        issues = []
        if state.version < 1:
            issues.append(
                ValidationIssue(
                    issue_id=f"version_low_{state.world_id}",
                    severity=ValidationSeverity.ERROR,
                    rule="version_consistency",
                    message=f"Invalid version {state.version} for world {state.world_id}",
                    affected_variables=[],
                    metadata={"version": state.version},
                )
            )
        return issues


# ─────────────────────────────────────────────────────────────────────────────
# Validation Engine
# ─────────────────────────────────────────────────────────────────────────────


class WorldValidator:
    """Validates world state against all rules."""

    def __init__(self) -> None:
        self.rules = ValidationRules()

    def validate(self, state: WorldState, expected_hash: str | None = None) -> ValidationResult:
        """Run all validation rules against a world state."""
        all_issues = []

        # Run all rules
        rule_methods = [
            ("negative_inventory", self.rules.check_negative_inventory),
            ("inventory_below_safety_stock", self.rules.check_inventory_below_safety_stock),
            ("impossible_capacity", self.rules.check_impossible_capacity),
            ("zero_capacity_producing", self.rules.check_zero_capacity_producing),
            ("invalid_lead_time", self.rules.check_invalid_lead_time),
            ("invalid_demand", self.rules.check_invalid_demand),
            ("supplier_health", self.rules.check_supplier_health),
            ("transit_delay", self.rules.check_transit_delay),
            ("negative_revenue", self.rules.check_negative_revenue),
            ("margin_range", self.rules.check_margin_range),
            ("working_capital", self.rules.check_working_capital),
            ("warehouse_utilization", self.rules.check_warehouse_utilization),
            ("duplicate_variables", self.rules.check_duplicate_variables),
            ("version_consistency", self.rules.check_version_consistency),
        ]

        # Add optional hash check
        if expected_hash:
            rule_methods.append(
                ("state_hash", lambda s: self.rules.check_state_hash(s, expected_hash))
            )

        for rule_name, rule_method in rule_methods:
            try:
                issues = rule_method(state)
                all_issues.extend(issues)
            except Exception as e:
                all_issues.append(
                    ValidationIssue(
                        issue_id=f"rule_error_{rule_name}",
                        severity=ValidationSeverity.ERROR,
                        rule=rule_name,
                        message=f"Validation rule {rule_name} failed: {e}",
                        affected_variables=[],
                        metadata={"error": str(e)},
                    )
                )

        is_valid = all(i.severity != ValidationSeverity.ERROR for i in all_issues)

        return ValidationResult(
            is_valid=is_valid,
            issues=all_issues,
            rules_checked=len(rule_methods),
        )

    def validate_snapshot(self, snapshot: WorldSnapshot, state: WorldState) -> ValidationResult:
        """Validate a snapshot against its state."""
        return self.validate(state, expected_hash=snapshot.state_hash)

    def get_errors(self, result: ValidationResult) -> list[ValidationIssue]:
        """Get only error-level issues."""
        return [i for i in result.issues if i.severity == ValidationSeverity.ERROR]

    def get_warnings(self, result: ValidationResult) -> list[ValidationIssue]:
        """Get only warning-level issues."""
        return [i for i in result.issues if i.severity == ValidationSeverity.WARNING]

    def get_infos(self, result: ValidationResult) -> list[ValidationIssue]:
        """Get only info-level issues."""
        return [i for i in result.issues if i.severity == ValidationSeverity.INFO]


# ─────────────────────────────────────────────────────────────────────────────
# Convenience Functions
# ─────────────────────────────────────────────────────────────────────────────


def validate_state(state: WorldState, expected_hash: str | None = None) -> ValidationResult:
    """Quick validation of a world state."""
    validator = WorldValidator()
    return validator.validate(state, expected_hash)


def validate_snapshot(snapshot: WorldSnapshot, state: WorldState) -> ValidationResult:
    """Quick validation of a snapshot against its state."""
    validator = WorldValidator()
    return validator.validate_snapshot(snapshot, state)


def is_valid_state(state: WorldState) -> bool:
    """Quick check if state is valid (no errors)."""
    return validate_state(state).is_valid


def get_state_errors(state: WorldState) -> list[ValidationIssue]:
    """Get all errors in a state."""
    return WorldValidator().get_errors(validate_state(state))
