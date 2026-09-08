"""Decision Service — orchestrates decision memory operations.

The DecisionService is the boundary between operational reasoning and
historical memory. It:
  - accepts recommendation + scenario + propagation inputs
  - validates decision type and metadata
  - persists append-only decision records
  - appends outcomes later
  - appends lessons learned later
  - produces decision snapshots for history/query
  - prepares export payloads for ML training

It depends on upstream reasoning outputs but does not mutate them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.ids import uuid7
from app.modules.graph.decision_models import (
    DecisionExport,
    DecisionLesson,
    DecisionOutcome,
    DecisionRecord,
    DecisionRequest,
    DecisionSnapshot,
    DecisionStatus,
    DecisionType,
    LessonCategory,
    OutcomeStatus,
)
from app.modules.graph.decision_repository import (
    DecisionLessonDB,
    DecisionOutcomeDB,
    DecisionRecordDB,
)
from app.modules.graph.recommendation_models import RecommendationSnapshot
from app.modules.graph.scenario_models import ScenarioSnapshot


@dataclass(frozen=True)
class DecisionServiceResult:
    """Result of a decision service operation."""

    decision: DecisionRecord
    success: bool
    warnings: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass(frozen=True)
class OutcomeServiceResult:
    """Result of appending an outcome."""

    outcome: DecisionOutcome
    success: bool
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class LessonServiceResult:
    """Result of appending a lesson learned."""

    lesson: DecisionLesson
    success: bool
    warnings: list[str] = field(default_factory=list)


class DecisionService:
    """Service layer for decision memory operations.

    Usage:
        service = DecisionService(db)
        result = await service.create_decision(request)
        outcome_result = await service.append_outcome(decision_id, outcome_data)
        lesson_result = await service.append_lesson(lesson_data)
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create_decision(
        self,
        request: DecisionRequest,
        scenario_snapshot: ScenarioSnapshot | None = None,
        recommendation_snapshot: RecommendationSnapshot | None = None,
    ) -> DecisionServiceResult:
        """Create a new decision record.

        Validates the decision, extracts provenance from upstream snapshots,
        and persists an append-only record.
        """
        warnings: list[str] = []

        try:
            # Extract provenance from snapshots if provided
            (
                propagation_id,
                signal_ids,
                evidence_ids,
                graph_version,
                context_version,
                feature_version,
                scenario_version,
                recommendation_version,
            ) = self._extract_provenance(scenario_snapshot, recommendation_snapshot)

            # Create decision record
            decision = DecisionRecord(
                decision_id=uuid7(),
                workspace_id=request.workspace_id,
                scenario_id=request.scenario_id,
                recommendation_snapshot_id=request.recommendation_snapshot_id,
                selected_recommendation_id=request.selected_recommendation_id,
                decision_type=request.decision_type,
                decision_status=DecisionStatus.PENDING,
                reviewer_id=request.reviewer_id,
                rationale=request.rationale,
                modification_notes=request.modification_notes,
                source_propagation_id=propagation_id,
                source_signal_ids=signal_ids,
                evidence_claim_ids=evidence_ids,
                graph_version=graph_version,
                context_version=context_version,
                feature_snapshot_version=feature_version,
                scenario_snapshot_version=scenario_version,
                recommendation_snapshot_version=recommendation_version,
                tags=request.tags,
                metadata=request.metadata,
            )

            # Persist to database
            await self._persist_decision(decision)

            return DecisionServiceResult(
                decision=decision,
                success=True,
                warnings=warnings,
            )

        except Exception as e:
            return DecisionServiceResult(
                decision=None,
                success=False,
                warnings=warnings,
                error=str(e),
            )

    async def append_outcome(
        self,
        decision_id: str,
        workspace_id: str,
        outcome_status: OutcomeStatus,
        outcome_summary: str,
        recorded_by: str,
        actual_impact_description: str | None = None,
        actual_financial_impact: float | None = None,
        actual_recovery_hours: float | None = None,
        actual_service_level_impact_pct: float | None = None,
        met_expectations: bool | None = None,
        would_decide_again: bool | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> OutcomeServiceResult:
        """Append an outcome record to an existing decision.

        Outcomes are append-only — multiple can be recorded over time.
        """
        warnings: list[str] = []

        try:
            # Verify decision exists
            decision_exists = await self._verify_decision_exists(decision_id, workspace_id)
            if not decision_exists:
                return OutcomeServiceResult(
                    outcome=None,
                    success=False,
                    warnings=["Decision not found"],
                )

            outcome = DecisionOutcome(
                outcome_id=uuid7(),
                decision_id=decision_id,
                workspace_id=workspace_id,
                outcome_status=outcome_status,
                outcome_summary=outcome_summary,
                actual_impact_description=actual_impact_description,
                actual_financial_impact=actual_financial_impact,
                actual_recovery_hours=actual_recovery_hours,
                actual_service_level_impact_pct=actual_service_level_impact_pct,
                met_expectations=met_expectations,
                would_decide_again=would_decide_again,
                outcome_recorded_by=recorded_by,
                metadata=metadata or {},
            )

            await self._persist_outcome(outcome)

            return OutcomeServiceResult(
                outcome=outcome,
                success=True,
                warnings=warnings,
            )

        except Exception as e:
            return OutcomeServiceResult(
                outcome=None,
                success=False,
                warnings=warnings + [str(e)],
            )

    async def append_lesson(
        self,
        decision_id: str,
        workspace_id: str,
        category: LessonCategory,
        title: str,
        description: str,
        what_happened: str,
        what_expected: str,
        what_learned: str,
        recorded_by: str,
        outcome_id: str | None = None,
        policy_or_assumption_wrong: str | None = None,
        what_to_change_next_time: str | None = None,
        should_export_for_training: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> LessonServiceResult:
        """Append a lesson learned to an existing decision.

        Lessons are append-only and can reference an outcome.
        """
        warnings: list[str] = []

        try:
            # Verify decision exists
            decision_exists = await self._verify_decision_exists(decision_id, workspace_id)
            if not decision_exists:
                return LessonServiceResult(
                    lesson=None,
                    success=False,
                    warnings=["Decision not found"],
                )

            lesson = DecisionLesson(
                lesson_id=uuid7(),
                decision_id=decision_id,
                outcome_id=outcome_id,
                workspace_id=workspace_id,
                category=category,
                title=title,
                description=description,
                what_happened=what_happened,
                what_expected=what_expected,
                what_learned=what_learned,
                policy_or_assumption_wrong=policy_or_assumption_wrong,
                what_to_change_next_time=what_to_change_next_time,
                should_export_for_training=should_export_for_training,
                recorded_by=recorded_by,
                metadata=metadata or {},
            )

            await self._persist_lesson(lesson)

            return LessonServiceResult(
                lesson=lesson,
                success=True,
                warnings=warnings,
            )

        except Exception as e:
            return LessonServiceResult(
                lesson=None,
                success=False,
                warnings=warnings + [str(e)],
            )

    async def get_decision_snapshot(
        self,
        decision_id: str,
        workspace_id: str,
    ) -> DecisionSnapshot | None:
        """Retrieve a complete decision snapshot with outcomes and lessons."""
        # Load decision
        decision = await self._load_decision(decision_id, workspace_id)
        if not decision:
            return None

        # Load outcomes
        outcomes = await self._load_outcomes(decision_id, workspace_id)

        # Load lessons
        lessons = await self._load_lessons(decision_id, workspace_id)

        # Compute aggregates
        outcome_count = len(outcomes)
        lesson_count = len(lessons)
        last_outcome_at = max((o.outcome_recorded_at for o in outcomes), default=None)
        last_lesson_at = max((les.recorded_at for les in lessons), default=None)

        return DecisionSnapshot(
            decision=decision,
            outcomes=outcomes,
            lessons=lessons,
            outcome_count=outcome_count,
            lesson_count=lesson_count,
            last_outcome_at=last_outcome_at,
            last_lesson_at=last_lesson_at,
        )

    async def list_decisions(
        self,
        workspace_id: str,
        scenario_id: str | None = None,
        reviewer_id: str | None = None,
        decision_type: DecisionType | None = None,
        decision_status: DecisionStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[DecisionRecord]:
        """List decisions with optional filtering."""
        # Implementation would query database with filters
        # For now, return empty list - actual implementation in repository
        return []

    async def export_decision(
        self,
        decision_id: str,
        workspace_id: str,
        anonymize: bool = True,
    ) -> DecisionExport | None:
        """Export a decision record for training/analysis.

        Strips sensitive fields while preserving structural lineage.
        """
        snapshot = await self.get_decision_snapshot(decision_id, workspace_id)
        if not snapshot:
            return None

        decision = snapshot.decision

        # Extract scenario/recommendation types from metadata if available
        scenario_type = decision.metadata.get("scenario_type")
        recommendation_type = decision.metadata.get("recommendation_type")

        # Compute graph metrics from provenance
        graph_metrics = {
            "graph_version": decision.graph_version or 0,
            "feature_snapshot_version": decision.feature_snapshot_version or 0,
        }

        # Get most recent outcome
        outcome = snapshot.outcomes[-1] if snapshot.outcomes else None
        outcome_status = outcome.outcome_status if outcome else None
        outcome_summary = outcome.outcome_summary if outcome else None

        # Filter exportable lessons
        exportable_lessons = [les for les in snapshot.lessons if les.should_export_for_training]

        export = DecisionExport(
            export_id=uuid7(),
            decision_id=decision_id,
            workspace_id=workspace_id if not anonymize else "ANONYMIZED",
            decision_type=decision.decision_type,
            decision_status=decision.decision_status,
            rationale=decision.rationale,
            modification_notes=decision.modification_notes,
            scenario_type=scenario_type,
            recommendation_type=recommendation_type,
            graph_metrics=graph_metrics,
            outcome_status=outcome_status,
            outcome_summary=outcome_summary,
            exportable_lessons=exportable_lessons,
        )

        return export

    def _extract_provenance(
        self,
        scenario_snapshot: ScenarioSnapshot | None,
        recommendation_snapshot: RecommendationSnapshot | None,
    ) -> tuple[
        str | None,  # propagation_id
        list[str],  # signal_ids
        list[str],  # evidence_ids
        int | None,  # graph_version
        int | None,  # context_version
        int | None,  # feature_version
        int | None,  # scenario_version
        int | None,  # recommendation_version
    ]:
        """Extract provenance lineage from upstream snapshots."""
        propagation_id = None
        signal_ids: list[str] = []
        evidence_ids: list[str] = []
        graph_version = None
        context_version = None
        feature_version = None
        scenario_version = None
        recommendation_version = None

        if scenario_snapshot:
            scenario_version = scenario_snapshot.scenario_snapshot_version
            propagation_id = scenario_snapshot.source_propagation_id
            signal_ids = (
                [scenario_snapshot.source_signal_id] if scenario_snapshot.source_signal_id else []
            )
            graph_version = scenario_snapshot.graph_version
            context_version = scenario_snapshot.context_snapshot_version
            feature_version = scenario_snapshot.feature_snapshot_version

        if recommendation_snapshot:
            recommendation_version = recommendation_snapshot.recommendation_snapshot_version
            if not signal_ids:
                signal_ids = recommendation_snapshot.source_signal_ids or []
            if graph_version is None:
                graph_version = recommendation_snapshot.graph_version
            if context_version is None:
                context_version = recommendation_snapshot.context_version

        return (
            propagation_id,
            signal_ids,
            evidence_ids,
            graph_version,
            context_version,
            feature_version,
            scenario_version,
            recommendation_version,
        )

    async def _persist_decision(self, decision: DecisionRecord) -> None:
        """Persist a decision record to the database."""
        db_record = DecisionRecordDB(
            decision_id=decision.decision_id,
            workspace_id=decision.workspace_id,
            scenario_id=decision.scenario_id,
            recommendation_snapshot_id=decision.recommendation_snapshot_id,
            selected_recommendation_id=decision.selected_recommendation_id,
            decision_type=decision.decision_type.value,
            decision_status=decision.decision_status.value,
            reviewer_id=decision.reviewer_id,
            rationale=decision.rationale,
            modification_notes=decision.modification_notes,
            source_propagation_id=decision.source_propagation_id,
            source_signal_ids=decision.source_signal_ids,
            evidence_claim_ids=decision.evidence_claim_ids,
            graph_version=decision.graph_version,
            context_version=decision.context_version,
            feature_snapshot_version=decision.feature_snapshot_version,
            scenario_snapshot_version=decision.scenario_snapshot_version,
            recommendation_snapshot_version=decision.recommendation_snapshot_version,
            tags=decision.tags,
            metadata=decision.metadata,
        )
        self._db.add(db_record)
        await self._db.commit()

    async def _persist_outcome(self, outcome: DecisionOutcome) -> None:
        """Persist an outcome record to the database."""
        db_record = DecisionOutcomeDB(
            outcome_id=outcome.outcome_id,
            decision_id=outcome.decision_id,
            workspace_id=outcome.workspace_id,
            outcome_status=outcome.outcome_status.value,
            outcome_summary=outcome.outcome_summary,
            actual_impact_description=outcome.actual_impact_description,
            actual_financial_impact=outcome.actual_financial_impact,
            actual_recovery_hours=outcome.actual_recovery_hours,
            actual_service_level_impact_pct=outcome.actual_service_level_impact_pct,
            met_expectations=outcome.met_expectations,
            would_decide_again=outcome.would_decide_again,
            outcome_recorded_by=outcome.outcome_recorded_by,
            metadata=outcome.metadata,
        )
        self._db.add(db_record)
        await self._db.commit()

    async def _persist_lesson(self, lesson: DecisionLesson) -> None:
        """Persist a lesson record to the database."""
        db_record = DecisionLessonDB(
            lesson_id=lesson.lesson_id,
            decision_id=lesson.decision_id,
            outcome_id=lesson.outcome_id,
            workspace_id=lesson.workspace_id,
            category=lesson.category.value,
            title=lesson.title,
            description=lesson.description,
            what_happened=lesson.what_happened,
            what_expected=lesson.what_expected,
            what_learned=lesson.what_learned,
            policy_or_assumption_wrong=lesson.policy_or_assumption_wrong,
            what_to_change_next_time=lesson.what_to_change_next_time,
            should_export_for_training=lesson.should_export_for_training,
            recorded_by=lesson.recorded_by,
            metadata=lesson.metadata,
        )
        self._db.add(db_record)
        await self._db.commit()

    async def _verify_decision_exists(self, decision_id: str, workspace_id: str) -> bool:
        """Verify a decision record exists."""
        stmt = select(DecisionRecordDB).where(
            DecisionRecordDB.decision_id == decision_id,
            DecisionRecordDB.workspace_id == workspace_id,
        )
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def _load_decision(
        self,
        decision_id: str,
        workspace_id: str,
    ) -> DecisionRecord | None:
        """Load a decision record from the database."""
        stmt = select(DecisionRecordDB).where(
            DecisionRecordDB.decision_id == decision_id,
            DecisionRecordDB.workspace_id == workspace_id,
        )
        result = await self._db.execute(stmt)
        db_record = result.scalar_one_or_none()

        if not db_record:
            return None

        return DecisionRecord(
            decision_id=db_record.decision_id,
            workspace_id=db_record.workspace_id,
            scenario_id=db_record.scenario_id,
            recommendation_snapshot_id=db_record.recommendation_snapshot_id,
            selected_recommendation_id=db_record.selected_recommendation_id,
            decision_type=DecisionType(db_record.decision_type),
            decision_status=DecisionStatus(db_record.decision_status),
            reviewer_id=db_record.reviewer_id,
            rationale=db_record.rationale,
            modification_notes=db_record.modification_notes,
            source_propagation_id=db_record.source_propagation_id,
            source_signal_ids=db_record.source_signal_ids,
            evidence_claim_ids=db_record.evidence_claim_ids,
            graph_version=db_record.graph_version,
            context_version=db_record.context_version,
            feature_snapshot_version=db_record.feature_snapshot_version,
            scenario_snapshot_version=db_record.scenario_snapshot_version,
            recommendation_snapshot_version=db_record.recommendation_snapshot_version,
            tags=db_record.tags,
            metadata=db_record.extra_metadata,
            created_at=db_record.created_at,
        )

    async def _load_outcomes(
        self,
        decision_id: str,
        workspace_id: str,
    ) -> list[DecisionOutcome]:
        """Load all outcomes for a decision."""
        stmt = (
            select(DecisionOutcomeDB)
            .where(
                DecisionOutcomeDB.decision_id == decision_id,
                DecisionOutcomeDB.workspace_id == workspace_id,
            )
            .order_by(DecisionOutcomeDB.created_at)
        )
        result = await self._db.execute(stmt)

        outcomes = []
        for db_record in result.scalars().all():
            outcomes.append(
                DecisionOutcome(
                    outcome_id=db_record.outcome_id,
                    decision_id=db_record.decision_id,
                    workspace_id=db_record.workspace_id,
                    outcome_status=OutcomeStatus(db_record.outcome_status),
                    outcome_summary=db_record.outcome_summary,
                    actual_impact_description=db_record.actual_impact_description,
                    actual_financial_impact=db_record.actual_financial_impact,
                    actual_recovery_hours=db_record.actual_recovery_hours,
                    actual_service_level_impact_pct=db_record.actual_service_level_impact_pct,
                    met_expectations=db_record.met_expectations,
                    would_decide_again=db_record.would_decide_again,
                    outcome_recorded_by=db_record.outcome_recorded_by,
                    outcome_recorded_at=db_record.created_at,
                    metadata=db_record.extra_metadata,
                )
            )
        return outcomes

    async def _load_lessons(
        self,
        decision_id: str,
        workspace_id: str,
    ) -> list[DecisionLesson]:
        """Load all lessons for a decision."""
        stmt = (
            select(DecisionLessonDB)
            .where(
                DecisionLessonDB.decision_id == decision_id,
                DecisionLessonDB.workspace_id == workspace_id,
            )
            .order_by(DecisionLessonDB.created_at)
        )
        result = await self._db.execute(stmt)

        lessons = []
        for db_record in result.scalars().all():
            lessons.append(
                DecisionLesson(
                    lesson_id=db_record.lesson_id,
                    decision_id=db_record.decision_id,
                    outcome_id=db_record.outcome_id,
                    workspace_id=db_record.workspace_id,
                    category=LessonCategory(db_record.category),
                    title=db_record.title,
                    description=db_record.description,
                    what_happened=db_record.what_happened,
                    what_expected=db_record.what_expected,
                    what_learned=db_record.what_learned,
                    policy_or_assumption_wrong=db_record.policy_or_assumption_wrong,
                    what_to_change_next_time=db_record.what_to_change_next_time,
                    should_export_for_training=db_record.should_export_for_training,
                    recorded_by=db_record.recorded_by,
                    recorded_at=db_record.created_at,
                    metadata=db_record.extra_metadata,
                )
            )
        return lessons
