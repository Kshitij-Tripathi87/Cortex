from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import sources
from app.common.enums import ClaimState
from app.infrastructure.database import get_db
from app.infrastructure.security import AuthContext, get_current_user

# Register the models before the db_engine fixture copies Base.metadata.
from app.modules.audit.models import AuditEvent
from app.modules.compiler.models import EvidenceClaim
from app.modules.sources.models import SourceBatch


@pytest.mark.asyncio
async def test_claim_review_is_authenticated_scoped_and_audited(
    db_session: AsyncSession,
) -> None:
    workspace_id = str(uuid4())
    batch_id = str(uuid4())
    file_id = str(uuid4())
    claim_id = str(uuid4())
    actor_id = str(uuid4())

    db_session.add(
        SourceBatch(
            batch_id=batch_id,
            workspace_id=workspace_id,
            checksum=(uuid4().hex * 2)[:64],
            source_system_hint="erp",
            file_count=1,
        )
    )
    db_session.add(
        EvidenceClaim(
            claim_id=claim_id,
            workspace_id=workspace_id,
            source_file_id=file_id,
            batch_id=batch_id,
            row_number=0,
            source_column="supplier_name",
            canonical_entity="Supplier",
            canonical_field="supplier_name",
            raw_value="Acme Ltd",
            normalized_value="Acme Ltd",
            confidence=0.95,
            claim_state=ClaimState.PENDING_REVIEW.value,
            provenance={"profile_id": str(uuid4())},
            requires_review=True,
        )
    )
    await db_session.flush()

    app = FastAPI()
    app.include_router(sources.router, prefix="/api/v1/sources")

    async def override_db() -> AsyncGenerator[AsyncSession]:
        yield db_session

    async def override_user() -> AuthContext:
        return AuthContext(
            user_id=actor_id,
            roles=["admin"],
            workspace_ids=[workspace_id],
            is_anonymous=False,
        )

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/sources/batches/{batch_id}/claims/{claim_id}/review",
            params={"workspace_id": workspace_id},
            json={
                "decision": "accepted",
                "rationale": "Verified against the ERP supplier master.",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["claim_id"] == claim_id
    assert body["claim_state"] == ClaimState.ACCEPTED.value
    assert body["requires_review"] is False

    stored_claim = await db_session.get(EvidenceClaim, claim_id)
    assert stored_claim is not None
    assert stored_claim.claim_state == ClaimState.ACCEPTED.value

    audit_events = list(
        (
            await db_session.scalars(
                select(AuditEvent).where(
                    AuditEvent.workspace_id == workspace_id,
                    AuditEvent.event_type == "evidence.claim.reviewed",
                    AuditEvent.subject_id == claim_id,
                )
            )
        ).all()
    )
    assert len(audit_events) == 1
    assert audit_events[0].actor_id == actor_id
    assert audit_events[0].payload["decision"] == "accepted"
    assert audit_events[0].payload["rationale"] == "Verified against the ERP supplier master."


@pytest.mark.asyncio
async def test_claim_review_rejects_cross_workspace_access_and_non_reviewers(
    db_session: AsyncSession,
) -> None:
    workspace_id = str(uuid4())
    other_workspace_id = str(uuid4())
    batch_id = str(uuid4())
    claim_id = str(uuid4())
    db_session.add(
        SourceBatch(
            batch_id=batch_id,
            workspace_id=workspace_id,
            checksum=(uuid4().hex * 2)[:64],
            source_system_hint="erp",
            file_count=1,
        )
    )
    db_session.add(
        EvidenceClaim(
            claim_id=claim_id,
            workspace_id=workspace_id,
            source_file_id=str(uuid4()),
            batch_id=batch_id,
            row_number=0,
            source_column="supplier_name",
            canonical_entity="Supplier",
            canonical_field="supplier_name",
            raw_value="Acme Ltd",
            normalized_value="Acme Ltd",
            confidence=0.95,
            claim_state=ClaimState.PENDING_REVIEW.value,
            provenance={},
            requires_review=True,
        )
    )
    await db_session.flush()

    app = FastAPI()
    app.include_router(sources.router, prefix="/api/v1/sources")
    current = {"workspace_ids": [workspace_id], "roles": ["engineer"]}

    async def override_db() -> AsyncGenerator[AsyncSession]:
        yield db_session

    async def override_user() -> AuthContext:
        return AuthContext(
            user_id=str(uuid4()),
            roles=current["roles"],
            workspace_ids=current["workspace_ids"],
            is_anonymous=False,
        )

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        wrong_workspace = await client.post(
            f"/api/v1/sources/batches/{batch_id}/claims/{claim_id}/review",
            params={"workspace_id": other_workspace_id},
            json={"decision": "accepted", "rationale": "Must be denied."},
        )
        assert wrong_workspace.status_code == 403

        not_reviewer = await client.post(
            f"/api/v1/sources/batches/{batch_id}/claims/{claim_id}/review",
            params={"workspace_id": workspace_id},
            json={"decision": "accepted", "rationale": "Must be denied."},
        )
        assert not_reviewer.status_code == 403

    stored_claim = await db_session.get(EvidenceClaim, claim_id)
    assert stored_claim is not None
    assert stored_claim.claim_state == ClaimState.PENDING_REVIEW.value


@pytest.mark.asyncio
async def test_claim_review_can_set_an_audited_canonical_mapping(db_session: AsyncSession) -> None:
    workspace_id = str(uuid4())
    batch_id = str(uuid4())
    claim_id = str(uuid4())
    actor_id = str(uuid4())
    db_session.add(
        SourceBatch(
            batch_id=batch_id,
            workspace_id=workspace_id,
            checksum=(uuid4().hex * 2)[:64],
            source_system_hint="erp",
            file_count=1,
        )
    )
    db_session.add(
        EvidenceClaim(
            claim_id=claim_id,
            workspace_id=workspace_id,
            source_file_id=str(uuid4()),
            batch_id=batch_id,
            row_number=0,
            source_column="Vendor Code",
            canonical_entity=None,
            canonical_field=None,
            raw_value="SUP-007",
            normalized_value=None,
            confidence=0.0,
            claim_state=ClaimState.PENDING_REVIEW.value,
            provenance={},
            requires_review=True,
        )
    )
    await db_session.flush()

    app = FastAPI()
    app.include_router(sources.router, prefix="/api/v1/sources")

    async def override_db() -> AsyncGenerator[AsyncSession]:
        yield db_session

    async def override_user() -> AuthContext:
        return AuthContext(
            user_id=actor_id,
            roles=["admin"],
            workspace_ids=[workspace_id],
            is_anonymous=False,
        )

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/sources/batches/{batch_id}/claims/{claim_id}/review",
            params={"workspace_id": workspace_id},
            json={
                "decision": "accepted",
                "rationale": "Verified against the vendor master identifier column.",
                "canonical_entity": "Supplier",
                "canonical_field": "supplier_id",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["canonical_entity"] == "Supplier"
    assert body["canonical_field"] == "supplier_id"
    assert body["confidence"] == 1.0
    stored_claim = await db_session.get(EvidenceClaim, claim_id)
    assert stored_claim is not None
    assert stored_claim.canonical_entity == "Supplier"
    assert stored_claim.canonical_field == "supplier_id"
    assert stored_claim.provenance["human_mapping_review"]["canonical_field"] == "supplier_id"


@pytest.mark.asyncio
async def test_claim_review_requires_a_complete_supported_canonical_mapping(
    db_session: AsyncSession,
) -> None:
    workspace_id = str(uuid4())
    batch_id = str(uuid4())
    claim_id = str(uuid4())
    db_session.add(
        SourceBatch(
            batch_id=batch_id,
            workspace_id=workspace_id,
            checksum=(uuid4().hex * 2)[:64],
            source_system_hint="erp",
            file_count=1,
        )
    )
    db_session.add(
        EvidenceClaim(
            claim_id=claim_id,
            workspace_id=workspace_id,
            source_file_id=str(uuid4()),
            batch_id=batch_id,
            row_number=0,
            source_column="Unknown Header",
            canonical_entity=None,
            canonical_field=None,
            raw_value="some value",
            normalized_value=None,
            confidence=0.0,
            claim_state=ClaimState.PENDING_REVIEW.value,
            provenance={},
            requires_review=True,
        )
    )
    await db_session.flush()

    app = FastAPI()
    app.include_router(sources.router, prefix="/api/v1/sources")

    async def override_db() -> AsyncGenerator[AsyncSession]:
        yield db_session

    async def override_user() -> AuthContext:
        return AuthContext(
            user_id=str(uuid4()),
            roles=["admin"],
            workspace_ids=[workspace_id],
            is_anonymous=False,
        )

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        incomplete = await client.post(
            f"/api/v1/sources/batches/{batch_id}/claims/{claim_id}/review",
            params={"workspace_id": workspace_id},
            json={
                "decision": "accepted",
                "rationale": "Mapping has not been completed.",
            },
        )
        assert incomplete.status_code == 422

        unsupported = await client.post(
            f"/api/v1/sources/batches/{batch_id}/claims/{claim_id}/review",
            params={"workspace_id": workspace_id},
            json={
                "decision": "accepted",
                "rationale": "Mapping has not been completed.",
                "canonical_entity": "__import__",
                "canonical_field": "supplier_id",
            },
        )
        assert unsupported.status_code == 422

    stored_claim = await db_session.get(EvidenceClaim, claim_id)
    assert stored_claim is not None
    assert stored_claim.claim_state == ClaimState.PENDING_REVIEW.value
