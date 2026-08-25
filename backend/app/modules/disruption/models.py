"""Disruption/impact ORM models — analytics.* schema (ADR-0006).

Tables:
- analytics.impact_reports    — output of propagation+impact+confidence engines (Week 2)
- analytics.backtest_results  — output of backtest runner (Week 4)

The `orders.disruption_events` row (the trigger event) lives in
`app.modules.supply_chain.models.DisruptionEvent` because it shares the
`orders` schema with `orders.orders` and is consumed during data ingestion.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.enums import ImpactStatus
from app.common.ids import uuid7_uuid
from app.infrastructure.database import Base


def _now() -> datetime:
    return datetime.now(UTC)


class ImpactReport(Base):
    """Result of running propagation+impact+confidence against a disruption_event.

    Persisted every time the Morning Brief is computed for a disruption_event;
    the `computation_run_id` distinguishes recomputes (e.g., after ingestion).
    JSON `payload` holds the full Morning Brief shape per ADR-010.
    """

    __tablename__ = "impact_reports"
    __table_args__ = (
        Index(
            "ix_impact_reports_workspace_event",
            "workspace_id",
            "disruption_event_id",
        ),
        {"schema": "analytics"},
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid7_uuid)
    workspace_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("core.workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    disruption_event_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("orders.disruption_events.id", ondelete="CASCADE"),
        nullable=False,
    )
    computation_run_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    status: Mapped[ImpactStatus] = mapped_column(
        String(32), nullable=False, default=ImpactStatus.PENDING
    )
    confidence_overall: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )


class BacktestResult(Base):
    """A single backtest run's accuracy metrics (Week 4 backtest runner output)."""

    __tablename__ = "backtest_results"
    __table_args__ = ({"schema": "analytics"},)

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid7_uuid)
    workspace_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("core.workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accuracy: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False)
    precision: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False)
    recall: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False)
    f1: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False)
    total_predictions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


__all__ = ["BacktestResult", "ImpactReport"]
