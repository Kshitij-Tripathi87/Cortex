"""Scenario Models — immutable contracts for the scenario pipeline.

Program F (Scenario Engine) consumes PropagationSnapshots and produces
ScenarioSnapshots. These contracts define the interface between
Propagation (Program E), Scenarios (Program F), Recommendations (Program G),
and Decisions (Program H).

Design rules:
  - Every record is frozen (immutable)
  - Every record is serializable (to_dict)
  - Every record carries provenance (graph_version, context_version, propagation_version)
  - Scenarios are deterministic: same inputs → same outputs
  - No recommendations, no decisions, no ML — pure what-if simulation
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────


class ScenarioType(StrEnum):
    """Types of what-if scenarios supported."""

    SUPPLIER_FAILURE = "supplier_failure"
    WAREHOUSE_OUTAGE = "warehouse_outage"
    ROUTE_CLOSURE = "route_closure"
    SHIPMENT_DELAY = "shipment_delay"
    DEMAND_SPIKE = "demand_spike"
    DEMAND_DROP = "demand_drop"
    INVENTORY_SHORTAGE = "inventory_shortage"
    CAPACITY_CONSTRAINT = "capacity_constraint"
    CUSTOM = "custom"


class ScenarioStatus(StrEnum):
    """Execution status of a scenario."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ComparisonOperator(StrEnum):
    """Operators for scenario comparison."""

    GREATER_THAN = "gt"
    LESS_THAN = "lt"
    EQUAL = "eq"
    NOT_EQUAL = "neq"


# ─────────────────────────────────────────────────────────────────────────────
# Scenario Definition
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ScenarioParameter:
    """A single parameter that defines a scenario."""

    name: str
    value: Any
    unit: str | None = None
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "description": self.description,
        }


@dataclass(frozen=True)
class ScenarioDefinition:
    """Complete definition of a what-if scenario.

    Immutable specification — does not contain results.
    """

    scenario_id: str
    workspace_id: str
    scenario_type: ScenarioType
    name: str
    description: str
    parameters: list[ScenarioParameter] = field(default_factory=list)

    # Source signal/propagation this scenario is based on
    source_propagation_id: str | None = None
    source_signal_id: str | None = None

    # Execution constraints
    max_depth: int | None = None
    min_confidence: float | None = None
    impact_type_filter: str | None = None

    # Metadata
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str | None = None
    version: str = "1.0.0"
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "workspace_id": self.workspace_id,
            "scenario_type": self.scenario_type.value,
            "name": self.name,
            "description": self.description,
            "parameters": [p.to_dict() for p in self.parameters],
            "source_propagation_id": self.source_propagation_id,
            "source_signal_id": self.source_signal_id,
            "max_depth": self.max_depth,
            "min_confidence": self.min_confidence,
            "impact_type_filter": self.impact_type_filter,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "version": self.version,
            "tags": list(self.tags),
            "metadata": dict(self.metadata),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Scenario Assumptions
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ScenarioAssumption:
    """An explicit assumption made for a scenario execution.

    All assumptions are recorded for auditability and replay.
    """

    assumption_id: str
    scenario_id: str
    description: str
    category: str  # "graph", "context", "propagation", "business"
    confidence: float  # 0..1 how certain this assumption is
    source: str  # "user_defined", "derived_from_context", "default"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_id": self.assumption_id,
            "scenario_id": self.scenario_id,
            "description": self.description,
            "category": self.category,
            "confidence": round(self.confidence, 4),
            "source": self.source,
            "metadata": dict(self.metadata),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Impact Records (from Propagation)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ScenarioImpactRecord:
    """A single impacted entity in a scenario execution.

    Derived from PropagationStep but enriched with scenario-specific
    interpretation (e.g., estimated recovery time, financial impact).
    """

    scenario_id: str
    affected_node_id: str
    affected_entity_id: str
    affected_entity_type: str
    hop_number: int
    impact_category: str  # "inventory", "logistics", "production", "order", "customer", "business"
    severity: str  # "info", "warning", "critical", "blocking"
    confidence: float

    # Scenario-specific estimates
    estimated_recovery_hours: float | None = None
    estimated_financial_impact: float | None = None
    estimated_service_level_impact_pct: float | None = None

    # Provenance
    source_propagation_step_id: str | None = None
    graph_version: int | None = None
    context_version: int | None = None
    propagation_version: int | None = None

    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "affected_node_id": self.affected_node_id,
            "affected_entity_id": self.affected_entity_id,
            "affected_entity_type": self.affected_entity_type,
            "hop_number": self.hop_number,
            "impact_category": self.impact_category,
            "severity": self.severity,
            "confidence": round(self.confidence, 4),
            "estimated_recovery_hours": self.estimated_recovery_hours,
            "estimated_financial_impact": self.estimated_financial_impact,
            "estimated_service_level_impact_pct": self.estimated_service_level_impact_pct,
            "source_propagation_step_id": self.source_propagation_step_id,
            "graph_version": self.graph_version,
            "context_version": self.context_version,
            "propagation_version": self.propagation_version,
            "created_at": self.created_at.isoformat(),
            "metadata": dict(self.metadata),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Scenario Execution Result
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ScenarioSummary:
    """Aggregate summary of a scenario execution."""

    total_impacted_entities: int
    by_impact_category: dict[str, int] = field(default_factory=dict)
    by_severity: dict[str, int] = field(default_factory=dict)
    by_entity_type: dict[str, int] = field(default_factory=dict)
    max_hop: int = 0
    avg_confidence: float = 0.0
    min_confidence: float = 0.0
    total_estimated_recovery_hours: float = 0.0
    total_estimated_financial_impact: float = 0.0
    max_service_level_impact_pct: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_impacted_entities": self.total_impacted_entities,
            "by_impact_category": dict(self.by_impact_category),
            "by_severity": dict(self.by_severity),
            "by_entity_type": dict(self.by_entity_type),
            "max_hop": self.max_hop,
            "avg_confidence": round(self.avg_confidence, 4),
            "min_confidence": round(self.min_confidence, 4),
            "total_estimated_recovery_hours": round(self.total_estimated_recovery_hours, 2),
            "total_estimated_financial_impact": round(self.total_estimated_financial_impact, 2),
            "max_service_level_impact_pct": round(self.max_service_level_impact_pct, 2),
        }


