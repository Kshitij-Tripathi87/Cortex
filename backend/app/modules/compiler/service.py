"""Compiler service — extract claims, detect conflicts, compute readiness."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import ClaimState, ConflictSeverity, ReadinessState
from app.common.ids import uuid7
from app.modules.compiler.models import (
    ConflictResolution,
    EvidenceClaim,
    EvidenceConflict,
)
from app.modules.graph.entity_keys import (
    ENTITY_PRIMARY_KEYS,
    canonical_column_name,
    infer_entity_type,
)
from app.modules.sources.models import SourceColumnProfile

# Claim states whose value can still reach the published graph.
LIVE_CLAIM_STATES = frozenset({ClaimState.PENDING_REVIEW.value, ClaimState.ACCEPTED.value})


@dataclass(frozen=True)
class ClaimExtractionResult:
    claims_created: int
    claims_requiring_review: int


@dataclass(frozen=True)
class ConflictDetectionResult:
    conflicts_detected: int
    blocking_conflicts: int


# The most values (cells) of one file that are kept as claims.
MAX_CLAIMS_PER_FILE = 250_000


class SourceClaimLimitError(ValueError):
    """A file holds more values than one upload can be reviewed as."""

    def __init__(self, values: int, limit: int = MAX_CLAIMS_PER_FILE) -> None:
        super().__init__(f"SOURCE_CLAIM_LIMIT_EXCEEDED: {values} values, limit {limit}")
        self.values = values
        self.limit = limit


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
        claim
        for claim in existing
        if isinstance(claim.provenance, dict) and claim.provenance.get("extraction_version") == 2
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
    # Counted before anything is stored: a file over the limit is refused
    # whole, with its size, instead of failing a quarter of a million claims in.
    values = sum(
        1
        for raw_row in raw_rows
        for column_name, raw_value in raw_row.items()
        if column_name in profile_by_name and raw_value is not None and str(raw_value).strip()
    )
    if values > MAX_CLAIMS_PER_FILE:
        raise SourceClaimLimitError(values, MAX_CLAIMS_PER_FILE)
    # What each row describes, by the rule publishing applies to the same
    # column names. When it is known, every column has the field publishing
    # would give it, so accepting a claim as suggested publishes the file as
    # it reads. When it is not, the profiler's guess for the column stands and
    # a reviewer has to say what the rows are.
    row_entity = infer_entity_type([str(profile.column_name) for profile in profiles])
    created = 0
    review_count = 0
    for row_number, raw_row in enumerate(raw_rows, start=1):
        payload = json.dumps(raw_row, sort_keys=True, separators=(",", ":"), default=str).encode()
        row_hash = hashlib.sha256(payload).hexdigest()
        for column_index, (column_name, raw_value) in enumerate(raw_row.items()):
            profile = profile_by_name.get(column_name)
            if profile is None or raw_value is None or not str(raw_value).strip():
                continue
            if row_entity is not None:
                # Fixed by the registries, not guessed: nothing to be unsure of.
                suggested_field: str | None = canonical_column_name(column_name, row_entity)
                confidence = 1.0
                needs_review = False
            else:
                suggested_field = profile.recommended_mapping
                confidence = float(profile.mapping_confidence or 0.0)
                needs_review = (
                    profile.requires_review or not profile.recommended_mapping or confidence < 0.90
                )
            db.add(
                EvidenceClaim(
                    claim_id=uuid7(),
                    workspace_id=workspace_id,
                    source_file_id=file_id,
                    batch_id=batch_id,
                    row_number=row_number,
                    source_column=column_name,
                    canonical_entity=row_entity,
                    canonical_field=suggested_field,
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
                        "mapping_source": "row_entity" if row_entity else "column_profile",
                    },
                    requires_review=needs_review,
                )
            )
            created += 1
            review_count += int(needs_review)

    await db.flush()
    return ClaimExtractionResult(
        claims_created=created,
        claims_requiring_review=review_count,
    )


async def row_entity_key(db: AsyncSession, claim: EvidenceClaim) -> str | None:
    """Identifier of the record that the claim's source row describes.

    It is the value of the row's primary-key cell: ``supplier_id`` for a
    supplier file, ``po_number`` for a purchase-order file. Two rows with the
    same key describe the same record, so different accepted values for one of
    its fields are a conflict. Returns None when the file's kind of record or
    its key column cannot be determined; such claims are not compared.
    """
    if claim.row_number < 1:
        return None
    header_result = await db.execute(
        select(SourceColumnProfile.column_name)
        .where(SourceColumnProfile.file_id == claim.source_file_id)
        .where(SourceColumnProfile.workspace_id == claim.workspace_id)
        .order_by(SourceColumnProfile.column_index)
    )
    headers = [str(name) for name in header_result.scalars().all()]
    entity = infer_entity_type(headers) if headers else None
    if entity is None and claim.canonical_entity in ENTITY_PRIMARY_KEYS:
        entity = claim.canonical_entity
    key_field = ENTITY_PRIMARY_KEYS.get(entity) if entity else None
    if not entity or not key_field:
        return None

    row_result = await db.execute(
        select(EvidenceClaim)
        .where(EvidenceClaim.workspace_id == claim.workspace_id)
        .where(EvidenceClaim.batch_id == claim.batch_id)
        .where(EvidenceClaim.source_file_id == claim.source_file_id)
        .where(EvidenceClaim.row_number == claim.row_number)
    )
    for cell in row_result.scalars().all():
        # An accepted mapping decides what a column means; otherwise the
        # column name does, exactly as when the batch is published.
        reviewed = cell.claim_state == ClaimState.ACCEPTED.value and cell.canonical_field
        field_name = (
            cell.canonical_field if reviewed else canonical_column_name(cell.source_column, entity)
        )
        if field_name == key_field:
            value = (cell.normalized_value or cell.raw_value or "").strip()
            return value or None
    return None


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
        .where(
            EvidenceClaim.claim_state.in_(
                [
                    ClaimState.ACCEPTED.value,
                    ClaimState.PENDING_REVIEW.value,
                ]
            )
        )
    )
    claims = list(result.scalars().all())
    existing_result = await db.execute(
        select(EvidenceConflict)
        .where(EvidenceConflict.workspace_id == workspace_id)
        .where(EvidenceConflict.batch_id == batch_id)
    )
    existing = list(existing_result.scalars().all())

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
        value_of = {
            claim.claim_id: claim.normalized_value or claim.raw_value for claim in claim_list
        }
        if len(set(value_of.values())) <= 1:
            continue
        claim_list.sort(key=lambda claim: (claim.row_number, claim.claim_id))
        claim_ids = [claim.claim_id for claim in claim_list]
        id_set = set(claim_ids)
        related = [
            conflict
            for conflict in existing
            if conflict.canonical_entity == entity
            and conflict.canonical_field == field_name
            and id_set.intersection(conflict.claim_ids)
        ]

        # One finding per field of a record: a claim that joins a disagreement
        # still under review is added to that conflict, not reported again.
        under_review = next(
            (conflict for conflict in related if conflict.status in {"open", "escalated"}), None
        )
        if under_review is not None:
            known = list(under_review.claim_ids)
            additions = [claim_id for claim_id in claim_ids if claim_id not in known]
            if additions:
                under_review.claim_ids = [*known, *additions]
            continue
        # The same claims were already decided or suppressed.
        if any(set(conflict.claim_ids) == id_set for conflict in related):
            continue
        # A suppressed disagreement is not raised again when further claims
        # merely repeat the values it already covered.
        if any(
            conflict.status == "suppressed"
            and set(conflict.claim_ids) <= id_set
            and {value_of[claim_id] for claim_id in conflict.claim_ids} == set(value_of.values())
            for conflict in related
        ):
            continue

        conflict = EvidenceConflict(
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
            explanation=f"Conflicting values for resolved {entity}.{field_name} entity.",
        )
        db.add(conflict)
        existing.append(conflict)
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

    # Count claims in the database. A claim is one cell of a file, so a batch
    # can hold a quarter of a million of them, and this runs every time the
    # review page is opened and after every decision.
    count_result = await db.execute(
        select(EvidenceClaim.claim_state, func.count(EvidenceClaim.claim_id))
        .where(EvidenceClaim.workspace_id == workspace_id)
        .where(EvidenceClaim.batch_id == batch_id)
        .group_by(EvidenceClaim.claim_state)
    )
    counts = {str(state): int(count) for state, count in count_result.all()}
    accepted_count = counts.get(ClaimState.ACCEPTED.value, 0)
    pending_count = counts.get(ClaimState.PENDING_REVIEW.value, 0)
    # Rejected claims do not hold a batch back; they are counted so that the
    # sentence below does not call them accepted.
    rejected_count = counts.get(ClaimState.REJECTED.value, 0)

    assumptions: list[str] = []
    explanation = ""

    if blocking_count > 0:
        state = ReadinessState.BLOCKED.value
        explanation = (
            f"Batch blocked by {blocking_count:,} blocking conflict(s). "
            "Resolve conflicts to proceed."
        )
    elif pending_count > 0 or open_count > 0:
        state = ReadinessState.REVIEW_REQUIRED.value
        explanation = f"{pending_count:,} claims and {open_count:,} conflicts require review."
    else:
        # Claims that would be published on less than full confidence. The
        # first five, oldest first, are named; more than that is not shown.
        low_result = await db.execute(
            select(EvidenceClaim)
            .where(EvidenceClaim.workspace_id == workspace_id)
            .where(EvidenceClaim.batch_id == batch_id)
            .where(
                EvidenceClaim.claim_state.notin_(
                    [ClaimState.SUPERSEDED.value, ClaimState.REJECTED.value]
                )
            )
            .where(EvidenceClaim.confidence < 1.0)
            .order_by(EvidenceClaim.claim_id)
            .limit(5)
        )
        low_confidence = list(low_result.scalars().all())
        if low_confidence:
            state = ReadinessState.READY_WITH_ASSUMPTIONS.value
            assumptions = [
                f"Claim {c.claim_id[:8]} has confidence {c.confidence}" for c in low_confidence
            ]
            explanation = "Ready with assumptions based on lower-confidence claims."
        else:
            state = ReadinessState.READY.value
            if rejected_count == 0:
                explanation = (
                    "All claims accepted, no conflicts. Batch is ready for downstream use."
                )
            elif accepted_count == 0:
                explanation = "Every claim was rejected, so nothing of this batch can be published."
            else:
                explanation = (
                    f"{accepted_count:,} claims accepted and {rejected_count:,} rejected, "
                    "no conflicts. The accepted claims are ready for downstream use."
                )

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
    """Record a human conflict decision without silently accepting alternatives.

    One value per field of a record reaches the published graph:

    * ``approved`` keeps the selected claim (accepting it if it was pending)
      and supersedes every other claim of the conflict, pending or accepted;
    * ``rejected`` with a claim rejects that claim; the conflict closes once the
      remaining claims agree and none is pending;
    * ``rejected`` without a claim rejects every claim of the conflict;
    * ``suppressed`` records that the finding is not a real conflict and leaves
      the claims as they are; publishing then keeps the value of the first row;
    * ``escalated`` keeps the conflict open and blocking.
    """
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
        if selected.claim_state not in LIVE_CLAIM_STATES:
            raise ValueError(
                f"The selected claim is {selected.claim_state}; "
                "only a pending or accepted claim can be kept"
            )
        selected.claim_state = ClaimState.ACCEPTED.value
        selected.requires_review = False
        for other_id, other_claim in claims_by_id.items():
            if other_id != selected_claim_id and other_claim.claim_state in LIVE_CLAIM_STATES:
                # Accepted alternatives are withdrawn too: only the kept value
                # may reach the published record.
                other_claim.claim_state = ClaimState.SUPERSEDED.value
                other_claim.requires_review = False
        conflict.status = "resolved"
        conflict.review_required = False

    elif action == "rejected":
        if selected_claim_id is None:
            # Explicit "Reject all": no value from this conflict is accepted.
            for claim in claims_by_id.values():
                if claim.claim_state in LIVE_CLAIM_STATES:
                    claim.claim_state = ClaimState.REJECTED.value
                    claim.requires_review = False
            conflict.status = "resolved"
            conflict.review_required = False
        else:
            selected = claims_by_id[selected_claim_id]
            if selected.claim_state not in LIVE_CLAIM_STATES:
                raise ValueError(
                    f"The selected claim is {selected.claim_state}; "
                    "only a pending or accepted claim can be rejected"
                )
            selected.claim_state = ClaimState.REJECTED.value
            selected.requires_review = False
            remaining = [
                claim
                for claim_id, claim in claims_by_id.items()
                if claim_id != selected_claim_id and claim.claim_state in LIVE_CLAIM_STATES
            ]
            remaining_pending = any(
                claim.claim_state == ClaimState.PENDING_REVIEW.value for claim in remaining
            )
            # Still a conflict while a claim awaits review or the accepted
            # claims that are left disagree.
            remaining_values = {claim.normalized_value or claim.raw_value for claim in remaining}
            still_open = remaining_pending or len(remaining_values) > 1
            conflict.status = "open" if still_open else "resolved"
            conflict.review_required = still_open

    elif action == "suppressed":
        # Suppressing a detector finding does not approve any source claim.
        conflict.status = "suppressed"
        conflict.review_required = False

    else:  # escalated
        conflict.status = "escalated"
        conflict.review_required = True

    await db.flush()
    return resolution
