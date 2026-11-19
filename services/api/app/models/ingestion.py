"""Ingestion ledger: one batch per uploaded file, one row per source row.

The ledger is the durable record of what a source said. Rows are never
deleted, valid or not, and a committed row points at the canonical record it
resulted in.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models import limits
from app.models._columns import CreatedAtMixin, UUIDPrimaryKeyMixin, enum_type
from app.models.enums import (
    BatchStatus,
    CanonicalEntityType,
    IngestionEntityType,
    PlannedAction,
    RowOutcome,
    RowStatus,
    SourceFormat,
)


def _in_list(column: str, values: type[CanonicalEntityType]) -> str:
    quoted = ", ".join(f"'{member.value}'" for member in values)
    return f"{column} IS NULL OR {column} IN ({quoted})"


class IngestionBatch(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "ingestion_batches"
    __table_args__ = (
        # The same bytes for the same entity type resolve to one batch. A
        # FAILED batch wrote nothing canonical and does not block a new
        # attempt with the same file.
        Index(
            "uq_ingestion_batches_active_checksum",
            "workspace_id",
            "entity_type",
            "file_sha256",
            unique=True,
            postgresql_where=text("status <> 'FAILED'"),
        ),
        Index("ix_ingestion_batches_workspace_id_created_at", "workspace_id", "created_at"),
        CheckConstraint("file_sha256 ~ '^[0-9a-f]{64}$'", name="file_sha256_format"),
        CheckConstraint("file_size_bytes > 0", name="file_size_positive"),
        CheckConstraint(
            "total_rows >= 0 AND valid_rows >= 0 AND invalid_rows >= 0 "
            "AND committed_rows >= 0 AND skipped_rows >= 0 AND failed_rows >= 0",
            name="counters_not_negative",
        ),
        CheckConstraint("valid_rows + invalid_rows = total_rows", name="preview_counters_add_up"),
        CheckConstraint(
            "(status = 'COMMITTED') = (committed_at IS NOT NULL)", name="committed_at_iff_committed"
        ),
        CheckConstraint(
            "(status = 'FAILED') = (failure_code IS NOT NULL)", name="failure_code_iff_failed"
        ),
        CheckConstraint("jsonb_typeof(file_warnings) = 'array'", name="file_warnings_is_array"),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id"))
    entity_type: Mapped[IngestionEntityType] = mapped_column(
        enum_type(IngestionEntityType, "entity_type")
    )
    # Display metadata only. Never used to build a filesystem path.
    original_filename: Mapped[str] = mapped_column(String(limits.FILENAME_MAX))
    file_sha256: Mapped[str] = mapped_column(String(64))
    source_format: Mapped[SourceFormat] = mapped_column(enum_type(SourceFormat, "source_format"))
    file_size_bytes: Mapped[int] = mapped_column(Integer)
    sheet_name: Mapped[str | None] = mapped_column(String(limits.SHEET_NAME_MAX))
    # Findings about the file as a whole (skipped blank rows, formula cells...).
    file_warnings: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    status: Mapped[BatchStatus] = mapped_column(enum_type(BatchStatus, "status"))
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, default=0)
    invalid_rows: Mapped[int] = mapped_column(Integer, default=0)
    committed_rows: Mapped[int] = mapped_column(Integer, default=0)
    skipped_rows: Mapped[int] = mapped_column(Integer, default=0)
    failed_rows: Mapped[int] = mapped_column(Integer, default=0)
    # The recorded result of the commit, returned as-is when a commit is replayed.
    commit_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(64))


class IngestionRow(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "ingestion_rows"
    __table_args__ = (
        UniqueConstraint("batch_id", "row_number", name="uq_ingestion_rows_batch_id_row_number"),
        CheckConstraint("row_number > 0", name="row_number_positive"),
        CheckConstraint(
            "(canonical_entity_type IS NULL) = (canonical_entity_id IS NULL)",
            name="canonical_link_complete",
        ),
        CheckConstraint(
            _in_list("canonical_entity_type", CanonicalEntityType),
            name="canonical_entity_type_allowed",
        ),
        # A committed source row always points at the record it produced.
        CheckConstraint(
            "status <> 'COMMITTED' OR canonical_entity_id IS NOT NULL",
            name="committed_row_has_canonical_link",
        ),
        CheckConstraint("jsonb_typeof(raw_data) = 'object'", name="raw_data_is_object"),
        CheckConstraint(
            "jsonb_typeof(normalized_data) = 'object'", name="normalized_data_is_object"
        ),
        CheckConstraint(
            "jsonb_typeof(validation_errors) = 'array'", name="validation_errors_is_array"
        ),
        CheckConstraint("jsonb_typeof(warnings) = 'array'", name="warnings_is_array"),
        Index("ix_ingestion_rows_batch_id_status", "batch_id", "status"),
        # "Which source rows are behind this record?"
        Index("ix_ingestion_rows_canonical_entity", "canonical_entity_type", "canonical_entity_id"),
    )

    batch_id: Mapped[UUID] = mapped_column(ForeignKey("ingestion_batches.id"))
    # Physical row number in the source file (the header is row 1 in a plain CSV).
    row_number: Mapped[int] = mapped_column(Integer)
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    normalized_data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    validation_errors: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    warnings: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    status: Mapped[RowStatus] = mapped_column(enum_type(RowStatus, "status"))
    planned_action: Mapped[PlannedAction | None] = mapped_column(
        enum_type(PlannedAction, "planned_action")
    )
    outcome: Mapped[RowOutcome | None] = mapped_column(enum_type(RowOutcome, "outcome"))
    # Polymorphic link to the canonical record. It cannot be a foreign key
    # (seven target tables); the ingestion service sets it only to a record it
    # created or resolved in the same workspace and transaction.
    canonical_entity_type: Mapped[str | None] = mapped_column(String(40))
    canonical_entity_id: Mapped[UUID | None] = mapped_column(Uuid)
