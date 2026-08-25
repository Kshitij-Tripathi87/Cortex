"""Signal dataclasses — frozen DTOs for the Signal Engine.

Signals are derived operational facts computed from graph features. They are
NOT predictions — they are explanations of current state with severity and
confidence scores.

Every signal includes:
  - The feature evidence that triggered it
  - Severity (info, warning, critical, blocking)
  - Confidence (0..1) based on feature quality and evidence completeness
  - Affected entities (which nodes are involved)
  - Propagation scope (how far the impact extends)
  - An explanation template (human-readable)

Program E (Propagation Engine) consumes SignalInstance objects to compute
cascading impacts. Program D produces them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class SignalSeverity(StrEnum):
    """Severity levels for signals. Determines escalation and UI presentation."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    BLOCKING = "blocking"


class SignalCategory(StrEnum):
    """Signal categories for grouping and filtering."""

    SUPPLIER_RISK = "supplier_risk"
    BOTTLENECK = "bottleneck"
    ISOLATION = "isolation"
    CONCENTRATION = "concentration"
    INSTABILITY = "instability"
    DEPENDENCY = "dependency"
    CUSTOMER_EXPOSURE = "customer_exposure"


@dataclass(frozen=True)
class SignalDefinition:
    """Formal definition of a signal type in the Signal Registry.

    Every signal detector is registered with a SignalDefinition that specifies:
      - Required input features
      - Thresholds for severity levels
      - Confidence calculation logic
      - Explanation template
      - Propagation scope rules

    This makes signals versioned, testable, and auditable.
    """

    name: str
    version: str
    category: SignalCategory
    description: str
    required_features: list[str]  # feature names needed to compute this signal
    severity_thresholds: dict[str, float]  # severity → threshold value
    confidence_formula: str  # description or reference to formula
    explanation_template: str  # template with {placeholders} for entity names
    propagation_scope: str  # "upstream", "downstream", "both", "none"
    algorithm_reference: str  # URL or module path


@dataclass(frozen=True)
class SignalInstance:
    """A concrete signal detected in a specific workspace at a specific time.

    SignalInstances are immutable once created. They carry the full evidence
    chain from features → severity → confidence → explanation.
    """

    signal_id: str
    signal_name: str  # matches SignalDefinition.name
    signal_version: str
    workspace_id: str
    snapshot_version: int | None
    snapshot_hash: str | None
    severity: SignalSeverity
    confidence: float  # 0..1
    category: SignalCategory
    affected_node_ids: list[str]
    affected_entity_types: list[str]
    affected_entity_ids: list[str]
    propagation_scope: str
    feature_evidence: dict[str, float]  # feature_name → value that triggered signal
    explanation: str  # human-readable, filled from template
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly representation for API responses and cache."""
        return {
            "signal_id": self.signal_id,
            "signal_name": self.signal_name,
            "signal_version": self.signal_version,
            "workspace_id": self.workspace_id,
            "snapshot_version": self.snapshot_version,
            "snapshot_hash": self.snapshot_hash,
            "severity": self.severity.value,
            "confidence": round(self.confidence, 4),
            "category": self.category.value,
            "affected_node_ids": list(self.affected_node_ids),
            "affected_entity_types": list(self.affected_entity_types),
            "affected_entity_ids": list(self.affected_entity_ids),
            "propagation_scope": self.propagation_scope,
            "feature_evidence": dict(self.feature_evidence),
            "explanation": self.explanation,
            "created_at": self.created_at.isoformat(),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class SignalSnapshot:
    """Complete set of signals detected for a workspace at a snapshot version.

    Analogous to FeatureSnapshot — carries all signals plus metadata.
    """

    workspace_id: str
    snapshot_version: int | None
    snapshot_hash: str | None
    signals: list[SignalInstance] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "snapshot_version": self.snapshot_version,
            "snapshot_hash": self.snapshot_hash,
            "signals": [s.to_dict() for s in self.signals],
            "metadata": dict(self.metadata),
        }


# Helper for building explanations
def format_explanation(template: str, **kwargs: Any) -> str:
    """Fill an explanation template with entity names and feature values."""
    return template.format(**kwargs)
