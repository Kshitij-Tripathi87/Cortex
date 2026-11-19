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

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import ClaimState
from app.config import get_settings
from app.infrastructure.database import get_db
from app.infrastructure.security import AuthContext, get_current_user, require_workspace_access
from app.modules.audit.service import emit as emit_audit
from app.modules.compiler.column_review import (
    ColumnReviewError,
    decide_columns,
    describe_file,
)
from app.modules.compiler.models import EvidenceClaim, EvidenceConflict
from app.modules.compiler.service import (
    SourceClaimLimitError,
    compute_readiness,
    detect_conflicts,
    extract_claims,
    resolve_conflict,
    row_entity_key,
)
from app.modules.graph.entity_keys import ENTITY_PRIMARY_KEYS, FACILITY_ENTITY_TYPES
from app.modules.nexus_spine.p0_migration.workspace_evidence import list_uploads
from app.modules.sources.models import SourceBatch, SourceFile
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


class UploadedFile(BaseModel):
    name: str
    rows: int | None


class BatchListItem(BaseModel):
    """One upload and where it stands between upload and publication."""

    batch_id: str
    files: list[UploadedFile]
    uploaded_at: str | None
    # published | ready_to_publish | review_required | blocked |
    # nothing_accepted | not_prepared
    state: str
    published_version: int | None
    claims_accepted: int
    claims_pending_review: int
    claims_rejected: int
    open_conflicts: int
    blocking_conflicts: int


class BatchListResponse(BaseModel):
    # Every upload of the workspace; ``batches`` lists the most recent ones.
    batch_count: int
    batches: list[BatchListItem]


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


class ClaimSummaryResponse(BaseModel):
    """How many values of a batch are in each state.

    ``total`` counts every value that matches the filters; the named states
    add up to it unless a value is in a state that has no field here.
    """

    total: int
    pending_review: int
    accepted: int
    rejected: int
    superseded: int


class ClaimReviewRequest(BaseModel):
    decision: Literal["accepted", "rejected"]
    rationale: str = Field(min_length=3, max_length=2000)
    canonical_entity: str | None = Field(default=None, min_length=1, max_length=64)
    canonical_field: str | None = Field(default=None, min_length=1, max_length=128)
    entity_key: str | None = Field(default=None, min_length=1, max_length=256)


class ReviewColumn(BaseModel):
    """One column of an uploaded file, as it stands."""

    source_column: str
    # The field its values are published under.
    canonical_field: str
    # "key": identifies the record of each row. "link": names another record.
    # "value": a plain field of the record.
    role: str
    # The kind of record a "link" column names.
    links_to: str | None
    # A few of its values, from the top of the file.
    examples: list[str]
    pending: int
    accepted: int
    rejected: int
    superseded: int
    # Waiting values that belong to an open conflict and are decided there.
    in_conflict: int


class ReviewFile(BaseModel):
    """A file of a batch: what its rows are and how each column is published."""

    file_id: str
    name: str
    rows: int | None
    # The kind of record each row describes; null when nothing says so yet.
    entity: str | None
    # "columns": recognised from the column names, as publishing does.
    # "review": set by an accepted decision on the identifying column.
    # "proposed": asked for with ``entity``, nothing accepted yet.
    entity_source: str | None
    key_field: str | None
    key_column: str | None
    # Why the file cannot be reviewed by column, when it cannot.
    problem: str | None
    columns: list[ReviewColumn]


class RecordKind(BaseModel):
    """A kind of record a file can hold, and the field that identifies one."""

    entity: str
    key_field: str


class ColumnReviewResponse(BaseModel):
    batch_id: str
    files: list[ReviewFile]
    record_kinds: list[RecordKind]


class ColumnDecisionRequest(BaseModel):
    """One decision for whole columns of one file."""

    decision: Literal["accepted", "rejected"]
    rationale: str = Field(min_length=3, max_length=2000)
    source_file_id: str = Field(min_length=1, max_length=36)
    # Left out: every column of the file.
    source_columns: list[str] | None = Field(default=None, max_length=2000)
    # For a file whose column names do not say what its rows are.
    canonical_entity: str | None = Field(default=None, min_length=1, max_length=64)
    # Source column -> the field it is published under, where that is not
    # the name its header gives.
    canonical_fields: dict[str, str] | None = None


