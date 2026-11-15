"""Fresh-data compiler invariants for the RC0 ingestion journey."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.modules.compiler.models import EvidenceClaim
from app.modules.compiler.service import extract_claims
from app.modules.sources.models import SourceColumnProfile


@pytest.mark.asyncio
async def test_claim_extraction_is_idempotent(db_session) -> None:
    profile = SourceColumnProfile(
        profile_id="profile-1",
        file_id="file-1",
        workspace_id="workspace-1",
        column_name="supplier_id",
        column_index=0,
        inferred_type="string",
        null_ratio=0.0,
        distinct_count=1,
        sample_values=["supplier-1"],
        recommended_mapping="supplier_id",
        mapping_confidence=1.0,
        requires_review=False,
    )
    db_session.add(profile)
    await db_session.flush()

    first = await extract_claims(
        db_session,
        "workspace-1",
        "batch-1",
        "file-1",
        [profile],
    )
    second = await extract_claims(
        db_session,
        "workspace-1",
        "batch-1",
        "file-1",
        [profile],
    )

    claims = (
        (
            await db_session.execute(
                select(EvidenceClaim).where(
                    EvidenceClaim.workspace_id == "workspace-1",
                    EvidenceClaim.batch_id == "batch-1",
                )
            )
        )
        .scalars()
        .all()
    )
    assert first.claims_created == 1
    assert second.claims_created == 0
    assert len(claims) == 1
