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

import re
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import ClaimState
from app.config import get_settings
from app.infrastructure.database import get_db
from app.infrastructure.security import AuthContext, get_current_user, require_workspace_access
from app.modules.audit.service import emit as emit_audit
from app.modules.compiler.models import EvidenceClaim, EvidenceConflict
from app.modules.compiler.service import (
    compute_readiness,
    detect_conflicts,
    extract_claims,
    resolve_conflict,
)
from app.modules.graph.entity_keys import ENTITY_PRIMARY_KEYS, FACILITY_ENTITY_TYPES
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
    workspace_id: str
    source_file_id: str
    batch_id: str
    row_number: int
    source_column: str
    canonical_entity: str | None
    canonical_field: str | None
    raw_value: str
    normalized_value: str | None
    confidence: float
    claim_state: str
    requires_review: bool
    created_at: str


class ClaimReviewRequest(BaseModel):
    decision: Literal["accepted", "rejected"]
    rationale: str = Field(min_length=3, max_length=2000)
    canonical_entity: str | None = Field(default=None, min_length=1, max_length=64)
    canonical_field: str | None = Field(default=None, min_length=1, max_length=128)


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
    action: Literal["approved", "rejected", "suppressed", "escalated"] = "approved"
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
            workspace_id=c.workspace_id,
            source_file_id=c.source_file_id,
            batch_id=c.batch_id,
            row_number=c.row_number,
            source_column=c.source_column,
            canonical_entity=c.canonical_entity,
            canonical_field=c.canonical_field,
            raw_value=c.raw_value,
            normalized_value=c.normalized_value,
            confidence=c.confidence,
            claim_state=c.claim_state,
            requires_review=c.requires_review,
            created_at=c.created_at.isoformat(),
        )
        for c in claims
    ]


def _require_claim_reviewer(auth: AuthContext) -> None:
    """Only workspace admins and operators may accept or reject source claims."""
    allowed_roles = {
        "admin",
        "operator",
        "system_admin",
        "workspace_admin",
        "operations_manager",
    }
    if auth.is_anonymous or not allowed_roles.intersection(auth.roles):
        raise HTTPException(
            status_code=403,
            detail={
                "error": "forbidden",
                "message": "Admin or operator role required to review evidence claims",
                "required_roles": sorted(allowed_roles),
            },
        )