class ColumnDecisionResponse(BaseModel):
    decision: str
    source_file_id: str
    canonical_entity: str | None
    # Column -> field it was accepted under; null for a rejected column.
    columns: dict[str, str | None]
    claims_decided: int
    claims_left_in_conflict: int
    conflicts_detected: int
    readiness: str
    explanation: str


class ConflictClaim(BaseModel):
    """One of the competing values of a conflict."""

    claim_id: str
    row_number: int
    source_column: str
    raw_value: str
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
    # The values that disagree, in file order, so that a conflict can be
    # shown and decided without the rest of the batch.
    claims: list[ConflictClaim] = Field(default_factory=list)


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


@router.get("/batches", response_model=BatchListResponse)
async def list_batches(
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> BatchListResponse:
    """Uploads of the workspace, newest first, each with its files and state.

    Without this list an upload could only be reopened by someone who had kept
    its address: the review page needs the batch ID and nothing showed it.
    """
    require_workspace_access(workspace_id, auth)
    uploads = await list_uploads(db, workspace_id)
    return BatchListResponse(
        batch_count=uploads["batch_count"],
        batches=[BatchListItem(**batch) for batch in uploads["batches"]],
    )


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


# The most values one request for a page may ask for.
CLAIM_PAGE_MAX = 500


def _claim_conditions(
    batch_id: str,
    workspace_id: str,
    *,
    claim_state: str | None = None,
    source_file_id: str | None = None,
    source_column: str | None = None,
    row_number: int | None = None,
    value: str | None = None,
) -> list[ColumnElement[bool]]:
    """The claims of a batch, narrowed the same way for a page and for its count."""
    conditions: list[ColumnElement[bool]] = [
        EvidenceClaim.batch_id == batch_id,
        EvidenceClaim.workspace_id == workspace_id,
    ]
    if claim_state is not None:
        conditions.append(EvidenceClaim.claim_state == claim_state)
    if source_file_id is not None:
        conditions.append(EvidenceClaim.source_file_id == source_file_id)
    if source_column is not None:
        conditions.append(EvidenceClaim.source_column == source_column)
    if row_number is not None:
        conditions.append(EvidenceClaim.row_number == row_number)
    if value is not None and value.strip():
        # The text as typed, anywhere in the value, whatever its case. "%"
        # and "_" are searched for as characters, not as wildcards.
        conditions.append(
            func.lower(EvidenceClaim.raw_value).contains(value.strip().lower(), autoescape=True)
        )
    return conditions


@router.get("/batches/{batch_id}/claims", response_model=list[ClaimResponse])
async def list_claims(
    batch_id: str,
    workspace_id: str,
    limit: int | None = Query(None, ge=1, le=CLAIM_PAGE_MAX),
    offset: int = Query(0, ge=0),
    claim_state: str | None = Query(None, max_length=32),
    source_file_id: str | None = Query(None, max_length=36),
    source_column: str | None = Query(None, max_length=256),
    row_number: int | None = Query(None, ge=0),
    value: str | None = Query(None, max_length=200),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> list[ClaimResponse]:
    """List evidence claims for a batch (workspace-scoped), in file order.

    A claim is one cell, so a file of 3,000 rows and eight columns has 24,000.
    With ``limit`` the list is read a page at a time, and it can be narrowed
    to a state, a file, a column, a row or a text the value contains. Without
    ``limit`` every claim is returned, as before. The order is file, row,
    then the order the cells were read in, and it does not change when a
    claim is decided.
    """
    require_workspace_access(workspace_id, auth)
    await _load_batch_for_workspace(db, batch_id, workspace_id)

    stmt = (
        select(EvidenceClaim)
        .where(
            *_claim_conditions(
                batch_id,
                workspace_id,
                claim_state=claim_state,
                source_file_id=source_file_id,
                source_column=source_column,
                row_number=row_number,
                value=value,
            )
        )
        .order_by(EvidenceClaim.source_file_id, EvidenceClaim.row_number, EvidenceClaim.claim_id)
    )
    if offset:
        stmt = stmt.offset(offset)
    if limit is not None:
        stmt = stmt.limit(limit)
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


@router.get("/batches/{batch_id}/claims/summary", response_model=ClaimSummaryResponse)
async def summarize_claims(
    batch_id: str,
    workspace_id: str,
    source_file_id: str | None = Query(None, max_length=36),
    source_column: str | None = Query(None, max_length=256),
    row_number: int | None = Query(None, ge=0),
    value: str | None = Query(None, max_length=200),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> ClaimSummaryResponse:
    """How many values of a batch wait, were accepted, rejected or withdrawn.

    Counted in the database, so the figures of a large batch do not need its
    claims to be read. The filters are those of the list, so a page can say
    how many values it is a part of.
    """
    require_workspace_access(workspace_id, auth)
    await _load_batch_for_workspace(db, batch_id, workspace_id)

    result = await db.execute(
        select(EvidenceClaim.claim_state, func.count(EvidenceClaim.claim_id))
        .where(
            *_claim_conditions(
                batch_id,
                workspace_id,
                source_file_id=source_file_id,
                source_column=source_column,
                row_number=row_number,
                value=value,
            )
        )
        .group_by(EvidenceClaim.claim_state)
    )
    counts = {str(state): int(count) for state, count in result.all()}
    return ClaimSummaryResponse(
        total=sum(counts.values()),
        pending_review=counts.get(ClaimState.PENDING_REVIEW.value, 0),
        accepted=counts.get(ClaimState.ACCEPTED.value, 0),
        rejected=counts.get(ClaimState.REJECTED.value, 0),
        superseded=counts.get(ClaimState.SUPERSEDED.value, 0),
    )


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

    # Locked, so that a decision on the whole column that is in flight is
    # finished before this one reads the state of the claim.
    claim_stmt = (
        select(EvidenceClaim)
        .where(EvidenceClaim.claim_id == claim_id)
        .where(EvidenceClaim.batch_id == batch_id)
        .where(EvidenceClaim.workspace_id == workspace_id)
        .with_for_update()
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
    if payload.entity_key is not None and not mapping_supplied:
        raise HTTPException(
            status_code=422,
            detail="entity_key requires a complete canonical entity and field mapping",
        )
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
            set(ENTITY_PRIMARY_KEYS) | set(FACILITY_ENTITY_TYPES) | {"Facility", "Organization"}
        )
        if payload.canonical_entity not in allowed_entities:
            raise HTTPException(status_code=422, detail="Unsupported canonical entity type")
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,127}", payload.canonical_field or ""):
            raise HTTPException(
                status_code=422, detail="canonical_field must be a lowercase snake_case identifier"
            )
        claim.canonical_entity = payload.canonical_entity
        claim.canonical_field = payload.canonical_field
        claim.confidence = 1.0
        claim.provenance = {
            **(claim.provenance or {}),
            "human_mapping_review": {
                "canonical_entity": payload.canonical_entity,
                "canonical_field": payload.canonical_field,
            },
            "entity_key": payload.entity_key or (claim.provenance or {}).get("entity_key"),
        }
    # An accepted claim is compared with other accepted claims about the same
    # record. The record is identified by the primary-key cell of the claim's
    # own source row unless the reviewer names it explicitly.
    entity_key_derived = False
    if payload.decision == ClaimState.ACCEPTED.value and not (claim.provenance or {}).get(
        "entity_key"
    ):
        derived_key = await row_entity_key(db, claim)
        if derived_key:
            claim.provenance = {**(claim.provenance or {}), "entity_key": derived_key}
            entity_key_derived = True
    claim.claim_state = payload.decision
    claim.requires_review = False
    await detect_conflicts(db, workspace_id, batch_id)
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
            "entity_key_supplied": payload.entity_key is not None,
            "entity_key_derived": entity_key_derived,
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


async def _files_of_batch(db: AsyncSession, batch_id: str, workspace_id: str) -> list[SourceFile]:
    result = await db.execute(
        select(SourceFile)
        .where(SourceFile.batch_id == batch_id)
        .where(SourceFile.workspace_id == workspace_id)
        .order_by(SourceFile.original_name, SourceFile.file_id)
    )
    return list(result.scalars().all())


@router.get("/batches/{batch_id}/columns", response_model=ColumnReviewResponse)
async def list_review_columns(
    batch_id: str,
    workspace_id: str,
    entity: str | None = None,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> ColumnReviewResponse:
    """The columns of a batch's files: what each means and how many values wait.

    A reviewer decides what a column means, not each of its cells. This is
    the view for that decision: the kind of record each row describes, the
    field every column is published under, which column identifies the record
    and which ones link it to another. ``entity`` shows the columns as they
    would be named for that kind of record; it is used only for a file whose
    column names do not say what its rows are.
    """
    require_workspace_access(workspace_id, auth)
    await _load_batch_for_workspace(db, batch_id, workspace_id)
    if entity is not None and entity not in ENTITY_PRIMARY_KEYS:
        raise HTTPException(status_code=422, detail="Unsupported kind of record")

    files: list[ReviewFile] = []
    for source_file in await _files_of_batch(db, batch_id, workspace_id):
        review = await describe_file(db, workspace_id, batch_id, source_file, entity)
        files.append(
            ReviewFile(
                file_id=review.file_id,
                name=review.name,
                rows=review.rows,
                entity=review.entity,
                entity_source=review.entity_source,
                key_field=review.key_field,
                key_column=review.key_column,
                problem=review.problem,
                columns=[
                    ReviewColumn(
                        source_column=column.source_column,
                        canonical_field=column.canonical_field,
                        role=column.role,
                        links_to=column.links_to,
                        examples=column.examples,
                        pending=column.pending,
                        accepted=column.accepted,
                        rejected=column.rejected,
                        superseded=column.superseded,
                        in_conflict=column.in_conflict,
                    )
                    for column in review.columns
                ],
            )
        )
    return ColumnReviewResponse(
        batch_id=batch_id,
        files=files,
        record_kinds=[
            RecordKind(entity=kind, key_field=key_field)
            for kind, key_field in sorted(ENTITY_PRIMARY_KEYS.items())
        ],
    )


@router.post("/batches/{batch_id}/columns/review", response_model=ColumnDecisionResponse)
async def review_columns_endpoint(
    batch_id: str,
    workspace_id: str,
    payload: ColumnDecisionRequest,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> ColumnDecisionResponse:
    """Record one audited decision for every waiting value of whole columns.

    Reviewing a file cell by cell is one decision per value. Here the
    reviewer accepts or rejects columns, or the whole file, in one decision
    with one rationale. Values that belong to an open conflict are left to
    the conflict; accepted values are compared with each other afterwards,
    so two rows that disagree about one record still block publishing.
    """
    require_workspace_access(workspace_id, auth)
    _require_claim_reviewer(auth)
    await _load_batch_for_workspace(db, batch_id, workspace_id)
    source_file = await get_file(db, payload.source_file_id)
    if (
        source_file is None
        or source_file.workspace_id != workspace_id
        or source_file.batch_id != batch_id
    ):
        raise HTTPException(status_code=404, detail="File not found in this batch")
    # Kept as text: a rollback below expires the record.
    file_id, file_name = source_file.file_id, source_file.original_name

    try:
        result = await decide_columns(
            db,
            workspace_id,
            batch_id,
            source_file,
            decision=payload.decision,
            source_columns=payload.source_columns,
            canonical_entity=payload.canonical_entity,
            canonical_fields=payload.canonical_fields,
        )
    except ColumnReviewError as exc:
        await db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    readiness = await compute_readiness(db, workspace_id, batch_id)
    await emit_audit(
        db,
        event_type="evidence.columns.reviewed",
        workspace_id=workspace_id,
        actor_id=auth.user_id or "unknown",
        actor_type="user",
        subject_type="SourceFile",
        subject_id=file_id,
        payload={
            "batch_id": batch_id,
            "decision": payload.decision,
            "rationale": payload.rationale,
            "source_file": file_name,
            "canonical_entity": result.canonical_entity,
            "columns": result.columns,
            "claims_decided": result.claims_decided,
            "claims_left_in_conflict": result.claims_left_in_conflict,
            "conflicts_detected": result.conflicts_detected,
        },
        message=(
            f"{result.claims_decided} values in {len(result.columns)} column(s) of "
            f"{file_name} {payload.decision}"
        ),
    )

    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return ColumnDecisionResponse(
        decision=result.decision,
        source_file_id=file_id,
        canonical_entity=result.canonical_entity,
        columns=result.columns,
        claims_decided=result.claims_decided,
        claims_left_in_conflict=result.claims_left_in_conflict,
        conflicts_detected=result.conflicts_detected,
        readiness=readiness.state,
        explanation=readiness.explanation,
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
        # Oldest first: the identifier starts with the time it was created.
        .order_by(EvidenceConflict.conflict_id)
    )
    result = await db.execute(stmt)
    conflicts = list(result.scalars().all())

    # The values of every conflict, read by identifier in portions: a
    # statement takes a limited number of parameters.
    wanted = sorted({str(claim_id) for c in conflicts for claim_id in (c.claim_ids or [])})
    values: dict[str, ConflictClaim] = {}
    for start in range(0, len(wanted), 2000):
        claim_result = await db.execute(
            select(EvidenceClaim)
            .where(EvidenceClaim.batch_id == batch_id)
            .where(EvidenceClaim.workspace_id == workspace_id)
            .where(EvidenceClaim.claim_id.in_(wanted[start : start + 2000]))
        )
        for claim in claim_result.scalars().all():
            values[claim.claim_id] = ConflictClaim(
                claim_id=claim.claim_id,
                row_number=claim.row_number,
                source_column=claim.source_column,
                raw_value=claim.raw_value,
                claim_state=claim.claim_state,
            )

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
            claims=sorted(
                (values[claim_id] for claim_id in (c.claim_ids or []) if claim_id in values),
                key=lambda claim: (claim.row_number, claim.claim_id),
            ),
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
    """Compile source rows into evidence claims, then assess conflicts/readiness."""
    require_workspace_access(workspace_id, auth)
    batch = await _load_batch_for_workspace(db, batch_id, workspace_id)

    from app.infrastructure.storage_client import get_storage
    from app.modules.sources.models import SourceFile
    from app.modules.sources.row_parser import SourceRowParseError, parse_source_rows

    file_stmt = (
        select(SourceFile)
        .where(SourceFile.batch_id == batch_id)
        .where(SourceFile.workspace_id == workspace_id)
    )
    file_result = await db.execute(file_stmt)
    files = list(file_result.scalars().all())

    claims_created = 0
    rows_compiled = 0
    claims_requiring_review = 0
    storage = get_storage()

    for source_file in files:
        if not source_file.profiled:
            continue
        profiles = await list_profiles(db, source_file.file_id)
        try:
            raw_bytes = await run_in_threadpool(storage.get_object, source_file.storage_key)
            raw_rows = await run_in_threadpool(
                parse_source_rows, raw_bytes, source_file.original_name
            )
        except SourceRowParseError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - retrieval failure is not a successful compile
            raise HTTPException(
                status_code=503, detail="Source artifact could not be retrieved"
            ) from exc

        try:
            result = await extract_claims(
                db, batch.workspace_id, batch_id, source_file.file_id, profiles, raw_rows
            )
        except SourceClaimLimitError as exc:
            # Nothing of the batch is prepared: the caller is told the size
            # and what to do, not handed an internal error. The message is
            # put together first; the rollback expires the file record.
            detail = (
                f"{source_file.original_name} holds {exc.values:,} values (rows times "
                f"columns, empty cells not counted). One file can hold at most "
                f"{exc.limit:,}. Split it into smaller files and upload each."
            )
            await db.rollback()
            raise HTTPException(status_code=413, detail=detail) from exc
        claims_created += result.claims_created
        claims_requiring_review += result.claims_requiring_review
        rows_compiled += len(raw_rows)

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
        "claims_requiring_review": claims_requiring_review,
        "rows_compiled": rows_compiled,
        "conflicts_detected": conflicts.conflicts_detected,
        "blocking_conflicts": conflicts.blocking_conflicts,
        "readiness": readiness.state,
        "explanation": readiness.explanation,
    }
