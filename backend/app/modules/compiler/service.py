"""Compiler service — extract claims, detect conflicts, compute readiness."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import ClaimState, ConflictSeverity, ReadinessState
from app.common.ids import uuid7
from app.modules.compiler.models import (
    ConflictResolution,
    EvidenceClaim,
    EvidenceConflict,
)
from app.modules.sources.models import SourceColumnProfile


@dataclass(frozen=True)
class ClaimExtractionResult:
    claims_created: int
    claims_requiring_review: int


@dataclass(frozen=True)
class ConflictDetectionResult:
    conflicts_detected: int
    blocking_conflicts: int


@dataclass(frozen=True)
class ReadinessResult:
    state: str
    blocking_conflict_count: int
    open_conflict_count: int
    accepted_claim_count: int
    pending_claim_count: int
    assumptions: list[str] = field(default_factory=list)
    explanation: str = ""


async def extract_claims(
    db: AsyncSession,
    workspace_id: str,
    batch_id: str,
    file_id: str,
    profiles: list[SourceColumnProfile],
    raw_rows: list[dict[str, object]],
) -> ClaimExtractionResult:
    """Persist one evidence claim per non-empty source row/column.

    Claims preserve the original cell value and a deterministic row hash.
    Mapping suggestions remain proposals: an unmapped or low-confidence
    field is never promoted to a canonical fact by this function.
    """
    if not raw_rows:
        return ClaimExtractionResult(claims_created=0, claims_requiring_review=0)

    existing_stmt = (
        select(EvidenceClaim)
        .where(EvidenceClaim.workspace_id == workspace_id)
        .where(EvidenceClaim.batch_id == batch_id)
        .where(EvidenceClaim.source_file_id == file_id)
    )
    existing_result = await db.execute(existing_stmt)
    existing_claims = list(existing_result.scalars().all())

    # Compile is safe to retry. A completed v2 row-level compilation is a no-op.
    if any(
        isinstance(claim.provenance, dict)
        and claim.provenance.get("extraction_version") == 2
        for claim in existing_claims
    ):
        return ClaimExtractionResult(
            claims_created=0,
            claims_requiring_review=sum(
                1 for claim in existing_claims if claim.requires_review
                and isinstance(claim.provenance, dict)
                and claim.provenance.get("extraction_version") == 2
            ),
        )

    # Retire old column-summary placeholders without deleting their audit history.
    for claim in existing_claims:
        if claim.row_number == 0:
            claim.claim_state = ClaimState.SUPERSEDED.value

    profiles_by_name = {profile.column_name: profile for profile in profiles}
    claims_created = 0
    claims_requiring_review = 0
    max_claims = 250_000

    for row_number, raw_row in enumerate(raw_rows, start=1):
        row_payload = json.dumps(
            raw_row, sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
        row_hash = hashlib.sha256(row_payload).hexdigest()

        for column_index, (column_name, raw_value) in enumerate(raw_row.items()):
            profile = profiles_by_name.get(column_name)
            if profile is None or raw_value is None:
                continue
            raw_text = str(raw_value)
            if raw_text.strip() == "":
                continue

            confidence = float(profile.mapping_confidence or 0.0)
            requires_review = (
                profile.requires_review
                or not profile.recommended_mapping
                or confidence < 0.90
            )
            db.add(
                EvidenceClaim(
                    claim_id=uuid7(),
                    workspace_id=workspace_id,
                    source_file_id=file_id,
                    batch_id=batch_id,
                    row_number=row_number,
                    source_column=column_name,
                    canonical_entity=None,
                    canonical_field=profile.recommended_mapping,
                    raw_value=raw_text,
                    normalized_value=raw_text.strip(),
                    confidence=confidence,
                    claim_state=ClaimState.PENDING_REVIEW.value,
                    provenance={
                        "extraction_version": 2,
                        "profile_id": profile.profile_id,
                        "column_index": column_index,
                        "source_locator": {
                            "file_id": file_id,
                            "row_number": row_number,
                            "physical_line_number": row_number + 1,
                            "column_name": column_name,
                        },
                        "row_sha256": row_hash,
                        "entity_key": None,
                        "mapping_is_suggestion": True,
                    },
                    requires_review=requires_review,
                )
            )
            claims_created += 1
            if requires_review:
                claims_requiring_review += 1
            if claims_created > max_claims:
                raise ValueError("SOURCE_CLAIM_LIMIT_EXCEEDED")

    await db.flush()
    return ClaimExtractionResult(
        claims_created=claims_created,
        claims_requiring_review=claims_requiring_review,
    )


async def detect_conflicts(
    db: AsyncSession,
    workspace_id: str,
    batch_id: str,
) -> ConflictDetectionResult:
    """Detect conflicts only after entity identity and field are resolved.

    Grouping all rows by column name creates false conflicts. Claims without
    a resolved canonical entity key remain reviewable evidence but cannot
    create entity-level conflicts.
    """
    stmt = (
        select(EvidenceClaim)
        .where(EvidenceClaim.workspace_id == workspace_id)
        .where(EvidenceClaim.batch_id == batch_id)
        .where(EvidenceClaim.claim_state == ClaimState.PENDING_REVIEW.value)
    )
    result = await db.execute(stmt)
    claims = list(result.scalars().all())

    existing_stmt = (
        select(EvidenceConflict)
        .where(EvidenceConflict.workspace_id == workspace_id)
        .where(EvidenceConflict.batch_id == batch_id)
    )
    existing_result = await db.execute(existing_stmt)
    existing_signatures = {
        tuple(sorted(conflict.claim_ids))
        for conflict in existing_result.scalars().all()
    }

    grouped: dict[tuple[str, str, str], list[EvidenceClaim]] = {}
    for claim in claims:
        provenance = claim.provenance if isinstance(claim.provenance, dict) else {}
        entity_key = provenance.get("entity_key")
        if not claim.canonical_entity or not claim.canonical_field or not entity_key:
            continue
        key = (claim.canonical_entity, claim.canonical_field, str(entity_key))
        grouped.setdefault(key, []).append(claim)

    conflicts_detected = 0
    blocking_conflicts = 0
    for (entity, field_name, _entity_key), claim_list in sorted(grouped.items()):
        if len(claim_list) <= 1:
            continue
        values = {
            claim.normalized_value if claim.normalized_value is not None else claim.raw_value
            for claim in claim_list
        }
        if len(values) <= 1:
            continue
        claim_ids = sorted(claim.claim_id for claim in claim_list)
        signature = tuple(claim_ids)
        if signature in existing_signatures:
            continue

        db.add(
            EvidenceConflict(
                conflict_id=uuid7(),
                workspace_id=workspace_id,
                batch_id=batch_id,
                claim_ids=claim_ids,
                canonical_entity=entity,
                canonical_field=field_name,
                severity=ConflictSeverity.MAJOR.value,
                blocking=True,
                status="open",
                review_required=True,
                explanation=(
                    f"Conflicting values for {entity}.{field_name} on the same "
                    f"canonical entity: {', '.join(sorted(str(value) for value in values))}"
                ),
            )
        )
        conflicts_detected += 1
        blocking_conflicts += 1

    await db.flush()
    return ConflictDetectionResult(
        conflicts_detected=conflicts_detected,
        blocking_conflicts=blocking_conflicts,
    )


async def compute_readiness(
    db: AsyncSession,
    workspace_id: str,
    batch_id: str,
) -> ReadinessResult:
    """Compute deterministic readiness state for a batch.

    Rules:
    - BLOCKED: no active row-level claims or a blocking conflict is open.
    - REVIEW_REQUIRED: unresolved claims or conflicts remain.
    - READY_WITH_ASSUMPTIONS: accepted claims remain below full confidence.
    - READY: all active claims are accepted and no conflict is open.
    """
    # Count conflicts
    conflict_stmt = (
        select(EvidenceConflict)
        .where(EvidenceConflict.workspace_id == workspace_id)
        .where(EvidenceConflict.batch_id == batch_id)
        .where(EvidenceConflict.status == "open")
    )
    conflict_result = await db.execute(conflict_stmt)
    conflicts = list(conflict_result.scalars().all())
    blocking_count = sum(1 for c in conflicts if c.blocking)
    open_count = len(conflicts)

    # Count claims
    claim_stmt = (
        select(EvidenceClaim)
        .where(EvidenceClaim.workspace_id == workspace_id)
        .where(EvidenceClaim.batch_id == batch_id)
        .where(
            EvidenceClaim.claim_state.notin_(
                [ClaimState.SUPERSEDED.value, ClaimState.REJECTED.value]
            )
        )
    )
    claim_result = await db.execute(claim_stmt)
    claims = list(claim_result.scalars().all())
    accepted_count = sum(1 for c in claims if c.claim_state == ClaimState.ACCEPTED.value)
    pending_count = sum(1 for c in claims if c.claim_state == ClaimState.PENDING_REVIEW.value)

    assumptions: list[str] = []
    explanation = ""

    if not claims:
        state = ReadinessState.BLOCKED.value
        explanation = "No row-level source claims were compiled; downstream projection is blocked."
    elif blocking_count > 0:
        state = ReadinessState.BLOCKED.value
        explanation = (
            f"Batch blocked by {blocking_count} blocking conflict(s). Resolve conflicts to proceed."
        )
    elif pending_count > 0 or open_count > 0:
        state = ReadinessState.REVIEW_REQUIRED.value
        explanation = f"{pending_count} claims and {open_count} conflicts require review."
    else:
        low_confidence = [c for c in claims if c.confidence < 1.0]
        if low_confidence:
            state = ReadinessState.READY_WITH_ASSUMPTIONS.value
            assumptions = [
                f"Claim {c.claim_id[:8]} has confidence {c.confidence}" for c in low_confidence[:5]
            ]
            explanation = "Ready with assumptions based on lower-confidence claims."
        else:
            state = ReadinessState.READY.value
            explanation = "All claims accepted, no conflicts. Batch is ready for downstream use."

    return ReadinessResult(
        state=state,
        blocking_conflict_count=blocking_count,
        open_conflict_count=open_count,
        accepted_claim_count=accepted_count,
        pending_claim_count=pending_count,
        assumptions=assumptions,
        explanation=explanation,
    )


async def resolve_conflict(
    db: AsyncSession,
    workspace_id: str,
    conflict_id: str,
    selected_claim_id: str | None,
    action: str,
    rationale: str,
    reviewer_id: str,
) -> ConflictResolution:
    """Record a human conflict resolution. Updates conflict status and selected claim state.

    Raises:
        NoResultFound: the requested conflict does not exist.
        PermissionError: the conflict exists but belongs to a different
            workspace — the caller is not authorized to resolve it.
    """
    conflict_stmt = select(EvidenceConflict).where(EvidenceConflict.conflict_id == conflict_id)
    conflict_result = await db.execute(conflict_stmt)
    conflict = conflict_result.scalar_one()
    if conflict.workspace_id != workspace_id:
        raise PermissionError(f"Conflict {conflict_id} does not belong to workspace {workspace_id}")

    if action == "approved" and selected_claim_id:
        if selected_claim_id not in conflict.claim_ids:
            raise ValueError("Selected claim is not part of this conflict")
        selected_stmt = (
            select(EvidenceClaim)
            .where(EvidenceClaim.claim_id == selected_claim_id)
            .where(EvidenceClaim.workspace_id == workspace_id)
            .where(EvidenceClaim.batch_id == conflict.batch_id)
        )
        selected_result = await db.execute(selected_stmt)
        if selected_result.scalar_one_or_none() is None:
            raise PermissionError("Selected claim is not available in this workspace")

    resolution = ConflictResolution(
        resolution_id=uuid7(),
        conflict_id=conflict_id,
        workspace_id=workspace_id,
        selected_claim_id=selected_claim_id,
        action=action,
        rationale=rationale,
        reviewer_id=reviewer_id,
    )
    db.add(resolution)

    conflict.status = "resolved"
    conflict.review_required = False

    if selected_claim_id and action == "approved":
        claim_stmt = (
            select(EvidenceClaim)
            .where(EvidenceClaim.claim_id == selected_claim_id)
            .where(EvidenceClaim.workspace_id == workspace_id)
            .where(EvidenceClaim.batch_id == conflict.batch_id)
        )
        claim_result = await db.execute(claim_stmt)
        claim = claim_result.scalar_one()
        claim.claim_state = ClaimState.ACCEPTED.value

        # Supersede only claims belonging to this conflict and workspace.
        for other_id in conflict.claim_ids:
            if other_id == selected_claim_id:
                continue
            other_stmt = (
                select(EvidenceClaim)
                .where(EvidenceClaim.claim_id == other_id)
                .where(EvidenceClaim.workspace_id == workspace_id)
                .where(EvidenceClaim.batch_id == conflict.batch_id)
            )
            other_result = await db.execute(other_stmt)
            other_claim = other_result.scalar_one_or_none()
            if other_claim is not None:
                other_claim.claim_state = ClaimState.SUPERSEDED.value

    await db.flush()
    return resolution
