"""Source intake on real PostgreSQL: upload -> prepare -> review -> conflicts -> readiness.

Regression for defects that the in-memory SQLite test database cannot show:

* the intake models declared ``Mapped[datetime]`` columns without a column type,
  so asyncpg rejected every INSERT into ``source_batches``, ``source_files``,
  ``evidence_claims``, ``evidence_conflicts``, ``conflict_resolutions`` and
  ``readiness_assessments`` (HTTP 500 on ``POST /sources/upload``);
* ``POST /readiness/batches/{id}`` stored every assessment under one fixed
  primary key, so only the first assessment in a database could be saved.

The test drives the HTTP routes with one database session per request, exactly
as production does, and skips when PostgreSQL is not available.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import MetaData, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateSchema

from app.api.v1 import readiness, sources
from app.infrastructure import storage_client
from app.infrastructure.database import get_db
from app.infrastructure.security import AuthContext, get_current_user
from app.modules.access.models import Organization, Workspace
from app.modules.audit.models import AuditEvent
from app.modules.compiler.models import (
    ConflictResolution,
    EvidenceClaim,
    EvidenceConflict,
    ReadinessAssessment,
)
from app.modules.sources.models import SourceBatch, SourceColumnProfile, SourceFile

INTAKE_MODELS = (
    SourceBatch,
    SourceFile,
    SourceColumnProfile,
    EvidenceClaim,
    EvidenceConflict,
    ConflictResolution,
    ReadinessAssessment,
    AuditEvent,
)

CANONICAL_FIELD = {
    "supplier_id": "supplier_id",
    "supplier_name": "legal_name",
    "country": "country",
}

# Two rows describe the same supplier with a different name and country.
SUPPLIERS_CSV = b"supplier_id,supplier_name,country\nS-1,Acme Metals,DE\nS-1,Acme Metals GmbH,AT\n"


class _MemoryStorage:
    """Stand-in for the S3 client; the database is the subject of this test."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def object_exists(self, key: str) -> bool:
        return key in self.objects

    def put_object(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> None:
        self.objects[key] = bytes(data)

    def get_object(self, key: str) -> bytes:
        return self.objects[key]


@pytest.fixture
async def intake_sessions(request: Any) -> AsyncGenerator[async_sessionmaker[AsyncSession]]:
    try:
        engine = create_async_engine(request.config.postgres_url, echo=False)
        async with engine.begin() as conn:
            await conn.execute(select(1))
    except Exception as exc:  # any connection failure means "no PostgreSQL here"
        pytest.skip(f"PostgreSQL not available: {exc}")

    # A migrated database (CI) already has these tables; create_all is then a no-op.
    # The audit writer resolves the tenant through core.organizations/core.workspaces.
    metadata = MetaData()
    for model in (Organization, Workspace, *INTAKE_MODELS):
        model.__table__.to_metadata(metadata)
    async with engine.begin() as conn:
        await conn.execute(CreateSchema("core", if_not_exists=True))
        await conn.run_sync(metadata.create_all)

    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def intake(
    intake_sessions: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[tuple[AsyncClient, str]]:
    workspace_id = str(uuid4())
    storage = _MemoryStorage()
    monkeypatch.setattr(storage_client, "get_storage", lambda settings=None: storage)

    app = FastAPI()
    app.include_router(sources.router, prefix="/api/v1/sources")
    app.include_router(readiness.router, prefix="/api/v1/readiness")

    async def override_db() -> AsyncGenerator[AsyncSession]:
        async with intake_sessions() as session:
            yield session

    async def override_user() -> AuthContext:
        return AuthContext(
            user_id=str(uuid4()),
            roles=["admin"],
            workspace_ids=[workspace_id],
            is_anonymous=False,
        )

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, workspace_id

    async with intake_sessions() as session:
        for model in reversed(INTAKE_MODELS):
            await session.execute(delete(model).where(model.workspace_id == workspace_id))
        await session.commit()


async def test_source_intake_path_persists_on_postgresql(
    intake: tuple[AsyncClient, str],
    intake_sessions: async_sessionmaker[AsyncSession],
) -> None:
    client, workspace_id = intake
    query = {"workspace_id": workspace_id}
    form = {"workspace_id": workspace_id, "source_system_hint": "erp"}
    files = {"file": ("suppliers.csv", SUPPLIERS_CSV, "text/csv")}

    upload = await client.post("/api/v1/sources/upload", data=form, files=files)
    assert upload.status_code == 200, upload.text
    batch_id = upload.json()["batch_id"]
    assert upload.json()["is_duplicate"] is False

    duplicate = await client.post("/api/v1/sources/upload", data=form, files=files)
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["is_duplicate"] is True
    assert duplicate.json()["batch_id"] == batch_id

    prepared = await client.post(f"/api/v1/sources/batches/{batch_id}/compile", params=query)
    assert prepared.status_code == 200, prepared.text
    assert prepared.json()["claims_created"] == 6

    claims = await client.get(f"/api/v1/sources/batches/{batch_id}/claims", params=query)
    assert claims.status_code == 200, claims.text
    assert len(claims.json()) == 6
    for claim in claims.json():
        review = await client.post(
            f"/api/v1/sources/batches/{batch_id}/claims/{claim['claim_id']}/review",
            params=query,
            json={
                "decision": "accepted",
                "rationale": "Checked against the supplier master.",
                "canonical_entity": "Supplier",
                "canonical_field": CANONICAL_FIELD[claim["source_column"]],
                "entity_key": "S-1",
            },
        )
        assert review.status_code == 200, review.text

    conflicts = await client.get(f"/api/v1/sources/batches/{batch_id}/conflicts", params=query)
    assert conflicts.status_code == 200, conflicts.text
    assert {item["canonical_field"] for item in conflicts.json()} == {"legal_name", "country"}

    resolved = await client.post(
        f"/api/v1/sources/conflicts/{conflicts.json()[0]['conflict_id']}/resolve",
        params=query,
        json={"action": "suppressed", "rationale": "Known alias of the same supplier."},
    )
    assert resolved.status_code == 200, resolved.text

    # The evidence page asks for readiness on every load, so it must be repeatable.
    first = await client.post(f"/api/v1/readiness/batches/{batch_id}", params=query)
    second = await client.post(f"/api/v1/readiness/batches/{batch_id}", params=query)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["assessment_id"] != second.json()["assessment_id"]

    async with intake_sessions() as session:
        stored = {
            model.__tablename__: await session.scalar(
                select(func.count()).select_from(model).where(model.workspace_id == workspace_id)
            )
            for model in INTAKE_MODELS
        }
        batch = await session.get(SourceBatch, batch_id)

    assert stored["source_batches"] == 1
    assert stored["source_files"] == 1
    assert stored["source_column_profiles"] == 3
    assert stored["evidence_claims"] == 6
    assert stored["evidence_conflicts"] == 2
    assert stored["conflict_resolutions"] == 1
    assert stored["readiness_assessments"] == 2
    assert batch is not None
    assert batch.created_at.tzinfo is not None  # read back as TIMESTAMP WITH TIME ZONE
