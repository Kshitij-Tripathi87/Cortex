"""IngestionLog ORM model — audit.ingestion_log table.

Records every CSV upload attempt: file metadata, S3 storage key, run
status, row counts (total/accepted/rejected), started/finished timestamps,
and a JSON error_log listing per-row failures. The endpoint
`GET /api/v1/mvp/ingest/{ingestion_id}` reads from this table.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.enums import IngestionStatus, MvpDatasetType
from app.common.ids import uuid7_uuid
from app.infrastructure.database import Base


def _now() -> datetime:
    return datetime.now(UTC)


class IngestionLog(Base):
    __tablename__ = "ingestion_log"
    __table_args__ = (
        Index("ix_ingestion_log_workspace_status", "workspace_id", "status"),
        Index("ix_ingestion_log_workspace_started_at", "workspace_id", "started_at"),
        {"schema": "audit"},
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
    dataset_type: Mapped[MvpDatasetType] = mapped_column(String(32), nullable=False)
    file_name: Mapped[str] = mapped_column(String(512), nullable=False)
    file_key: Mapped[str] = mapped_column(String(1024), nullable=False, comment="S3 object key")
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[IngestionStatus] = mapped_column(
        String(32), nullable=False, default=IngestionStatus.RECEIVED
    )
    rows_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_accepted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_rejected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_log: Mapped[list] = mapped_column(JSON, nullable=False, default=list)


__all__ = ["IngestionLog"]
