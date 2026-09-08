"""ML Model Registry — track model versions, metrics, and deployment artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, Integer, String, Text, select
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.common.ids import uuid7
from app.infrastructure.database import Base


class ModelStage(StrEnum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    ARCHIVED = "archived"


class ModelType(StrEnum):
    CLASSIFICATION = "classification"
    REGRESSION = "regression"
    RANKING = "ranking"
    CLUSTERING = "clustering"


class ModelRegistry(Base):
    """Model registry for tracking trained models.

    Each model version is immutable once registered.
    """

    __tablename__ = "ml_model_registry"

    model_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    model_type: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[str] = mapped_column(String(16), nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default="development")
    description: Mapped[str] = mapped_column(Text, nullable=False)
    training_data_version: Mapped[str] = mapped_column(String(64), nullable=False)
    training_samples: Mapped[int] = mapped_column(Integer, nullable=False)
    hyperparameters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    metrics: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False, default=dict)
    artifact_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    parent_model_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    meta_data: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )


class ModelEvaluation(Base):
    """Model evaluation results.

    Multiple evaluations can be stored per model version.
    """

    __tablename__ = "ml_model_evaluations"

    evaluation_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    model_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    evaluation_name: Mapped[str] = mapped_column(String(128), nullable=False)
    dataset_name: Mapped[str] = mapped_column(String(128), nullable=False)
    dataset_version: Mapped[str] = mapped_column(String(64), nullable=False)
    metrics: Mapped[dict[str, float]] = mapped_column(JSON, nullable=False, default=dict)
    confusion_matrix: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    evaluated_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    meta_data: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )


@dataclass(frozen=True)
class ModelCard:
    """Model card for documentation and governance."""

    model_id: str
    model_name: str
    version: str
    model_type: str
    stage: str
    description: str
    training_data_summary: dict[str, Any]
    hyperparameters: dict[str, Any]
    performance_metrics: dict[str, float]
    intended_use: str
    limitations: list[str]
    ethical_considerations: list[str]
    created_at: datetime
    created_by: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_name": self.model_name,
            "version": self.version,
            "model_type": self.model_type,
            "stage": self.stage,
            "description": self.description,
            "training_data_summary": self.training_data_summary,
            "hyperparameters": self.hyperparameters,
            "performance_metrics": self.performance_metrics,
            "intended_use": self.intended_use,
            "limitations": self.limitations,
            "ethical_considerations": self.ethical_considerations,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
        }


@dataclass(frozen=True)
class ModelComparison:
    """Comparison between multiple model versions."""

    comparison_id: str
    model_name: str
    versions: list[str]
    metrics_comparison: dict[str, dict[str, float]]
    recommendation: str | None
    created_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "comparison_id": self.comparison_id,
            "model_name": self.model_name,
            "versions": self.versions,
            "metrics_comparison": self.metrics_comparison,
            "recommendation": self.recommendation,
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True)
class ModelArtifact:
    """Model artifact for shadow inference."""

    model_id: str
    model_name: str
    version: str
    model_type: str
    artifact_path: str | None
    hyperparameters: dict[str, Any]
    metadata: dict[str, Any]


async def get_model(db: AsyncSession, model_name: str, version: str) -> ModelArtifact | None:
    """Get a model artifact by name and version for inference."""
    stmt = select(ModelRegistry).where(
        ModelRegistry.model_name == model_name,
        ModelRegistry.version == version,
    )
    result = await db.execute(stmt)
    model = result.scalar_one_or_none()

    if not model:
        return None

    return ModelArtifact(
        model_id=model.model_id,
        model_name=model.model_name,
        version=model.version,
        model_type=model.model_type,
        artifact_path=model.artifact_path,
        hyperparameters=model.hyperparameters,
        metadata=model.meta_data,
    )


async def register_model(
    db: AsyncSession,
    model_name: str,
    model_type: str,
    version: str,
    description: str,
    training_data_version: str,
    training_samples: int,
    hyperparameters: dict[str, Any],
    metrics: dict[str, float],
    artifact_path: str | None = None,
    parent_model_id: str | None = None,
    created_by: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ModelRegistry:
    """Register a new model version."""
    model = ModelRegistry(
        model_name=model_name,
        model_type=model_type,
        version=version,
        description=description,
        training_data_version=training_data_version,
        training_samples=training_samples,
        hyperparameters=hyperparameters,
        metrics=metrics,
        artifact_path=artifact_path,
        parent_model_id=parent_model_id,
        created_by=created_by,
        meta_data=metadata or {},
    )
    db.add(model)
    await db.flush()
    return model


async def promote_model(
    db: AsyncSession,
    model_name: str,
    version: str,
    stage: str,
    promoted_by: str | None = None,
) -> ModelRegistry | None:
    """Promote a model to a new stage."""
    stmt = select(ModelRegistry).where(
        ModelRegistry.model_name == model_name,
        ModelRegistry.version == version,
    )
    result = await db.execute(stmt)
    model = result.scalar_one_or_none()

    if not model:
        return None

    model.stage = stage
    model.meta_data = {
        **model.meta_data,
        "promoted_by": promoted_by,
        "promoted_at": datetime.now(UTC).isoformat(),
    }
    await db.flush()
    return model
