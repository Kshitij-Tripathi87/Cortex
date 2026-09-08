"""Evaluation Registry — Stores all benchmark runs for comparison."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import JSON, DateTime, Index, String, Text, select
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.ids import uuid7_uuid
from app.infrastructure.database import Base


class EvaluationRunRecord(Base):
    """ORM model for evaluation runs."""

    __tablename__ = "evaluation_runs"
    __table_args__ = (
        Index("ix_eval_runs_dataset", "dataset_id"),
        Index("ix_eval_runs_engine", "engine_type"),
        Index("ix_eval_runs_created", "created_at"),
        Index("ix_eval_runs_status", "status"),
        {"schema": "analytics"},
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid7_uuid)
    dataset_id: Mapped[str] = mapped_column(String(128), nullable=False)
    dataset_version: Mapped[int] = mapped_column(default=1)
    engine_type: Mapped[str] = mapped_column(String(64), nullable=False)
    engine_version: Mapped[str | None] = mapped_column(String(64), nullable=True)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")

    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    aggregate_metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    scenario_results: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(nullable=True)


class EvaluationRegistry:
    """Registry for evaluation runs."""

    def __init__(self, db):
        self.db = db

    async def create_run(
        self,
        dataset_id: str,
        dataset_version: int,
        engine_type: str,
        engine_version: str | None = None,
        config: dict | None = None,
    ) -> UUID:
        """Create a new evaluation run record."""
        record = EvaluationRunRecord(
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            engine_type=engine_type,
            engine_version=engine_version,
            config=config or {},
        )
        self.db.add(record)
        await self.db.flush()
        return record.id

    async def update_run(
        self,
        run_id: UUID,
        status: str | None = None,
        aggregate_metrics: dict | None = None,
        scenario_results: list | None = None,
        error: str | None = None,
    ) -> bool:
        """Update an evaluation run."""
        result = await self.db.execute(
            select(EvaluationRunRecord).where(EvaluationRunRecord.id == run_id)
        )
        record = result.scalar_one_or_none()
        if not record:
            return False

        if status is not None:
            record.status = status
        if aggregate_metrics is not None:
            record.aggregate_metrics = aggregate_metrics
        if scenario_results is not None:
            record.scenario_results = scenario_results
        if error is not None:
            record.error = error
            record.status = "failed"

        if status == "completed":
            record.completed_at = datetime.now(UTC)
            # Duration will be calculated by the runner

        await self.db.flush()
        return True

    async def complete_run(
        self,
        run_id: UUID,
        aggregate_metrics: dict,
        scenario_results: list,
        duration_seconds: float,
    ) -> bool:
        """Mark a run as completed with results."""
        result = await self.db.execute(
            select(EvaluationRunRecord).where(EvaluationRunRecord.id == run_id)
        )
        record = result.scalar_one_or_none()
        if not record:
            return False

        record.status = "completed"
        record.aggregate_metrics = aggregate_metrics
        record.scenario_results = scenario_results
        record.completed_at = datetime.now(UTC)
        record.duration_seconds = duration_seconds
        await self.db.flush()
        return True

    async def get_run(self, run_id: UUID) -> dict | None:
        """Get evaluation run by ID."""
        result = await self.db.execute(
            select(EvaluationRunRecord).where(EvaluationRunRecord.id == run_id)
        )
        record = result.scalar_one_or_none()
        if not record:
            return None

        return {
            "run_id": str(record.id),
            "dataset_id": record.dataset_id,
            "dataset_version": record.dataset_version,
            "engine_type": record.engine_type,
            "engine_version": record.engine_version,
            "status": record.status,
            "config": record.config,
            "aggregate_metrics": record.aggregate_metrics,
            "scenario_results": record.scenario_results,
            "error": record.error,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "completed_at": record.completed_at.isoformat() if record.completed_at else None,
            "duration_seconds": record.duration_seconds,
        }

    async def list_runs(
        self,
        dataset_id: str | None = None,
        engine_type: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """List evaluation runs with filters."""
        stmt = select(EvaluationRunRecord)

        if dataset_id:
            stmt = stmt.where(EvaluationRunRecord.dataset_id == dataset_id)
        if engine_type:
            stmt = stmt.where(EvaluationRunRecord.engine_type == engine_type)
        if status:
            stmt = stmt.where(EvaluationRunRecord.status == status)

        stmt = stmt.order_by(EvaluationRunRecord.created_at.desc())
        stmt = stmt.limit(limit).offset(offset)

        result = await self.db.execute(stmt)
        records = result.scalars().all()

        return [
            {
                "run_id": str(r.id),
                "dataset_id": r.dataset_id,
                "dataset_version": r.dataset_version,
                "engine_type": r.engine_type,
                "engine_version": r.engine_version,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "duration_seconds": r.duration_seconds,
            }
            for r in records
        ]

    async def compare_engines(
        self,
        dataset_id: str,
        engine_a: str,
        version_a: str | None,
        engine_b: str,
        version_b: str | None,
    ) -> dict:
        """Compare two engines on the same dataset."""
        # Get best runs for each engine
        stmt_a = (
            select(EvaluationRunRecord)
            .where(
                EvaluationRunRecord.dataset_id == dataset_id,
                EvaluationRunRecord.engine_type == engine_a,
                EvaluationRunRecord.status == "completed",
            )
            .order_by(EvaluationRunRecord.created_at.desc())
            .limit(1)
        )

        stmt_b = (
            select(EvaluationRunRecord)
            .where(
                EvaluationRunRecord.dataset_id == dataset_id,
                EvaluationRunRecord.engine_type == engine_b,
                EvaluationRunRecord.status == "completed",
            )
            .order_by(EvaluationRunRecord.created_at.desc())
            .limit(1)
        )

        if version_a:
            stmt_a = stmt_a.where(EvaluationRunRecord.engine_version == version_a)
        if version_b:
            stmt_b = stmt_b.where(EvaluationRunRecord.engine_version == version_b)

        result_a = await self.db.execute(stmt_a)
        result_b = await self.db.execute(stmt_b)

        run_a = result_a.scalar_one_or_none()
        run_b = result_b.scalar_one_or_none()

        if not run_a or not run_b:
            return {"error": "Not enough completed runs for comparison"}

        metrics_a = run_a.aggregate_metrics or {}
        metrics_b = run_b.aggregate_metrics or {}

        # Compare metrics
        comparison = {}
        all_keys = set(metrics_a.keys()) | set(metrics_b.keys())
        for key in all_keys:
            a = metrics_a.get(key)
            b = metrics_b.get(key)
            if a is not None and b is not None:
                diff = b - a
                pct = (diff / a * 100) if a != 0 else float("inf") if b > 0 else 0
                comparison[key] = {
                    "engine_a": a,
                    "engine_b": b,
                    "difference": diff,
                    "percent_change": pct,
                    "better": "b" if b > a else "a" if a > b else "tie",
                }

        return {
            "engine_a": {"type": engine_a, "version": version_a, "metrics": metrics_a},
            "engine_b": {"type": engine_b, "version": version_b, "metrics": metrics_b},
            "comparison": comparison,
        }


__all__ = ["EvaluationRunRecord", "EvaluationRegistry"]
