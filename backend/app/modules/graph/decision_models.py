"""Decision Memory — immutable contracts for recording human decisions.

Program H (Decision Memory) consumes RecommendationSnapshots and produces
DecisionRecords. These contracts define how Cortex records:
  - what was decided
  - why it was decided
  - what evidence supported it
  - what outcome followed
  - what lessons were learned

Design rules:
  - Every record is frozen (immutable)
  - Every record is serializable (to_dict)
  - Every record carries provenance (scenario_id, recommendation_id, graph_version)
  - Decisions are append-only — never overwritten
  - Decisions are workspace-scoped and auditable
  - Closed taxonomy of decision types
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

# ─────────────────────────────────────────────────────────────────────────────
# Decision Taxonomy (Closed Vocabulary)
# ─────────────────────────────────────────────────────────────────────────────


class DecisionType(StrEnum):
    """Closed taxonomy of decision types supported by Cortex.

    Each type has:
      - canonical ID (this enum value)
      - human-readable name
      - whether it is terminal
      - whether it is reversible
      - required metadata
      - allowed upstream sources
      - allowed workflow states
    """

    APPROVE_RECOMMENDATION = "approve_recommendation"
    APPROVE_WITH_MODIFICATION = "approve_with_modification"
    REJECT_RECOMMENDATION = "reject_recommendation"
    DEFER_DECISION = "defer_decision"
    REQUEST_MORE_EVIDENCE = "request_more_evidence"
    ESCALATE_FOR_REVIEW = "escalate_for_review"
    NO_ACTION_MONITOR = "no_action_monitor"

    @property
    def is_terminal(self) -> bool:
        """Whether this decision type ends the workflow."""
        _terminal = {
            DecisionType.APPROVE_RECOMMENDATION,
            DecisionType.APPROVE_WITH_MODIFICATION,
            DecisionType.REJECT_RECOMMENDATION,
            DecisionType.NO_ACTION_MONITOR,
        }
        return self in _terminal

    @property
    def is_reversible(self) -> bool:
        """Whether this decision can be reversed later."""
        _reversible = {
            DecisionType.APPROVE_RECOMMENDATION,
            DecisionType.APPROVE_WITH_MODIFICATION,
            DecisionType.DEFER_DECISION,
            DecisionType.NO_ACTION_MONITOR,
        }
        return self in _reversible


class DecisionStatus(StrEnum):
    """Status of a decision record."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    DEFERRED = "deferred"
    ESCALATED = "escalated"
    IMPLEMENTED = "implemented"
    CLOSED = "closed"


class OutcomeStatus(StrEnum):
    """Status of a decision outcome."""

    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"
    NO_IMPACT = "no_impact"
    UNINTENDED_CONSEQUENCES = "unintended_consequences"
    PENDING = "pending"


class LessonCategory(StrEnum):
    """Category of a lesson learned."""

    POLICY_ERROR = "policy_error"
    ASSUMPTION_ERROR = "assumption_error"
    DATA_QUALITY_ISSUE = "data_quality_issue"
    MODEL_BIAS = "model_bias"
    PROCESS_GAP = "process_gap"
    SUCCESS_PATTERN = "success_pattern"
    BEST_PRACTICE = "best_practice"


