"""Compiler service — extract claims, detect conflicts, compute readiness."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import ClaimState, ConflictSeverity, ReadinessState
from app.common.ids import uuid7
from app.modules.graph.entity_keys import COLUMN_TO_ENTITY_TYPE, canonical_column_name
from app.modules.inference.rules_provider import suggest_mapping
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

    existing_stmt = (
        select(EvidenceClaim.source_column, EvidenceClaim.provenance)
        .where(EvidenceClaim.workspace_id == workspace_id)
        .where(EvidenceClaim.batch_id == batch_id)
        .where(EvidenceClaim.source_file_id == file_id)
    )
    existing_result = await db.execute(existing_stmt)
    existing_rows = list(existing_result.all())
    existing_columns = {row.source_column for row in existing_rows}
    existing_profile_ids = {
        row.provenance.get("profile_id")
        for row in existing_rows
        if isinstance(row.provenance, dict) and row.provenance.get("profile_id")
    }

    canonical_headers = sorted({canonical_column_name(profile.column_name) for profile in profiles})
    row_entity_type = next(
        (COLUMN_TO_ENTITY_TYPE[field] for field in canonical_headers if field in COLUMN_TO_ENTITY_TYPE),
        None,
    )

    for profile in profiles:
        # A retried batch compilation must not multiply the same column claims.
        if profile.profile_id in existing_profile_ids or profile.column_name in existing_columns:
            continue
        existing_columns.add(profile.column_name)
        suggestion = suggest_mapping(profile.column_name, row_entity_type=row_entity_type)
        canonical_field = suggestion.canonical_field or profile.recommended_mapping
        confidence = max(profile.mapping_confidence or 0.0, suggestion.confidence)
        requires_review = (
            profile.requires_review
            or suggestion.requires_review
            or not suggestion.canonical_entity
            or not canonical_field
            or confidence < 0.9
        )
        claim = EvidenceClaim(
            claim_id=uuid7(),
            workspace_id=workspace_id,
            source_file_id=file_id,
            batch_id=batch_id,
            row_number=0,  # Phase 2: one claim per column
            source_column=profile.column_name,
            canonical_entity=suggestion.canonical_entity,
            canonical_field=canonical_field,
            raw_value=", ".join(profile.sample_values),
            normalized_value=None,
            confidence=confidence,
            claim_state=ClaimState.PENDING_REVIEW.value,
            provenance={
                "profile_id": profile.profile_id,
                "inferred_type": profile.inferred_type,
                "matched_alias": suggestion.matched_alias,
            },
            requires_review=requires_review,
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

    existing_conflict_stmt = (
        select(EvidenceConflict.claim_ids)
        .where(EvidenceConflict.workspace_id == workspace_id)
        .where(EvidenceConflict.batch_id == batch_id)
    )
    existing_conflict_result = await db.execute(existing_conflict_stmt)
    existing_signatures = {
        tuple(sorted(claim_ids)) for claim_ids in existing_conflict_result.scalars().all()
    }

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
        signature = tuple(sorted(c.claim_id for c in claim_list))
        if len(values) > 1 and signature not in existing_signatures:
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
