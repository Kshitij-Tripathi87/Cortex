"""Recommendation Explanations — structured explanation generation.

This module generates human-readable but structured explanations for
recommendations.

Explanations are:
  - Structured: consistent format for frontend rendering
  - Evidence-based: reference actual scenario impacts
  - Honest: include uncertainties and assumptions
  - Actionable: provide review guidance
  - Traceable: link back to source data
"""

from __future__ import annotations

from typing import Any

from app.common.ids import uuid7
from app.modules.graph.context_fusion import EnrichedSnapshot
from app.modules.graph.recommendation_models import (
    RecommendationCandidate,
    RecommendationExplanation,
    RecommendationScores,
    RecommendationTradeOff,
)
from app.modules.graph.recommendation_rules import (
    get_recommendation_type_spec,
)
from app.modules.graph.scenario_models import (
    ScenarioSnapshot,
)


def generate_explanation(
    candidate: RecommendationCandidate,
    scores: RecommendationScores,
    scenario_snapshot: ScenarioSnapshot,
    enriched_snapshot: EnrichedSnapshot | None = None,
) -> RecommendationExplanation:
    """Generate structured explanation for a recommendation.

    Args:
        candidate: The recommendation candidate
        scores: The candidate's scores
        scenario_snapshot: The scenario being addressed
        enriched_snapshot: Optional operational context

    Returns:
        RecommendationExplanation with all required fields
    """
    explanation_id = f"exp-{uuid7()}"

    # What action is recommended
    what = _generate_what(candidate)

    # Why this action was recommended
    why = _generate_why(
        candidate,
        scores,
        scenario_snapshot,
    )

    # Summary of supporting evidence
    evidence_summary = _generate_evidence_summary(
        candidate,
        scenario_snapshot,
    )

    # Which scenario impact this mitigates
    scenario_addressed = _generate_scenario_addressed(
        candidate,
        scenario_snapshot,
    )

    # Which propagation impact this addresses
    propagation_impact = _generate_propagation_impact(
        candidate,
        scenario_snapshot,
    )

    # Assumptions affecting this recommendation
    assumptions = _generate_assumptions(
        candidate,
        scenario_snapshot,
        enriched_snapshot,
    )

    # What remains uncertain
    uncertainties = _generate_uncertainties(
        candidate,
        scores,
        scenario_snapshot,
    )

    # What human should review before execution
    review_guidance = _generate_review_guidance(
        candidate,
        scores,
        scenario_snapshot,
    )

    return RecommendationExplanation(
        explanation_id=explanation_id,
        what=what,
        why=why,
        evidence_summary=evidence_summary,
        scenario_addressed=scenario_addressed,
        propagation_impact=propagation_impact,
        assumptions=assumptions,
        uncertainties=uncertainties,
        review_guidance=review_guidance,
    )


def _generate_what(candidate: RecommendationCandidate) -> str:
    """Generate 'what' - the action being recommended."""
    spec = get_recommendation_type_spec(candidate.recommendation_type)

    if not spec:
        return f"Execute {candidate.name}"

    # Build action statement
    action = spec.name

    # Add affected entities if available
    if candidate.affected_entity_ids:
        entities = candidate.affected_entity_ids[:3]
        if len(candidate.affected_entity_ids) > 3:
            entities_str = (
                f"{', '.join(entities)} and {len(candidate.affected_entity_ids) - 3} others"
            )
        else:
            entities_str = ", ".join(entities)
        return f"{action} for: {entities_str}"

    return action


def _generate_why(
    candidate: RecommendationCandidate,
    scores: RecommendationScores,
    scenario_snapshot: ScenarioSnapshot,
) -> str:
    """Generate 'why' - rationale for this recommendation."""
    reasons = []

    # Primary reason based on scenario type
    scenario_type = scenario_snapshot.scenario_definition.scenario_type.value
    reasons.append(f"Recommended response to {scenario_type.replace('_', ' ')} scenario")

    # Add score-based reasons
    if scores.risk_reduction_score > 0.7:
        reasons.append("significantly reduces operational risk")

    if scores.impact_reduction_score > 0.7:
        reasons.append("addresses major impact areas")

    if scores.time_score > 0.7:
        reasons.append("can be executed quickly")

    if scores.cost_score > 0.7:
        reasons.append("cost-effective option")

    if scores.confidence_score > 0.7:
        reasons.append("high confidence based on available evidence")

    # Join reasons
    if len(reasons) > 1:
        return f"{reasons[0]}; {', '.join(reasons[1:])}"
    return reasons[0] if reasons else "Standard response for this scenario type"


def _generate_evidence_summary(
    candidate: RecommendationCandidate,
    scenario_snapshot: ScenarioSnapshot,
) -> str:
    """Generate evidence summary."""
    parts = []

    # Count impacted entities
    total_impacts = len(scenario_snapshot.impacts)
    parts.append(f"{total_impacts} impacted entities identified")

    # Severity breakdown
    severity_counts = {}
    for impact in scenario_snapshot.impacts:
        sev = impact.severity
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

    if severity_counts:
        sev_parts = [f"{count} {sev}" for sev, count in sorted(severity_counts.items())]
        parts.append(f"Severity: {', '.join(sev_parts)}")

    # Entity types
    entity_types = set(i.affected_entity_type for i in scenario_snapshot.impacts)
    if entity_types:
        parts.append(f"Entity types: {', '.join(sorted(entity_types))}")

    return "; ".join(parts)