@dataclass(frozen=True)
class ScenarioSnapshot:
    """Complete scenario execution result — consumed by Program G (Recommendations).

    Immutable, deterministic, serializable, auditable.
    """

    scenario_id: str
    workspace_id: str
    scenario_definition: ScenarioDefinition

    # Status
    status: ScenarioStatus = ScenarioStatus.PENDING

    # Assumptions made
    assumptions: list[ScenarioAssumption] = field(default_factory=list)

    # Results
    impacts: list[ScenarioImpactRecord] = field(default_factory=list)
    summary: ScenarioSummary = field(
        default_factory=lambda: ScenarioSummary(total_impacted_entities=0)
    )

    # Provenance (from source propagation)
    source_propagation_id: str | None = None
    source_signal_id: str | None = None
    graph_version: int | None = None
    feature_snapshot_version: int | None = None
    context_snapshot_version: int | None = None
    propagation_snapshot_version: int | None = None

    # Execution metadata
    execution_time_ms: float = 0.0
    rules_applied: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    # Versioning
    scenario_snapshot_version: int = 1  # Set by service layer
    scenario_snapshot_hash: str | None = None

    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "workspace_id": self.workspace_id,
            "scenario_definition": self.scenario_definition.to_dict(),
            "status": self.status.value,
            "assumptions": [a.to_dict() for a in self.assumptions],
            "impacts": [i.to_dict() for i in self.impacts],
            "summary": self.summary.to_dict(),
            "source_propagation_id": self.source_propagation_id,
            "source_signal_id": self.source_signal_id,
            "graph_version": self.graph_version,
            "feature_snapshot_version": self.feature_snapshot_version,
            "context_snapshot_version": self.context_snapshot_version,
            "propagation_snapshot_version": self.propagation_snapshot_version,
            "execution_time_ms": round(self.execution_time_ms, 2),
            "rules_applied": list(self.rules_applied),
            "warnings": list(self.warnings),
            "error": self.error,
            "scenario_snapshot_version": self.scenario_snapshot_version,
            "scenario_snapshot_hash": self.scenario_snapshot_hash,
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "metadata": dict(self.metadata),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Scenario Comparison
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ScenarioComparison:
    """Comparison between two or more scenarios."""

    comparison_id: str
    scenario_ids: list[str]
    workspace_id: str
    metric: str  # e.g., "total_financial_impact", "recovery_hours"
    operator: ComparisonOperator
    threshold: float | None = None
    results: dict[str, Any] = field(default_factory=dict)
    recommendation: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "comparison_id": self.comparison_id,
            "scenario_ids": list(self.scenario_ids),
            "workspace_id": self.workspace_id,
            "metric": self.metric,
            "operator": self.operator.value,
            "threshold": self.threshold,
            "results": dict(self.results),
            "recommendation": self.recommendation,
            "created_at": self.created_at.isoformat(),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Request/Response
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ScenarioRequest:
    """Request to execute a scenario."""

    workspace_id: str
    scenario_definition: ScenarioDefinition
    source_propagation_id: str | None = None
    source_signal_id: str | None = None
    dry_run: bool = False
    snapshot_version: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "scenario_definition": self.scenario_definition.to_dict(),
            "source_propagation_id": self.source_propagation_id,
            "source_signal_id": self.source_signal_id,
            "dry_run": self.dry_run,
            "snapshot_version": self.snapshot_version,
        }


@dataclass(frozen=True)
class ScenarioResult:
    """Wrapper for scenario execution result."""

    snapshot: ScenarioSnapshot
    success: bool
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot": self.snapshot.to_dict(),
            "success": self.success,
            "warnings": list(self.warnings),
        }
