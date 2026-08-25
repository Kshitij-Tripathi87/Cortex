"""Decision Repository — append-only persistence for decision memory.

This module provides database-backed storage for decision records, outcomes,
and lessons learned. All operations are append-only — no overwrites, no deletes.

Design principles:
  - Append-only: decisions are never modified
  - Workspace-scoped: all queries filtered by workspace_id
  - Traceable: every record links to upstream reasoning
  - Auditable: full history preserved
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.common.ids import uuid7
from app.infrastructure.database import Base


class DecisionRecordDB(Base):
    """Database model for decision records.

    Append-only: once created, records are never modified.
    """

    __tablename__ = "decision_records"

    decision_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    scenario_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    recommendation_snapshot_id: Mapped[str] = mapped_column(String(36), nullable=False)
    selected_recommendation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # Decision details
    decision_type: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    reviewer_id: Mapped[str] = mapped_column(String(36), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    modification_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Provenance
    source_propagation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_signal_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    evidence_claim_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    graph_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    context_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    feature_snapshot_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scenario_snapshot_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recommendation_snapshot_version: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Metadata
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, name="metadata"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class DecisionOutcomeDB(Base):
    """Database model for decision outcomes.

    Append-only: multiple outcomes can be recorded per decision.
    """

    __tablename__ = "decision_outcomes"

    outcome_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    decision_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    # Outcome details
    outcome_status: Mapped[str] = mapped_column(String(32), nullable=False)
    outcome_summary: Mapped[str] = mapped_column(Text, nullable=False)
    actual_impact_description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Quantitative measures
    actual_financial_impact: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_recovery_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_service_level_impact_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Assessment
    met_expectations: Mapped[bool | None] = mapped_column(nullable=True)
    would_decide_again: Mapped[bool | None] = mapped_column(nullable=True)

    # Provenance
    outcome_recorded_by: Mapped[str] = mapped_column(String(36), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, name="metadata"
    )


class DecisionLessonDB(Base):
    """Database model for lessons learned.

    Append-only: multiple lessons can be recorded per decision.
    """

    __tablename__ = "decision_lessons"

    lesson_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    decision_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    outcome_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    # Lesson details
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Structured fields
    what_happened: Mapped[str] = mapped_column(Text, nullable=False)
    what_expected: Mapped[str] = mapped_column(Text, nullable=False)
    what_learned: Mapped[str] = mapped_column(Text, nullable=False)
    policy_or_assumption_wrong: Mapped[str | None] = mapped_column(Text, nullable=True)
    what_to_change_next_time: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Export flag
    should_export_for_training: Mapped[bool] = mapped_column(nullable=False, default=False)

    # Provenance
    recorded_by: Mapped[str] = mapped_column(String(36), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, name="metadata"
    )
