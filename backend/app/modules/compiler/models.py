"""Compiler DB models — EvidenceClaim, EvidenceConflict, ConflictResolution, ReadinessAssessment."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.common.enums import ClaimState, ConflictSeverity, ReadinessState
from app.common.ids import uuid7
from app.infrastructure.database import Base


class EvidenceClaim(Base):
    __tablename__ = "evidence_claims"

    claim_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    source_file_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    batch_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_column: Mapped[str] = mapped_column(String(256), nullable=False)
    canonical_entity: Mapped[str | None] = mapped_column(String(64), nullable=True)
    canonical_field: Mapped[str | None] = mapped_column(String(128), nullable=True)
    raw_value: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    claim_state: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ClaimState.PENDING_REVIEW.value
    )
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    requires_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=lambda: datetime.now(UTC))


class EvidenceConflict(Base):
    __tablename__ = "evidence_conflicts"

    conflict_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    batch_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    claim_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    canonical_entity: Mapped[str | None] = mapped_column(String(64), nullable=True)
    canonical_field: Mapped[str | None] = mapped_column(String(128), nullable=True)
    severity: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ConflictSeverity.WARNING.value
    )
    blocking: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    review_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=lambda: datetime.now(UTC))


class ConflictResolution(Base):
    __tablename__ = "conflict_resolutions"

    resolution_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    conflict_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    selected_claim_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    reviewer_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=lambda: datetime.now(UTC))


class ReadinessAssessment(Base):
    __tablename__ = "readiness_assessments"

    assessment_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    batch_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    state: Mapped[str] = mapped_column(
        String(32), nullable=False, default=ReadinessState.BLOCKED.value
    )
    blocking_conflict_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    open_conflict_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accepted_claim_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pending_claim_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    assumptions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    explanation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=lambda: datetime.now(UTC))