# ─────────────────────────────────────────────────────────────────────────────
# Decision Request
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DecisionRequest:
    """Request to create a decision record.

    This is the input payload when a human makes a decision.
    """

    workspace_id: str
    scenario_id: str
    recommendation_snapshot_id: str
    selected_recommendation_id: str | None
    decision_type: DecisionType
    reviewer_id: str
    rationale: str
    modification_notes: str | None = None
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "scenario_id": self.scenario_id,
            "recommendation_snapshot_id": self.recommendation_snapshot_id,
            "selected_recommendation_id": self.selected_recommendation_id,
            "decision_type": self.decision_type.value,
            "reviewer_id": self.reviewer_id,
            "rationale": self.rationale,
            "modification_notes": self.modification_notes,
            "tags": list(self.tags),
            "metadata": dict(self.metadata),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Decision Record (Core)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DecisionRecord:
    """A decision record — the core unit of Decision Memory.

    Append-only, immutable, auditable. Records what a human decided,
    why, and what upstream reasoning it was based on.
    """

    decision_id: str
    workspace_id: str
    scenario_id: str
    recommendation_snapshot_id: str
    selected_recommendation_id: str | None

    # Decision details
    decision_type: DecisionType
    decision_status: DecisionStatus
    reviewer_id: str
    rationale: str

    # Optional fields must come after required fields
    modification_notes: str | None = None

    # Provenance — upstream reasoning lineage
    source_propagation_id: str | None = None
    source_signal_ids: list[str] = field(default_factory=list)
    evidence_claim_ids: list[str] = field(default_factory=list)
    graph_version: int | None = None
    context_version: int | None = None
    feature_snapshot_version: int | None = None
    scenario_snapshot_version: int | None = None
    recommendation_snapshot_version: int | None = None

    # Metadata
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    # Timestamps
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "workspace_id": self.workspace_id,
            "scenario_id": self.scenario_id,
            "recommendation_snapshot_id": self.recommendation_snapshot_id,
            "selected_recommendation_id": self.selected_recommendation_id,
            "decision_type": self.decision_type.value,
            "decision_status": self.decision_status.value,
            "reviewer_id": self.reviewer_id,
            "rationale": self.rationale,
            "modification_notes": self.modification_notes,
            "source_propagation_id": self.source_propagation_id,
            "source_signal_ids": list(self.source_signal_ids),
            "evidence_claim_ids": list(self.evidence_claim_ids),
            "graph_version": self.graph_version,
            "context_version": self.context_version,
            "feature_snapshot_version": self.feature_snapshot_version,
            "scenario_snapshot_version": self.scenario_snapshot_version,
            "recommendation_snapshot_version": self.recommendation_snapshot_version,
            "tags": list(self.tags),
            "metadata": dict(self.metadata),
            "created_at": self.created_at.isoformat(),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Decision Outcome
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DecisionOutcome:
    """An outcome record appended to a decision.

    Records what happened after the decision was implemented.
    Append-only — multiple outcomes can be recorded over time.
    """

    outcome_id: str
    decision_id: str
    workspace_id: str

    # Outcome details
    outcome_status: OutcomeStatus
    outcome_summary: str
    outcome_recorded_by: str

    # Optional fields
    actual_impact_description: str | None = None
    actual_financial_impact: float | None = None
    actual_recovery_hours: float | None = None
    actual_service_level_impact_pct: float | None = None
    met_expectations: bool | None = None
    would_decide_again: bool | None = None

    outcome_recorded_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome_id": self.outcome_id,
            "decision_id": self.decision_id,
            "workspace_id": self.workspace_id,
            "outcome_status": self.outcome_status.value,
            "outcome_summary": self.outcome_summary,
            "actual_impact_description": self.actual_impact_description,
            "actual_financial_impact": self.actual_financial_impact,
            "actual_recovery_hours": self.actual_recovery_hours,
            "actual_service_level_impact_pct": self.actual_service_level_impact_pct,
            "met_expectations": self.met_expectations,
            "would_decide_again": self.would_decide_again,
            "outcome_recorded_by": self.outcome_recorded_by,
            "outcome_recorded_at": self.outcome_recorded_at.isoformat(),
            "metadata": dict(self.metadata),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Lesson Learned
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DecisionLesson:
    """A lesson learned from a decision and its outcome.

    Structured learning that can be exported for future training.
    Append-only — multiple lessons can be recorded per decision.
    """

    lesson_id: str
    decision_id: str
    outcome_id: str | None
    workspace_id: str

    # Lesson details
    category: LessonCategory
    title: str
    description: str

    # Structured learning fields
    what_happened: str
    what_expected: str
    what_learned: str
    recorded_by: str

    # Optional fields
    policy_or_assumption_wrong: str | None = None
    what_to_change_next_time: str | None = None
    should_export_for_training: bool = False

    recorded_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "lesson_id": self.lesson_id,
            "decision_id": self.decision_id,
            "outcome_id": self.outcome_id,
            "workspace_id": self.workspace_id,
            "category": self.category.value,
            "title": self.title,
            "description": self.description,
            "what_happened": self.what_happened,
            "what_expected": self.what_expected,
            "what_learned": self.what_learned,
            "policy_or_assumption_wrong": self.policy_or_assumption_wrong,
            "what_to_change_next_time": self.what_to_change_next_time,
            "should_export_for_training": self.should_export_for_training,
            "recorded_by": self.recorded_by,
            "recorded_at": self.recorded_at.isoformat(),
            "metadata": dict(self.metadata),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Decision Snapshot (for export/query)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DecisionSnapshot:
    """Complete decision snapshot with outcomes and lessons.

    This is the full record returned when querying decision history.
    """

    decision: DecisionRecord
    outcomes: list[DecisionOutcome] = field(default_factory=list)
    lessons: list[DecisionLesson] = field(default_factory=list)

    # Aggregated metadata
    outcome_count: int = 0
    lesson_count: int = 0
    last_outcome_at: datetime | None = None
    last_lesson_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.to_dict(),
            "outcomes": [o.to_dict() for o in self.outcomes],
            "lessons": [les.to_dict() for les in self.lessons],
            "outcome_count": self.outcome_count,
            "lesson_count": self.lesson_count,
            "last_outcome_at": self.last_outcome_at.isoformat() if self.last_outcome_at else None,
            "last_lesson_at": self.last_lesson_at.isoformat() if self.last_lesson_at else None,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Decision Export (for ML/training)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DecisionExport:
    """Exportable decision record for training/analysis.

    Strips sensitive fields while preserving lineage for ML export.
    """

    export_id: str
    decision_id: str
    workspace_id: str

    # Decision details (anonymized)
    decision_type: DecisionType
    decision_status: DecisionStatus
    rationale: str
    modification_notes: str | None = None

    # Upstream context (structural only)
    scenario_type: str | None = None
    recommendation_type: str | None = None
    graph_metrics: dict[str, float] = field(default_factory=dict)

    # Outcome summary
    outcome_status: OutcomeStatus | None = None
    outcome_summary: str | None = None

    # Lessons (exportable only)
    exportable_lessons: list[DecisionLesson] = field(default_factory=list)

    # Export metadata
    exported_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    export_version: str = "1.0.0"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "export_id": self.export_id,
            "decision_id": self.decision_id,
            "workspace_id": self.workspace_id,
            "decision_type": self.decision_type.value,
            "decision_status": self.decision_status.value,
            "rationale": self.rationale,
            "modification_notes": self.modification_notes,
            "scenario_type": self.scenario_type,
            "recommendation_type": self.recommendation_type,
            "graph_metrics": dict(self.graph_metrics),
            "outcome_status": self.outcome_status.value if self.outcome_status else None,
            "outcome_summary": self.outcome_summary,
            "exportable_lessons": [
                les.to_dict() for les in self.exportable_lessons if les.should_export_for_training
            ],
            "exported_at": self.exported_at.isoformat() if self.exported_at else None,
            "export_version": self.export_version,
            "metadata": dict(self.metadata),
        }
