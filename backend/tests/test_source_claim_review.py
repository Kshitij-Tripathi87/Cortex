from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import ClaimState
from app.modules.compiler.models import (
    ConflictResolution,
    EvidenceClaim,
    EvidenceConflict,
)
from app.modules.compiler.service import (
    compute_readiness,
    detect_conflicts,
    extract_claims,
    resolve_conflict,
)
from app.modules.sources.models import SourceColumnProfile


def _claim(
    *,
    workspace_id: str,
    batch_id: str,
    file_id: str,
    claim_id: str | None = None,
    source_column: str = "supplier_name",
    raw_value: str = "Acme",
) -> EvidenceClaim:
    return EvidenceClaim(
        claim_id=claim_id or str(uuid4()),
        workspace_id=workspace_id,
        source_file_id=file_id,
        batch_id=batch_id,
        row_number=0,
        source_column=source_column,
        canonical_entity="Supplier",
        canonical_field=source_column,
        raw_value=raw_value,
        normalized_value=raw_value,
        confidence=0.95,
        claim_state=ClaimState.PENDING_REVIEW.value,
        provenance={},
        requires_review=True,
    )


def _conflict(
    *,
    workspace_id: str,
    batch_id: str,
    claim_ids: list[str],
    conflict_id: str | None = None,
) -> EvidenceConflict:
    return EvidenceConflict(
        conflict_id=conflict_id or str(uuid4()),
        workspace_id=workspace_id,
        batch_id=batch_id,
        claim_ids=claim_ids,
        canonical_entity="Supplier",
        canonical_field="supplier_name",
        severity="major",
        blocking=True,
        status="open",
        review_required=True,
        explanation="Conflicting source values for the same canonical field.",
    )


@pytest.mark.asyncio
async def test_approved_conflict_claim_supersedes_pending_alternatives(
    db_session: AsyncSession,
) -> None:
    workspace_id, batch_id, file_id = str(uuid4()), str(uuid4()), str(uuid4())
    approved = _claim(
        workspace_id=workspace_id,
        batch_id=batch_id,
        file_id=file_id,
        raw_value="Acme Ltd",
    )
    alternative = _claim(
        workspace_id=workspace_id,
        batch_id=batch_id,
        file_id=file_id,
        raw_value="ACME Limited",
    )
    conflict = _conflict(
        workspace_id=workspace_id,
        batch_id=batch_id,
        claim_ids=[approved.claim_id, alternative.claim_id],
    )
    db_session.add_all([approved, alternative, conflict])
    await db_session.flush()

    resolution = await resolve_conflict(
        db_session,
        workspace_id,
        conflict.conflict_id,
        approved.claim_id,
        "approved",
        "The ERP supplier master is the authoritative source.",
        str(uuid4()),
    )
    await db_session.flush()

    assert resolution.action == "approved"
    assert approved.claim_state == ClaimState.ACCEPTED.value
    assert approved.requires_review is False
    assert alternative.claim_state == ClaimState.SUPERSEDED.value
    assert alternative.requires_review is False
    assert conflict.status == "resolved"
    assert conflict.review_required is False

    stored = await db_session.scalar(
        select(ConflictResolution).where(
            ConflictResolution.resolution_id == resolution.resolution_id
        )
    )
    assert stored is not None
    assert stored.rationale == "The ERP supplier master is the authoritative source."


@pytest.mark.asyncio
async def test_rejecting_one_conflict_claim_keeps_other_values_pending(
    db_session: AsyncSession,
) -> None:
    workspace_id, batch_id, file_id = str(uuid4()), str(uuid4()), str(uuid4())
    rejected = _claim(
        workspace_id=workspace_id,
        batch_id=batch_id,
        file_id=file_id,
        raw_value="Wrong Supplier",
    )
    remaining = _claim(
        workspace_id=workspace_id,
        batch_id=batch_id,
        file_id=file_id,
        raw_value="Correct Supplier",
    )
    conflict = _conflict(
        workspace_id=workspace_id,
        batch_id=batch_id,
        claim_ids=[rejected.claim_id, remaining.claim_id],
    )
    db_session.add_all([rejected, remaining, conflict])
    await db_session.flush()

    await resolve_conflict(
        db_session,
        workspace_id,
        conflict.conflict_id,
        rejected.claim_id,
        "rejected",
        "This value does not match the ERP supplier master.",
        str(uuid4()),
    )

    assert rejected.claim_state == ClaimState.REJECTED.value
    assert remaining.claim_state == ClaimState.PENDING_REVIEW.value
    assert conflict.status == "open"
    assert conflict.review_required is True


@pytest.mark.asyncio
async def test_suppressing_conflict_does_not_accept_claims(
    db_session: AsyncSession,
) -> None:
    workspace_id, batch_id, file_id = str(uuid4()), str(uuid4()), str(uuid4())
    first = _claim(workspace_id=workspace_id, batch_id=batch_id, file_id=file_id)
    second = _claim(
        workspace_id=workspace_id,
        batch_id=batch_id,
        file_id=file_id,
        raw_value="ACME",
    )
    conflict = _conflict(
        workspace_id=workspace_id,
        batch_id=batch_id,
        claim_ids=[first.claim_id, second.claim_id],
    )
    db_session.add_all([first, second, conflict])
    await db_session.flush()

    await resolve_conflict(
        db_session,
        workspace_id,
        conflict.conflict_id,
        None,
        "suppressed",
        "The duplicate is explained by an upstream formatting rule; claims still need review.",
        str(uuid4()),
    )

    assert conflict.status == "suppressed"
    assert first.claim_state == ClaimState.PENDING_REVIEW.value
    assert second.claim_state == ClaimState.PENDING_REVIEW.value


