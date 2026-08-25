"""Sources service — orchestrate upload → validate → store → profile → lineage → job."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import SourceBatchStatus, SourceSystemHint
from app.common.ids import uuid7
from app.modules.audit.service import emit as emit_audit
from app.modules.sources.models import SourceBatch, SourceColumnProfile, SourceFile
from app.modules.sources.profiler import FileProfileResult, profile_csv, profile_xlsx
from app.modules.sources.storage import SourceStorage, compute_checksum
from app.modules.sources.validation import validate_upload

if TYPE_CHECKING:
    from app.infrastructure.storage_client import ObjectStorageClient


@dataclass(frozen=True)
class UploadResult:
    batch_id: str
    file_id: str
    status: str
    checksum: str
    is_duplicate: bool
    profiling_scheduled: bool


async def process_upload(
    db: AsyncSession,
    workspace_id: str,
    uploader_id: str | None,
    filename: str,
    data: bytes,
    declared_mime: str | None = None,
    source_system_hint: str = SourceSystemHint.UNKNOWN.value,
    storage_client: ObjectStorageClient | None = None,
) -> UploadResult:
    """Process a file upload end-to-end: validate, store, create batch/file records, schedule profiling.

    A real :class:`ObjectStorageClient` must be supplied. When ``storage_client``
    is ``None`` and no real client can be resolved from the infrastructure
    registry, a ``RuntimeError`` is raised before any DB write happens — so
    callers cannot accidentally persist batch records pointing at a phantom
    storage blob.
    """
    # 1. Validate
    validation = validate_upload(data, filename, declared_mime)
    if not validation.valid:
        await emit_audit(
            db,
            event_type="upload.rejected",
            workspace_id=workspace_id,
            actor_id=uploader_id,
            subject_type="SourceFile",
            payload={"filename": filename, "errors": validation.errors},
            message=f"Upload rejected: {', '.join(validation.errors)}",
        )
        await db.commit()
        raise ValueError(f"Validation failed: {validation.errors}")

    # 2. Compute checksum and store
    checksum = compute_checksum(data)
    if storage_client is None:
        try:
            from app.infrastructure.storage_client import get_storage

            storage_client = get_storage()
        except Exception as exc:
            raise RuntimeError("Object storage is not configured; cannot accept uploads") from exc
    storage = SourceStorage(storage_client)
    stored = storage.put(workspace_id, data)

    # 3. Create or retrieve batch (dedupe by checksum within workspace)
    existing_batch_stmt = (
        select(SourceBatch)
        .where(SourceBatch.workspace_id == workspace_id)
        .where(SourceBatch.checksum == checksum)
    )
    existing_batch_result = await db.execute(existing_batch_stmt)
    existing_batch = existing_batch_result.scalar_one_or_none()

    if existing_batch:
        # Duplicate upload — return existing batch info
        return UploadResult(
            batch_id=existing_batch.batch_id,
            file_id="",  # No new file created
            status=existing_batch.status,
            checksum=checksum,
            is_duplicate=True,
            profiling_scheduled=False,
        )

    # 4. Create new batch
    batch = SourceBatch(
        batch_id=uuid7(),
        workspace_id=workspace_id,
        uploader_id=uploader_id,
        status=SourceBatchStatus.VALIDATED.value,
        checksum=checksum,
        source_system_hint=source_system_hint,
        file_count=1,
    )
    db.add(batch)
    await db.flush()

    # 5. Create file record
    file = SourceFile(
        file_id=uuid7(),
        batch_id=batch.batch_id,
        workspace_id=workspace_id,
        storage_key=stored.storage_key,
        original_name=filename,
        mime_type=validation.mime_type,
        size=stored.size,
        checksum=checksum,
        encoding=validation.encoding,
    )
    db.add(file)
    await db.flush()

    # 6. Emit audit event
    await emit_audit(
        db,
        event_type="upload.received",
        workspace_id=workspace_id,
        actor_id=uploader_id,
        subject_type="SourceFile",
        subject_id=file.file_id,
        payload={"filename": filename, "mime_type": validation.mime_type, "size": stored.size},
        message=f"Upload received: {filename}",
    )

    # 7. Profile synchronously (Phase 2 simplification; Phase 3+ can make async)
    await _profile_file(db, file, data, validation.file_kind, validation.encoding)

    # Persist the entire upload atomically. If profiling raised, this rollback
    # discards the partial batch/file/audit rows rather than leaving the upload
    # half-recorded.
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return UploadResult(
        batch_id=batch.batch_id,
        file_id=file.file_id,
        status=batch.status,
        checksum=checksum,
        is_duplicate=stored.is_duplicate,
        profiling_scheduled=True,
    )


async def _profile_file(
    db: AsyncSession,
    file: SourceFile,
    data: bytes,
    file_kind: str,
    encoding: str | None,
) -> FileProfileResult:
    """Profile a stored file and persist column profiles."""
    if file_kind == "csv":
        profile = profile_csv(data, encoding)
    elif file_kind == "xlsx":
        profile = profile_xlsx(data)
    else:
        raise ValueError(f"Unknown file kind: {file_kind}")

    file.profiled = True
    file.row_count = profile.row_count
    file.column_count = profile.column_count

    for col_idx, col_profile in enumerate(profile.columns):
        from app.modules.inference.rules_provider import suggest_mapping

        suggestion = suggest_mapping(col_profile.column_name)

        db_profile = SourceColumnProfile(
            profile_id=uuid7(),
            file_id=file.file_id,
            workspace_id=file.workspace_id,
            column_name=col_profile.column_name,
            column_index=col_idx,
            inferred_type=col_profile.inferred_type,
            null_ratio=col_profile.null_ratio,
            distinct_count=col_profile.distinct_count,
            sample_values=col_profile.sample_values,
            recommended_mapping=suggestion.canonical_field,
            mapping_confidence=suggestion.confidence,
            requires_review=suggestion.requires_review,
        )
        db.add(db_profile)

    await emit_audit(
        db,
        event_type="evidence.extracted",
        workspace_id=file.workspace_id,
        subject_type="SourceFile",
        subject_id=file.file_id,
        payload={"row_count": profile.row_count, "column_count": profile.column_count},
        message=f"Profiled {file.original_name}: {profile.row_count} rows, {profile.column_count} columns",
    )

    await db.flush()
    return profile


async def get_batch(db: AsyncSession, batch_id: str) -> SourceBatch | None:
    """Retrieve a source batch by ID."""
    return await db.get(SourceBatch, batch_id)


async def get_file(db: AsyncSession, file_id: str) -> SourceFile | None:
    """Retrieve a source file by ID."""
    return await db.get(SourceFile, file_id)


async def list_profiles(db: AsyncSession, file_id: str) -> list[SourceColumnProfile]:
    """List column profiles for a file."""
    stmt = select(SourceColumnProfile).where(SourceColumnProfile.file_id == file_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())
