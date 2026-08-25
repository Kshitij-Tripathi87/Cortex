"""Recommendation Engine — core orchestration for Program G.

The RecommendationEngine orchestrates:
  - Candidate generation from scenario snapshots
  - Scoring and ranking of candidates
  - Explanation and trade-off generation
  - Deduplication and snapshot creation

This is the main entry point for generating recommendations.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from app.common.ids import uuid7
from app.modules.graph.context_fusion import EnrichedSnapshot
from app.modules.graph.propagation_models import PropagationSnapshot
from app.modules.graph.recommendation_explanations import (
    generate_explanation,
    generate_trade_offs,
)
from app.modules.graph.recommendation_generation import generate_candidates
from app.modules.graph.recommendation_models import (
    PolicyClassification,
    RankedRecommendation,
    RecommendationCandidate,
    RecommendationRequest,
    RecommendationResult,
    RecommendationScores,
    RecommendationSnapshot,
    ReversibilityLevel,
)
from app.modules.graph.recommendation_rules import (
    get_recommendation_type_spec,
)
from app.modules.graph.recommendation_scoring import (
    compute_snapshot_hash,
    deduplicate_candidates,
    rank_candidates,
    score_candidate,
)
from app.modules.graph.scenario_models import (
    ScenarioSnapshot,
)
from app.modules.graph.signal_models import SignalSnapshot


class RecommendationEngine:
    """Main recommendation engine for Program G.

    Usage:
        engine = RecommendationEngine()
        result = engine.generate_recommendations(
            scenario_snapshot=scenario,
            enriched_snapshot=enriched,
            request=request,
        )
    """

    def __init__(self) -> None:
        self._scoring_version = "1.0.0"
        self._ranking_version = "1.0.0"

    def generate_recommendations(
        self,
        scenario_snapshot: ScenarioSnapshot,
        request: RecommendationRequest,
        enriched_snapshot: EnrichedSnapshot | None = None,
        propagation_snapshot: PropagationSnapshot | None = None,
        signal_snapshot: SignalSnapshot | None = None,
    ) -> RecommendationResult:
        """Generate recommendations for a scenario.

        Args:
            scenario_snapshot: The scenario execution result
            request: Recommendation request parameters
            enriched_snapshot: Optional operational context
            propagation_snapshot: Optional propagation snapshot
            signal_snapshot: Optional signal snapshot

        Returns:
            RecommendationResult with ranked recommendations
        """
        start_time = time.perf_counter()
        warnings: list[str] = []

        # 1. Generate candidates
        candidates = generate_candidates(
            scenario_snapshot=scenario_snapshot,
            enriched_snapshot=enriched_snapshot,
            propagation_snapshot=propagation_snapshot,
            signal_snapshot=signal_snapshot,
        )

        total_candidates_generated = len(candidates)

        if not candidates:
            # No candidates generated - return empty result
            snapshot = self._build_empty_snapshot(
                scenario_snapshot=scenario_snapshot,
                request=request,
                warnings=["No candidates generated for this scenario"],
            )
            return RecommendationResult(
                snapshot=snapshot,
                success=True,
                warnings=["No candidates generated for this scenario"],
            )

        # 2. Score candidates
        scores = [
            score_candidate(candidate, scenario_snapshot, enriched_snapshot)
            for candidate in candidates
        ]

        # 3. Filter by minimum confidence
        if request.min_confidence > 0:
            filtered = [
                (c, s)
                for c, s in zip(candidates, scores, strict=True)
                if s.confidence_score >= request.min_confidence
            ]
            if len(filtered) < len(candidates):
                warnings.append(
                    f"Filtered {len(candidates) - len(filtered)} candidates below confidence threshold"
                )
            candidates, scores = zip(*filtered, strict=True) if filtered else ([], [])
            candidates = list(candidates)
            scores = list(scores)

        # 4. Deduplicate
        candidates, scores = deduplicate_candidates(candidates, scores)
        total_candidates_after_dedup = len(candidates)

        # 5. Rank
        ranked = rank_candidates(candidates, scores)

        # 6. Apply max_recommendations limit
        if request.max_recommendations and len(ranked) > request.max_recommendations:
            ranked = ranked[: request.max_recommendations]

        # 7. Build ranked recommendations with explanations
        ranked_recommendations = self._build_ranked_recommendations(
            ranked=ranked,
            scenario_snapshot=scenario_snapshot,
            enriched_snapshot=enriched_snapshot,
            include_explanations=request.include_explanations,
            include_trade_offs=request.include_trade_offs,
        )

        # 8. Build snapshot
        elapsed_ms = (time.perf_counter() - start_time) * 1000

        snapshot = RecommendationSnapshot(
            recommendation_snapshot_id=f"rec-{uuid7()}",
            workspace_id=request.workspace_id,
            source_scenario_id=scenario_snapshot.scenario_id,
            source_scenario_snapshot_version=scenario_snapshot.scenario_snapshot_version,
            source_propagation_id=scenario_snapshot.source_propagation_id,
            source_propagation_snapshot_version=scenario_snapshot.propagation_snapshot_version,
            source_signal_ids=self._collect_signal_ids(scenario_snapshot, signal_snapshot),
            graph_version=scenario_snapshot.graph_version,
            context_version=scenario_snapshot.context_snapshot_version,
            feature_snapshot_version=scenario_snapshot.feature_snapshot_version,
            recommendations=ranked_recommendations,
            total_candidates_generated=total_candidates_generated,
            total_candidates_after_dedup=total_candidates_after_dedup,
            scoring_version=self._scoring_version,
            ranking_version=self._ranking_version,
            execution_time_ms=round(elapsed_ms, 2),
            warnings=warnings,
            created_at=datetime.now(UTC),
            recommendation_snapshot_version=request.snapshot_version
            or scenario_snapshot.scenario_snapshot_version
            or 0,
            recommendation_snapshot_hash=compute_snapshot_hash(
                candidates=[r.candidate for r in ranked_recommendations],
                scores=[r.scores for r in ranked_recommendations],
                scenario_snapshot_id=scenario_snapshot.scenario_id,
                timestamp=datetime.now(UTC),
            ),
        )

        return RecommendationResult(
            snapshot=snapshot,
            success=True,
            warnings=warnings,
        )

    def _build_empty_snapshot(
        self,
        scenario_snapshot: ScenarioSnapshot,
        request: RecommendationRequest,
        warnings: list[str],
    ) -> RecommendationSnapshot:
        """Build empty snapshot when no candidates generated."""
        return RecommendationSnapshot(
            recommendation_snapshot_id=f"rec-{uuid7()}",
            workspace_id=request.workspace_id,
            source_scenario_id=scenario_snapshot.scenario_id,
            source_scenario_snapshot_version=scenario_snapshot.scenario_snapshot_version,
            source_propagation_id=scenario_snapshot.source_propagation_id,
            source_propagation_snapshot_version=scenario_snapshot.propagation_snapshot_version,
            source_signal_ids=self._collect_signal_ids(scenario_snapshot, None),
            graph_version=scenario_snapshot.graph_version,
            context_version=scenario_snapshot.context_snapshot_version,
            feature_snapshot_version=scenario_snapshot.feature_snapshot_version,
            recommendations=[],
            total_candidates_generated=0,
            total_candidates_after_dedup=0,
            scoring_version=self._scoring_version,
            ranking_version=self._ranking_version,
            execution_time_ms=0.0,
            warnings=warnings,
            created_at=datetime.now(UTC),
            recommendation_snapshot_version=request.snapshot_version
            or scenario_snapshot.scenario_snapshot_version
            or 0,
        )

    def _build_ranked_recommendations(
        self,
        ranked: list[tuple[RecommendationCandidate, RecommendationScores, int]],
        scenario_snapshot: ScenarioSnapshot,
        enriched_snapshot: EnrichedSnapshot | None = None,
        include_explanations: bool = True,
        include_trade_offs: bool = True,
    ) -> list[RankedRecommendation]:
        """Build ranked recommendations with explanations and trade-offs."""
        recommendations = []

        for candidate, scores, rank in ranked:
            spec = get_recommendation_type_spec(candidate.recommendation_type)

            # Generate explanation if requested
            explanation = None
            if include_explanations:
                explanation = generate_explanation(
                    candidate=candidate,
                    scores=scores,
                    scenario_snapshot=scenario_snapshot,
                    enriched_snapshot=enriched_snapshot,
                )

            # Generate trade-offs if requested
            trade_offs = []
            if include_trade_offs:
                trade_offs = generate_trade_offs(
                    candidate=candidate,
                    scores=scores,
                    scenario_snapshot=scenario_snapshot,
                )

            # Get spec metadata
            estimated_cost = None
            estimated_time = None
            reversibility = ReversibilityLevel.UNKNOWN
            policy_class = PolicyClassification.REVIEW_REQUIRED

            if spec:
                if spec.estimated_cost_range:
                    estimated_cost = (
                        spec.estimated_cost_range[0] + spec.estimated_cost_range[1]
                    ) / 2
                if spec.estimated_time_range:
                    estimated_time = (
                        spec.estimated_time_range[0] + spec.estimated_time_range[1]
                    ) / 2
                reversibility = spec.reversibility
                policy_class = spec.policy_classification

            # Calculate estimated impact reduction
            impact_reduction_pct = scores.impact_reduction_score * 100

            recommendation = RankedRecommendation(
                recommendation_id=f"rec-{uuid7()}",
                rank=rank,
                candidate=candidate,
                scores=scores,
                trade_offs=trade_offs,
                explanation=explanation,  # type: ignore
                reversibility=reversibility,
                policy_classification=policy_class,
                estimated_cost_usd=round(estimated_cost, 2) if estimated_cost else None,
                estimated_time_to_benefit_hours=round(estimated_time, 2)
                if estimated_time
                else None,
                estimated_impact_reduction_pct=round(impact_reduction_pct, 2),
                graph_version=scenario_snapshot.graph_version,
                context_version=scenario_snapshot.context_snapshot_version,
                scenario_snapshot_version=scenario_snapshot.scenario_snapshot_version,
                created_at=datetime.now(UTC),
                metadata={
                    "generation_method": "rule_based",
                    "scoring_version": self._scoring_version,
                },
            )

            recommendations.append(recommendation)

        return recommendations

    def _collect_signal_ids(
        self,
        scenario_snapshot: ScenarioSnapshot,
        signal_snapshot: SignalSnapshot | None,
    ) -> list[str]:
        """Collect all source signal IDs."""
        signal_ids = []

        if scenario_snapshot.source_signal_id:
            signal_ids.append(scenario_snapshot.source_signal_id)

        if signal_snapshot:
            signal_ids.extend([s.signal_id for s in signal_snapshot.signals])

        return signal_ids