def _generate_scenario_addressed(
    candidate: RecommendationCandidate,
    scenario_snapshot: ScenarioSnapshot,
) -> str:
    """Generate scenario impact statement."""
    scenario_def = scenario_snapshot.scenario_definition

    # Get summary statistics
    total_impacts = len(scenario_snapshot.impacts)
    total_financial = sum(i.estimated_financial_impact or 0 for i in scenario_snapshot.impacts)
    max_recovery = 0.0
    if scenario_snapshot.impacts:
        max_recovery = max(i.estimated_recovery_hours or 0 for i in scenario_snapshot.impacts)

    parts = [
        f"Scenario '{scenario_def.name}' affects {total_impacts} entities",
    ]

    if total_financial > 0:
        parts.append(f"estimated financial impact ${total_financial:,.0f}")

    if max_recovery > 0:
        parts.append(f"max recovery time {max_recovery:.1f} hours")

    return "; ".join(parts)


def _generate_propagation_impact(
    candidate: RecommendationCandidate,
    scenario_snapshot: ScenarioSnapshot,
) -> str:
    """Generate propagation impact statement."""
    if not scenario_snapshot.impacts:
        return "No propagation impacts recorded"

    # Get max hop
    max_hop = max(i.hop_number for i in scenario_snapshot.impacts)

    # Get affected categories
    categories = set(i.impact_category for i in scenario_snapshot.impacts)

    parts = [
        f"Propagation extends {max_hop} hop(s) from source",
        f"Impact categories: {', '.join(sorted(categories))}",
    ]

    # Source info
    if scenario_snapshot.source_propagation_id:
        parts.append(f"Source propagation: {scenario_snapshot.source_propagation_id}")

    return "; ".join(parts)


def _generate_assumptions(
    candidate: RecommendationCandidate,
    scenario_snapshot: ScenarioSnapshot,
    enriched_snapshot: EnrichedSnapshot | None = None,
) -> list[str]:
    """Generate list of assumptions."""
    assumptions = []

    # General assumptions
    assumptions.append("Scenario propagation model accurately reflects operational reality")

    # Evidence assumptions
    if not candidate.required_evidence:
        assumptions.append("No specific evidence requirements for this recommendation")
    else:
        missing = set(candidate.required_evidence) - set(candidate.affected_entity_types)
        if missing:
            assumptions.append(f"Required evidence types {', '.join(missing)} assumed available")

    # Context assumptions
    if enriched_snapshot:
        if not enriched_snapshot.by_node:
            assumptions.append("Operational context loaded but no node states available")
    else:
        assumptions.append("Recommendation generated without operational context")

    # Confidence assumptions
    if len(scenario_snapshot.impacts) < 3:
        assumptions.append("Limited impact data may affect recommendation quality")

    return assumptions


def _generate_uncertainties(
    candidate: RecommendationCandidate,
    scores: RecommendationScores,
    scenario_snapshot: ScenarioSnapshot,
) -> list[str]:
    """Generate list of uncertainties."""
    uncertainties = []

    # Score-based uncertainties
    if scores.confidence_score < 0.5:
        uncertainties.append("Low confidence in recommendation due to limited evidence")

    if scores.risk_reduction_score < 0.5:
        uncertainties.append("Uncertain effectiveness for risk reduction")

    # Impact-based uncertainties
    critical_impacts = [
        i for i in scenario_snapshot.impacts if i.severity in ("critical", "blocking")
    ]

    if critical_impacts:
        uncertainties.append(
            f"{len(critical_impacts)} critical impacts require immediate attention"
        )

    # Recovery time uncertainty
    recovery_times = [
        i.estimated_recovery_hours
        for i in scenario_snapshot.impacts
        if i.estimated_recovery_hours is not None
    ]

    if recovery_times:
        max_recovery = max(recovery_times)
        if max_recovery > 72:
            uncertainties.append(
                f"Extended recovery time ({max_recovery:.1f}h) increases uncertainty"
            )

    # Default if no specific uncertainties
    if not uncertainties:
        uncertainties.append("Execution outcomes may vary based on real-world conditions")

    return uncertainties


