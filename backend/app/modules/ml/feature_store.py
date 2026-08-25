"""ML Pipeline — Feature Store for Training.

Stores and retrieves features used for ML model training.
Features are versioned and workspace-scoped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.common.ids import uuid7
from app.infrastructure.database import Base


class FeatureStore(Base):
    """Feature store for ML training data.

    Stores computed features with versioning for reproducibility.
    """

    __tablename__ = "ml_feature_store"

    feature_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(128), nullable=False)
    feature_name: Mapped[str] = mapped_column(String(128), nullable=False)
    feature_value: Mapped[float] = mapped_column(Float, nullable=False)
    feature_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0.0")
    snapshot_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    extra_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, nullable=False, default=dict)


class FeatureGroup(Base):
    """Feature groups for organizing related features.

    Groups can be exported together for training.
    """

    __tablename__ = "ml_feature_groups"

    group_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    group_name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[Text] = mapped_column(Text, nullable=False)
    feature_names: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0.0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    extra_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, nullable=False, default=dict)


@dataclass(frozen=True)
class FeatureVector:
    """A feature vector for a single entity."""

    entity_type: str
    entity_id: str
    workspace_id: str
    features: dict[str, float]
    snapshot_version: int | None
    computed_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "workspace_id": self.workspace_id,
            "features": self.features,
            "snapshot_version": self.snapshot_version,
            "computed_at": self.computed_at.isoformat(),
        }


@dataclass(frozen=True)
class FeatureGroupExport:
    """Exported feature group for training."""

    group_id: str
    group_name: str
    workspace_id: str
    version: str
    features: list[FeatureVector]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_id": self.group_id,
            "group_name": self.group_name,
            "workspace_id": self.workspace_id,
            "version": self.version,
            "features": [f.to_dict() for f in self.features],
            "metadata": self.metadata,
        }
