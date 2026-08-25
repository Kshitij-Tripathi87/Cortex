"""Recommendation Scoring — deterministic scoring and ranking.

This module implements the scoring model for ranking recommendation candidates.

Scoring is:
  - Deterministic: same inputs → same scores
  - Explainable: each score component is documented
  - Normalized: all scores in 0.0 to 1.0 range
  - Context-aware: uses operational context to adjust scores
  - Versioned: scoring formula is tracked for audit

Scoring formula:
  overall_score = (
    risk_reduction_score * 0.25 +
    impact_reduction_score * 0.20 +
    time_score * 0.15 +
    confidence_score * 0.15 +
    cost_score * 0.10 +
    reversibility_score * 0.10 +
    policy_fit_score * 0.05
  )
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from app.modules.graph.context_fusion import EnrichedSnapshot
from app.modules.graph.recommendation_models import (
    RecommendationCandidate,
    RecommendationScores,
    ReversibilityLevel,
)
from app.modules.graph.recommendation_rules import (
    get_recommendation_type_spec,
    get_scenario_recommendation_rule,
)
from app.modules.graph.scenario_models import (
    ScenarioSnapshot,
)

# Scoring weights (versioned and documented)
SCORING_WEIGHTS = {
    "risk_reduction": 0.25,
    "impact_reduction": 0.20,
    "time": 0.15,
    "confidence": 0.15,
    "cost": 0.10,
    "reversibility": 0.10,
    "policy_fit": 0.05,
}

SCORING_VERSION = "1.0.0"
SCORING_FORMULA = (
    "overall = 0.25*risk + 0.20*impact + 0.15*time + 0.15*confidence + "
    "0.10*cost + 0.10*reversibility + 0.05*policy"
)


def score_candidate(
    candidate: RecommendationCandidate,
    scenario_snapshot: ScenarioSnapshot,
    enriched_snapshot: EnrichedSnapshot | None = None,
) -> RecommendationScores:
    """Score a single recommendation candidate.

    Args:
        candidate: The candidate to score
        scenario_snapshot: The scenario being addressed
        enriched_snapshot: Optional operational context

    Returns:
        RecommendationScores with all components
    """
    # Calculate each component score
    risk_score = _calculate_risk_reduction_score(
        candidate,
        scenario_snapshot,
    )

    impact_score = _calculate_impact_reduction_score(
        candidate,
        scenario_snapshot,
    )

    time_score = _calculate_time_score(
        candidate,
        scenario_snapshot,
    )

    confidence_score = _calculate_confidence_score(
        candidate,
        scenario_snapshot,
        enriched_snapshot,
    )

    cost_score = _calculate_cost_score(
        candidate,
    )

    reversibility_score = _calculate_reversibility_score(
        candidate,
    )

    policy_score = _calculate_policy_fit_score(
        candidate,
        scenario_snapshot,
    )

    # Calculate overall score
    overall_score = (
        risk_score * SCORING_WEIGHTS["risk_reduction"]
        + impact_score * SCORING_WEIGHTS["impact_reduction"]
        + time_score * SCORING_WEIGHTS["time"]
        + confidence_score * SCORING_WEIGHTS["confidence"]
        + cost_score * SCORING_WEIGHTS["cost"]
        + reversibility_score * SCORING_WEIGHTS["reversibility"]
        + policy_score * SCORING_WEIGHTS["policy_fit"]
    )

    # Clamp to 0-1 range
    overall_score = max(0.0, min(1.0, overall_score))

    return RecommendationScores(
        overall_score=overall_score,
        risk_reduction_score=risk_score,
        cost_score=cost_score,
        time_score=time_score,
        reversibility_score=reversibility_score,
        confidence_score=confidence_score,
        policy_fit_score=policy_score,
        impact_reduction_score=impact_score,
        scoring_version=SCORING_VERSION,
        scoring_formula=SCORING_FORMULA,
    )


def _calculate_risk_reduction_score(
    candidate: RecommendationCandidate,
    scenario_snapshot: ScenarioSnapshot,
) -> float:
    """Calculate risk reduction score (0..1).

    Higher score = more risk reduction.

    Factors:
      - Severity of impacts addressed
      - Number of critical entities protected
      - Alignment with scenario type
    """
    score = 0.5  # Base score

    # Bonus for addressing critical/blocking impacts
    critical_impacts = [
        i for i in scenario_snapshot.impacts if i.severity in ("critical", "blocking")
    ]

    if critical_impacts:
        # Check if candidate affects the same nodes
        candidate_nodes = set(candidate.affected_node_ids)
        critical_nodes = {i.affected_node_id for i in critical_impacts}

        overlap = len(candidate_nodes & critical_nodes)
        if overlap > 0:
            score += 0.3 * (overlap / max(len(critical_nodes), 1))

    # Bonus for alignment with scenario type
    scenario_type = scenario_snapshot.scenario_definition.scenario_type
    rule = get_scenario_recommendation_rule(scenario_type)

    if rule and candidate.recommendation_type in rule.candidate_types:
        # Higher priority = higher score
        priority = rule.priority_weights.get(candidate.recommendation_type, 0.5)
        score += 0.2 * priority

    return min(1.0, score)


def _calculate_impact_reduction_score(
    candidate: RecommendationCandidate,
    scenario_snapshot: ScenarioSnapshot,
) -> float:
    """Calculate impact reduction score (0..1).

    Higher score = more impact reduction.

    Factors:
      - Estimated impact reduction percentage
      - Number of impacts addressed
      - Total financial impact addressed
    """
    score = 0.5  # Base score

    # Calculate what percentage of impacts this candidate addresses
    candidate_nodes = set(candidate.affected_node_ids)
    scenario_nodes = {i.affected_node_id for i in scenario_snapshot.impacts}

    if scenario_nodes:
        coverage = len(candidate_nodes & scenario_nodes) / len(scenario_nodes)
        score += 0.3 * coverage

    # Bonus for addressing high financial impact
    total_financial = sum(i.estimated_financial_impact or 0 for i in scenario_snapshot.impacts)

    if total_financial > 0:
        # Candidates that address more entities get higher score
        entity_coverage = len(candidate.affected_entity_ids) / max(
            len(scenario_snapshot.impacts), 1
        )
        score += 0.2 * entity_coverage

    return min(1.0, score)


def _calculate_time_score(
    candidate: RecommendationCandidate,
    scenario_snapshot: ScenarioSnapshot,
) -> float:
    """Calculate time-to-benefit score (0..1).

    Higher score = faster to benefit.

    Based on recommendation type's typical time range.
    """
    spec = get_recommendation_type_spec(candidate.recommendation_type)

    if not spec or not spec.estimated_time_range:
        return 0.5  # Default if no time estimate

    min_hours, max_hours = spec.estimated_time_range

    # Faster = higher score
    # Normalize: 0 hours = 1.0, 168 hours (1 week) = 0.0
    avg_hours = (min_hours + max_hours) / 2
    time_score = 1.0 - (avg_hours / 168.0)

    return max(0.0, min(1.0, time_score))


def _calculate_confidence_score(
    candidate: RecommendationCandidate,
    scenario_snapshot: ScenarioSnapshot,
    enriched_snapshot: EnrichedSnapshot | None = None,
) -> float:
    """Calculate confidence score (0..1).

    Higher score = higher confidence in recommendation.

    Factors:
      - Scenario confidence
      - Evidence completeness
      - Operational context availability
    """
    score = 0.5  # Base score

    # Factor in scenario confidence
    if scenario_snapshot.impacts:
        avg_confidence = sum(i.confidence for i in scenario_snapshot.impacts) / len(
            scenario_snapshot.impacts
        )
        score += 0.3 * avg_confidence

    # Bonus for complete evidence
    required_evidence = candidate.required_evidence
    available_evidence = candidate.affected_entity_types

    if required_evidence:
        evidence_match = len(set(required_evidence) & set(available_evidence))
        evidence_score = evidence_match / len(required_evidence)
        score += 0.2 * evidence_score

    # Bonus for having operational context
    if enriched_snapshot:
        score += 0.1

    return min(1.0, score)


def _calculate_cost_score(
    candidate: RecommendationCandidate,
) -> float:
    """Calculate cost score (0..1).

    Higher score = lower cost (inverse).

    Based on recommendation type's typical cost range.
    """
    spec = get_recommendation_type_spec(candidate.recommendation_type)

    if not spec or not spec.estimated_cost_range:
        return 0.5  # Default if no cost estimate

    min_cost, max_cost = spec.estimated_cost_range

    # Lower cost = higher score
    # Normalize: $0 = 1.0, $10000 = 0.0
    avg_cost = (min_cost + max_cost) / 2
    cost_score = 1.0 - (avg_cost / 10000.0)

    return max(0.0, min(1.0, cost_score))


def _calculate_reversibility_score(
    candidate: RecommendationCandidate,
) -> float:
    """Calculate reversibility score (0..1).

    Higher score = more reversible.
    """
    spec = get_recommendation_type_spec(candidate.recommendation_type)

    if not spec:
        return 0.5

    reversibility_map = {
        ReversibilityLevel.FULLY_REVERSIBLE: 1.0,
        ReversibilityLevel.PARTIALLY_REVERSIBLE: 0.5,
        ReversibilityLevel.IRREVERSIBLE: 0.0,
        ReversibilityLevel.UNKNOWN: 0.5,
    }

    return reversibility_map.get(spec.reversibility, 0.5)


def _calculate_policy_fit_score(
    candidate: RecommendationCandidate,
    scenario_snapshot: ScenarioSnapshot,
) -> float:
    """Calculate policy fit score (0..1).

    Higher score = better policy alignment.
    """
    spec = get_recommendation_type_spec(candidate.recommendation_type)

    if not spec:
        return 0.5

    # Policy classification affects score
    policy_map = {
        "auto_approved": 1.0,
        "review_required": 0.7,
        "high_risk": 0.3,
        "policy_restricted": 0.0,
    }

    return policy_map.get(spec.policy_classification.value, 0.5)


def rank_candidates(
    candidates: list[RecommendationCandidate],
    scores: list[RecommendationScores],
) -> list[tuple[RecommendationCandidate, RecommendationScores, int]]:
    """Rank candidates by overall score.

    Args:
        candidates: List of candidates
        scores: Corresponding scores (same order)

    Returns:
        List of (candidate, score, rank) tuples sorted by score descending
    """
    if not candidates:
        return []

    # Pair candidates with scores
    paired = list(zip(candidates, scores, strict=True))

    # Sort by overall score descending, then by candidate_id for stability
    sorted_paired = sorted(
        paired,
        key=lambda x: (-x[1].overall_score, x[0].candidate_id),
    )

    # Assign ranks
    ranked = []
    for rank, (candidate, score) in enumerate(sorted_paired, start=1):
        ranked.append((candidate, score, rank))

    return ranked


def deduplicate_candidates(
    candidates: list[RecommendationCandidate],
    scores: list[RecommendationScores],
) -> tuple[list[RecommendationCandidate], list[RecommendationScores]]:
    """Deduplicate candidates keeping best-scoring representative.

    Candidates are considered duplicates if they have:
      - Same recommendation type
      - Same affected entity IDs (as a set)

    Args:
        candidates: List of candidates (may contain duplicates)
        scores: Corresponding scores

    Returns:
        Tuple of (deduplicated_candidates, deduplicated_scores)
    """
    if not candidates:
        return [], []

    # Group by (recommendation_type, frozenset of entity_ids)
    groups: dict[tuple, list[tuple[RecommendationCandidate, RecommendationScores]]] = {}

    for candidate, score in zip(candidates, scores, strict=True):
        key = (
            candidate.recommendation_type,
            frozenset(candidate.affected_entity_ids),
        )

        if key not in groups:
            groups[key] = []
        groups[key].append((candidate, score))

    # Keep best-scoring representative from each group
    deduped_candidates = []
    deduped_scores = []

    for group in groups.values():
        # Sort by overall score descending
        best = max(group, key=lambda x: x[1].overall_score)
        deduped_candidates.append(best[0])
        deduped_scores.append(best[1])

    return deduped_candidates, deduped_scores


def compute_snapshot_hash(
    candidates: list[RecommendationCandidate],
    scores: list[RecommendationScores],
    scenario_snapshot_id: str,
    timestamp: datetime,
) -> str:
    """Compute deterministic hash for a recommendation snapshot.

    Used for audit and replay verification.
    """
    # Create deterministic string representation
    content_parts = [
        f"scenario:{scenario_snapshot_id}",
        f"timestamp:{timestamp.isoformat()}",
        f"scoring_version:{SCORING_VERSION}",
    ]

    # Add candidate data in sorted order
    for candidate, score in sorted(
        zip(candidates, scores, strict=True),
        key=lambda x: x[0].candidate_id,
    ):
        content_parts.append(
            f"{candidate.candidate_id}:{candidate.recommendation_type.value}:{score.overall_score:.4f}"
        )

    content = "|".join(content_parts)

    # Compute SHA-256 hash
    hash_bytes = hashlib.sha256(content.encode("utf-8")).hexdigest()

    return f"rec-{hash_bytes[:16]}"
