"""Source module DB models — SourceBatch, SourceFile, SourceColumnProfile."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.common.enums import SourceBatchStatus, SourceSystemHint
from app.common.ids import uuid7
from app.infrastructure.database import Base


class SourceBatch(Base):
    __tablename__ = "source_batches"

    batch_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    uploader_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=SourceBatchStatus.RECEIVED.value
    )
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    source_system_hint: Mapped[str] = mapped_column(
        String(32), nullable=False, default=SourceSystemHint.UNKNOWN.value
    )
    job_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=lambda: datetime.now(UTC))
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )


class SourceFile(Base):
    __tablename__ = "source_files"

    file_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    batch_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    original_name: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=lambda: datetime.now(UTC))
    profiled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    encoding: Mapped[str | None] = mapped_column(String(32), nullable=True)
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    column_count: Mapped[int | None] = mapped_column(Integer, nullable=True)


class SourceColumnProfile(Base):
    __tablename__ = "source_column_profiles"

    profile_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    file_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    column_name: Mapped[str] = mapped_column(String(256), nullable=False)
    column_index: Mapped[int] = mapped_column(Integer, nullable=False)
    inferred_type: Mapped[str] = mapped_column(String(32), nullable=False)
    null_ratio: Mapped[float] = mapped_column(nullable=False)
    distinct_count: Mapped[int] = mapped_column(Integer, nullable=False)
    sample_values: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    recommended_mapping: Mapped[str | None] = mapped_column(String(128), nullable=True)
    mapping_confidence: Mapped[float | None] = mapped_column(nullable=True)
    requires_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
