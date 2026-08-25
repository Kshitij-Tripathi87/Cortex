"""Compiler service — extract claims, detect conflicts, compute readiness."""

from __future__ import annotations

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
) -> ClaimExtractionResult:
    """Extract evidence claims from profiled source file columns.

    Each column profile becomes a set of claims (one per row, simplified for Phase 2).
    In Phase 2, we create one claim per column per file as a placeholder; Phase 3+
    will expand to per-row claims.
    """
    claims_created = 0
    claims_requiring_review = 0

    for profile in profiles:
        claim = EvidenceClaim(
            claim_id=uuid7(),
            workspace_id=workspace_id,
            source_file_id=file_id,
            batch_id=batch_id,
            row_number=0,  # Phase 2: one claim per column
            source_column=profile.column_name,
            canonical_entity=None,  # To be resolved by mapping
            canonical_field=profile.recommended_mapping,
            raw_value=", ".join(profile.sample_values),
            normalized_value=None,
            confidence=profile.mapping_confidence or 0.0,
            claim_state=ClaimState.PENDING_REVIEW.value,
            provenance={"profile_id": profile.profile_id, "inferred_type": profile.inferred_type},
            requires_review=profile.requires_review or (profile.mapping_confidence or 0.0) < 1.0,
        )
        if claim.requires_review:
            claims_requiring_review += 1
        db.add(claim)
        claims_created += 1

    await db.flush()
    return ClaimExtractionResult(
        claims_created=claims_created, claims_requiring_review=claims_requiring_review
    )


async def detect_conflicts(
    db: AsyncSession,
    workspace_id: str,
    batch_id: str,
) -> ConflictDetectionResult:
    """Detect conflicts among pending claims in a batch.

    Phase 2 logic: conflicts arise when multiple claims target the same canonical_field
    with different normalized_value. Blocking if severity is critical/major.
    """
    stmt = (
        select(EvidenceClaim)
        .where(EvidenceClaim.workspace_id == workspace_id)
        .where(EvidenceClaim.batch_id == batch_id)
        .where(EvidenceClaim.claim_state == ClaimState.PENDING_REVIEW.value)
    )
    result = await db.execute(stmt)
    claims = list(result.scalars().all())

    conflicts_detected = 0
    blocking_conflicts = 0

    # Group by (canonical_entity, canonical_field)
    from collections import defaultdict

    grouped: dict[tuple[str | None, str | None], list[EvidenceClaim]] = defaultdict(list)
    for claim in claims:
        key = (claim.canonical_entity, claim.canonical_field)
        if claim.canonical_field:
            grouped[key].append(claim)

    for (entity, field_name), claim_list in grouped.items():
        if len(claim_list) <= 1:
            continue
        # Check for value disagreement
        values = set(c.normalized_value or c.raw_value for c in claim_list)
        if len(values) > 1:
            severity = ConflictSeverity.MAJOR.value if entity else ConflictSeverity.WARNING.value
            is_blocking = severity in {
                ConflictSeverity.MAJOR.value,
                ConflictSeverity.CRITICAL.value,
            }
            conflict = EvidenceConflict(
                conflict_id=uuid7(),
                workspace_id=workspace_id,
                batch_id=batch_id,
                claim_ids=[c.claim_id for c in claim_list],
                canonical_entity=entity,
                canonical_field=field_name,
                severity=severity,
                blocking=is_blocking,
                status="open",
                review_required=True,
                explanation=f"Multiple claims for {entity or 'unknown'}.{field_name or 'unknown'} with differing values: {values}",
            )
            db.add(conflict)
            conflicts_detected += 1
            if is_blocking:
                blocking_conflicts += 1

    await db.flush()
    return ConflictDetectionResult(
        conflicts_detected=conflicts_detected, blocking_conflicts=blocking_conflicts
    )


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
        claim_stmt = select(EvidenceClaim).where(EvidenceClaim.claim_id == selected_claim_id)
        claim_result = await db.execute(claim_stmt)
        claim = claim_result.scalar_one()
        claim.claim_state = ClaimState.ACCEPTED.value
        # Mark others as superseded
        for other_id in conflict.claim_ids:
            if other_id != selected_claim_id:
                other_claim = await db.get(EvidenceClaim, other_id)
                if other_claim:
                    other_claim.claim_state = ClaimState.SUPERSEDED.value

    await db.flush()
    return resolution