def _generate_review_guidance(
    candidate: RecommendationCandidate,
    scores: RecommendationScores,
    scenario_snapshot: ScenarioSnapshot,
) -> str:
    """Generate review guidance for humans."""
    spec = get_recommendation_type_spec(candidate.recommendation_type)

    if not spec:
        return "Review recommendation details and approve if appropriate"

    guidance_parts = []

    # Policy-based guidance
    if spec.policy_classification.value == "review_required":
        guidance_parts.append("Requires human review before execution")
    elif spec.policy_classification.value == "high_risk":
        guidance_parts.append("Requires senior approval due to high risk")

    # Cost-based guidance
    if spec.estimated_cost_range:
        max_cost = spec.estimated_cost_range[1]
        if max_cost > 5000:
            guidance_parts.append(f"Verify budget availability (up to ${max_cost:,.0f})")

    # Time-based guidance
    if spec.estimated_time_range:
        max_time = spec.estimated_time_range[1]
        if max_time > 48:
            guidance_parts.append(f"Confirm timeline feasibility (up to {max_time:.0f}h)")

    # Reversibility guidance
    if spec.reversibility.value == "irreversible":
        guidance_parts.append("Action is irreversible - verify before execution")
    elif spec.reversibility.value == "partially_reversible":
        guidance_parts.append("Action is partially reversible - plan rollback strategy")

    # Scenario-specific guidance
    scenario_type = scenario_snapshot.scenario_definition.scenario_type
    if scenario_type.value == "supplier_failure":
        guidance_parts.append("Verify alternate supplier capacity and quality")
    elif scenario_type.value == "warehouse_outage":
        guidance_parts.append("Confirm alternate facility availability")
    elif scenario_type.value == "inventory_shortage":
        guidance_parts.append("Check inventory accuracy before transfer")

    # Default guidance
    if not guidance_parts:
        return "Review recommendation and approve if appropriate for current situation"

    return ". ".join(guidance_parts)


def generate_trade_offs(
    candidate: RecommendationCandidate,
    scores: RecommendationScores,
    scenario_snapshot: ScenarioSnapshot,
) -> list[RecommendationTradeOff]:
    """Generate structured trade-offs for a recommendation.

    Each trade-off explicitly states what is gained vs what is lost.
    """
    trade_offs = []
    spec = get_recommendation_type_spec(candidate.recommendation_type)

    if not spec:
        return trade_offs

    # Generate trade-offs based on typical trade-offs from spec
    for dimension in spec.typical_trade_offs:
        trade_off = _generate_trade_off(
            dimension,
            candidate,
            scores,
            spec,
        )
        if trade_off:
            trade_offs.append(trade_off)

    # Always include at least one trade-off
    if not trade_offs:
        trade_offs.append(
            RecommendationTradeOff(
                trade_off_id=f"to-{uuid7()}",
                dimension="general",
                gain="Addresses scenario impact",
                loss="Requires resource allocation",
                magnitude="medium",
            )
        )

    return trade_offs


def _generate_trade_off(
    dimension: str,
    candidate: RecommendationCandidate,
    scores: RecommendationScores,
    spec: Any,
) -> RecommendationTradeOff | None:
    """Generate a single trade-off for a dimension."""
    trade_off_id = f"to-{uuid7()}"

    # Dimension-specific trade-offs
    if dimension == "cost":
        cost_range = spec.estimated_cost_range
        if cost_range:
            return RecommendationTradeOff(
                trade_off_id=trade_off_id,
                dimension="cost",
                gain=f"Reduces scenario impact (score: {scores.impact_reduction_score:.2f})",
                loss=f"Requires budget allocation (${cost_range[0]:,.0f}-${cost_range[1]:,.0f})",
                magnitude="high" if cost_range[1] > 5000 else "medium",
                quantified_loss=cost_range[1],
            )

    elif dimension == "speed":
        time_range = spec.estimated_time_range
        if time_range:
            return RecommendationTradeOff(
                trade_off_id=trade_off_id,
                dimension="speed",
                gain=f"Time to benefit: {time_range[0]:.0f}-{time_range[1]:.0f} hours",
                loss="May require expedited processing fees",
                magnitude="low" if time_range[1] < 24 else "medium",
                quantified_gain=time_range[0],
            )

    elif dimension == "risk":
        return RecommendationTradeOff(
            trade_off_id=trade_off_id,
            dimension="risk",
            gain=f"Risk reduction score: {scores.risk_reduction_score:.2f}",
            loss="Execution risk if conditions change",
            magnitude="low" if scores.risk_reduction_score > 0.7 else "medium",
            quantified_gain=scores.risk_reduction_score,
        )

    elif dimension == "service_level":
        return RecommendationTradeOff(
            trade_off_id=trade_off_id,
            dimension="service_level",
            gain="Protects service levels for critical entities",
            loss="May impact service for non-critical entities",
            magnitude="medium",
        )

    elif dimension == "complexity":
        return RecommendationTradeOff(
            trade_off_id=trade_off_id,
            dimension="complexity",
            gain="Addresses multiple impacted entities",
            loss="Requires coordination across multiple teams",
            magnitude="medium" if len(candidate.affected_node_ids) > 3 else "low",
        )

    elif dimension == "reversibility":
        reversibility = spec.reversibility.value
        return RecommendationTradeOff(
            trade_off_id=trade_off_id,
            dimension="reversibility",
            gain="Provides operational flexibility",
            loss=f"Reversibility: {reversibility.replace('_', ' ')}",
            magnitude="low" if reversibility == "fully_reversible" else "high",
        )

    return None
