"""MVP ingestion API v1 — CSV upload + status.

Endpoints
---------
POST /api/v1/mvp/ingest
    multipart/form-data upload of a CSV file
    form fields: file (UploadFile), dataset_type (str), strict (bool, default false)
    Response 202 Accepted with ingestion_id

GET /api/v1/mvp/ingest/{ingestion_id}
    Status poll for an ingestion job.
    Response 200 with IngestionStatusResponse

Authentication
--------------
Uses the existing `get_current_user` dependency (header-based in dev/test,
JWT in pilot/prod). The workspace is taken from the `X-Workspace-Id`
header; in Week 3 the workspace claim moves into the JWT body. Until then
we validate via `require_workspace_access` for the auth context.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import MvpDatasetType
from app.common.workspace_scope import reset_workspace_scope, set_workspace_scope
from app.config import get_settings
from app.infrastructure.database import get_db
from app.infrastructure.security import (
    AuthContext,
    get_current_user,
    require_workspace_access,
)
from app.infrastructure.storage_client import ObjectStorageClient, get_storage
from app.modules.ingestion.repository import IngestionLogRepository
from app.modules.ingestion.service import ingest_csv_streaming

router = APIRouter()


class IngestionAccepted(BaseModel):
    ingestion_id: UUID
    status: str
    file_key: str
    file_size_bytes: int
    rows_total: int | None = Field(default=None, description="Populated on completion only")


class IngestionStatusResponse(BaseModel):
    ingestion_id: UUID
    workspace_id: UUID
    user_id: UUID | None
    dataset_type: str
    file_name: str
    file_size_bytes: int
    status: str
    rows_total: int
    rows_accepted: int
    rows_rejected: int
    started_at: datetime
    finished_at: datetime | None
    message: str | None = None
    errors: list = Field(default_factory=list, description="Truncated for response")


@router.post(
    "/ingest",
    response_model=IngestionAccepted,
    status_code=202,
    summary="Upload a CSV to ingest into MVP wedge tables.",
)
async def post_ingest(
    file: UploadFile = File(..., description="CSV file to ingest"),
    dataset_type: MvpDatasetType = Form(...),
    strict: bool = Form(False, description="If true, any error aborts the upload"),
    workspace_id: str = Form(..., description="Target workspace UUID"),
    auth: AuthContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    storage: ObjectStorageClient = Depends(get_storage),
) -> IngestionAccepted:
    """Receive a CSV upload, stream to S3, parse, validate, and insert rows.

    Returns 202 Accepted with the ingestion_id; the actual row processing
    happens synchronously during this request (no background queue in MVP).
    The GET status endpoint returns the finalised counts.
    """
    settings = get_settings()
    if file.size is not None and file.size > settings.upload_max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large (limit {settings.upload_max_bytes} bytes)",
        )

    try:
        workspace_uuid = UUID(workspace_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="workspace_id must be a UUID") from exc

    require_workspace_access(workspace_uuid, auth)

    file_name = file.filename or "upload.csv"
    user_uuid = UUID(auth.user_id) if auth.user_id and auth.user_id != "anonymous" else None

    token = set_workspace_scope(workspace_uuid)
    try:
        log = await ingest_csv_streaming(
            session=session,
            workspace_id=workspace_uuid,
            user_id=user_uuid,
            storage=storage,
            dataset_type=dataset_type,
            file=file,
            file_name=file_name,
            strict=strict,
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        reset_workspace_scope(token)

    return IngestionAccepted(
        ingestion_id=log.id,
        status=log.status,
        file_key=log.file_key,
        file_size_bytes=log.file_size_bytes,
        rows_total=log.rows_total if log.finished_at else None,
    )


@router.get(
    "/ingest/{ingestion_id}",
    response_model=IngestionStatusResponse,
    summary="Get the status and counts of an ingestion job.",
)
async def get_ingest(
    ingestion_id: UUID,
    workspace_id: str = ...,
    auth: AuthContext = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> IngestionStatusResponse:
    """Return the finalised ingestion record.

    `workspace_id` is required so the repository cannot leak across
    tenants. Status is read from `audit.ingestion_log`.
    """
    try:
        workspace_uuid = UUID(workspace_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="workspace_id must be a UUID") from exc

    require_workspace_access(workspace_uuid, auth)

    token = set_workspace_scope(workspace_uuid)
    try:
        repo = IngestionLogRepository(session, workspace_uuid)
        log = await repo.get(ingestion_id)
    finally:
        reset_workspace_scope(token)

    if log is None:
        raise HTTPException(status_code=404, detail="ingestion not found")

    return IngestionStatusResponse(
        ingestion_id=log.id,
        workspace_id=log.workspace_id,
        user_id=log.user_id,
        dataset_type=str(log.dataset_type),
        file_name=log.file_name,
        file_size_bytes=log.file_size_bytes,
        status=str(log.status),
        rows_total=log.rows_total,
        rows_accepted=log.rows_accepted,
        rows_rejected=log.rows_rejected,
        started_at=log.started_at,
        finished_at=log.finished_at,
        message=log.message,
        errors=list(log.error_log or [])[:50],
    )


__all__ = ["router"]
