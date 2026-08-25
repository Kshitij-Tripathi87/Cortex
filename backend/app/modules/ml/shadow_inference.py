"""ML Pipeline — Shadow Inference Service.

Runs shadow mode inference alongside production decisions.
Shadow predictions are logged but not shown to users.
Used for model validation and A/B testing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, String, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.common.ids import uuid7
from app.infrastructure.database import Base


class ShadowPrediction(Base):
    """Shadow mode prediction log.

    Records model predictions made in shadow mode for later analysis.
    """

    __tablename__ = "ml_shadow_predictions"

    prediction_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    model_id: Mapped[str] = mapped_column(String(36), nullable=False)
    model_version: Mapped[str] = mapped_column(String(16), nullable=False)
    input_features: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    prediction: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_outcome: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    matched: Mapped[bool | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    extra_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, nullable=False, default=dict)


@dataclass(frozen=True)
class ShadowInferenceResult:
    """Result of a shadow inference run."""

    prediction_id: str
    model_id: str
    model_version: str
    workspace_id: str
    input_features: dict[str, Any]
    prediction: dict[str, Any]
    confidence: float | None
    actual_outcome: dict[str, Any] | None
    matched: bool | None
    created_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "prediction_id": self.prediction_id,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "workspace_id": self.workspace_id,
            "input_features": self.input_features,
            "prediction": self.prediction,
            "confidence": self.confidence,
            "actual_outcome": self.actual_outcome,
            "matched": self.matched,
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True)
class ShadowAnalysis:
    """Analysis of shadow mode predictions."""

    model_id: str
    model_version: str
    workspace_id: str
    total_predictions: int
    matched_count: int
    match_rate: float
    accuracy_by_class: dict[str, float]
    avg_confidence: float
    predictions: list[ShadowInferenceResult]
    analyzed_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_version": self.model_version,
            "workspace_id": self.workspace_id,
            "total_predictions": self.total_predictions,
            "matched_count": self.matched_count,
            "match_rate": self.match_rate,
            "accuracy_by_class": self.accuracy_by_class,
            "avg_confidence": self.avg_confidence,
            "predictions": [p.to_dict() for p in self.predictions],
            "analyzed_at": self.analyzed_at.isoformat(),
        }


async def log_shadow_prediction(
    db: AsyncSession,
    workspace_id: str,
    model_id: str,
    model_version: str,
    input_features: dict[str, Any],
    prediction: dict[str, Any],
    confidence: float | None = None,
) -> str:
    """Log a shadow mode prediction.

    Returns the prediction_id for later matching with actual outcome.
    """
    prediction_record = ShadowPrediction(
        prediction_id=uuid7(),
        workspace_id=workspace_id,
        model_id=model_id,
        model_version=model_version,
        input_features=input_features,
        prediction=prediction,
        confidence=confidence,
        created_at=datetime.now(UTC),
    )
    db.add(prediction_record)
    await db.flush()
    return prediction_record.prediction_id


async def match_shadow_prediction(
    db: AsyncSession,
    prediction_id: str,
    actual_outcome: dict[str, Any],
    matched: bool,
) -> None:
    """Match a shadow prediction with its actual outcome."""
    stmt = select(ShadowPrediction).where(ShadowPrediction.prediction_id == prediction_id)
    result = await db.execute(stmt)
    prediction = result.scalar_one_or_none()
    if prediction:
        prediction.actual_outcome = actual_outcome
        prediction.matched = matched
        await db.commit()
