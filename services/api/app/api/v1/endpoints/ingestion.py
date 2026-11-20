"""Import routes: preview, batches, source rows and provenance."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, Query, Response, UploadFile, status

from app.api.deps import PaginationDep, SessionDep, SettingsDep, WorkspaceDep
from app.models.enums import (
    BatchStatus,
    CanonicalEntityType,
    IngestionEntityType,
    RowStatus,
)
from app.models.ingestion import IngestionBatch, IngestionRow
from app.models.limits import SHEET_NAME_MAX
from app.schemas.common import ERROR_RESPONSES, ErrorResponse
from app.schemas.ingestion import (
    BatchDetailResponse,
    BatchListResponse,
    BatchRead,
    CommitResponse,
    EntityCounts,
    PreviewResponse,
    RowIssue,
    RowListResponse,
    RowRead,
    SourceListResponse,
    SourceRowRead,
)
from app.services import ingestion_service

router = APIRouter(prefix="/workspaces/{workspace_id}/ingestion", tags=["ingestion"])

UPLOAD_ERRORS = {
    **ERROR_RESPONSES,
    413: {"model": ErrorResponse, "description": "The upload exceeds the size limit."},
    415: {"model": ErrorResponse, "description": "The upload is not a CSV or XLSX file."},
    429: {"model": ErrorResponse, "description": "The XLSX reader is occupied. Retry the request shortly."},
}


def _batch(batch: IngestionBatch) -> BatchRead:
    return BatchRead.model_validate(batch)


def _row(row: IngestionRow) -> RowRead:
    return RowRead.model_validate(row)


@router.post(
    "/preview",
    response_model=PreviewResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload, parse, validate and preview a file",
    description=(
        "Writes the batch and one ledger row per source row. No project, supplier, "
        "equipment, purchase order, line item, milestone or commitment is created or changed."
    ),
    responses={
        **UPLOAD_ERRORS,
        status.HTTP_200_OK: {
            "model": PreviewResponse,
            "description": "The same bytes were already submitted; the existing batch is returned.",
        },
    },
)
def preview_import(
    workspace: WorkspaceDep,
    session: SessionDep,
    settings: SettingsDep,
    response: Response,
    file: Annotated[UploadFile, File(description="A CSV (UTF-8, comma-separated) or XLSX file.")],
    entity_type: Annotated[IngestionEntityType, Form(description="What the file describes.")],
    sheet_name: Annotated[
        str | None,
        Form(
            max_length=SHEET_NAME_MAX,
            description="Worksheet to read. Required when a workbook has several sheets with data.",
        ),
    ] = None,
) -> PreviewResponse:
    limits = ingestion_service.ImportLimits.from_settings(settings)
    # The request body is already capped by the upload guard; one byte more
    # than the limit is enough to know the file is too large.
    data = file.file.read(limits.max_upload_bytes + 1)
    upload = ingestion_service.UploadedFile(
        filename=file.filename or "", content_type=file.content_type, data=data
    )
    result = ingestion_service.preview_import(
        session,
        workspace.workspace_id,
        upload,
        entity_type,
        sheet_name.strip() if sheet_name and sheet_name.strip() else None,
        limits=limits,
    )
    if not result.created:
        response.status_code = status.HTTP_200_OK
    batch = result.batch
    return PreviewResponse(
        batch_id=batch.id,
        status=batch.status,
        entity_type=batch.entity_type,
        original_filename=batch.original_filename,
        source_format=batch.source_format,
        sheet_name=batch.sheet_name,
        file_sha256=batch.file_sha256,
        duplicate_file=result.duplicate_file,
        total_rows=batch.total_rows,
        valid_rows=batch.valid_rows,
        invalid_rows=batch.invalid_rows,
        planned_actions=dict(result.planned_actions),
        errors_count=result.errors_count,
        warnings_count=result.warnings_count,
        quality=dict(result.quality),
        errors=[RowIssue.model_validate(issue) for issue in result.errors],
        warnings=[RowIssue.model_validate(issue) for issue in result.warnings],
        truncated=result.truncated,
    )


@router.get("/batches", response_model=BatchListResponse, summary="List ingestion batches")
def list_batches(
    workspace: WorkspaceDep,
    session: SessionDep,
    page: PaginationDep,
    batch_status: Annotated[BatchStatus | None, Query(alias="status")] = None,
    entity_type: Annotated[IngestionEntityType | None, Query()] = None,
) -> BatchListResponse:
    result = ingestion_service.list_batches(
        session,
        workspace.workspace_id,
        limit=page.limit,
        offset=page.offset,
        status=batch_status,
        entity_type=entity_type,
    )
    return BatchListResponse(
        items=[_batch(item) for item in result.items],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )


@router.get(
    "/sources",
    response_model=SourceListResponse,
    summary="Source rows behind one canonical record",
    description="Answers which file and which row supplied a record, and what happened to the row.",
)
def list_sources(
    workspace: WorkspaceDep,
    session: SessionDep,
    page: PaginationDep,
    entity_type: Annotated[CanonicalEntityType, Query()],
    entity_id: Annotated[UUID, Query()],
) -> SourceListResponse:
    result = ingestion_service.list_sources(
        session,
        workspace.workspace_id,
        entity_type.value,
        entity_id,
        limit=page.limit,
        offset=page.offset,
    )
    return SourceListResponse(
        items=[
            SourceRowRead(
                batch_id=item.batch.id,
                original_filename=item.batch.original_filename,
                file_sha256=item.batch.file_sha256,
                source_format=item.batch.source_format,
                entity_type=item.batch.entity_type,
                batch_status=item.batch.status,
                committed_at=item.batch.committed_at,
                row_id=item.row.id,
                row_number=item.row.row_number,
                row_status=item.row.status,
                outcome=item.row.outcome,
            )
            for item in result.items
        ],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )


@router.get(
    "/{batch_id}",
    response_model=BatchDetailResponse,
    summary="Retrieve a batch and its row outcomes",
)
def get_batch(
    workspace: WorkspaceDep,
    session: SessionDep,
    batch_id: UUID,
    page: PaginationDep,
    row_status: Annotated[RowStatus | None, Query(alias="status")] = None,
) -> BatchDetailResponse:
    detail = ingestion_service.get_batch(
        session,
        workspace.workspace_id,
        batch_id,
        limit=page.limit,
        offset=page.offset,
        status=row_status,
    )
    return BatchDetailResponse(
        **_batch(detail.batch).model_dump(),
        rows=RowListResponse(
            items=[_row(row) for row in detail.rows.items],
            total=detail.rows.total,
            limit=detail.rows.limit,
            offset=detail.rows.offset,
        ),
    )


@router.post(
    "/{batch_id}/commit",
    response_model=CommitResponse,
    summary="Commit the valid rows of a previewed batch",
    description=(
        "All valid rows are applied in one transaction, or none. Committing a batch that "
        "is already committed returns the recorded result and writes nothing."
    ),
)
def commit_import(workspace: WorkspaceDep, session: SessionDep, batch_id: UUID) -> CommitResponse:
    result = ingestion_service.commit_import(session, workspace.workspace_id, batch_id)
    batch = result.batch
    assert batch.committed_at is not None
    recorded = (batch.commit_summary or {}).get("entities", {})
    return CommitResponse(
        batch_id=batch.id,
        status=batch.status,
        entity_type=batch.entity_type,
        replayed=result.replayed,
        total_rows=batch.total_rows,
        valid_rows=batch.valid_rows,
        invalid_rows=batch.invalid_rows,
        committed_rows=batch.committed_rows,
        skipped_rows=batch.skipped_rows,
        failed_rows=batch.failed_rows,
        entities={kind: EntityCounts(**counts) for kind, counts in recorded.items()},
        committed_at=batch.committed_at,
    )
