"""Intelligence Plane — Shadow Dispatcher.

Runs experimental models in shadow mode alongside the deterministic wedge.
Shadow predictions are logged for comparison but NEVER affect production output.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.disruption.engines.types import (
    DisruptionScenario,
    MorningBrief,
    SupplyChainSnapshot,
)
from app.modules.ml.model_registry import get_model
from app.modules.ml.shadow_inference import log_shadow_prediction


@dataclass(frozen=True)
class ShadowComparison:
    """Comparison between deterministic and shadow model outputs."""

    prediction_id: str
    model_id: str
    model_version: str
    workspace_id: str
    scenario_id: str

    # Deterministic outputs (ground truth from wedge)
    det_recommendations: list[dict[str, Any]]
    det_confidence: float
    det_revenue_risk: float
    det_margin_risk: float
    det_deadline_hours: float

    # Shadow model outputs
    shadow_recommendations: list[dict[str, Any]] | None
    shadow_confidence: float | None
    shadow_revenue_risk: float | None
    shadow_margin_risk: float | None
    shadow_deadline_hours: float | None

    # Comparison metrics
    rank_agreement: float | None
    confidence_delta: float | None
    revenue_error_delta: float | None
    deadline_delta: float | None

    created_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "prediction_id": self.prediction_id,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "workspace_id": self.workspace_id,
            "scenario_id": self.scenario_id,
            "det_recommendations": self.det_recommendations,
            "det_confidence": self.det_confidence,
            "det_revenue_risk": self.det_revenue_risk,
            "det_margin_risk": self.det_margin_risk,
            "det_deadline_hours": self.det_deadline_hours,
            "shadow_recommendations": self.shadow_recommendations,
            "shadow_confidence": self.shadow_confidence,
            "shadow_revenue_risk": self.shadow_revenue_risk,
            "shadow_margin_risk": self.shadow_margin_risk,
            "shadow_deadline_hours": self.shadow_deadline_hours,
            "rank_agreement": self.rank_agreement,
            "confidence_delta": self.confidence_delta,
            "revenue_error_delta": self.revenue_error_delta,
            "deadline_delta": self.deadline_delta,
            "created_at": self.created_at.isoformat(),
        }


async def extract_brief_features(
    snapshot: SupplyChainSnapshot,
    scenario: DisruptionScenario,
    brief: MorningBrief,
) -> dict[str, Any]:
    """Extract features from the deterministic brief for shadow model input."""
    return {
        "supplier_id": str(scenario.supplier_id),
        "scenario_kind": scenario.kind.value,
        "scenario_severity": scenario.severity,
        "num_suppliers": len(snapshot.suppliers),
        "num_components": len(snapshot.components),
        "num_products": len(snapshot.products),
        "num_warehouses": len(snapshot.warehouses),
        "num_orders": len(snapshot.orders),
        # Propagation features
        "affected_components": len(brief.propagation.affected_components),
        "affected_products": len(brief.propagation.affected_products),
        "affected_warehouses": len(brief.propagation.affected_warehouses),
        "open_orders_at_risk": len(brief.propagation.open_orders_at_risk),
        "max_hop": brief.propagation.max_hop,
        "traversed_edge_types": list(brief.propagation.traversed_edge_types),
        # Impact features
        "revenue_risk_usd": brief.business_impact.revenue_risk_usd,
        "margin_risk_usd": brief.business_impact.margin_risk_usd,
        "penalty_exposure_usd": brief.business_impact.penalty_exposure_usd,
        "working_capital_impact_usd": brief.business_impact.working_capital_impact_usd,
        "overall_score": brief.business_impact.overall_score,
        # Confidence features
        "confidence_overall": brief.confidence.overall,
        "confidence_completeness": brief.confidence.completeness,
        "confidence_freshness": brief.confidence.freshness,
        "confidence_agreement": brief.confidence.agreement,
        "confidence_conflict_density": brief.confidence.conflict_density,
        # Recommendation features
        "num_recommendations": len(brief.recommendations.recommendations),
        "top_rec_action": brief.recommendations.recommendations[0].action.value
        if brief.recommendations.recommendations
        else None,
        "top_rec_net_benefit": brief.recommendations.recommendations[0].scores.net_benefit
        if brief.recommendations.recommendations
        else 0.0,
        # Timeline features
        "deadline_hours": 72,  # Will be computed by caller
        "stockout_deadline_at": brief.timeline.stockout_deadline_at.isoformat()
        if brief.timeline.stockout_deadline_at
        else None,
    }


async def run_shadow_inference(
    db: AsyncSession,
    workspace_id: UUID,
    model_id: str,
    model_version: str,
    features: dict[str, Any],
) -> tuple[str, dict[str, Any] | None, float | None]:
    """Run a shadow model and log the prediction.

    Returns:
        Tuple of (prediction_id, prediction_dict, confidence)
    """
    # Load model from registry
    model_artifact = await get_model(db, model_id, model_version)
    if not model_artifact:
        return "", None, None

    # For now, return a placeholder - actual model inference would go here
    # This is where the baseline/learned model would be invoked
    prediction = {"status": "model_not_implemented", "model_id": model_id}
    confidence = 0.5

    prediction_id = await log_shadow_prediction(
        db=db,
        workspace_id=str(workspace_id),
        model_id=model_id,
        model_version=model_version,
        input_features=features,
        prediction=prediction,
        confidence=confidence,
    )

    return prediction_id, prediction, confidence


async def compare_outputs(
    det_brief: MorningBrief,
    shadow_prediction: dict[str, Any] | None,
    shadow_confidence: float | None,
    scenario_id: str,
    workspace_id: UUID,
    model_id: str,
    model_version: str,
    prediction_id: str,
) -> ShadowComparison:
    """Compare deterministic brief outputs with shadow model predictions."""
    det_recs = [
        {
            "rank": r.rank,
            "action": r.action.value,
            "name": r.name,
            "net_benefit": r.scores.net_benefit,
        }
        for r in det_brief.recommendations.recommendations
    ]

    shadow_recs = shadow_prediction.get("recommendations") if shadow_prediction else None

    # Compute rank agreement (NDCG-style)
    rank_agreement = None
    if shadow_recs and det_recs:
        det_ranks = {r["action"]: r["rank"] for r in det_recs}
        shadow_ranks = {r["action"]: r["rank"] for r in shadow_recs}
        common = set(det_ranks.keys()) & set(shadow_ranks.keys())
        if common:
            rank_diffs = [abs(det_ranks[a] - shadow_ranks[a]) for a in common]
            rank_agreement = 1.0 - (
                sum(rank_diffs)
                / (len(common) * max(max(det_ranks.values()), max(shadow_ranks.values())))
            )

    confidence_delta = None
    if shadow_confidence is not None:
        confidence_delta = abs(det_brief.confidence.overall - shadow_confidence)

    revenue_error_delta = None
    if shadow_prediction and "revenue_risk_usd" in shadow_prediction:
        revenue_error_delta = abs(
            det_brief.business_impact.revenue_risk_usd - shadow_prediction["revenue_risk_usd"]
        )

    deadline_delta = None
    if shadow_prediction and "deadline_hours" in shadow_prediction:
        det_deadline = 72  # Default from API
        if det_brief.timeline.stockout_deadline_at:
            delta = det_brief.timeline.stockout_deadline_at - det_brief.timeline.bucket_zero
            det_deadline = max(1, int(delta.total_seconds() / 3600))
        deadline_delta = abs(det_deadline - shadow_prediction["deadline_hours"])

    return ShadowComparison(
        prediction_id=prediction_id,
        model_id=model_id,
        model_version=model_version,
        workspace_id=str(workspace_id),
        scenario_id=scenario_id,
        det_recommendations=det_recs,
        det_confidence=det_brief.confidence.overall,
        det_revenue_risk=det_brief.business_impact.revenue_risk_usd,
        det_margin_risk=det_brief.business_impact.margin_risk_usd,
        det_deadline_hours=72,
        shadow_recommendations=shadow_recs,
        shadow_confidence=shadow_confidence,
        shadow_revenue_risk=shadow_prediction.get("revenue_risk_usd")
        if shadow_prediction
        else None,
        shadow_margin_risk=shadow_prediction.get("margin_risk_usd") if shadow_prediction else None,
        shadow_deadline_hours=shadow_prediction.get("deadline_hours")
        if shadow_prediction
        else None,
        rank_agreement=rank_agreement,
        confidence_delta=confidence_delta,
        revenue_error_delta=revenue_error_delta,
        deadline_delta=deadline_delta,
        created_at=datetime.now(UTC),
    )


async def dispatch_shadow_models(
    db: AsyncSession,
    workspace_id: UUID,
    snapshot: SupplyChainSnapshot,
    scenario: DisruptionScenario,
    brief: MorningBrief,
    scenario_id: str,
) -> list[ShadowComparison]:
    """Dispatch all registered shadow models and compare against deterministic wedge.

    This is the main entry point called from the brief API after deterministic
    brief generation. It runs in the background and NEVER affects the response.
    """
    comparisons = []

    # Extract features once for all models
    features = await extract_brief_features(snapshot, scenario, brief)

    # TODO: Get active shadow models from registry
    # For now, we have a placeholder for the baseline ranking model
    shadow_models = [
        {"model_id": "baseline_ranking_v1", "model_version": "1.0.0"},
        {"model_id": "baseline_calibration_v1", "model_version": "1.0.0"},
    ]

    for model_spec in shadow_models:
        prediction_id, prediction, confidence = await run_shadow_inference(
            db=db,
            workspace_id=workspace_id,
            model_id=model_spec["model_id"],
            model_version=model_spec["model_version"],
            features=features,
        )

        if prediction_id:
            comparison = await compare_outputs(
                det_brief=brief,
                shadow_prediction=prediction,
                shadow_confidence=confidence,
                scenario_id=scenario_id,
                workspace_id=workspace_id,
                model_id=model_spec["model_id"],
                model_version=model_spec["model_version"],
                prediction_id=prediction_id,
            )
            comparisons.append(comparison)

    return comparisons
