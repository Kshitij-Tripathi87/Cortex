"""Import contracts: preview, batches, source rows, commit result, provenance."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from app.models.enums import (
    BatchStatus,
    IngestionEntityType,
    PlannedAction,
    RowOutcome,
    RowStatus,
    SourceFormat,
)
from app.schemas.common import Page, ResponseModel


class FileIssue(ResponseModel):
    """A finding about the file as a whole."""

    code: str
    message: str
    column: str | None = None


class RowIssue(ResponseModel):
    """A finding about one source row. Names the row and the column, never the value."""

    row_number: int | None = Field(description="Physical row in the source file.")
    column: str | None = Field(
        default=None,
        description="Canonical field, or the source header for UNKNOWN_SOURCE_COLUMN.",
    )
    code: str
    message: str


class PreviewResponse(ResponseModel):
    batch_id: UUID
    status: BatchStatus
    entity_type: IngestionEntityType
    original_filename: str
    source_format: SourceFormat
    sheet_name: str | None
    file_sha256: str
    duplicate_file: bool = Field(
        description="True when the same bytes were already submitted for this entity type."
    )
    total_rows: int
    valid_rows: int
    invalid_rows: int
    planned_actions: dict[str, int] = Field(
        description="What a commit would do with the valid rows: CREATE, UPDATE, NO_CHANGE."
    )
    errors_count: int
    warnings_count: int
    quality: dict[str, int] = Field(
        description="Blocking errors by data-quality dimension. Counts, never a score."
    )
    errors: list[RowIssue] = Field(description="At most 100 entries; errors_count is complete.")
    warnings: list[RowIssue] = Field(description="At most 100 entries; warnings_count is complete.")
    truncated: bool


class BatchRead(ResponseModel):
    id: UUID
    entity_type: IngestionEntityType
    original_filename: str
    file_sha256: str
    source_format: SourceFormat
    sheet_name: str | None
    file_size_bytes: int
    status: BatchStatus
    total_rows: int
    valid_rows: int
    invalid_rows: int
    committed_rows: int
    skipped_rows: int
    failed_rows: int
    failure_code: str | None
    file_warnings: list[FileIssue]
    created_at: datetime
    committed_at: datetime | None


class BatchListResponse(Page[BatchRead]):
    """Batches, newest first."""


class StoredIssue(ResponseModel):
    code: str
    message: str
    column: str | None = None


class RowRead(ResponseModel):
    id: UUID
    row_number: int
    status: RowStatus
    planned_action: PlannedAction | None
    outcome: RowOutcome | None
    canonical_entity_type: str | None
    canonical_entity_id: UUID | None
    validation_errors: list[StoredIssue]
    warnings: list[StoredIssue]
    raw_data: dict[str, Any] = Field(description="The source values under their original headers.")
    normalized_data: dict[str, Any] = Field(description="The canonical values derived from them.")


class RowListResponse(Page[RowRead]):
    """Source rows in file order."""


class BatchDetailResponse(BatchRead):
    rows: RowListResponse


class EntityCounts(ResponseModel):
    created: int = 0
    updated: int = 0
    unchanged: int = 0


class CommitResponse(ResponseModel):
    batch_id: UUID
    status: BatchStatus
    entity_type: IngestionEntityType
    replayed: bool = Field(
        description="True when the batch was already committed and nothing was written now."
    )
    total_rows: int
    valid_rows: int
    invalid_rows: int
    committed_rows: int = Field(description="Rows that created or changed a canonical record.")
    skipped_rows: int = Field(
        description="Valid rows that changed nothing: already up to date, or a repeated row."
    )
    failed_rows: int
    entities: dict[str, EntityCounts] = Field(
        description="Canonical records touched, by kind of record."
    )
    committed_at: datetime


class SourceRowRead(ResponseModel):
    """One source row behind a canonical record, with the file it came in."""

    batch_id: UUID
    original_filename: str
    file_sha256: str
    source_format: SourceFormat
    entity_type: IngestionEntityType
    batch_status: BatchStatus
    committed_at: datetime | None
    row_id: UUID
    row_number: int
    row_status: RowStatus
    outcome: RowOutcome | None


class SourceListResponse(Page[SourceRowRead]):
    """Source rows, oldest batch first."""
