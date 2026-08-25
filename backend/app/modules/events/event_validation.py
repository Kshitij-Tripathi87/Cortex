"""Event Validation — Structural Validation for the Event Kernel.

Program J (World State & Digital Twin) — invariants I1 (append-only),
I3 (deterministic projections), and I10 (forward-compatible metadata).

This module validates:
- Required keys present per event_type
- Numeric types match expected ranges (e.g., capacity in [0, 100])
- Event identity fields are non-empty (event_id, world_id, workspace_id, entity_id)
- Metadata uses only declared keys (forward-compat keys or event-hash infra)

Validation is non-blocking by design. Errors raise EventValidationError for
hard contract violations (missing required fields, wrong types). Warnings
are returned alongside for soft policy violations (out-of-range values that
may be intentional, e.g. capacity surge above 100%).

Usage:
    validate_event(event)               # raises on hard errors
    issues = check_event(event)         # returns list (hard + soft)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.modules.events.event_models import (
    METADATA_KEYS,
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
    WorldEvent,
    WorldEventType,
)


class ValidationSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class ValidationIssue:
    severity: ValidationSeverity
    rule: str
    message: str
    field: str | None = None


class EventValidationError(ValueError):
    """Raised when a hard validation rule fails."""

    def __init__(self, issues: list[ValidationIssue]) -> None:
        self.issues = issues
        super().__init__("; ".join(f"[{i.rule}] {i.message}" for i in issues))


# ─────────────────────────────────────────────────────────────────────────────
# Per-event-type payload schemas (required keys + numeric ranges)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FieldSpec:
    name: str
    type_: type | tuple[type, ...]
    required: bool = True
    min_value: float | None = None
    max_value: float | None = None


_PAYLOAD_SCHEMAS: dict[type[WorldEvent], tuple[FieldSpec, ...]] = {
    InventoryChanged: (
        FieldSpec("warehouse_id", str),
        FieldSpec("component_id", str),
        FieldSpec("quantity_change", int),
        FieldSpec("reason", str, required=False),
    ),
    SupplierDelayed: (
        FieldSpec("delay_days", int, min_value=0),
        FieldSpec("disruption_type", str, required=False),
    ),
    SupplierHealthChanged: (
        FieldSpec("health_score", (int, float), min_value=0.0, max_value=1.0),
        FieldSpec("previous_score", (int, float, type(None)), required=False),
    ),
    OrderPlaced: (
        FieldSpec("warehouse_id", str),
        FieldSpec("component_id", str),
        FieldSpec("quantity", int, min_value=1),
        FieldSpec("customer_id", (str, type(None)), required=False),
        FieldSpec("priority", str, required=False),
    ),
    OrderCancelled: (
        FieldSpec("warehouse_id", str),
        FieldSpec("component_id", str),
        FieldSpec("quantity", int, min_value=1),
        FieldSpec("order_id", str),
        FieldSpec("reason", str, required=False),
    ),
    CapacityChanged: (
        FieldSpec("capacity_pct", (int, float), min_value=0.0, max_value=100.0),
        FieldSpec("reason", str, required=False),
    ),
    FactoryShutdown: (
        FieldSpec("capacity_pct", (int, float), min_value=0.0, max_value=100.0),
        FieldSpec("estimated_recovery_days", (int, type(None)), required=False, min_value=0),
        FieldSpec("cause", str, required=False),
    ),
    RouteDisruption: (
        FieldSpec("delay_days", int, min_value=0),
        FieldSpec("disruption_type", str, required=False),
    ),
    ShipmentDelayed: (
        FieldSpec("delay_days", int, min_value=0),
        FieldSpec("shipment_id", str),
        FieldSpec("cause", str, required=False),
    ),
    DemandChanged: (
        FieldSpec("demand_change", int),
        FieldSpec("confidence", (int, float), min_value=0.0, max_value=1.0),
        FieldSpec("source", str, required=False),
    ),
    PriceChanged: (
        FieldSpec("new_price", (int, float), min_value=0.0),
        FieldSpec("previous_price", (int, float, type(None)), required=False, min_value=0.0),
        FieldSpec("currency", str, required=False),
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
# Validation
# ─────────────────────────────────────────────────────────────────────────────


def _identity_issues(event: WorldEvent) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not event.event_id:
        issues.append(ValidationIssue(ValidationSeverity.ERROR, "missing_event_id", "event_id is required", "event_id"))
    if not event.world_id:
        issues.append(ValidationIssue(ValidationSeverity.ERROR, "missing_world_id", "world_id is required", "world_id"))
    if not event.workspace_id:
        issues.append(ValidationIssue(ValidationSeverity.ERROR, "missing_workspace_id", "workspace_id is required", "workspace_id"))
    if not event.entity_id:
        issues.append(ValidationIssue(ValidationSeverity.ERROR, "missing_entity_id", "entity_id is required", "entity_id"))
    if not event.entity_type:
        issues.append(ValidationIssue(ValidationSeverity.ERROR, "missing_entity_type", "entity_type is required", "entity_type"))
    return issues


def _metadata_issues(event: WorldEvent) -> list[ValidationIssue]:
    """Metadata may contain hash-chain infra keys plus forward-compat keys.

    Hash-chain keys (event_hash, prev_event_hash, sequence) are written by
    the event store and are permitted. Forward-compat keys come from
    METADATA_KEYS. Any other keys are flagged as warnings (not errors)
    because Program J does not own the metadata schema for Programs K–N.
    """
    ALLOWED_INFRA = {"event_hash", "prev_event_hash", "sequence"}
    allowed = ALLOWED_INFRA | METADATA_KEYS
    issues: list[ValidationIssue] = []
    for key in event.metadata:
        if key not in allowed:
            issues.append(
                ValidationIssue(
                    ValidationSeverity.WARNING,
                    "unknown_metadata_key",
                    f"metadata key '{key}' is not declared in METADATA_KEYS",
                    "metadata",
                )
            )
    return issues


def _payload_issues(event: WorldEvent, payload: dict[str, Any]) -> list[ValidationIssue]:
    schema = _PAYLOAD_SCHEMAS.get(type(event))
    if schema is None:
        # No schema registered — accept any payload (forward-compat for new event types)
        return []

    issues: list[ValidationIssue] = []

    declared = {f.name for f in schema if f.required}
    optional = {f.name for f in schema if not f.required}
    seen = set(payload.keys())

    missing = declared - seen
    for name in sorted(missing):
        issues.append(
            ValidationIssue(
                ValidationSeverity.ERROR,
                "missing_payload_field",
                f"event_type={event.event_type.value} requires field '{name}'",
                name,
            )
        )

    for spec in schema:
        if spec.name not in payload:
            continue
        value = payload[spec.name]

        if not isinstance(value, spec.type_):
            issues.append(
                ValidationIssue(
                    ValidationSeverity.ERROR,
                    "wrong_payload_type",
                    f"field '{spec.name}' expected {spec.type_}, got {type(value).__name__}",
                    spec.name,
                )
            )
            continue

        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if spec.min_value is not None and value < spec.min_value:
                sev = ValidationSeverity.WARNING if spec.required else ValidationSeverity.WARNING
                issues.append(
                    ValidationIssue(
                        sev,
                        "field_below_minimum",
                        f"field '{spec.name}' value {value} below minimum {spec.min_value}",
                        spec.name,
                    )
                )
            if spec.max_value is not None and value > spec.max_value:
                issues.append(
                    ValidationIssue(
                        ValidationSeverity.WARNING,
                        "field_above_maximum",
                        f"field '{spec.name}' value {value} above maximum {spec.max_value}",
                        spec.name,
                    )
                )

    extras = seen - declared - optional
    for name in sorted(extras):
        issues.append(
            ValidationIssue(
                ValidationSeverity.WARNING,
                "unknown_payload_field",
                f"event_type={event.event_type.value} has unexpected field '{name}'",
                name,
            )
        )

    return issues


def check_event(event: WorldEvent, payload: dict[str, Any] | None = None) -> list[ValidationIssue]:
    """Return all validation issues for an event (hard + soft).

    If `payload` is omitted, the event's `to_payload()` is used (typed events
    supply their own payload). For replay from DB rows, the stored payload
    is passed in directly.
    """
    if payload is None:
        payload = event.to_payload()
    issues: list[ValidationIssue] = []
    issues.extend(_identity_issues(event))
    issues.extend(_metadata_issues(event))
    issues.extend(_payload_issues(event, payload))
    return issues


def validate_event(event: WorldEvent, payload: dict[str, Any] | None = None) -> None:
    """Raise EventValidationError if the event fails any hard (error) rule."""
    issues = [i for i in check_event(event, payload) if i.severity == ValidationSeverity.ERROR]
    if issues:
        raise EventValidationError(issues)


def has_errors(issues: list[ValidationIssue]) -> bool:
    return any(i.severity == ValidationSeverity.ERROR for i in issues)


def is_valid_event(event: WorldEvent, payload: dict[str, Any] | None = None) -> bool:
    return not has_errors(check_event(event, payload))


__all__ = [
    "CapacityChanged",
    "DemandChanged",
    "EventValidationError",
    "FactoryShutdown",
    "FieldSpec",
    "InventoryChanged",
    "METADATA_KEYS",
    "OrderCancelled",
    "OrderPlaced",
    "PriceChanged",
    "RouteDisruption",
    "ShipmentDelayed",
    "SupplierDelayed",
    "SupplierHealthChanged",
    "ValidationIssue",
    "ValidationSeverity",
    "WorldEvent",
    "WorldEventType",
    "check_event",
    "has_errors",
    "is_valid_event",
    "validate_event",
]
