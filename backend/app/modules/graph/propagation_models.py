"""Propagation Models — immutable contracts for the propagation pipeline.

Program E (Propagation Engine) consumes signals + enriched state + graph
and outputs a deterministic impact tree. These contracts are the bridge
between Signals (Program D) and Scenarios (Program F).

Design rules:
  - Every record is frozen (immutable)
  - Every record is serializable (to_dict)
  - Every record carries provenance (graph_version, context_version, signal refs)
  - Propagation is deterministic: same inputs → same outputs
  - Confidence and attenuation are explicit, never hidden
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────


class ImpactType(StrEnum):
    """What kind of operational impact a propagation step represents."""

    INVENTORY = "inventory"
    LOGISTICS = "logistics"
    PRODUCTION = "production"
    ORDER = "order"
    CUSTOMER = "customer"
    SUPPLIER = "supplier"
    FACILITY = "facility"
    BUSINESS = "business"
    UNKNOWN = "unknown"


class PropagationDirection(StrEnum):
    """Direction of graph traversal for a propagation rule."""

    DOWNSTREAM = "downstream"  # follow out-edges (e.g., supplier → plant)
    UPSTREAM = "upstream"  # follow in-edges (e.g., customer ← order)
    BOTH = "both"


class Severity(StrEnum):
    """Impact severity at a propagation step."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    BLOCKING = "blocking"


# ─────────────────────────────────────────────────────────────────────────────
# Hop / Step contracts
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PropagationStep:
    """A single hop in the propagation tree.

    Each step records:
      - which node is affected
      - the edge traversed to get here
      - the hop distance from source
      - attenuation applied (0..1, multiplicative)
      - confidence at this step (0..1)
      - impact type and reason
      - provenance for audit
    """

    propagation_id: str  # groups all steps in one propagation run
    source_signal_id: str  # signal that triggered this propagation
    source_node_id: str
    source_node_type: str

    affected_node_id: str
    affected_node_type: str
    affected_entity_id: str
    hop_number: int  # 0 = source, 1 = first hop, etc.
    relationship_type: str  # edge type traversed to reach this node
    parent_node_id: str | None  # None for source; otherwise the node we came from

    # Impact scoring (deterministic)
    attenuation: float  # 0..1 multiplicative reduction at this hop
    confidence: float  # 0..1 — confidence attenuates per hop
    impact_type: ImpactType
    impact_severity: Severity
    impact_reason: str  # human-readable explanation

    # Provenance
    graph_version: int | None
    feature_snapshot_version: int | None
    context_snapshot_version: int | None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "propagation_id": self.propagation_id,
            "source_signal_id": self.source_signal_id,
            "source_node_id": self.source_node_id,
            "source_node_type": self.source_node_type,
            "affected_node_id": self.affected_node_id,
            "affected_node_type": self.affected_node_type,
            "affected_entity_id": self.affected_entity_id,
            "hop_number": self.hop_number,
            "relationship_type": self.relationship_type,
            "parent_node_id": self.parent_node_id,
            "attenuation": round(self.attenuation, 4),
            "confidence": round(self.confidence, 4),
            "impact_type": self.impact_type.value,
            "impact_severity": self.impact_severity.value,
            "impact_reason": self.impact_reason,
            "graph_version": self.graph_version,
            "feature_snapshot_version": self.feature_snapshot_version,
            "context_snapshot_version": self.context_snapshot_version,
            "created_at": self.created_at.isoformat(),
            "metadata": dict(self.metadata),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Tree & Summary contracts
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AffectedEntity:
    """An entity impacted by propagation, deduplicated by node_id."""

    node_id: str
    entity_id: str
    entity_type: str
    hop_number: int
    impact_type: ImpactType
    impact_severity: Severity
    confidence: float
    impact_reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "hop_number": self.hop_number,
            "impact_type": self.impact_type.value,
            "impact_severity": self.impact_severity.value,
            "confidence": round(self.confidence, 4),
            "impact_reason": self.impact_reason,
        }