@pytest.mark.asyncio
async def test_conflict_cannot_be_resolved_from_another_workspace(
    db_session: AsyncSession,
) -> None:
    workspace_id, batch_id, file_id = str(uuid4()), str(uuid4()), str(uuid4())
    claim = _claim(workspace_id=workspace_id, batch_id=batch_id, file_id=file_id)
    conflict = _conflict(
        workspace_id=workspace_id,
        batch_id=batch_id,
        claim_ids=[claim.claim_id],
    )
    db_session.add_all([claim, conflict])
    await db_session.flush()

    with pytest.raises(NoResultFound):
        await resolve_conflict(
            db_session,
            str(uuid4()),
            conflict.conflict_id,
            claim.claim_id,
            "approved",
            "Cross-workspace access must not resolve this record.",
            str(uuid4()),
        )


@pytest.mark.asyncio
async def test_claim_extraction_is_idempotent_for_retried_batch_compile(
    db_session: AsyncSession,
) -> None:
    workspace_id, batch_id, file_id = str(uuid4()), str(uuid4()), str(uuid4())
    profiles = [
        SourceColumnProfile(
            profile_id=str(uuid4()),
            file_id=file_id,
            workspace_id=workspace_id,
            column_name="supplier_id",
            column_index=0,
            inferred_type="string",
            null_ratio=0.0,
            distinct_count=1,
            sample_values=["SUP-001"],
            recommended_mapping="supplier_id",
            mapping_confidence=0.99,
            requires_review=False,
        ),
        SourceColumnProfile(
            profile_id=str(uuid4()),
            file_id=file_id,
            workspace_id=workspace_id,
            column_name="supplier_name",
            column_index=1,
            inferred_type="string",
            null_ratio=0.0,
            distinct_count=1,
            sample_values=["Acme Ltd"],
            recommended_mapping="supplier_name",
            mapping_confidence=0.95,
            requires_review=True,
        ),
    ]

    first = await extract_claims(db_session, workspace_id, batch_id, file_id, profiles)
    second = await extract_claims(db_session, workspace_id, batch_id, file_id, profiles)
    await db_session.flush()

    claims = list(
        (
            await db_session.scalars(
                select(EvidenceClaim).where(
                    EvidenceClaim.workspace_id == workspace_id,
                    EvidenceClaim.batch_id == batch_id,
                    EvidenceClaim.source_file_id == file_id,
                )
            )
        ).all()
    )
    assert first.claims_created == 2
    assert second.claims_created == 0
    assert len(claims) == 2
    assert {claim.source_column for claim in claims} == {"supplier_id", "supplier_name"}


@pytest.mark.asyncio
async def test_escalated_conflict_blocks_readiness_until_a_later_decision(
    db_session: AsyncSession,
) -> None:
    workspace_id, batch_id, file_id = str(uuid4()), str(uuid4()), str(uuid4())
    first = _claim(
        workspace_id=workspace_id,
        batch_id=batch_id,
        file_id=file_id,
        raw_value="Acme Ltd",
    )
    second = _claim(
        workspace_id=workspace_id,
        batch_id=batch_id,
        file_id=file_id,
        raw_value="ACME",
    )
    conflict = _conflict(
        workspace_id=workspace_id,
        batch_id=batch_id,
        claim_ids=[first.claim_id, second.claim_id],
    )
    db_session.add_all([first, second, conflict])
    await db_session.flush()

    await resolve_conflict(
        db_session,
        workspace_id,
        conflict.conflict_id,
        None,
        "escalated",
        "The values need confirmation from the workspace owner.",
        str(uuid4()),
    )
    readiness = await compute_readiness(db_session, workspace_id, batch_id)

    assert conflict.status == "escalated"
    assert readiness.state == "blocked"
    assert readiness.blocking_conflict_count == 1
    assert readiness.open_conflict_count == 1
    assert readiness.pending_claim_count == 2

    await resolve_conflict(
        db_session,
        workspace_id,
        conflict.conflict_id,
        first.claim_id,
        "approved",
        "The owner confirmed the ERP master value.",
        str(uuid4()),
    )

    assert conflict.status == "resolved"
    assert first.claim_state == ClaimState.ACCEPTED.value
    assert second.claim_state == ClaimState.SUPERSEDED.value
    final_readiness = await compute_readiness(db_session, workspace_id, batch_id)
    assert final_readiness.state == "ready_with_assumptions"


@pytest.mark.asyncio
async def test_detect_conflicts_does_not_recreate_suppressed_conflict(
    db_session: AsyncSession,
) -> None:
    workspace_id, batch_id, file_id = str(uuid4()), str(uuid4()), str(uuid4())
    first = _claim(
        workspace_id=workspace_id,
        batch_id=batch_id,
        file_id=file_id,
        raw_value="Acme Ltd",
    )
    second = _claim(
        workspace_id=workspace_id,
        batch_id=batch_id,
        file_id=file_id,
        raw_value="ACME",
    )
    conflict = _conflict(
        workspace_id=workspace_id,
        batch_id=batch_id,
        claim_ids=[first.claim_id, second.claim_id],
    )
    conflict.status = "suppressed"
    conflict.review_required = False
    db_session.add_all([first, second, conflict])
    await db_session.flush()

    result = await detect_conflicts(db_session, workspace_id, batch_id)

    assert result.conflicts_detected == 0
    stored_conflicts = list(
        (
            await db_session.scalars(
                select(EvidenceConflict).where(
                    EvidenceConflict.workspace_id == workspace_id,
                    EvidenceConflict.batch_id == batch_id,
                )
            )
        ).all()
    )
    assert len(stored_conflicts) == 1
    assert stored_conflicts[0].status == "suppressed"
