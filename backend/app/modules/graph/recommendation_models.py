"""Recommendation Models — immutable contracts for the recommendation engine.

Program G (Recommendation Engine) consumes ScenarioSnapshots and produces
RecommendationSnapshots. These contracts define the interface between
Scenarios (Program F), Recommendations (Program G), and Decisions (Program H).

Design rules:
  - Every record is frozen (immutable)
  - Every record is serializable (to_dict)
  - Every record carries provenance (scenario_id, propagation_id, graph_version)
  - Recommendations are deterministic: same inputs → same outputs
  - Recommendations are advisory only — humans make decisions
  - No autonomous actions, no hidden heuristics
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

# ─────────────────────────────────────────────────────────────────────────────
# Recommendation Taxonomy
# ─────────────────────────────────────────────────────────────────────────────


class RecommendationType(StrEnum):
    """Closed taxonomy of recommendation types supported by Cortex.

    Each type has:
      - canonical ID (this enum value)
      - human-readable name
      - allowed scenario types
      - required evidence inputs
      - expected trade-offs
      - reversibility expectation
    """

    # Supply-side actions
    EXPEDITE_SHIPMENT = "expedite_shipment"
    USE_ALTERNATE_SUPPLIER = "use_alternate_supplier"
    TRANSFER_INVENTORY = "transfer_inventory"
    REBALANCE_STOCK = "rebalance_stock"

    # Demand-side actions
    PRIORITIZE_CRITICAL_ORDERS = "prioritize_critical_orders"
    DELAY_LOW_PRIORITY_ORDERS = "delay_low_priority_orders"
    SPLIT_FULFILLMENT = "split_fulfillment"

    # Logistics actions
    REROUTE_SHIPMENT = "reroute_shipment"
    EXPEDITE_ALTERNATIVE_CARRIER = "expedite_alternative_carrier"

    # Operational actions
    HOLD_SHIPMENT_PENDING_REVIEW = "hold_shipment_pending_review"
    REALLOCATE_TO_CRITICAL_CUSTOMERS = "reallocate_to_critical_customers"

    # Monitoring / no-action
    NO_ACTION_MONITOR = "no_action_monitor"

    # Custom (for future extension, requires explicit policy approval)
    CUSTOM = "custom"


class RecommendationCategory(StrEnum):
    """High-level categories for grouping and filtering."""

    SUPPLY_SIDE = "supply_side"
    DEMAND_SIDE = "demand_side"
    LOGISTICS = "logistics"
    OPERATIONAL = "operational"
    MONITORING = "monitoring"


class ReversibilityLevel(StrEnum):
    """How reversible is a recommendation if executed."""

    FULLY_REVERSIBLE = "fully_reversible"
    PARTIALLY_REVERSIBLE = "partially_reversible"
    IRREVERSIBLE = "irreversible"
    UNKNOWN = "unknown"


class PolicyClassification(StrEnum):
    """Policy classification for approval workflows."""

    AUTO_APPROVED = "auto_approved"  # low risk, can be auto-executed
    REVIEW_REQUIRED = "review_required"  # requires human review
    HIGH_RISK = "high_risk"  # requires senior approval
    POLICY_RESTRICTED = "policy_restricted"  # blocked by policy


# ─────────────────────────────────────────────────────────────────────────────
# Recommendation Candidate
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RecommendationCandidate:
    """A single candidate action generated from scenario analysis.

    This is the raw output of candidate generation rules before scoring.
    """

    candidate_id: str
    recommendation_type: RecommendationType
    category: RecommendationCategory
    name: str
    description: str

    # What scenario/propagation this addresses
    source_scenario_id: str
    source_propagation_id: str | None
    source_signal_ids: list[str]

    # Required evidence for this candidate
    required_evidence: list[str]  # entity IDs that must exist
    affected_node_ids: list[str]
    affected_entity_ids: list[str]
    affected_entity_types: list[str]

    # Initial metadata
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "recommendation_type": self.recommendation_type.value,
            "category": self.category.value,
            "name": self.name,
            "description": self.description,
            "source_scenario_id": self.source_scenario_id,
            "source_propagation_id": self.source_propagation_id,
            "source_signal_ids": list(self.source_signal_ids),
            "required_evidence": list(self.required_evidence),
            "affected_node_ids": list(self.affected_node_ids),
            "affected_entity_ids": list(self.affected_entity_ids),
            "affected_entity_types": list(self.affected_entity_types),
            "metadata": dict(self.metadata),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Recommendation Scores
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RecommendationScores:
    """Normalized scores for a recommendation candidate.

    All scores are in range 0.0 to 1.0 unless otherwise noted.
    Higher is better (except cost_score where lower is better).
    """

    # Overall composite score (0..1)
    overall_score: float

    # Component scores (0..1, higher is better)
    risk_reduction_score: float  # how much this reduces scenario impact
    cost_score: float  # inverse of cost (higher = cheaper)
    time_score: float  # speed to benefit (higher = faster)
    reversibility_score: float  # how reversible (higher = more reversible)
    confidence_score: float  # confidence in recommendation
    policy_fit_score: float  # alignment with policy preferences
    impact_reduction_score: float  # reduction in scenario impact

    # Metadata
    scoring_version: str = "1.0.0"
    scoring_formula: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_score": round(self.overall_score, 4),
            "risk_reduction_score": round(self.risk_reduction_score, 4),
            "cost_score": round(self.cost_score, 4),
            "time_score": round(self.time_score, 4),
            "reversibility_score": round(self.reversibility_score, 4),
            "confidence_score": round(self.confidence_score, 4),
            "policy_fit_score": round(self.policy_fit_score, 4),
            "impact_reduction_score": round(self.impact_reduction_score, 4),
            "scoring_version": self.scoring_version,
            "scoring_formula": self.scoring_formula,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Trade-offs
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RecommendationTradeOff:
    """A structured trade-off for a recommendation.

    Each trade-off explicitly states what is gained vs what is lost.
    """

    trade_off_id: str
    dimension: str  # "cost", "speed", "risk", "service_level", "complexity"
    gain: str  # what is improved
    loss: str  # what is compromised
    magnitude: str  # "low", "medium", "high"
    quantified_gain: float | None = None  # optional numeric value
    quantified_loss: float | None = None  # optional numeric value

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_off_id": self.trade_off_id,
            "dimension": self.dimension,
            "gain": self.gain,
            "loss": self.loss,
            "magnitude": self.magnitude,
            "quantified_gain": self.quantified_gain,
            "quantified_loss": self.quantified_loss,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Explanation
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RecommendationExplanation:
    """Structured explanation for why a recommendation was made.

    This is human-readable but also structured for frontend rendering.
    """

    explanation_id: str
    what: str  # what action is recommended
    why: str  # why this action was recommended
    evidence_summary: str  # summary of supporting evidence
    scenario_addressed: str  # which scenario impact this mitigates
    propagation_impact: str  # which propagation impact this addresses
    assumptions: list[str]  # assumptions affecting this recommendation
    uncertainties: list[str]  # what remains uncertain
    review_guidance: str  # what human should review before execution

    def to_dict(self) -> dict[str, Any]:
        return {
            "explanation_id": self.explanation_id,
            "what": self.what,
            "why": self.why,
            "evidence_summary": self.evidence_summary,
            "scenario_addressed": self.scenario_addressed,
            "propagation_impact": self.propagation_impact,
            "assumptions": list(self.assumptions),
            "uncertainties": list(self.uncertainties),
            "review_guidance": self.review_guidance,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Ranked Recommendation
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RankedRecommendation:
    """A fully scored, ranked recommendation ready for presentation.

    This combines candidate + scores + trade-offs + explanation.
    """

    recommendation_id: str
    rank: int
    candidate: RecommendationCandidate
    scores: RecommendationScores
    trade_offs: list[RecommendationTradeOff]
    explanation: RecommendationExplanation

    # Execution metadata
    reversibility: ReversibilityLevel
    policy_classification: PolicyClassification
    estimated_cost_usd: float | None = None
    estimated_time_to_benefit_hours: float | None = None
    estimated_impact_reduction_pct: float | None = None

    # Provenance
    graph_version: int | None = None
    context_version: int | None = None
    scenario_snapshot_version: int | None = None

    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommendation_id": self.recommendation_id,
            "rank": self.rank,
            "candidate": self.candidate.to_dict(),
            "scores": self.scores.to_dict(),
            "trade_offs": [t.to_dict() for t in self.trade_offs],
            "explanation": self.explanation.to_dict(),
            "reversibility": self.reversibility.value,
            "policy_classification": self.policy_classification.value,
            "estimated_cost_usd": self.estimated_cost_usd,
            "estimated_time_to_benefit_hours": self.estimated_time_to_benefit_hours,
            "estimated_impact_reduction_pct": self.estimated_impact_reduction_pct,
            "graph_version": self.graph_version,
            "context_version": self.context_version,
            "scenario_snapshot_version": self.scenario_snapshot_version,
            "created_at": self.created_at.isoformat(),
            "metadata": dict(self.metadata),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Recommendation Snapshot
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RecommendationSnapshot:
    """Complete recommendation snapshot — output of Program G.

    Immutable, deterministic, serializable, auditable.
    """

    recommendation_snapshot_id: str
    workspace_id: str

    # Source references
    source_scenario_id: str
    source_scenario_snapshot_version: int | None
    source_propagation_id: str | None
    source_propagation_snapshot_version: int | None
    source_signal_ids: list[str]

    # Graph/context versions at time of recommendation
    graph_version: int | None
    context_version: int | None
    feature_snapshot_version: int | None

    # Ranked recommendations
    recommendations: list[RankedRecommendation]

    # Metadata
    total_candidates_generated: int
    total_candidates_after_dedup: int
    scoring_version: str
    ranking_version: str

    # Execution metadata
    execution_time_ms: float = 0.0
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    recommendation_snapshot_version: int = 1  # Set by service layer when persisted
    recommendation_snapshot_hash: str | None = None

    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommendation_snapshot_id": self.recommendation_snapshot_id,
            "workspace_id": self.workspace_id,
            "source_scenario_id": self.source_scenario_id,
            "source_scenario_snapshot_version": self.source_scenario_snapshot_version,
            "source_propagation_id": self.source_propagation_id,
            "source_propagation_snapshot_version": self.source_propagation_snapshot_version,
            "source_signal_ids": list(self.source_signal_ids),
            "graph_version": self.graph_version,
            "context_version": self.context_version,
            "feature_snapshot_version": self.feature_snapshot_version,
            "recommendations": [r.to_dict() for r in self.recommendations],
            "total_candidates_generated": self.total_candidates_generated,
            "total_candidates_after_dedup": self.total_candidates_after_dedup,
            "scoring_version": self.scoring_version,
            "ranking_version": self.ranking_version,
            "execution_time_ms": round(self.execution_time_ms, 2),
            "warnings": list(self.warnings),
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "recommendation_snapshot_version": self.recommendation_snapshot_version,
            "recommendation_snapshot_hash": self.recommendation_snapshot_hash,
            "metadata": dict(self.metadata),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Request/Response
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RecommendationRequest:
    """Request to generate recommendations for a scenario."""

    workspace_id: str
    scenario_id: str
    scenario_snapshot_version: int | None = None
    include_explanations: bool = True
    include_trade_offs: bool = True
    min_confidence: float = 0.0
    max_recommendations: int | None = None
    snapshot_version: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "scenario_id": self.scenario_id,
            "scenario_snapshot_version": self.scenario_snapshot_version,
            "include_explanations": self.include_explanations,
            "include_trade_offs": self.include_trade_offs,
            "min_confidence": self.min_confidence,
            "max_recommendations": self.max_recommendations,
            "snapshot_version": self.snapshot_version,
        }


@dataclass(frozen=True)
class RecommendationResult:
    """Wrapper for recommendation engine result."""

    snapshot: RecommendationSnapshot
    success: bool
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot": self.snapshot.to_dict(),
            "success": self.success,
            "warnings": list(self.warnings),
        }
