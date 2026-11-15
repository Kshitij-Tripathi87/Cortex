"""Compiler service — extract claims, detect conflicts, compute readiness."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.exc import NoResultFound
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
async def extract_claims(
    db: AsyncSession,
    workspace_id: str,
    batch_id: str,
    file_id: str,
    profiles: list[SourceColumnProfile],
    raw_rows: list[dict[str, object]],
) -> ClaimExtractionResult:
    """Persist deterministic row/cell evidence with source-hash provenance."""
    if not raw_rows:
        return ClaimExtractionResult(claims_created=0, claims_requiring_review=0)

    existing_result = await db.execute(
        select(EvidenceClaim)
        .where(EvidenceClaim.workspace_id == workspace_id)
        .where(EvidenceClaim.batch_id == batch_id)
        .where(EvidenceClaim.source_file_id == file_id)
    )
    existing = list(existing_result.scalars().all())
    completed = [
        claim for claim in existing
        if isinstance(claim.provenance, dict)
        and claim.provenance.get("extraction_version") == 2
    ]
    if completed:
        return ClaimExtractionResult(
            claims_created=0,
            claims_requiring_review=sum(1 for claim in completed if claim.requires_review),
        )

    for claim in existing:
        if claim.row_number == 0 and claim.claim_state == ClaimState.PENDING_REVIEW.value:
            claim.claim_state = ClaimState.SUPERSEDED.value
            claim.requires_review = False

    profile_by_name = {profile.column_name: profile for profile in profiles}
    created = 0
    review_count = 0
    for row_number, raw_row in enumerate(raw_rows, start=1):
        payload = json.dumps(raw_row, sort_keys=True, separators=(",", ":"), default=str).encode()
        row_hash = hashlib.sha256(payload).hexdigest()
        for column_index, (column_name, raw_value) in enumerate(raw_row.items()):
            profile = profile_by_name.get(column_name)
            if profile is None or raw_value is None or not str(raw_value).strip():
                continue
            confidence = float(profile.mapping_confidence or 0.0)
            needs_review = (
                profile.requires_review
                or not profile.recommended_mapping
                or confidence < 0.90
            )
            db.add(EvidenceClaim(
                claim_id=uuid7(),
                workspace_id=workspace_id,
                source_file_id=file_id,
                batch_id=batch_id,
                row_number=row_number,
                source_column=column_name,
                canonical_entity=None,
                canonical_field=profile.recommended_mapping,
                raw_value=str(raw_value),
                normalized_value=str(raw_value).strip(),
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
                requires_review=needs_review,
            ))
            created += 1
            review_count += int(needs_review)
            if created > 250_000:
                raise ValueError("SOURCE_CLAIM_LIMIT_EXCEEDED")

    await db.flush()
    return ClaimExtractionResult(
        claims_created=created,
        claims_requiring_review=review_count,
    )


async def detect_conflicts(
    db: AsyncSession,
    workspace_id: str,
    batch_id: str,
) -> ConflictDetectionResult:
    """Compare claims only after entity, field and entity key have been resolved."""
    from collections import defaultdict

    result = await db.execute(
        select(EvidenceClaim)
        .where(EvidenceClaim.workspace_id == workspace_id)
        .where(EvidenceClaim.batch_id == batch_id)
        .where(EvidenceClaim.claim_state.in_([
            ClaimState.ACCEPTED.value,
            ClaimState.PENDING_REVIEW.value,
        ]))
    )
    claims = list(result.scalars().all())
    existing_result = await db.execute(
        select(EvidenceConflict.claim_ids)
        .where(EvidenceConflict.workspace_id == workspace_id)
        .where(EvidenceConflict.batch_id == batch_id)
    )
    existing_signatures = {
        tuple(sorted(claim_ids)) for claim_ids in existing_result.scalars().all()
    }

    grouped: dict[tuple[str, str, str], list[EvidenceClaim]] = defaultdict(list)
    for claim in claims:
        provenance = claim.provenance if isinstance(claim.provenance, dict) else {}
        entity_key = provenance.get("entity_key")
        if claim.canonical_entity and claim.canonical_field and entity_key:
            grouped[(claim.canonical_entity, claim.canonical_field, str(entity_key))].append(claim)

    created = 0
    blocking = 0
    for (entity, field_name, _entity_key), claim_list in grouped.items():
        if len(claim_list) < 2:
            continue
        values = {claim.normalized_value or claim.raw_value for claim in claim_list}
        signature = tuple(sorted(claim.claim_id for claim in claim_list))
        if len(values) <= 1 or signature in existing_signatures:
            continue
        db.add(EvidenceConflict(
            conflict_id=uuid7(),
            workspace_id=workspace_id,
            batch_id=batch_id,
            claim_ids=[claim.claim_id for claim in claim_list],
            canonical_entity=entity,
            canonical_field=field_name,
            severity=ConflictSeverity.MAJOR.value,
            blocking=True,
            status="open",
            review_required=True,
            explanation=f"Conflicting values for resolved {entity}.{field_name} entity.",
        ))
        created += 1
        blocking += 1

    await db.flush()
    return ConflictDetectionResult(conflicts_detected=created, blocking_conflicts=blocking)


async def compute_readiness(
    db: AsyncSession,
    workspace_id: str,
    batch_id: str,
) -> ReadinessResult:
    """Compute deterministic readiness state for a batch.

    Rules (Phase 2):
    - READY: no blocking conflicts, all claims accepted or none require review.
    - BLOCKED: any blocking conflict open.
    - REVIEW_REQUIRED: non-blocking conflicts open or claims pending review.
    - READY_WITH_ASSUMPTIONS: ready but some claims have confidence < 1.0.
    """
    # Count conflicts
    conflict_stmt = (
        select(EvidenceConflict)
        .where(EvidenceConflict.workspace_id == workspace_id)
        .where(EvidenceConflict.batch_id == batch_id)
        .where(EvidenceConflict.status.in_(["open", "escalated"]))
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
        .where(EvidenceClaim.claim_state.notin_([ClaimState.SUPERSEDED.value, ClaimState.REJECTED.value]))
    )
    claim_result = await db.execute(claim_stmt)
    claims = list(claim_result.scalars().all())
    accepted_count = sum(1 for c in claims if c.claim_state == ClaimState.ACCEPTED.value)
    pending_count = sum(1 for c in claims if c.claim_state == ClaimState.PENDING_REVIEW.value)

    assumptions: list[str] = []
    explanation = ""

    if blocking_count > 0:
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
    """Record a human conflict decision without silently accepting alternatives."""
    conflict_stmt = (
        select(EvidenceConflict)
        .where(EvidenceConflict.conflict_id == conflict_id)
        .where(EvidenceConflict.workspace_id == workspace_id)
        .with_for_update()
    )
    conflict_result = await db.execute(conflict_stmt)
    conflict = conflict_result.scalar_one_or_none()
    if conflict is None:
        raise NoResultFound(f"Conflict {conflict_id} not found")

    allowed_actions = {"approved", "rejected", "suppressed", "escalated"}
    if action not in allowed_actions:
        raise ValueError(f"Unsupported conflict action: {action}")
    if conflict.status not in {"open", "escalated"}:
        raise ValueError(f"Conflict is already {conflict.status}")
    if action == "approved" and selected_claim_id is None:
        raise ValueError("A claim must be selected for approval")

    claims_by_id: dict[str, EvidenceClaim] = {}
    for claim_id in conflict.claim_ids:
        stmt = (
            select(EvidenceClaim)
            .where(EvidenceClaim.claim_id == claim_id)
            .where(EvidenceClaim.workspace_id == workspace_id)
            .where(EvidenceClaim.batch_id == conflict.batch_id)
        )
        result = await db.execute(stmt)
        claim = result.scalar_one_or_none()
        if claim is not None:
            claims_by_id[claim_id] = claim
    if not claims_by_id:
        raise ValueError("Conflict has no reviewable claims")
    if selected_claim_id is not None and selected_claim_id not in claims_by_id:
        raise ValueError("Selected claim does not belong to this conflict and workspace")

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

    if action == "approved":
        assert selected_claim_id is not None
        selected = claims_by_id[selected_claim_id]
        if selected.claim_state != ClaimState.PENDING_REVIEW.value:
            raise ValueError("Only a pending claim can be approved")
        selected.claim_state = ClaimState.ACCEPTED.value
        selected.requires_review = False
        for other_id, other_claim in claims_by_id.items():
            if (
                other_id != selected_claim_id
                and other_claim.claim_state == ClaimState.PENDING_REVIEW.value
            ):
                other_claim.claim_state = ClaimState.SUPERSEDED.value
                other_claim.requires_review = False
        conflict.status = "resolved"
        conflict.review_required = False

    elif action == "rejected":
        if selected_claim_id is None:
            # Explicit "Reject all": no value from this conflict is accepted.
            for claim in claims_by_id.values():
                if claim.claim_state == ClaimState.PENDING_REVIEW.value:
                    claim.claim_state = ClaimState.REJECTED.value
                    claim.requires_review = False
            conflict.status = "resolved"
            conflict.review_required = False
        else:
            selected = claims_by_id[selected_claim_id]
            if selected.claim_state != ClaimState.PENDING_REVIEW.value:
                raise ValueError("Only a pending claim can be rejected")
            selected.claim_state = ClaimState.REJECTED.value
            selected.requires_review = False
            remaining_pending = any(
                claim.claim_state == ClaimState.PENDING_REVIEW.value
                for claim_id, claim in claims_by_id.items()
                if claim_id != selected_claim_id
            )
            conflict.status = "open" if remaining_pending else "resolved"
            conflict.review_required = remaining_pending

    elif action == "suppressed":
        # Suppressing a detector finding does not approve any source claim.
        conflict.status = "suppressed"
        conflict.review_required = False

    else:  # escalated
        conflict.status = "escalated"
        conflict.review_required = True

    await db.flush()
    return resolution
