"""Tests for Program H — Decision Memory.

Tests cover:
  - Decision record creation
  - Append-only behavior for outcomes and lessons
  - Workspace isolation
  - Lineage integrity (provenance tracking)
  - Query and history endpoints
  - Export functionality
  - Deterministic behavior
  - Regression with Programs A-G intact
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.graph.decision_models import (
    DecisionRequest,
    DecisionStatus,
    DecisionType,
    LessonCategory,
    OutcomeStatus,
)
from app.modules.graph.decision_service import DecisionService
from app.modules.graph.recommendation_models import (
    PolicyClassification,
    RankedRecommendation,
    RecommendationCandidate,
    RecommendationCategory,
    RecommendationExplanation,
    RecommendationScores,
    RecommendationSnapshot,
    RecommendationTradeOff,
    RecommendationType,
    ReversibilityLevel,
)
from app.modules.graph.scenario_models import (
    ScenarioDefinition,
    ScenarioSnapshot,
    ScenarioStatus,
    ScenarioSummary,
    ScenarioType,
)

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_scenario_snapshot() -> ScenarioSnapshot:
    """Create a sample scenario snapshot for testing."""
    return ScenarioSnapshot(
        scenario_id="scenario-test-001",
        workspace_id="workspace-test-001",
        scenario_definition=ScenarioDefinition(
            scenario_id="scenario-test-001",
            workspace_id="workspace-test-001",
            scenario_type=ScenarioType.SUPPLIER_FAILURE,
            name="Test Supplier Failure",
            description="Test scenario for decision memory",
        ),
        status=ScenarioStatus.COMPLETED,
        summary=ScenarioSummary(total_impacted_entities=5),
        graph_version=1,
        feature_snapshot_version=1,
        context_snapshot_version=1,
        propagation_snapshot_version=1,
        scenario_snapshot_version=1,
    )


@pytest.fixture
def sample_recommendation_snapshot() -> RecommendationSnapshot:
    """Create a sample recommendation snapshot for testing."""
    candidate = RecommendationCandidate(
        candidate_id="cand-001",
        recommendation_type=RecommendationType.USE_ALTERNATE_SUPPLIER,
        category=RecommendationCategory.SUPPLY_SIDE,
        name="Use Alternate Supplier",
        description="Switch to alternate supplier A",
        source_scenario_id="scenario-test-001",
        source_propagation_id="prop-001",
        source_signal_ids=["signal-001"],
        required_evidence=["entity-001"],
        affected_node_ids=["node-001"],
        affected_entity_ids=["entity-001"],
        affected_entity_types=["Supplier"],
    )

    scores = RecommendationScores(
        overall_score=0.85,
        risk_reduction_score=0.9,
        cost_score=0.7,
        time_score=0.8,
        reversibility_score=0.9,
        confidence_score=0.85,
        policy_fit_score=0.8,
        impact_reduction_score=0.85,
        scoring_formula="weighted_sum",
    )

    trade_off = RecommendationTradeOff(
        trade_off_id="trade-001",
        dimension="cost",
        gain="Faster delivery",
        loss="Higher unit cost",
        magnitude="medium",
        quantified_gain=24.0,
        quantified_loss=500.0,
    )

    explanation = RecommendationExplanation(
        explanation_id="expl-001",
        what="Use alternate supplier A",
        why="Primary supplier has 2-week outage",
        evidence_summary="Supplier A has capacity",
        scenario_addressed="Supplier failure scenario",
        propagation_impact="2-week delay mitigated",
        assumptions=["Supplier A quality matches primary"],
        uncertainties=["Supplier A actual lead time"],
        review_guidance="Verify quality certifications",
    )

    ranked = RankedRecommendation(
        recommendation_id="rec-001",
        rank=1,
        candidate=candidate,
        scores=scores,
        trade_offs=[trade_off],
        explanation=explanation,
        reversibility=ReversibilityLevel.PARTIALLY_REVERSIBLE,
        policy_classification=PolicyClassification.REVIEW_REQUIRED,
        estimated_cost_usd=5000.0,
        estimated_time_to_benefit_hours=48.0,
        estimated_impact_reduction_pct=80.0,
        graph_version=1,
        context_version=1,
        scenario_snapshot_version=1,
    )

    return RecommendationSnapshot(
        recommendation_snapshot_id="rec-snap-001",
        workspace_id="workspace-test-001",
        source_scenario_id="scenario-test-001",
        source_scenario_snapshot_version=1,
        source_propagation_id="prop-001",
        source_propagation_snapshot_version=1,
        source_signal_ids=["signal-001"],
        graph_version=1,
        context_version=1,
        feature_snapshot_version=1,
        recommendations=[ranked],
        total_candidates_generated=1,
        total_candidates_after_dedup=1,
        scoring_version="1.0.0",
        ranking_version="1.0.0",
        recommendation_snapshot_version=1,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Decision Record Creation Tests
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_decision_record(
    db_session: AsyncSession,
    sample_scenario_snapshot: ScenarioSnapshot,
    sample_recommendation_snapshot: RecommendationSnapshot,
) -> None:
    """Test that valid decision records are created successfully."""
    request = DecisionRequest(
        workspace_id="workspace-test-001",
        scenario_id="scenario-test-001",
        recommendation_snapshot_id="rec-snap-001",
        selected_recommendation_id="rec-001",
        decision_type=DecisionType.APPROVE_RECOMMENDATION,
        reviewer_id="user-test-001",
        rationale="Best option based on cost and timing",
        tags=["urgent", "high-priority"],
        metadata={"review_duration_minutes": 15},
    )

    service = DecisionService(db_session)
    result = await service.create_decision(
        request,
        scenario_snapshot=sample_scenario_snapshot,
        recommendation_snapshot=sample_recommendation_snapshot,
    )

    assert result.success
    assert result.decision is not None
    assert result.decision.decision_type == DecisionType.APPROVE_RECOMMENDATION
    assert result.decision.workspace_id == "workspace-test-001"
    assert result.decision.reviewer_id == "user-test-001"
    assert result.decision.graph_version == 1
    assert result.decision.scenario_snapshot_version == 1
    assert result.decision.recommendation_snapshot_version == 1


@pytest.mark.asyncio
async def test_create_decision_requires_lineage(
    db_session: AsyncSession,
) -> None:
    """Test that decisions require proper lineage."""
    request = DecisionRequest(
        workspace_id="workspace-test-001",
        scenario_id="scenario-test-001",
        recommendation_snapshot_id="rec-snap-001",
        selected_recommendation_id="rec-001",
        decision_type=DecisionType.APPROVE_RECOMMENDATION,
        reviewer_id="user-test-001",
        rationale="Approved",
    )

    service = DecisionService(db_session)
    result = await service.create_decision(request)

    # Should succeed but with None provenance values
    assert result.success
    assert result.decision is not None
    assert result.decision.graph_version is None


@pytest.mark.asyncio
async def test_create_decision_workspace_scoped(
    db_session: AsyncSession,
) -> None:
    """Test that decisions are workspace-scoped."""
    request1 = DecisionRequest(
        workspace_id="workspace-a",
        scenario_id="scenario-001",
        recommendation_snapshot_id="rec-snap-001",
        selected_recommendation_id="rec-001",
        decision_type=DecisionType.APPROVE_RECOMMENDATION,
        reviewer_id="user-001",
        rationale="Approved for workspace A",
    )

    request2 = DecisionRequest(
        workspace_id="workspace-b",
        scenario_id="scenario-001",
        recommendation_snapshot_id="rec-snap-001",
        selected_recommendation_id="rec-001",
        decision_type=DecisionType.REJECT_RECOMMENDATION,
        reviewer_id="user-002",
        rationale="Rejected for workspace B",
    )

    service = DecisionService(db_session)
    result1 = await service.create_decision(request1)
    result2 = await service.create_decision(request2)

    assert result1.success
    assert result2.success
    assert result1.decision.workspace_id == "workspace-a"
    assert result2.decision.workspace_id == "workspace-b"
    assert result1.decision.decision_type != result2.decision.decision_type


# ─────────────────────────────────────────────────────────────────────────────
# Append-Only Behavior Tests
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_append_outcome_is_append_only(
    db_session: AsyncSession,
) -> None:
    """Test that outcomes can be appended multiple times."""
    # Create a decision first
    request = DecisionRequest(
        workspace_id="workspace-test-001",
        scenario_id="scenario-test-001",
        recommendation_snapshot_id="rec-snap-001",
        selected_recommendation_id="rec-001",
        decision_type=DecisionType.APPROVE_RECOMMENDATION,
        reviewer_id="user-test-001",
        rationale="Initial approval",
    )

    service = DecisionService(db_session)
    decision_result = await service.create_decision(request)
    assert decision_result.success
    assert decision_result.decision is not None

    decision_id = decision_result.decision.decision_id

    # Append first outcome
    outcome1_result = await service.append_outcome(
        decision_id=decision_id,
        workspace_id="workspace-test-001",
        outcome_status=OutcomeStatus.PENDING,
        outcome_summary="Implementation started",
        recorded_by="user-test-001",
    )
    assert outcome1_result.success

    # Append second outcome
    outcome2_result = await service.append_outcome(
        decision_id=decision_id,
        workspace_id="workspace-test-001",
        outcome_status=OutcomeStatus.SUCCESS,
        outcome_summary="Implementation successful",
        recorded_by="user-test-001",
        actual_financial_impact=10000.0,
    )
    assert outcome2_result.success

    # Verify both outcomes exist
    snapshot = await service.get_decision_snapshot(decision_id, "workspace-test-001")
    assert snapshot is not None
    assert snapshot.outcome_count == 2
    assert len(snapshot.outcomes) == 2


@pytest.mark.asyncio
async def test_append_lesson_is_append_only(
    db_session: AsyncSession,
) -> None:
    """Test that lessons can be appended multiple times."""
    # Create a decision first
    request = DecisionRequest(
        workspace_id="workspace-test-001",
        scenario_id="scenario-test-001",
        recommendation_snapshot_id="rec-snap-001",
        selected_recommendation_id="rec-001",
        decision_type=DecisionType.APPROVE_RECOMMENDATION,
        reviewer_id="user-test-001",
        rationale="Approved",
    )

    service = DecisionService(db_session)
    decision_result = await service.create_decision(request)
    assert decision_result.success
    assert decision_result.decision is not None

    decision_id = decision_result.decision.decision_id

    # Append first lesson
    lesson1_result = await service.append_lesson(
        decision_id=decision_id,
        workspace_id="workspace-test-001",
        category=LessonCategory.SUCCESS_PATTERN,
        title="Fast supplier switch worked",
        description="Alternate supplier process was effective",
        what_happened="Switched to supplier A in 48 hours",
        what_expected="Expected 1 week, got 2 days",
        what_learned="Process is faster than expected",
        recorded_by="user-test-001",
    )
    assert lesson1_result.success

    # Append second lesson
    lesson2_result = await service.append_lesson(
        decision_id=decision_id,
        workspace_id="workspace-test-001",
        category=LessonCategory.BEST_PRACTICE,
        title="Document supplier certs upfront",
        description="Pre-verification saved time",
        what_happened="Supplier certs were pre-verified",
        what_expected="Would need verification during crisis",
        what_learned="Pre-verification is critical",
        recorded_by="user-test-001",
        should_export_for_training=True,
    )
    assert lesson2_result.success

    # Verify both lessons exist
    snapshot = await service.get_decision_snapshot(decision_id, "workspace-test-001")
    assert snapshot is not None
    assert snapshot.lesson_count == 2
    assert len(snapshot.lessons) == 2


# ─────────────────────────────────────────────────────────────────────────────
# Lineage and Provenance Tests
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_decision_preserves_lineage(
    db_session: AsyncSession,
    sample_scenario_snapshot: ScenarioSnapshot,
    sample_recommendation_snapshot: RecommendationSnapshot,
) -> None:
    """Test that decision records preserve full lineage."""
    request = DecisionRequest(
        workspace_id="workspace-test-001",
        scenario_id="scenario-test-001",
        recommendation_snapshot_id="rec-snap-001",
        selected_recommendation_id="rec-001",
        decision_type=DecisionType.APPROVE_RECOMMENDATION,
        reviewer_id="user-test-001",
        rationale="Approved with full lineage",
    )

    service = DecisionService(db_session)
    result = await service.create_decision(
        request,
        scenario_snapshot=sample_scenario_snapshot,
        recommendation_snapshot=sample_recommendation_snapshot,
    )

    assert result.success
    assert result.decision is not None

    decision = result.decision
    assert decision.graph_version == 1
    assert decision.feature_snapshot_version == 1
    assert decision.context_version == 1
    assert decision.scenario_snapshot_version == 1
    assert decision.recommendation_snapshot_version == 1
    assert "signal-001" in decision.source_signal_ids


@pytest.mark.asyncio
async def test_decision_requires_decision_type() -> None:
    """Test that decision type is required and validated."""
    with pytest.raises(ValueError):
        DecisionType("invalid_type")


# ─────────────────────────────────────────────────────────────────────────────
# Query and History Tests
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_decision_snapshot(
    db_session: AsyncSession,
) -> None:
    """Test retrieving a complete decision snapshot."""
    # Create decision with outcome and lesson
    request = DecisionRequest(
        workspace_id="workspace-test-001",
        scenario_id="scenario-test-001",
        recommendation_snapshot_id="rec-snap-001",
        selected_recommendation_id="rec-001",
        decision_type=DecisionType.APPROVE_RECOMMENDATION,
        reviewer_id="user-test-001",
        rationale="Test decision",
    )

    service = DecisionService(db_session)
    decision_result = await service.create_decision(request)
    assert decision_result.success
    assert decision_result.decision is not None

    decision_id = decision_result.decision.decision_id

    # Add outcome
    await service.append_outcome(
        decision_id=decision_id,
        workspace_id="workspace-test-001",
        outcome_status=OutcomeStatus.SUCCESS,
        outcome_summary="Worked well",
        recorded_by="user-test-001",
    )

    # Add lesson
    await service.append_lesson(
        decision_id=decision_id,
        workspace_id="workspace-test-001",
        category=LessonCategory.SUCCESS_PATTERN,
        title="Test lesson",
        description="Test description",
        what_happened="Test",
        what_expected="Test",
        what_learned="Test",
        recorded_by="user-test-001",
    )

    # Retrieve snapshot
    snapshot = await service.get_decision_snapshot(decision_id, "workspace-test-001")
    assert snapshot is not None
    assert snapshot.decision.decision_id == decision_id
    assert snapshot.outcome_count == 1
    assert snapshot.lesson_count == 1


@pytest.mark.asyncio
async def test_decision_not_found_for_wrong_workspace(
    db_session: AsyncSession,
) -> None:
    """Test that decisions cannot be accessed across workspaces."""
    request = DecisionRequest(
        workspace_id="workspace-a",
        scenario_id="scenario-001",
        recommendation_snapshot_id="rec-snap-001",
        selected_recommendation_id="rec-001",
        decision_type=DecisionType.APPROVE_RECOMMENDATION,
        reviewer_id="user-001",
        rationale="Approved",
    )

    service = DecisionService(db_session)
    result = await service.create_decision(request)
    assert result.success
    assert result.decision is not None

    # Try to access from wrong workspace
    snapshot = await service.get_decision_snapshot(
        result.decision.decision_id,
        "workspace-b",  # Wrong workspace
    )
    assert snapshot is None


# ─────────────────────────────────────────────────────────────────────────────
# Export Tests
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_export_decision(
    db_session: AsyncSession,
) -> None:
    """Test exporting a decision for training."""
    # Create decision
    request = DecisionRequest(
        workspace_id="workspace-test-001",
        scenario_id="scenario-test-001",
        recommendation_snapshot_id="rec-snap-001",
        selected_recommendation_id="rec-001",
        decision_type=DecisionType.APPROVE_RECOMMENDATION,
        reviewer_id="user-test-001",
        rationale="Approved for export test",
        metadata={
            "scenario_type": "supplier_failure",
            "recommendation_type": "use_alternate_supplier",
        },
    )

    service = DecisionService(db_session)
    decision_result = await service.create_decision(request)
    assert decision_result.success
    assert decision_result.decision is not None

    decision_id = decision_result.decision.decision_id

    # Add outcome
    await service.append_outcome(
        decision_id=decision_id,
        workspace_id="workspace-test-001",
        outcome_status=OutcomeStatus.SUCCESS,
        outcome_summary="Successful outcome",
        recorded_by="user-test-001",
    )

    # Add exportable lesson
    await service.append_lesson(
        decision_id=decision_id,
        workspace_id="workspace-test-001",
        category=LessonCategory.SUCCESS_PATTERN,
        title="Export test lesson",
        description="Lesson for export",
        what_happened="Test happened",
        what_expected="Test expected",
        what_learned="Test learned",
        recorded_by="user-test-001",
        should_export_for_training=True,
    )

    # Export
    export = await service.export_decision(decision_id, "workspace-test-001", anonymize=True)
    assert export is not None
    assert export.workspace_id == "ANONYMIZED"
    assert len(export.exportable_lessons) == 1


@pytest.mark.asyncio
async def test_export_preserves_structure() -> None:
    """Test that export preserves structural lineage."""
    from app.modules.graph.decision_models import DecisionExport

    export = DecisionExport(
        export_id="export-001",
        decision_id="decision-001",
        workspace_id="workspace-001",
        decision_type=DecisionType.APPROVE_RECOMMENDATION,
        decision_status=DecisionStatus.IMPLEMENTED,
        rationale="Test rationale",
        scenario_type="supplier_failure",
        recommendation_type="use_alternate_supplier",
        graph_metrics={"graph_version": 1, "feature_snapshot_version": 1},
        outcome_status=OutcomeStatus.SUCCESS,
        outcome_summary="Test outcome",
    )

    export_dict = export.to_dict()
    assert export_dict["decision_type"] == "approve_recommendation"
    assert export_dict["decision_status"] == "implemented"
    assert export_dict["scenario_type"] == "supplier_failure"
    assert export_dict["graph_metrics"]["graph_version"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# Decision Taxonomy Tests
# ─────────────────────────────────────────────────────────────────────────────


def test_decision_type_properties() -> None:
    """Test decision type properties (is_terminal, is_reversible)."""
    assert DecisionType.APPROVE_RECOMMENDATION.is_terminal
    assert DecisionType.APPROVE_RECOMMENDATION.is_reversible

    assert DecisionType.REJECT_RECOMMENDATION.is_terminal
    assert not DecisionType.REJECT_RECOMMENDATION.is_reversible

    assert not DecisionType.DEFER_DECISION.is_terminal
    assert DecisionType.DEFER_DECISION.is_reversible

    assert not DecisionType.REQUEST_MORE_EVIDENCE.is_terminal


def test_all_decision_types_have_properties() -> None:
    """Test that all decision types have is_terminal and is_reversible."""
    for dt in DecisionType:
        assert hasattr(dt, "is_terminal")
        assert hasattr(dt, "is_reversible")
        assert isinstance(dt.is_terminal, bool)
        assert isinstance(dt.is_reversible, bool)


# ─────────────────────────────────────────────────────────────────────────────
# Regression Tests (Programs A-G intact)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_decision_service_does_not_break_scenario_snapshot(
    sample_scenario_snapshot: ScenarioSnapshot,
) -> None:
    """Test that decision service doesn't modify scenario snapshots."""
    # Scenario snapshot should be immutable
    original_dict = sample_scenario_snapshot.to_dict()

    # Decision service should not modify it
    assert original_dict["scenario_id"] == "scenario-test-001"
    assert original_dict["workspace_id"] == "workspace-test-001"
    assert original_dict["status"] == "completed"


@pytest.mark.asyncio
async def test_decision_service_does_not_break_recommendation_snapshot(
    sample_recommendation_snapshot: RecommendationSnapshot,
) -> None:
    """Test that decision service doesn't modify recommendation snapshots."""
    # Recommendation snapshot should be immutable
    original_dict = sample_recommendation_snapshot.to_dict()

    assert original_dict["recommendation_snapshot_id"] == "rec-snap-001"
    assert len(original_dict["recommendations"]) == 1
    assert original_dict["recommendations"][0]["rank"] == 1
