"""Feature Store Registry — Central registry for feature definitions."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, select
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.ids import uuid7_uuid
from app.infrastructure.database import Base
from app.modules.feature_store.models import (
    FeatureDefinition,
    FeatureGroup,
    FeatureStatistics,
    FeatureStatus,
    FeatureType,
)


class FeatureDefinitionRecord(Base):
    """ORM model for feature definitions."""

    __tablename__ = "feature_definitions"
    __table_args__ = (
        Index("ix_feature_def_name", "name"),
        Index("ix_feature_def_group", "group_id"),
        Index("ix_feature_def_status", "status"),
        {"schema": "analytics"},
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid7_uuid)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    feature_type: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    group_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("analytics.feature_groups.id"), nullable=True
    )

    dtype: Mapped[str] = mapped_column(String(32), nullable=False, default="float32")
    shape: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    min_value: Mapped[float | None] = mapped_column(nullable=True)
    max_value: Mapped[float | None] = mapped_column(nullable=True)
    mean: Mapped[float | None] = mapped_column(nullable=True)
    std: Mapped[float | None] = mapped_column(nullable=True)
    null_ratio: Mapped[float] = mapped_column(default=0.0)

    min_allowed: Mapped[float | None] = mapped_column(nullable=True)
    max_allowed: Mapped[float | None] = mapped_column(nullable=True)
    allowed_categories: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    source: Mapped[str] = mapped_column(String(32), nullable=False, default="computed")
    computation_logic: Mapped[str] = mapped_column(Text, nullable=False, default="")
    dependencies: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=FeatureStatus.DRAFT.value
    )
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0.0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    deprecated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)


class FeatureGroupRecord(Base):
    """ORM model for feature groups."""

    __tablename__ = "feature_groups"
    __table_args__ = ({"schema": "analytics"},)

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid7_uuid)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    feature_names: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0.0")
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    extra_metadata: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)


class FeatureStatisticsRecord(Base):
    """ORM model for feature statistics."""

    __tablename__ = "feature_statistics"
    __table_args__ = (
        Index("ix_feat_stats_workspace", "workspace_id"),
        Index("ix_feat_stats_feature", "feature_name"),
        Index("ix_feat_stats_version", "snapshot_version"),
        {"schema": "analytics"},
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid7_uuid)
    workspace_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    feature_name: Mapped[str] = mapped_column(String(128), nullable=False)
    snapshot_version: Mapped[int] = mapped_column(nullable=False)

    count: Mapped[int] = mapped_column(default=0)
    null_count: Mapped[int] = mapped_column(default=0)
    null_ratio: Mapped[float] = mapped_column(default=0.0)

    mean: Mapped[float | None] = mapped_column(nullable=True)
    std: Mapped[float | None] = mapped_column(nullable=True)
    min: Mapped[float | None] = mapped_column(nullable=True)
    max: Mapped[float | None] = mapped_column(nullable=True)
    percentiles: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    categories: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    unique_count: Mapped[int | None] = mapped_column(nullable=True)

    missing_ratio: Mapped[float] = mapped_column(default=0.0)
    outlier_count: Mapped[int] = mapped_column(default=0)
    outlier_ratio: Mapped[float] = mapped_column(default=0.0)

    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class FeatureRegistry:
    """Feature store registry service."""

    def __init__(self, db):
        self.db = db

    async def register_feature(self, definition: FeatureDefinition) -> FeatureDefinition:
        """Register a new feature definition."""
        record = FeatureDefinitionRecord(
            name=definition.name,
            feature_type=definition.feature_type.value,
            description=definition.description,
            group_id=definition.group_id,
            dtype=definition.dtype,
            shape=list(definition.shape),
            min_value=definition.min_value,
            max_value=definition.max_value,
            mean=definition.mean,
            std=definition.std,
            null_ratio=definition.null_ratio,
            min_allowed=definition.min_allowed,
            max_allowed=definition.max_allowed,
            allowed_categories=definition.allowed_categories,
            source=definition.source,
            computation_logic=definition.computation_logic,
            dependencies=list(definition.dependencies),
            tags=list(definition.tags),
            status=definition.status.value,
            version=definition.version,
            created_by=definition.created_by,
        )
        self.db.add(record)
        await self.db.flush()
        return self._to_definition(record)

    async def get_feature(self, feature_id: UUID) -> FeatureDefinition | None:
        """Get feature by ID."""
        result = await self.db.execute(
            select(FeatureDefinitionRecord).where(FeatureDefinitionRecord.id == feature_id)
        )
        record = result.scalar_one_or_none()
        return self._to_definition(record) if record else None

    async def get_feature_by_name(self, name: str) -> FeatureDefinition | None:
        """Get feature by name."""
        result = await self.db.execute(
            select(FeatureDefinitionRecord).where(FeatureDefinitionRecord.name == name)
        )
        record = result.scalar_one_or_none()
        return self._to_definition(record) if record else None

    async def list_features(
        self,
        feature_type: str | None = None,
        status: str | None = None,
        group_id: UUID | None = None,
        tags: list[str] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[FeatureDefinition]:
        """List features with filters."""
        stmt = select(FeatureDefinitionRecord)

        if feature_type:
            stmt = stmt.where(FeatureDefinitionRecord.feature_type == feature_type)
        if status:
            stmt = stmt.where(FeatureDefinitionRecord.status == status)
        if group_id:
            stmt = stmt.where(FeatureDefinitionRecord.group_id == group_id)
        if tags:
            for tag in tags:
                stmt = stmt.where(FeatureDefinitionRecord.tags.op("@>")([tag]))

        stmt = stmt.order_by(FeatureDefinitionRecord.name).limit(limit).offset(offset)
        result = await self.db.execute(stmt)
        records = result.scalars().all()
        return [self._to_definition(r) for r in records]

    async def update_feature(self, feature_id: UUID, updates: dict) -> FeatureDefinition | None:
        """Update a feature definition."""
        result = await self.db.execute(
            select(FeatureDefinitionRecord).where(FeatureDefinitionRecord.id == feature_id)
        )
        record = result.scalar_one_or_none()
        if not record:
            return None

        for key, value in updates.items():
            if hasattr(record, key):
                setattr(record, key, value)

        record.updated_at = datetime.now(UTC)
        await self.db.flush()
        return self._to_definition(record)

    async def deprecate_feature(self, feature_id: UUID, reason: str = "") -> bool:
        """Deprecate a feature."""
        result = await self.db.execute(
            select(FeatureDefinitionRecord).where(FeatureDefinitionRecord.id == feature_id)
        )
        record = result.scalar_one_or_none()
        if not record:
            return False

        record.status = FeatureStatus.DEPRECATED.value
        record.deprecated_at = datetime.now(UTC)
        record.updated_at = datetime.now(UTC)
        await self.db.flush()
        return True

    async def register_group(self, group: FeatureGroup) -> FeatureGroup:
        """Register a feature group."""
        record = FeatureGroupRecord(
            name=group.name,
            description=group.description,
            feature_names=group.feature_names,
            version=group.version,
            created_by=group.created_by,
            metadata=group.metadata,
        )
        self.db.add(record)
        await self.db.flush()
        return self._to_group(record)

    async def get_group(self, group_id: UUID) -> FeatureGroup | None:
        result = await self.db.execute(
            select(FeatureGroupRecord).where(FeatureGroupRecord.id == group_id)
        )
        record = result.scalar_one_or_none()
        return self._to_group(record) if record else None

    async def compute_statistics(
        self,
        workspace_id: UUID,
        snapshot_version: int,
        feature_vectors: list[dict],
    ) -> list[FeatureStatistics]:
        """Compute statistics for features across a dataset."""
        # Aggregate by feature name
        feature_data: dict[str, list] = {}
        for fv in feature_vectors:
            for fname, value in fv.get("features", {}).items():
                if fname not in feature_data:
                    feature_data[fname] = []
                feature_data[fname].append(value)

        stats = []
        for fname, values in feature_data.items():
            valid = [v for v in values if v is not None]
            null_count = len(values) - len(valid)

            if not valid:
                continue

            # Try to infer type
            first_val = valid[0]
            if isinstance(first_val, (int, float)):
                stats.append(self._compute_numerical_stats(fname, valid, len(values), null_count))
            elif isinstance(first_val, str):
                stats.append(self._compute_categorical_stats(fname, values, null_count))

        # Persist
        records = []
        for stat in stats:
            record = FeatureStatisticsRecord(
                workspace_id=workspace_id,
                feature_name=stat.feature_name,
                snapshot_version=0,  # will be set by caller
                count=stat.count,
                null_count=stat.null_count,
                null_ratio=stat.null_ratio,
                mean=stat.mean,
                std=stat.std,
                min=stat.min,
                max=stat.max,
                percentiles=stat.percentiles,
                categories=stat.categories,
                unique_count=stat.unique_count,
                missing_ratio=stat.missing_ratio,
                outlier_count=stat.outlier_count,
                outlier_ratio=stat.outlier_ratio,
            )
            self.db.add(record)
            records.append(record)

        await self.db.flush()
        return stats

    def _compute_numerical_stats(
        self, name: str, values: list, total: int, null_count: int
    ) -> FeatureStatistics:
        import numpy as np

        arr = np.array([float(v) for v in values])
        return FeatureStatistics(
            feature_name=name,
            count=len(values),
            null_count=null_count,
            null_ratio=null_count / total if total > 0 else 0.0,
            mean=float(np.mean(arr)),
            std=float(np.std(arr)),
            min=float(np.min(arr)),
            max=float(np.max(arr)),
            percentiles={
                "p25": float(np.percentile(arr, 25)),
                "p50": float(np.percentile(arr, 50)),
                "p75": float(np.percentile(arr, 75)),
                "p90": float(np.percentile(arr, 90)),
                "p99": float(np.percentile(arr, 99)),
            },
        )

    def _compute_categorical_stats(
        self, name: str, values: list, null_count: int
    ) -> FeatureStatistics:
        from collections import Counter

        total = len(values) + null_count
        valid = [v for v in values if v is not None]
        counts = Counter(str(v) for v in valid)
        return FeatureStatistics(
            feature_name=name,
            count=len(valid),
            null_count=null_count,
            null_ratio=null_count / total if total > 0 else 0.0,
            categories=dict(counts),
            unique_count=len(counts),
        )

    def _to_definition(self, record: FeatureDefinitionRecord) -> FeatureDefinition:
        return FeatureDefinition(
            feature_id=record.id,
            name=record.name,
            feature_type=FeatureType(record.feature_type),
            description=record.description,
            group_id=record.group_id,
            dtype=record.dtype,
            shape=tuple(record.shape),
            min_value=record.min_value,
            max_value=record.max_value,
            mean=record.mean,
            std=record.std,
            null_ratio=record.null_ratio,
            min_allowed=record.min_allowed,
            max_allowed=record.max_allowed,
            allowed_categories=record.allowed_categories,
            source=record.source,
            computation_logic=record.computation_logic,
            dependencies=list(record.dependencies),
            tags=list(record.tags),
            status=FeatureStatus(record.status),
            version=record.version,
            created_at=record.created_at,
            updated_at=record.updated_at,
            deprecated_at=record.deprecated_at,
            created_by=record.created_by,
        )

    def _to_group(self, record: FeatureGroupRecord) -> FeatureGroup:
        return FeatureGroup(
            group_id=record.id,
            name=record.name,
            description=record.description,
            feature_names=record.feature_names,
            version=record.version,
            created_by=record.created_by,
            created_at=record.created_at,
            metadata=record.metadata,
        )


__all__ = [
    "FeatureDefinitionRecord",
    "FeatureGroupRecord",
    "FeatureStatisticsRecord",
    "FeatureRegistry",
]
