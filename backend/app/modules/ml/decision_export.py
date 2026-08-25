"""ML Pipeline — Decision Export for Training Data.

This module exports decision records with anonymized features for ML training.
Exports include:
  - Source inputs (scenario, snapshot)
  - Graph snapshot at decision time
  - Propagation trace
  - Recommendation list with scores
  - Human decision (accept/override/reject)
  - Outcome (actual impact)
  - Backtest result
  - Calibration score

Exports are JSONL format for easy ingestion into training pipelines.
This is the REAL MOAT: every future model trains on validated operational memory.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.graph.decision_repository import (
    DecisionLessonDB,
    DecisionOutcomeDB,
    DecisionRecordDB,
)


@dataclass(frozen=True)
class PropagationTrace:
    """Propagation trace captured at decision time."""

    source_supplier_id: str
    affected_components: list[dict[str, Any]]
    affected_products: list[dict[str, Any]]
    affected_warehouses: list[dict[str, Any]]
    open_orders_at_risk: list[dict[str, Any]]
    max_hop: int
    traversed_edge_types: list[str]
    attenuation_factors: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class RecommendationRecord:
    """A single recommendation with full scoring breakdown."""

    rank: int
    action: str
    name: str
    explanation: str
    applicable: bool
    scores: dict[str, float]
    was_selected: bool = False
    human_override: bool = False


@dataclass(frozen=True)
class DecisionContext:
    """Full context of the decision for ML training."""

    # Source inputs
    scenario_type: str
    scenario_kind: str
    scenario_severity: str
    supplier_id: str
    supplier_tier: str
    supplier_country: str
    supplier_lead_time_days: int

    # Graph snapshot
    graph_version: int
    graph_snapshot_hash: str
    node_count: int
    edge_count: int

    # Propagation trace
    propagation: PropagationTrace

    # Business impact
    revenue_risk_usd: float
    margin_risk_usd: float
    penalty_exposure_usd: float
    working_capital_impact_usd: float
    overall_impact_score: float

    # Confidence
    confidence_overall: float
    confidence_completeness: float
    confidence_freshness: float
    confidence_agreement: float
    confidence_conflict_density: float

    # Recommendations
    recommendations: list[RecommendationRecord]
    ranking_formula: str

    # Timeline
    deadline_hours: int
    stockout_deadline_at: str | None


@dataclass(frozen=True)
class TrainingSample:
    """A single training sample exported from a decision record.

    This is the complete operational memory record - the real moat.
    """

    # Identifiers
    sample_id: str
    decision_id: str
    workspace_id: str  # anonymized in production
    export_version: str = "2.0.0"

    # Decision metadata
    decision_type: str
    decision_status: str
    decision_outcome: str | None  # accepted, overridden, rejected
    human_decision: str | None  # accept, override, reject
    human_override_reason: str | None

    # Full context
    context: DecisionContext

    # Outcome (ground truth)
    outcome_label: str | None  # success, partial_success, failed, no_impact
    outcome_success: bool | None
    actual_revenue_impact_usd: float | None
    actual_margin_impact_usd: float | None
    actual_penalty_usd: float | None
    actual_deadline_hours: float | None
    outcome_captured_at: str | None

    # Backtest result
    backtest_run_id: str | None
    backtest_accuracy: float | None
    backtest_revenue_error: float | None
    backtest_timeline_error: float | None

    # Calibration
    predicted_confidence: float | None
    calibration_score: float | None  # Brier score, ECE, etc.

    # Lessons
    lessons_count: int
    lessons: list[dict[str, Any]] = field(default_factory=list)

    # Timestamps
    created_at: str
    decided_at: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "decision_id": self.decision_id,
            "workspace_id": self.workspace_id,
            "export_version": self.export_version,
            "decision_type": self.decision_type,
            "decision_status": self.decision_status,
            "decision_outcome": self.decision_outcome,
            "human_decision": self.human_decision,
            "human_override_reason": self.human_override_reason,
            "context": {
                "scenario_type": self.context.scenario_type,
                "scenario_kind": self.context.scenario_kind,
                "scenario_severity": self.context.scenario_severity,
                "supplier_id": self.context.supplier_id,
                "supplier_tier": self.context.supplier_tier,
                "supplier_country": self.context.supplier_country,
                "supplier_lead_time_days": self.context.supplier_lead_time_days,
                "graph_version": self.context.graph_version,
                "graph_snapshot_hash": self.context.graph_snapshot_hash,
                "node_count": self.context.node_count,
                "edge_count": self.context.edge_count,
                "propagation": {
                    "source_supplier_id": self.context.propagation.source_supplier_id,
                    "affected_components": self.context.propagation.affected_components,
                    "affected_products": self.context.propagation.affected_products,
                    "affected_warehouses": self.context.propagation.affected_warehouses,
                    "open_orders_at_risk": self.context.propagation.open_orders_at_risk,
                    "max_hop": self.context.propagation.max_hop,
                    "traversed_edge_types": self.context.propagation.traversed_edge_types,
                    "attenuation_factors": self.context.propagation.attenuation_factors,
                },
                "revenue_risk_usd": self.context.revenue_risk_usd,
                "margin_risk_usd": self.context.margin_risk_usd,
                "penalty_exposure_usd": self.context.penalty_exposure_usd,
                "working_capital_impact_usd": self.context.working_capital_impact_usd,
                "overall_impact_score": self.context.overall_impact_score,
                "confidence_overall": self.context.confidence_overall,
                "confidence_completeness": self.context.confidence_completeness,
                "confidence_freshness": self.context.confidence_freshness,
                "confidence_agreement": self.context.confidence_agreement,
                "confidence_conflict_density": self.context.confidence_conflict_density,
                "recommendations": [
                    {
                        "rank": r.rank,
                        "action": r.action,
                        "name": r.name,
                        "explanation": r.explanation,
                        "applicable": r.applicable,
                        "scores": r.scores,
                        "was_selected": r.was_selected,
                        "human_override": r.human_override,
                    }
                    for r in self.context.recommendations
                ],
                "ranking_formula": self.context.ranking_formula,
                "deadline_hours": self.context.deadline_hours,
                "stockout_deadline_at": self.context.stockout_deadline_at,
            },
            "outcome_label": self.outcome_label,
            "outcome_success": self.outcome_success,
            "actual_revenue_impact_usd": self.actual_revenue_impact_usd,
            "actual_margin_impact_usd": self.actual_margin_impact_usd,
            "actual_penalty_usd": self.actual_penalty_usd,
            "actual_deadline_hours": self.actual_deadline_hours,
            "outcome_captured_at": self.outcome_captured_at,
            "backtest_run_id": self.backtest_run_id,
            "backtest_accuracy": self.backtest_accuracy,
            "backtest_revenue_error": self.backtest_revenue_error,
            "backtest_timeline_error": self.backtest_timeline_error,
            "predicted_confidence": self.predicted_confidence,
            "calibration_score": self.calibration_score,
            "lessons_count": self.lessons_count,
            "lessons": self.lessons,
            "created_at": self.created_at,
            "decided_at": self.decided_at,
        }


async def export_decisions_for_training(
    db: AsyncSession,
    workspace_id: str,
    output_path: Path,
    anonymize: bool = True,
    include_unlabeled: bool = False,
) -> int:
    """Export decision records as training samples.

    Args:
        db: Database session
        workspace_id: Workspace to export from
        output_path: Path to write JSONL file
        anonymize: If True, replace workspace_id with "ANONYMIZED"
        include_unlabeled: If True, include decisions without outcomes

    Returns:
        Number of samples exported
    """
    # Fetch decisions with outcomes and lessons
    decisions_stmt = select(DecisionRecordDB).where(DecisionRecordDB.workspace_id == workspace_id)
    decisions_result = await db.execute(decisions_stmt)
    decisions = decisions_result.scalars().all()

    samples = []
    for decision in decisions:
        # Fetch outcomes
        outcomes_stmt = select(DecisionOutcomeDB).where(
            DecisionOutcomeDB.decision_id == decision.decision_id
        )
        outcomes_result = await db.execute(outcomes_stmt)
        outcomes = outcomes_result.scalars().all()

        # Fetch lessons
        lessons_stmt = select(DecisionLessonDB).where(
            DecisionLessonDB.decision_id == decision.decision_id
        )
        lessons_result = await db.execute(lessons_stmt)
        lessons = lessons_result.scalars().all()

        # Skip if no outcome and include_unlabeled is False
        if not outcomes and not include_unlabeled:
            continue

        # Get outcome label from most recent outcome
        outcome_label = None
        outcome_success = None
        actual_revenue_impact = None
        actual_margin_impact = None
        actual_penalty = None
        actual_deadline = None
        outcome_captured_at = None

        if outcomes:
            latest_outcome = outcomes[-1]
            outcome_label = latest_outcome.outcome_status
            outcome_success = latest_outcome.met_expectations
            actual_revenue_impact = latest_outcome.actual_revenue_impact_usd
            actual_margin_impact = latest_outcome.actual_margin_impact_usd
            actual_penalty = latest_outcome.actual_penalty_usd
            actual_deadline = latest_outcome.actual_deadline_hours
            outcome_captured_at = latest_outcome.captured_at.isoformat() if latest_outcome.captured_at else None

        # Extract full context from metadata
        metadata = decision.metadata or {}

        # Build propagation trace
        propagation_data = metadata.get("propagation", {})
        propagation = PropagationTrace(
            source_supplier_id=propagation_data.get("source_supplier_id", ""),
            affected_components=propagation_data.get("affected_components", []),
            affected_products=propagation_data.get("affected_products", []),
            affected_warehouses=propagation_data.get("affected_warehouses", []),
            open_orders_at_risk=propagation_data.get("open_orders_at_risk", []),
            max_hop=propagation_data.get("max_hop", 0),
            traversed_edge_types=propagation_data.get("traversed_edge_types", []),
            attenuation_factors=propagation_data.get("attenuation_factors", {}),
        )

        # Build recommendations
        recs_data = metadata.get("recommendations", [])
        recommendations = []
        for i, r in enumerate(recs_data):
            recommendations.append(RecommendationRecord(
                rank=r.get("rank", i + 1),
                action=r.get("action", ""),
                name=r.get("name", ""),
                explanation=r.get("explanation", ""),
                applicable=r.get("applicable", True),
                scores=r.get("scores", {}),
                was_selected=r.get("was_selected", False),
                human_override=r.get("human_override", False),
            ))

        # Build context
        context = DecisionContext(
            scenario_type=metadata.get("scenario_type", ""),
            scenario_kind=metadata.get("scenario_kind", ""),
            scenario_severity=metadata.get("scenario_severity", ""),
            supplier_id=metadata.get("supplier_id", ""),
            supplier_tier=metadata.get("supplier_tier", ""),
            supplier_country=metadata.get("supplier_country", ""),
            supplier_lead_time_days=metadata.get("supplier_lead_time_days", 0),
            graph_version=decision.graph_version or 0,
            graph_snapshot_hash=metadata.get("graph_snapshot_hash", ""),
            node_count=metadata.get("node_count", 0),
            edge_count=metadata.get("edge_count", 0),
            propagation=propagation,
            revenue_risk_usd=metadata.get("revenue_risk_usd", 0.0),
            margin_risk_usd=metadata.get("margin_risk_usd", 0.0),
            penalty_exposure_usd=metadata.get("penalty_exposure_usd", 0.0),
            working_capital_impact_usd=metadata.get("working_capital_impact_usd", 0.0),
            overall_impact_score=metadata.get("overall_impact_score", 0.0),
            confidence_overall=metadata.get("confidence_overall", 0.0),
            confidence_completeness=metadata.get("confidence_completeness", 0.0),
            confidence_freshness=metadata.get("confidence_freshness", 0.0),
            confidence_agreement=metadata.get("confidence_agreement", 0.0),
            confidence_conflict_density=metadata.get("confidence_conflict_density", 0.0),
            recommendations=recommendations,
            ranking_formula=metadata.get("ranking_formula", ""),
            deadline_hours=metadata.get("deadline_hours", 72),
            stockout_deadline_at=metadata.get("stockout_deadline_at"),
        )

        # Lessons
        lesson_list = [
            {
                "lesson_id": l.lesson_id,
                "category": l.category,
                "description": l.description,
                "impact": l.impact,
                "created_at": l.created_at.isoformat() if l.created_at else None,
            }
            for l in lessons
        ]

        # Backtest info
        backtest_run_id = metadata.get("backtest_run_id")
        backtest_accuracy = metadata.get("backtest_accuracy")
        backtest_revenue_error = metadata.get("backtest_revenue_error")
        backtest_timeline_error = metadata.get("backtest_timeline_error")

        # Calibration
        predicted_confidence = metadata.get("predicted_confidence", context.confidence_overall)
        calibration_score = metadata.get("calibration_score")

        # Human decision
        human_decision = metadata.get("human_decision")
        human_override_reason = metadata.get("human_override_reason")
        decision_outcome = metadata.get("decision_outcome")

        sample = TrainingSample(
            sample_id=f"sample-{decision.decision_id}",
            decision_id=decision.decision_id,
            workspace_id="ANONYMIZED" if anonymize else workspace_id,
            decision_type=decision.decision_type,
            decision_status=decision.decision_status,
            decision_outcome=decision_outcome,
            human_decision=human_decision,
            human_override_reason=human_override_reason,
            context=context,
            outcome_label=outcome_label,
            outcome_success=outcome_success,
            actual_revenue_impact_usd=actual_revenue_impact,
            actual_margin_impact_usd=actual_margin_impact,
            actual_penalty_usd=actual_penalty,
            actual_deadline_hours=actual_deadline,
            outcome_captured_at=outcome_captured_at,
            backtest_run_id=backtest_run_id,
            backtest_accuracy=backtest_accuracy,
            backtest_revenue_error=backtest_revenue_error,
            backtest_timeline_error=backtest_timeline_error,
            predicted_confidence=predicted_confidence,
            calibration_score=calibration_score,
            lessons_count=len(lessons),
            lessons=lesson_list,
            created_at=decision.created_at.isoformat(),
            decided_at=decision.decided_at.isoformat() if decision.decided_at else None,
        )
        samples.append(sample)

    # Write to JSONL file
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for sample in samples:
            f.write(json.dumps(sample.to_dict()) + "\n")

    return len(samples)


async def get_training_data_summary(
    db: AsyncSession,
    workspace_id: str,
) -> dict[str, Any]:
    """Get summary statistics for training data in a workspace."""
    decisions_stmt = select(DecisionRecordDB).where(DecisionRecordDB.workspace_id == workspace_id)
    decisions_result = await db.execute(decisions_stmt)
    decisions = decisions_result.scalars().all()

    total = len(decisions)
    with_outcomes = 0
    outcome_counts: dict[str, int] = {}
    decision_type_counts: dict[str, int] = {}
    human_decision_counts: dict[str, int] = {}

    for decision in decisions:
        decision_type_counts[decision.decision_type] = (
            decision_type_counts.get(decision.decision_type, 0) + 1
        )

        outcomes_stmt = select(DecisionOutcomeDB).where(
            DecisionOutcomeDB.decision_id == decision.decision_id
        )
        outcomes_result = await db.execute(outcomes_stmt)
        outcomes = outcomes_result.scalars().all()

        if outcomes:
            with_outcomes += 1
            latest = outcomes[-1]
            outcome_counts[latest.outcome_status] = outcome_counts.get(latest.outcome_status, 0) + 1

        # Human decision distribution
        human_dec = (decision.metadata or {}).get("human_decision")
        if human_dec:
            human_decision_counts[human_dec] = human_decision_counts.get(human_dec, 0) + 1

    return {
        "total_decisions": total,
        "decisions_with_outcomes": with_outcomes,
        "decisions_without_outcomes": total - with_outcomes,
        "outcome_distribution": outcome_counts,
        "decision_type_distribution": decision_type_counts,
        "human_decision_distribution": human_decision_counts,
        "export_ready": with_outcomes if with_outcomes > 0 else total,
        "export_version": "2.0.0",
    }
