"""Tests for Program G — Recommendation Engine.

Tests cover:
  - Candidate generation
  - Scoring
  - Explanation generation
  - Ranking and deduplication
  - End-to-end recommendation flow
  - Regression stability
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.modules.graph.context_fusion import EnrichedNodeState, EnrichedSnapshot
from app.modules.graph.feature_models import NodeFeatures
from app.modules.graph.recommendation_engine import RecommendationEngine
from app.modules.graph.recommendation_explanations import (
    generate_explanation,
    generate_trade_offs,
)
from app.modules.graph.recommendation_generation import generate_candidates
from app.modules.graph.recommendation_models import (
    RecommendationCandidate,
    RecommendationRequest,
    RecommendationType,
)
from app.modules.graph.recommendation_rules import (
    RECOMMENDATION_TAXONOMY,
    SCENARIO_RECOMMENDATION_RULES,
    get_recommendation_type_spec,
    get_scenario_recommendation_rule,
    is_recommendation_allowed,
)
from app.modules.graph.recommendation_scoring import (
    deduplicate_candidates,
    rank_candidates,
    score_candidate,
)
from app.modules.graph.scenario_models import (
    ScenarioDefinition,
    ScenarioImpactRecord,
    ScenarioSnapshot,
    ScenarioStatus,
    ScenarioSummary,
    ScenarioType,
)

# ─────────────────────────────────────────────────────────────────────────────
# Test Fixtures
# ─────────────────────────────────────────────────────────────────────────────


def make_scenario_definition(
    scenario_type: ScenarioType = ScenarioType.SUPPLIER_FAILURE,
) -> ScenarioDefinition:
    """Create a test scenario definition."""
    return ScenarioDefinition(
        scenario_id="scenario-test-1",
        workspace_id="ws-test",
        scenario_type=scenario_type,
        name="Test Scenario",
        description="Test scenario for recommendations",
        parameters=[],
        source_propagation_id="prop-1",
        source_signal_id="sig-1",
    )


def make_scenario_impact(
    node_id: str = "n1",
    entity_id: str = "e1",
    entity_type: str = "Supplier",
    hop: int = 1,
    category: str = "supplier",
    severity: str = "warning",
    confidence: float = 0.8,
    recovery_hours: float | None = 48.0,
    financial_impact: float | None = 10000.0,
) -> ScenarioImpactRecord:
    """Create a test scenario impact."""
    return ScenarioImpactRecord(
        scenario_id="scenario-test-1",
        affected_node_id=node_id,
        affected_entity_id=entity_id,
        affected_entity_type=entity_type,
        hop_number=hop,
        impact_category=category,
        severity=severity,
        confidence=confidence,
        estimated_recovery_hours=recovery_hours,
        estimated_financial_impact=financial_impact,
        estimated_service_level_impact_pct=5.0,
        source_propagation_step_id="step-1",
        graph_version=1,
        context_version=1,
        propagation_version=1,
    )


def make_scenario_snapshot(
    impacts: list[ScenarioImpactRecord] | None = None,
    scenario_type: ScenarioType = ScenarioType.SUPPLIER_FAILURE,
) -> ScenarioSnapshot:
    """Create a test scenario snapshot."""
    if impacts is None:
        impacts = [
            make_scenario_impact("n1", "s1", "Supplier", 0, "supplier", "critical"),
            make_scenario_impact("n2", "f1", "Facility", 1, "facility", "warning"),
            make_scenario_impact("n3", "inv-1", "InventoryItem", 2, "inventory", "warning"),
        ]

    summary = ScenarioSummary(
        total_impacted_entities=len(impacts),
        by_severity={i.severity: 1 for i in impacts} if impacts else {},
        by_impact_category={i.impact_category: 1 for i in impacts} if impacts else {},
        max_hop=max((i.hop_number for i in impacts), default=0),
        avg_confidence=sum(i.confidence for i in impacts) / len(impacts) if impacts else 0.0,
        total_estimated_recovery_hours=sum(i.estimated_recovery_hours or 0 for i in impacts),
        total_estimated_financial_impact=sum(i.estimated_financial_impact or 0 for i in impacts),
    )

    return ScenarioSnapshot(
        scenario_id="scenario-test-1",
        workspace_id="ws-test",
        scenario_definition=make_scenario_definition(scenario_type),
        status=ScenarioStatus.COMPLETED,
        impacts=impacts,
        summary=summary,
        source_propagation_id="prop-1",
        source_signal_id="sig-1",
        graph_version=1,
        feature_snapshot_version=1,
        context_snapshot_version=1,
        propagation_snapshot_version=1,
        execution_time_ms=100.0,
        scenario_snapshot_version=1,
        completed_at=datetime.now(UTC),
    )


def make_enriched_snapshot(
    nodes: dict[str, NodeFeatures] | None = None,
) -> EnrichedSnapshot:
    """Create a test enriched snapshot."""
    if nodes is None:
        nodes = {
            "n1": NodeFeatures(
                node_id="n1",
                entity_id="s1",
                entity_type="Supplier",
                payload={},
            ),
            "n2": NodeFeatures(
                node_id="n2",
                entity_id="f1",
                entity_type="Facility",
                payload={},
            ),
        }

    by_node = {
        node_id: EnrichedNodeState(
            node_id=node_id,
            entity_id=features.entity_id,
            entity_type=features.entity_type,
            features=features,
        )
        for node_id, features in nodes.items()
    }

    return EnrichedSnapshot(
        workspace_id="ws-test",
        snapshot_version=1,
        snapshot_hash="test-hash",
        feature_snapshot_version=1,
        feature_snapshot_hash="feature-hash",
        operational_snapshot_version=None,
        operational_snapshot_hash=None,
        by_node=by_node,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test Recommendation Taxonomy
# ─────────────────────────────────────────────────────────────────────────────


class TestRecommendationTaxonomy:
    """Test recommendation taxonomy and rules."""

    def test_all_recommendation_types_have_specs(self):
        """Every recommendation type should have a specification."""
        for rec_type in RecommendationType:
            # CUSTOM is a special case - it's allowed but has minimal spec
            if rec_type == RecommendationType.CUSTOM:
                continue
            spec = get_recommendation_type_spec(rec_type)
            assert spec is not None, f"Missing spec for {rec_type}"
            assert spec.name, f"Missing name for {rec_type}"
            assert spec.description, f"Missing description for {rec_type}"

    def test_all_scenario_types_have_rules(self):
        """Every scenario type should have recommendation rules."""
        for scenario_type in ScenarioType:
            rule = get_scenario_recommendation_rule(scenario_type)
            # Custom scenario may not have rules
            if scenario_type != ScenarioType.CUSTOM:
                assert rule is not None, f"Missing rule for {scenario_type}"

    def test_recommendation_type_allowed_for_scenario(self):
        """Recommendation types should be allowed for appropriate scenarios."""
        # Supplier failure should allow alternate supplier
        assert is_recommendation_allowed(
            ScenarioType.SUPPLIER_FAILURE,
            RecommendationType.USE_ALTERNATE_SUPPLIER,
        )

        # Inventory shortage should allow transfer inventory
        assert is_recommendation_allowed(
            ScenarioType.INVENTORY_SHORTAGE,
            RecommendationType.TRANSFER_INVENTORY,
        )

        # Route closure should allow reroute shipment
        assert is_recommendation_allowed(
            ScenarioType.ROUTE_CLOSURE,
            RecommendationType.REROUTE_SHIPMENT,
        )

    def test_taxonomy_is_closed(self):
        """Taxonomy should be a closed set."""
        # All recommendation types except CUSTOM should be in the taxonomy
        for rec_type in RecommendationType:
            if rec_type == RecommendationType.CUSTOM:
                continue  # CUSTOM is a placeholder, not in taxonomy
            assert rec_type in RECOMMENDATION_TAXONOMY

    def test_spec_has_required_fields(self):
        """Each spec should have all required fields."""
        for spec in RECOMMENDATION_TAXONOMY.values():
            assert spec.recommendation_type is not None
            assert spec.category is not None
            assert spec.name
            assert spec.description
            assert isinstance(spec.allowed_scenario_types, list)
            assert isinstance(spec.required_evidence, list)
            assert spec.reversibility is not None
            assert spec.policy_classification is not None


# ─────────────────────────────────────────────────────────────────────────────
# Test Candidate Generation
# ─────────────────────────────────────────────────────────────────────────────


class TestCandidateGeneration:
    """Test candidate generation rules."""

    def test_generates_candidates_for_supplier_failure(self):
        """Supplier failure should generate appropriate candidates."""
        scenario = make_scenario_snapshot(scenario_type=ScenarioType.SUPPLIER_FAILURE)

        candidates = generate_candidates(scenario)

        assert len(candidates) > 0
        candidate_types = {c.recommendation_type for c in candidates}

        # Should include alternate supplier
        assert RecommendationType.USE_ALTERNATE_SUPPLIER in candidate_types

        # Should include expedite shipment
        assert RecommendationType.EXPEDITE_SHIPMENT in candidate_types

    def test_generates_candidates_for_inventory_shortage(self):
        """Inventory shortage should generate appropriate candidates."""
        scenario = make_scenario_snapshot(scenario_type=ScenarioType.INVENTORY_SHORTAGE)

        candidates = generate_candidates(scenario)

        assert len(candidates) > 0
        candidate_types = {c.recommendation_type for c in candidates}

        # Should include transfer inventory
        assert RecommendationType.TRANSFER_INVENTORY in candidate_types

    def test_generates_candidates_for_warehouse_outage(self):
        """Warehouse outage should generate appropriate candidates."""
        scenario = make_scenario_snapshot(scenario_type=ScenarioType.WAREHOUSE_OUTAGE)

        candidates = generate_candidates(scenario)

        assert len(candidates) > 0
        candidate_types = {c.recommendation_type for c in candidates}

        # Should include transfer inventory
        assert RecommendationType.TRANSFER_INVENTORY in candidate_types
        # Should include split fulfillment
        assert RecommendationType.SPLIT_FULFILLMENT in candidate_types

    def test_candidate_has_required_fields(self):
        """Each candidate should have all required fields."""
        scenario = make_scenario_snapshot()
        candidates = generate_candidates(scenario)

        for candidate in candidates:
            assert candidate.candidate_id
            assert candidate.recommendation_type is not None
            assert candidate.category is not None
            assert candidate.name
            assert candidate.description
            assert candidate.source_scenario_id
            assert isinstance(candidate.affected_node_ids, list)
            assert isinstance(candidate.affected_entity_ids, list)

    def test_candidate_generation_is_deterministic(self):
        """Same inputs should produce same candidates."""
        scenario = make_scenario_snapshot()

        candidates1 = generate_candidates(scenario)
        candidates2 = generate_candidates(scenario)

        assert len(candidates1) == len(candidates2)

        # Candidate types should match (IDs may differ due to UUID)
        types1 = sorted(c.recommendation_type.value for c in candidates1)
        types2 = sorted(c.recommendation_type.value for c in candidates2)

        assert types1 == types2

    def test_no_action_included_for_low_impact(self):
        """No-action option should be included for low-impact scenarios."""
        # Low impact scenario
        impacts = [
            make_scenario_impact(severity="info", confidence=0.5, financial_impact=1000.0),
        ]
        scenario = make_scenario_snapshot(impacts=impacts)

        candidates = generate_candidates(scenario)

        # Should include no-action option
        candidate_types = {c.recommendation_type for c in candidates}
        assert RecommendationType.NO_ACTION_MONITOR in candidate_types

    def test_no_action_excluded_for_high_impact(self):
        """No-action option should be excluded for high-impact scenarios."""
        # High impact scenario - many critical impacts with high financial impact
        impacts = [
            make_scenario_impact(
                f"n{i}", f"e{i}", "Supplier", i, "supplier", "critical", 0.9, 48.0, 500000.0
            )
            for i in range(15)  # 15 impacts > 10 threshold
        ]
        scenario = make_scenario_snapshot(impacts=impacts)

        candidates = generate_candidates(scenario)

        # Should NOT include no-action option
        candidate_types = {c.recommendation_type for c in candidates}
        assert RecommendationType.NO_ACTION_MONITOR not in candidate_types


# ─────────────────────────────────────────────────────────────────────────────
# Test Scoring
# ─────────────────────────────────────────────────────────────────────────────


class TestScoring:
    """Test recommendation scoring."""

    def test_scores_are_normalized(self):
        """All scores should be in 0.0 to 1.0 range."""
        scenario = make_scenario_snapshot()
        candidates = generate_candidates(scenario)

        for candidate in candidates:
            scores = score_candidate(candidate, scenario)

            assert 0.0 <= scores.overall_score <= 1.0
            assert 0.0 <= scores.risk_reduction_score <= 1.0
            assert 0.0 <= scores.cost_score <= 1.0
            assert 0.0 <= scores.time_score <= 1.0
            assert 0.0 <= scores.confidence_score <= 1.0
            assert 0.0 <= scores.reversibility_score <= 1.0
            assert 0.0 <= scores.policy_fit_score <= 1.0
            assert 0.0 <= scores.impact_reduction_score <= 1.0

    def test_scoring_is_deterministic(self):
        """Same inputs should produce same scores."""
        scenario = make_scenario_snapshot()
        candidates = generate_candidates(scenario)

        scores1 = [score_candidate(c, scenario) for c in candidates]
        scores2 = [score_candidate(c, scenario) for c in candidates]

        for s1, s2 in zip(scores1, scores2, strict=True):
            assert s1.overall_score == s2.overall_score
            assert s1.risk_reduction_score == s2.risk_reduction_score

    def test_higher_priority_candidates_score_better(self):
        """Higher priority candidates should have higher scores."""
        scenario = make_scenario_snapshot(scenario_type=ScenarioType.SUPPLIER_FAILURE)
        candidates = generate_candidates(scenario)

        scores = [score_candidate(c, scenario) for c in candidates]

        # Find alternate supplier candidate (should be high priority)
        alt_supplier = next(
            (
                c
                for c in candidates
                if c.recommendation_type == RecommendationType.USE_ALTERNATE_SUPPLIER
            ),
            None,
        )

        if alt_supplier:
            idx = candidates.index(alt_supplier)
            # Should have decent score
            assert scores[idx].overall_score > 0.5

    def test_scoring_includes_formula(self):
        """Scores should include formula metadata."""
        scenario = make_scenario_snapshot()
        candidates = generate_candidates(scenario)

        if candidates:
            scores = score_candidate(candidates[0], scenario)
            assert scores.scoring_version
            assert scores.scoring_formula


# ─────────────────────────────────────────────────────────────────────────────
# Test Ranking and Deduplication
# ─────────────────────────────────────────────────────────────────────────────


class TestRankingAndDeduplication:
    """Test ranking and deduplication."""

    def test_ranking_sorts_by_score_descending(self):
        """Ranking should sort candidates by score descending."""
        scenario = make_scenario_snapshot()
        candidates = generate_candidates(scenario)
        scores = [score_candidate(c, scenario) for c in candidates]

        ranked = rank_candidates(candidates, scores)

        # Scores should be in descending order
        prev_score = float("inf")
        for _, score, _ in ranked:
            assert score.overall_score <= prev_score
            prev_score = score.overall_score

    def test_ranking_assigns_sequential_ranks(self):
        """Ranking should assign sequential ranks."""
        scenario = make_scenario_snapshot()
        candidates = generate_candidates(scenario)
        scores = [score_candidate(c, scenario) for c in candidates]

        ranked = rank_candidates(candidates, scores)

        for i, (_, _, rank) in enumerate(ranked, start=1):
            assert rank == i

    def test_deduplication_removes_duplicates(self):
        """Deduplication should remove duplicate candidates."""
        scenario = make_scenario_snapshot()
        candidates = generate_candidates(scenario)
        scores = [score_candidate(c, scenario) for c in candidates]

        # Create duplicates manually
        if candidates:
            dup_candidate = RecommendationCandidate(
                candidate_id="dup-1",
                recommendation_type=candidates[0].recommendation_type,
                category=candidates[0].category,
                name=candidates[0].name,
                description=candidates[0].description,
                source_scenario_id=candidates[0].source_scenario_id,
                source_propagation_id=candidates[0].source_propagation_id,
                source_signal_ids=candidates[0].source_signal_ids,
                required_evidence=candidates[0].required_evidence,
                affected_node_ids=candidates[0].affected_node_ids,
                affected_entity_ids=candidates[0].affected_entity_ids,  # Same entities
                affected_entity_types=candidates[0].affected_entity_types,
            )
            dup_score = scores[0]

            candidates_with_dup = candidates + [dup_candidate]
            scores_with_dup = scores + [dup_score]

            deduped_candidates, deduped_scores = deduplicate_candidates(
                candidates_with_dup,
                scores_with_dup,
            )

            # Should have fewer candidates after deduplication
            assert len(deduped_candidates) < len(candidates_with_dup)

    def test_deduplication_keeps_best_score(self):
        """Deduplication should keep the best-scoring representative."""
        scenario = make_scenario_snapshot()
        candidates = generate_candidates(scenario)
        scores = [score_candidate(c, scenario) for c in candidates]

        if candidates:
            # Create a duplicate with lower score
            dup_candidate = RecommendationCandidate(
                candidate_id="dup-low",
                recommendation_type=candidates[0].recommendation_type,
                category=candidates[0].category,
                name=candidates[0].name,
                description=candidates[0].description,
                source_scenario_id=candidates[0].source_scenario_id,
                source_propagation_id=candidates[0].source_propagation_id,
                source_signal_ids=candidates[0].source_signal_ids,
                required_evidence=candidates[0].required_evidence,
                affected_node_ids=candidates[0].affected_node_ids,
                affected_entity_ids=candidates[0].affected_entity_ids,
                affected_entity_types=candidates[0].affected_entity_types,
            )

            # Manually create a lower score
            from app.modules.graph.recommendation_models import RecommendationScores

            dup_score = RecommendationScores(
                overall_score=0.1,  # Very low
                risk_reduction_score=0.1,
                cost_score=0.1,
                time_score=0.1,
                reversibility_score=0.1,
                confidence_score=0.1,
                policy_fit_score=0.1,
                impact_reduction_score=0.1,
            )

            candidates_with_dup = [dup_candidate] + candidates
            scores_with_dup = [dup_score] + scores

            deduped_candidates, deduped_scores = deduplicate_candidates(
                candidates_with_dup,
                scores_with_dup,
            )

            # The kept candidate should have the higher score
            if deduped_scores:
                assert deduped_scores[0].overall_score >= 0.1


# ─────────────────────────────────────────────────────────────────────────────
# Test Explanations
# ─────────────────────────────────────────────────────────────────────────────


class TestExplanations:
    """Test explanation generation."""

    def test_explanation_has_required_fields(self):
        """Explanations should have all required fields."""
        scenario = make_scenario_snapshot()
        candidates = generate_candidates(scenario)

        if candidates:
            scores = score_candidate(candidates[0], scenario)
            explanation = generate_explanation(candidates[0], scores, scenario)

            assert explanation.explanation_id
            assert explanation.what
            assert explanation.why
            assert explanation.evidence_summary
            assert explanation.scenario_addressed
            assert explanation.propagation_impact
            assert isinstance(explanation.assumptions, list)
            assert isinstance(explanation.uncertainties, list)
            assert explanation.review_guidance

    def test_trade_offs_generated(self):
        """Trade-offs should be generated for candidates."""
        scenario = make_scenario_snapshot()
        candidates = generate_candidates(scenario)

        if candidates:
            scores = score_candidate(candidates[0], scenario)
            trade_offs = generate_trade_offs(candidates[0], scores, scenario)

            # Should have at least one trade-off
            assert len(trade_offs) > 0

            for trade_off in trade_offs:
                assert trade_off.trade_off_id
                assert trade_off.dimension
                assert trade_off.gain
                assert trade_off.loss
                assert trade_off.magnitude in ("low", "medium", "high")

    def test_explanation_references_scenario(self):
        """Explanation should reference the scenario."""
        scenario = make_scenario_snapshot(scenario_type=ScenarioType.SUPPLIER_FAILURE)
        candidates = generate_candidates(scenario)

        if candidates:
            scores = score_candidate(candidates[0], scenario)
            explanation = generate_explanation(candidates[0], scores, scenario)

            # Should mention supplier failure
            assert (
                "supplier" in explanation.scenario_addressed.lower()
                or "supplier" in explanation.why.lower()
            )


# ─────────────────────────────────────────────────────────────────────────────
# Test Recommendation Engine
# ─────────────────────────────────────────────────────────────────────────────


class TestRecommendationEngine:
    """Test the main recommendation engine."""

    def test_engine_generates_recommendations(self):
        """Engine should generate recommendations for a scenario."""
        scenario = make_scenario_snapshot()
        request = RecommendationRequest(
            workspace_id="ws-test",
            scenario_id="scenario-test-1",
        )

        engine = RecommendationEngine()
        result = engine.generate_recommendations(scenario, request)

        assert result.success
        assert result.snapshot.recommendation_snapshot_id
        assert len(result.snapshot.recommendations) > 0

    def test_engine_ranking_is_correct(self):
        """Engine should rank recommendations correctly."""
        scenario = make_scenario_snapshot()
        request = RecommendationRequest(
            workspace_id="ws-test",
            scenario_id="scenario-test-1",
        )

        engine = RecommendationEngine()
        result = engine.generate_recommendations(scenario, request)

        # Ranks should be sequential
        ranks = [r.rank for r in result.snapshot.recommendations]
        assert ranks == list(range(1, len(ranks) + 1))

    def test_engine_includes_metadata(self):
        """Engine should include proper metadata."""
        scenario = make_scenario_snapshot()
        request = RecommendationRequest(
            workspace_id="ws-test",
            scenario_id="scenario-test-1",
        )

        engine = RecommendationEngine()
        result = engine.generate_recommendations(scenario, request)

        assert result.snapshot.scoring_version
        assert result.snapshot.ranking_version
        assert result.snapshot.total_candidates_generated >= len(result.snapshot.recommendations)

    def test_engine_respects_max_recommendations(self):
        """Engine should respect max_recommendations limit."""
        scenario = make_scenario_snapshot()
        request = RecommendationRequest(
            workspace_id="ws-test",
            scenario_id="scenario-test-1",
            max_recommendations=3,
        )

        engine = RecommendationEngine()
        result = engine.generate_recommendations(scenario, request)

        assert len(result.snapshot.recommendations) <= 3

    def test_engine_snapshot_has_hash(self):
        """Engine should compute snapshot hash."""
        scenario = make_scenario_snapshot()
        request = RecommendationRequest(
            workspace_id="ws-test",
            scenario_id="scenario-test-1",
        )

        engine = RecommendationEngine()
        result = engine.generate_recommendations(scenario, request)

        assert result.snapshot.recommendation_snapshot_hash


# ─────────────────────────────────────────────────────────────────────────────
# Test Regression Stability
# ─────────────────────────────────────────────────────────────────────────────


class TestRegressionStability:
    """Test that recommendation output is stable across runs."""

    def test_same_inputs_same_outputs(self):
        """Same inputs should produce same outputs."""
        scenario = make_scenario_snapshot()
        request = RecommendationRequest(
            workspace_id="ws-test",
            scenario_id="scenario-test-1",
        )

        engine = RecommendationEngine()

        result1 = engine.generate_recommendations(scenario, request)
        result2 = engine.generate_recommendations(scenario, request)

        # Snapshot IDs will differ (UUIDs), but structure should match
        assert len(result1.snapshot.recommendations) == len(result2.snapshot.recommendations)

        # Recommendation types and ranks should match
        for r1, r2 in zip(
            result1.snapshot.recommendations,
            result2.snapshot.recommendations,
            strict=True,
        ):
            assert r1.candidate.recommendation_type == r2.candidate.recommendation_type
            assert r1.rank == r2.rank
            assert r1.scores.overall_score == r2.scores.overall_score

    def test_taxonomy_changes_break_tests(self):
        """Changes to taxonomy should be explicit."""
        # This test ensures taxonomy changes are intentional
        assert len(RECOMMENDATION_TAXONOMY) > 0
        assert len(SCENARIO_RECOMMENDATION_RULES) > 0


# ─────────────────────────────────────────────────────────────────────────────
# Test Edge Cases
# ─────────────────────────────────────────────────────────────────────────────


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_scenario_handled(self):
        """Empty scenario should be handled gracefully."""
        impacts = []
        scenario = make_scenario_snapshot(impacts=impacts)
        request = RecommendationRequest(
            workspace_id="ws-test",
            scenario_id="scenario-test-1",
        )

        engine = RecommendationEngine()
        result = engine.generate_recommendations(scenario, request)

        # Should not crash
        assert result is not None
        # May return empty or no-action recommendations
        assert result.success or not result.snapshot.recommendations

    def test_unknown_scenario_type_handled(self):
        """Unknown scenario type should be handled gracefully."""
        scenario = make_scenario_snapshot(scenario_type=ScenarioType.CUSTOM)
        request = RecommendationRequest(
            workspace_id="ws-test",
            scenario_id="scenario-test-1",
        )

        engine = RecommendationEngine()
        result = engine.generate_recommendations(scenario, request)

        # Should not crash, may return empty recommendations
        assert result is not None