@dataclass(frozen=True)
class ImpactSummary:
    """Aggregate impact counts by category.

    Deterministic aggregation of all propagation steps.
    """

    total_affected: int
    by_impact_type: dict[str, int] = field(default_factory=dict)
    by_severity: dict[str, int] = field(default_factory=dict)
    by_entity_type: dict[str, int] = field(default_factory=dict)
    max_hop: int = 0
    avg_confidence: float = 0.0
    min_confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_affected": self.total_affected,
            "by_impact_type": dict(self.by_impact_type),
            "by_severity": dict(self.by_severity),
            "by_entity_type": dict(self.by_entity_type),
            "max_hop": self.max_hop,
            "avg_confidence": round(self.avg_confidence, 4),
            "min_confidence": round(self.min_confidence, 4),
        }


@dataclass(frozen=True)
class PropagationTree:
    """The tree of propagation steps from a source signal.

    Ordered by hop_number then affected_node_id for determinism.
    """

    propagation_id: str
    source_signal_id: str
    source_node_id: str
    source_node_type: str
    steps: list[PropagationStep] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "propagation_id": self.propagation_id,
            "source_signal_id": self.source_signal_id,
            "source_node_id": self.source_node_id,
            "source_node_type": self.source_node_type,
            "steps": [s.to_dict() for s in self.steps],
        }


@dataclass(frozen=True)
class PropagationSnapshot:
    """Complete propagation result for a single signal — consumed by Program F.

    Immutable, deterministic, serializable, auditable.
    """

    propagation_id: str
    workspace_id: str
    source_signal_id: str
    source_signal_name: str
    source_node_id: str
    source_node_type: str

    # Source metadata
    source_severity: Severity
    source_confidence: float

    # Snapshots referenced (provenance)
    graph_version: int | None
    feature_snapshot_version: int | None
    context_snapshot_version: int | None
    signal_snapshot_version: int | None

    # Result
    tree: PropagationTree
    affected_entities: list[AffectedEntity]
    summary: ImpactSummary

    # Impact category lists (convenience accessors)
    affected_facilities: list[str] = field(default_factory=list)
    affected_inventory: list[str] = field(default_factory=list)
    affected_orders: list[str] = field(default_factory=list)
    affected_customers: list[str] = field(default_factory=list)

    # Execution metadata
    execution_time_ms: float = 0.0
    max_depth_reached: int = 0
    rules_applied: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "propagation_id": self.propagation_id,
            "workspace_id": self.workspace_id,
            "source_signal_id": self.source_signal_id,
            "source_signal_name": self.source_signal_name,
            "source_node_id": self.source_node_id,
            "source_node_type": self.source_node_type,
            "source_severity": self.source_severity.value,
            "source_confidence": round(self.source_confidence, 4),
            "graph_version": self.graph_version,
            "feature_snapshot_version": self.feature_snapshot_version,
            "context_snapshot_version": self.context_snapshot_version,
            "signal_snapshot_version": self.signal_snapshot_version,
            "tree": self.tree.to_dict(),
            "affected_entities": [e.to_dict() for e in self.affected_entities],
            "summary": self.summary.to_dict(),
            "affected_facilities": list(self.affected_facilities),
            "affected_inventory": list(self.affected_inventory),
            "affected_orders": list(self.affected_orders),
            "affected_customers": list(self.affected_customers),
            "execution_time_ms": round(self.execution_time_ms, 2),
            "max_depth_reached": self.max_depth_reached,
            "rules_applied": list(self.rules_applied),
            "created_at": self.created_at.isoformat(),
            "metadata": dict(self.metadata),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Input contract
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PropagationRequest:
    """Input to the PropagationEngine.

    Identifies which signal to propagate from and optional constraints.
    """

    workspace_id: str
    source_signal_id: str
    source_node_id: str
    max_depth: int = 5
    min_confidence: float = 0.1
    impact_type_filter: ImpactType | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PropagationResult:
    """Wrapper for propagation execution — includes timing and status."""

    snapshot: PropagationSnapshot
    success: bool
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot": self.snapshot.to_dict(),
            "success": self.success,
            "warnings": list(self.warnings),
        }