@router.post("/batches/{batch_id}/claims/{claim_id}/review", response_model=ClaimResponse)
async def review_claim_endpoint(
    batch_id: str,
    claim_id: str,
    workspace_id: str,
    payload: ClaimReviewRequest,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> ClaimResponse:
    """Record an explicit, audited human decision for a pending source claim."""
    require_workspace_access(workspace_id, auth)
    _require_claim_reviewer(auth)
    await _load_batch_for_workspace(db, batch_id, workspace_id)

    claim_stmt = (
        select(EvidenceClaim)
        .where(EvidenceClaim.claim_id == claim_id)
        .where(EvidenceClaim.batch_id == batch_id)
        .where(EvidenceClaim.workspace_id == workspace_id)
    )
    claim_result = await db.execute(claim_stmt)
    claim = claim_result.scalar_one_or_none()
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")

    if claim.claim_state != ClaimState.PENDING_REVIEW.value:
        raise HTTPException(
            status_code=409,
            detail=f"Claim is already {claim.claim_state}; only pending claims can be reviewed",
        )

    open_conflict_stmt = (
        select(EvidenceConflict)
        .where(EvidenceConflict.workspace_id == workspace_id)
        .where(EvidenceConflict.batch_id == batch_id)
        .where(EvidenceConflict.status.in_(["open", "escalated"]))
    )
    open_conflict_result = await db.execute(open_conflict_stmt)
    open_conflicts = list(open_conflict_result.scalars().all())
    if any(claim_id in conflict.claim_ids for conflict in open_conflicts):
        raise HTTPException(
            status_code=409,
            detail="Resolve the claim's open or escalated conflict in Conflict Center before reviewing it",
        )

    mapping_supplied = payload.canonical_entity is not None or payload.canonical_field is not None
    if mapping_supplied and (not payload.canonical_entity or not payload.canonical_field):
        raise HTTPException(
            status_code=422,
            detail="canonical_entity and canonical_field must be supplied together",
        )
    if (
        payload.decision == ClaimState.ACCEPTED.value
        and not mapping_supplied
        and (not claim.canonical_entity or not claim.canonical_field)
    ):
        raise HTTPException(
            status_code=422,
            detail="This claim has no complete canonical mapping. Supply canonical_entity and canonical_field before accepting it.",
        )
    if mapping_supplied:
        allowed_entities = (
            set(ENTITY_PRIMARY_KEYS)
            | set(FACILITY_ENTITY_TYPES)
            | {"Facility", "Organization"}
        )
        if payload.canonical_entity not in allowed_entities:
            raise HTTPException(status_code=422, detail="Unsupported canonical entity type")
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,127}", payload.canonical_field or ""):
            raise HTTPException(status_code=422, detail="canonical_field must be a lowercase snake_case identifier")
        claim.canonical_entity = payload.canonical_entity
        claim.canonical_field = payload.canonical_field
        claim.confidence = 1.0
        claim.provenance = {
            **(claim.provenance or {}),
            "human_mapping_review": {
                "canonical_entity": payload.canonical_entity,
                "canonical_field": payload.canonical_field,
            },
        }
    claim.claim_state = payload.decision
    claim.requires_review = False
    await emit_audit(
        db,
        event_type="evidence.claim.reviewed",
        workspace_id=workspace_id,
        actor_id=auth.user_id or "unknown",
        actor_type="user",
        subject_type="EvidenceClaim",
        subject_id=claim.claim_id,
        payload={
            "batch_id": batch_id,
            "decision": payload.decision,
            "rationale": payload.rationale,
            "source_file_id": claim.source_file_id,
            "source_column": claim.source_column,
            "confidence": claim.confidence,
            "canonical_entity": claim.canonical_entity,
            "canonical_field": claim.canonical_field,
        },
        message=f"Evidence claim {claim.claim_id} {payload.decision}",
    )

    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return ClaimResponse(
        claim_id=claim.claim_id,
        workspace_id=claim.workspace_id,
        source_file_id=claim.source_file_id,
        batch_id=claim.batch_id,
        row_number=claim.row_number,
        source_column=claim.source_column,
        canonical_entity=claim.canonical_entity,
        canonical_field=claim.canonical_field,
        raw_value=claim.raw_value,
        normalized_value=claim.normalized_value,
        confidence=claim.confidence,
        claim_state=claim.claim_state,
        requires_review=claim.requires_review,
        created_at=claim.created_at.isoformat(),
    )


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
    _require_claim_reviewer(auth)

    try:
        resolution = await resolve_conflict(
            db=db,
            workspace_id=workspace_id,
            conflict_id=conflict_id,
            selected_claim_id=payload.selected_claim_id,
            action=payload.action,
            rationale=payload.rationale,
            reviewer_id=auth.user_id or "unknown",
        )
        await emit_audit(
            db,
            event_type="evidence.conflict.reviewed",
            workspace_id=workspace_id,
            actor_id=auth.user_id or "unknown",
            actor_type="user",
            subject_type="EvidenceConflict",
            subject_id=conflict_id,
            payload={
                "resolution_id": resolution.resolution_id,
                "selected_claim_id": payload.selected_claim_id,
                "action": payload.action,
                "rationale": payload.rationale,
            },
            message=f"Evidence conflict {conflict_id}: {payload.action}",
        )
        await db.commit()
    except NoResultFound as exc:
        await db.rollback()
        raise HTTPException(status_code=404, detail="Conflict not found") from exc
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception:
        await db.rollback()
        raise
    return {
        "status": "recorded",
        "conflict_id": conflict_id,
        "resolution_id": resolution.resolution_id,
        "action": payload.action,
    }


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
