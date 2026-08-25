"""Sources API v1 — upload, batch status, profile, claims, conflicts, resolve.

Security posture
----------------
Every endpoint resolves a principal via :func:`get_current_user` and enforces
workspace access via :func:`require_workspace_access`. Cross-workspace reads
return 404 (rather than 403) to avoid leaking resource existence.

Uploads bound their in-memory read to ``settings.upload_max_bytes`` so a
malicious or oversized multipart payload cannot exhaust server memory.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.infrastructure.database import get_db
from app.infrastructure.security import AuthContext, get_current_user, require_workspace_access
from app.modules.compiler.models import EvidenceClaim, EvidenceConflict
from app.modules.compiler.service import (
    compute_readiness,
    detect_conflicts,
    extract_claims,
    resolve_conflict,
)
from app.modules.sources.models import SourceBatch
from app.modules.sources.service import get_batch, get_file, list_profiles, process_upload

router = APIRouter()


class UploadResponse(BaseModel):
    batch_id: str
    file_id: str
    status: str
    checksum: str
    is_duplicate: bool
    profiling_scheduled: bool


class BatchStatusResponse(BaseModel):
    batch_id: str
    workspace_id: str
    status: str
    file_count: int
    checksum: str
    source_system_hint: str


class FileProfileResponse(BaseModel):
    file_id: str
    original_name: str
    mime_type: str
    size: int
    row_count: int | None
    column_count: int | None
    profiled: bool
    columns: list[dict[str, Any]]


class ClaimResponse(BaseModel):
    claim_id: str
    source_column: str
    canonical_entity: str | None
    canonical_field: str | None
    raw_value: str
    normalized_value: str | None
    confidence: float
    claim_state: str


class ConflictResponse(BaseModel):
    conflict_id: str
    claim_ids: list[str]
    canonical_entity: str | None
    canonical_field: str | None
    severity: str
    blocking: bool
    status: str
    explanation: str


class ResolveRequest(BaseModel):
    """Payload for conflict resolution.

    ``rationale`` must be non-empty — humans must record a reason. ``action``
    is constrained to the known resolution verbs; anything else is a 422.
    """

    selected_claim_id: str | None = None
    action: Literal["approved", "rejected", "deferred", "merge"] = "approved"
    rationale: str = Field(min_length=1, max_length=2000)


class ReadinessResponse(BaseModel):
    state: str
    blocking_conflict_count: int
    open_conflict_count: int
    accepted_claim_count: int
    pending_claim_count: int
    assumptions: list[str]
    explanation: str


def _read_validated_size_or_reject(file: UploadFile) -> bytes:
    """Read ``file`` fully, rejecting payloads over the configured max size.

    ``UploadFile.read()`` streams into memory; without a bound a client can
    push a multi-GB body and OOM the worker. Re-checking size explicitly
    also defends against partial/spooofed Content-Length headers.
    """
    settings = get_settings()
    max_bytes = settings.upload_max_bytes
    contents = file.file.read(max_bytes + 1)
    if len(contents) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Upload exceeds maximum allowed size of {max_bytes} bytes",
        )
    return contents


async def _load_batch_for_workspace(
    db: AsyncSession, batch_id: str, workspace_id: str
) -> SourceBatch:
    """Fetch a batch, returning 404 if it does not exist or belongs to
    another workspace.

    Cross-workspace access is masked as 404 so a caller cannot probe for
    batch existence in workspaces they do not own.
    """
    batch = await get_batch(db, batch_id)
    if batch is None or batch.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Batch not found")
    return batch


@router.post("/upload", response_model=UploadResponse)
async def upload_source_file(
    workspace_id: str = Form(...),
    file: UploadFile = File(...),
    source_system_hint: str = Form(default="unknown"),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> UploadResponse:
    """Upload a source file (CSV/XLSX). Validates, stores immutably, profiles, and creates batch/file records."""
    require_workspace_access(workspace_id, auth)
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename required")

    contents = _read_validated_size_or_reject(file)

    try:
        result = await process_upload(
            db=db,
            workspace_id=workspace_id,
            uploader_id=auth.user_id,
            filename=file.filename,
            data=contents,
            declared_mime=file.content_type,
            source_system_hint=source_system_hint,
        )
        return UploadResponse(
            batch_id=result.batch_id,
            file_id=result.file_id,
            status=result.status,
            checksum=result.checksum,
            is_duplicate=result.is_duplicate,
            profiling_scheduled=result.profiling_scheduled,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/batches/{batch_id}", response_model=BatchStatusResponse)
async def get_batch_status(
    batch_id: str,
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> BatchStatusResponse:
    """Get batch status and metadata (workspace-scoped)."""
    require_workspace_access(workspace_id, auth)
    batch = await _load_batch_for_workspace(db, batch_id, workspace_id)
    return BatchStatusResponse(
        batch_id=batch.batch_id,
        workspace_id=batch.workspace_id,
        status=batch.status,
        file_count=batch.file_count,
        checksum=batch.checksum,
        source_system_hint=batch.source_system_hint,
    )


@router.get("/files/{file_id}/profile", response_model=FileProfileResponse)
async def get_file_profile(
    file_id: str,
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> FileProfileResponse:
    """Get file profiling results (workspace-scoped)."""
    require_workspace_access(workspace_id, auth)
    file = await get_file(db, file_id)
    if file is None or file.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="File not found")

    profiles = await list_profiles(db, file_id)
    columns = [
        {
            "column_name": p.column_name,
            "inferred_type": p.inferred_type,
            "null_ratio": p.null_ratio,
            "distinct_count": p.distinct_count,
            "sample_values": p.sample_values,
            "recommended_mapping": p.recommended_mapping,
            "mapping_confidence": p.mapping_confidence,
            "requires_review": p.requires_review,
        }
        for p in profiles
    ]

    return FileProfileResponse(
        file_id=file.file_id,
        original_name=file.original_name,
        mime_type=file.mime_type,
        size=file.size,
        row_count=file.row_count,
        column_count=file.column_count,
        profiled=file.profiled,
        columns=columns,
    )


@router.get("/batches/{batch_id}/claims", response_model=list[ClaimResponse])
async def list_claims(
    batch_id: str,
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> list[ClaimResponse]:
    """List evidence claims for a batch (workspace-scoped)."""
    require_workspace_access(workspace_id, auth)
    await _load_batch_for_workspace(db, batch_id, workspace_id)

    stmt = (
        select(EvidenceClaim)
        .where(EvidenceClaim.batch_id == batch_id)
        .where(EvidenceClaim.workspace_id == workspace_id)
    )
    result = await db.execute(stmt)
    claims = list(result.scalars().all())
    return [
        ClaimResponse(
            claim_id=c.claim_id,
            source_column=c.source_column,
            canonical_entity=c.canonical_entity,
            canonical_field=c.canonical_field,
            raw_value=c.raw_value,
            normalized_value=c.normalized_value,
            confidence=c.confidence,
            claim_state=c.claim_state,
        )
        for c in claims
    ]


@router.get("/batches/{batch_id}/conflicts", response_model=list[ConflictResponse])
async def list_conflicts(
    batch_id: str,
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> list[ConflictResponse]:
    """List conflicts for a batch (workspace-scoped)."""
    require_workspace_access(workspace_id, auth)
    await _load_batch_for_workspace(db, batch_id, workspace_id)

    stmt = (
        select(EvidenceConflict)
        .where(EvidenceConflict.batch_id == batch_id)
        .where(EvidenceConflict.workspace_id == workspace_id)
    )
    result = await db.execute(stmt)
    conflicts = list(result.scalars().all())
    return [
        ConflictResponse(
            conflict_id=c.conflict_id,
            claim_ids=c.claim_ids,
            canonical_entity=c.canonical_entity,
            canonical_field=c.canonical_field,
            severity=c.severity,
            blocking=c.blocking,
            status=c.status,
            explanation=c.explanation,
        )
        for c in conflicts
    ]


@router.post("/conflicts/{conflict_id}/resolve")
async def resolve_conflict_endpoint(
    conflict_id: str,
    workspace_id: str,
    payload: ResolveRequest,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, str]:
    """Resolve a conflict by selecting a claim or taking an action (workspace-scoped)."""
    require_workspace_access(workspace_id, auth)

    try:
        await resolve_conflict(
            db=db,
            workspace_id=workspace_id,
            conflict_id=conflict_id,
            selected_claim_id=payload.selected_claim_id,
            action=payload.action,
            rationale=payload.rationale,
            reviewer_id=auth.user_id or "unknown",
        )
    except NoResultFound as e:
        raise HTTPException(status_code=404, detail="Conflict not found") from e
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e

    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    return {"status": "resolved", "conflict_id": conflict_id}


@router.post("/batches/{batch_id}/compile")
async def compile_batch(
    batch_id: str,
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Compile a batch: extract claims, detect conflicts, compute readiness."""
    require_workspace_access(workspace_id, auth)
    batch = await _load_batch_for_workspace(db, batch_id, workspace_id)

    from app.modules.sources.models import SourceFile

    file_stmt = (
        select(SourceFile)
        .where(SourceFile.batch_id == batch_id)
        .where(SourceFile.workspace_id == workspace_id)
    )
    file_result = await db.execute(file_stmt)
    files = list(file_result.scalars().all())

    claims_created = 0
    for file in files:
        if file.profiled:
            profiles = await list_profiles(db, file.file_id)
            result = await extract_claims(db, batch.workspace_id, batch_id, file.file_id, profiles)
            claims_created += result.claims_created

    conflicts = await detect_conflicts(db, batch.workspace_id, batch_id)
    readiness = await compute_readiness(db, batch.workspace_id, batch_id)

    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return {
        "batch_id": batch_id,
        "claims_created": claims_created,
        "conflicts_detected": conflicts.conflicts_detected,
        "blocking_conflicts": conflicts.blocking_conflicts,
        "readiness": readiness.state,
        "explanation": readiness.explanation,
    }
