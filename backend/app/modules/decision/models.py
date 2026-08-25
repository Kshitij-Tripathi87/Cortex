"""Decision module — decision.* schema (ADR-0006).

Tables:
- decision.decision_log      — every operator accept/reject/modify on a recommendation
- decision.decision_memory   — Phase 2 ML training cache; table exists in MVP but is unused

The `decision_memory` table is created by the Week 1 migration so future
ML-on-decisions code (Phase 2) doesn't need a schema migration. In the MVP
nothing writes to it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.enums import DecisionOutcome
from app.common.ids import uuid7_uuid
from app.infrastructure.database import Base


def _now() -> datetime:
    return datetime.now(UTC)


class DecisionLog(Base):
    """Append-only record of an operator's decision on a recommendation.

    Every row records: which disruption_event, which recommendation_id
    (an opaque ID emitted by the recommendation engine in Week 2),
    the decision outcome, the operator's rationale, and the
    `contract_version` of the response shape they were shown (ADR-010).
    """

    __tablename__ = "decision_log"
    __table_args__ = (
        Index(
            "ix_decision_log_workspace_event",
            "workspace_id",
            "disruption_event_id",
        ),
        Index("ix_decision_log_workspace_user", "workspace_id", "user_id"),
        {"schema": "decision"},
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid7_uuid)
    workspace_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("core.workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("core.users.id", ondelete="SET NULL"),
        nullable=True,
    )
    disruption_event_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("orders.disruption_events.id", ondelete="CASCADE"),
        nullable=False,
    )
    recommendation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[DecisionOutcome] = mapped_column(String(48), nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    contract_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0")
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class DecisionMemory(Base):
    """Long-lived cache for Phase 2 ML-on-decisions. Empty in MVP.

    The schema is laid out now so future writes don't require a migration.
    Pattern signature is a deterministic hash of (disruption features, decision
    taken, recommendation shape); outcome_metrics are backfilled when the
    actual outcome of the disruption is observed.
    """

    __tablename__ = "decision_memory"
    __table_args__ = (
        Index("ix_decision_memory_workspace", "workspace_id"),
        {"schema": "decision"},
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid7_uuid)
    workspace_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("core.workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    decision_log_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("decision.decision_log.id", ondelete="CASCADE"),
        nullable=False,
    )
    pattern_signature: Mapped[str] = mapped_column(String(128), nullable=False)
    outcome_metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )


__all__ = ["DecisionLog", "DecisionMemory"]
