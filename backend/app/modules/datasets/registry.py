"""Dataset Registry — Central registry for all dataset metadata."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, select
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.ids import uuid7_uuid
from app.infrastructure.database import Base
from app.modules.datasets.models import (
    DatasetMetadata,
    DatasetRegistrationRequest,
    DatasetSearchFilters,
    DatasetSize,
    DatasetStatus,
    DatasetUpdateRequest,
    SchemaVersion,
)


class DatasetRecord(Base):
    """ORM model for dataset registry."""

    __tablename__ = "dataset_registry"
    __table_args__ = (
        Index("ix_dataset_registry_workspace", "workspace_id"),
        Index("ix_dataset_registry_status", "status"),
        Index("ix_dataset_registry_size", "size"),
        Index("ix_dataset_registry_seed", "seed"),
        Index("ix_dataset_registry_created", "created_at"),
        {"schema": "analytics"},
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid7_uuid
    )
    version: Mapped[int] = mapped_column(default=1)
    workspace_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("core.workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    size: Mapped[str] = mapped_column(String(32), nullable=False)
    seed: Mapped[int] = mapped_column(nullable=False)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)

    generation_params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    generation_duration_seconds: Mapped[float | None] = mapped_column(nullable=True)
    generated_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    generator_version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0")

    statistics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    scenarios: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    label_coverage: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    checksums: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    last_validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    storage_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    storage_size_bytes: Mapped[int] = mapped_column(default=0)

    parent_dataset_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True
    )
    tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    # Relationships
    workspace = relationship("Workspace", lazy="raise")


class DatasetRegistry:
    """Dataset registry service."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def register(
        self,
        workspace_id: UUID,
        request: DatasetRegistrationRequest,
        generated_by: str | None = None,
    ) -> DatasetMetadata:
        """Register a new dataset."""
        record = DatasetRecord(
            workspace_id=workspace_id,
            name=request.name,
            description=request.description,
            size=request.size.value,
            seed=request.seed,
            schema_version=request.schema_version.value,
            status=DatasetStatus.GENERATING.value,
            generation_params=request.generation_params,
            generated_by=generated_by,
            parent_dataset_id=request.parent_dataset_id,
            tags=request.tags,
        )
        self.db.add(record)
        await self.db.flush()
        return self._to_metadata(record)

    async def get(self, dataset_id: UUID) -> DatasetMetadata | None:
        """Get dataset by ID."""
        result = await self.db.execute(
            select(DatasetRecord).where(DatasetRecord.id == dataset_id)
        )
        record = result.scalar_one_or_none()
        return self._to_metadata(record) if record else None

    async def list(
        self,
        workspace_id: UUID | None = None,
        filters: DatasetSearchFilters | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[DatasetMetadata], int]:
        """List datasets with filters and pagination."""
        stmt = select(DatasetRecord)

        if workspace_id:
            stmt = stmt.where(DatasetRecord.workspace_id == workspace_id)

        if filters:
            if filters.name:
                stmt = stmt.where(DatasetRecord.name.ilike(f"%{filters.name}%"))
            if filters.size:
                stmt = stmt.where(DatasetRecord.size == filters.size.value)
            if filters.status:
                stmt = stmt.where(DatasetRecord.status == filters.status.value)
            if filters.seed is not None:
                stmt = stmt.where(DatasetRecord.seed == filters.seed)
            if filters.schema_version:
                stmt = stmt.where(DatasetRecord.schema_version == filters.schema_version.value)
            if filters.tags:
                # JSON array contains all tags
                for tag in filters.tags:
                    stmt = stmt.where(DatasetRecord.tags.op("@>")([tag]))
            if filters.created_after:
                stmt = stmt.where(DatasetRecord.created_at >= filters.created_after)
            if filters.created_before:
                stmt = stmt.where(DatasetRecord.created_at <= filters.created_before)

        # Count total
        count_stmt = stmt.with_only_columns(select(func.count(DatasetRecord.id)))
        total_result = await self.db.execute(count_stmt)
        total = total_result.scalar() or 0

        # Pagination
        stmt = stmt.order_by(DatasetRecord.created_at.desc())
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)

        result = await self.db.execute(stmt)
        records = result.scalars().all()

        return [self._to_metadata(r) for r in records], total

    async def update(
        self, dataset_id: UUID, request: DatasetUpdateRequest
    ) -> DatasetMetadata | None:
        """Update dataset metadata."""
        result = await self.db.execute(
            select(DatasetRecord).where(DatasetRecord.id == dataset_id)
        )
        record = result.scalar_one_or_none()
        if not record:
            return None

        if request.name is not None:
            record.name = request.name
        if request.description is not None:
            record.description = request.description
        if request.status is not None:
            record.status = request.status.value
        if request.tags is not None:
            record.tags = request.tags

        record.updated_at = datetime.now(UTC)
        await self.db.flush()
        return self._to_metadata(record)

    async def update_status(
        self, dataset_id: UUID, status: DatasetStatus
    ) -> DatasetMetadata | None:
        """Update dataset status."""
        return await self.update(dataset_id, DatasetUpdateRequest(status=status))

    async def finalize(
        self,
        dataset_id: UUID,
        storage_path: str,
        storage_size_bytes: int,
        statistics: dict,
        scenarios: list[dict],
        label_coverage: dict,
        checksums: dict,
        generation_duration: float,
    ) -> DatasetMetadata | None:
        """Mark dataset as ready with final metadata."""
        result = await self.db.execute(
            select(DatasetRecord).where(DatasetRecord.id == dataset_id)
        )
        record = result.scalar_one_or_none()
        if not record:
            return None

        record.status = DatasetStatus.READY.value
        record.storage_path = storage_path
        record.storage_size_bytes = storage_size_bytes
        record.statistics = statistics
        record.scenarios = scenarios
        record.label_coverage = label_coverage
        record.checksums = checksums
        record.generation_duration_seconds = generation_duration
        record.updated_at = datetime.now(UTC)
        record.last_validated_at = datetime.now(UTC)

        await self.db.flush()
        return self._to_metadata(record)

    async def archive(self, dataset_id: UUID) -> bool:
        """Archive a dataset."""
        result = await self.db.execute(
            select(DatasetRecord).where(DatasetRecord.id == dataset_id)
        )
        record = result.scalar_one_or_none()
        if not record:
            return False

        record.status = DatasetStatus.ARCHIVED.value
        record.archived_at = datetime.now(UTC)
        record.updated_at = datetime.now(UTC)
        await self.db.flush()
        return True

    async def delete(self, dataset_id: UUID) -> bool:
        """Hard delete a dataset (use with caution)."""
        result = await self.db.execute(
            select(DatasetRecord).where(DatasetRecord.id == dataset_id)
        )
        record = result.scalar_one_or_none()
        if not record:
            return False

        await self.db.delete(record)
        await self.db.flush()
        return True

    def _to_metadata(self, record: DatasetRecord) -> DatasetMetadata:
        """Convert ORM record to Pydantic metadata."""
        return DatasetMetadata(
            id=record.id,
            version=record.version,
            name=record.name,
            description=record.description,
            size=DatasetSize(record.size),
            seed=record.seed,
            schema_version=SchemaVersion(record.schema_version),
            status=DatasetStatus(record.status),
            generation_params=record.generation_params,
            generation_duration_seconds=record.generation_duration_seconds,
            generated_by=record.generated_by,
            generator_version=record.generator_version,
            statistics=record.statistics,
            scenarios=record.scenarios,
            label_coverage=record.label_coverage,
            checksums=record.checksums,
            created_at=record.created_at,
            updated_at=record.updated_at,
            last_validated_at=record.last_validated_at,
            archived_at=record.archived_at,
            storage_path=record.storage_path,
            storage_size_bytes=record.storage_size_bytes,
            parent_dataset_id=record.parent_dataset_id,
            tags=record.tags,
        )


from sqlalchemy import func  # noqa: E402

__all__ = ["DatasetRecord", "DatasetRegistry"]
