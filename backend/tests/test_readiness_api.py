"""Readiness API: an assessment can be computed and stored more than once."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import uuid4

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import readiness
from app.infrastructure.database import get_db
from app.infrastructure.security import AuthContext, get_current_user

# Register the models before the db_engine fixture copies Base.metadata.
from app.modules.compiler.models import ReadinessAssessment
from app.modules.sources.models import SourceBatch


async def test_readiness_is_stored_for_every_request(db_session: AsyncSession) -> None:
    workspace_id = str(uuid4())
    batch_ids = [str(uuid4()), str(uuid4())]
    for batch_id in batch_ids:
        db_session.add(
            SourceBatch(
                batch_id=batch_id,
                workspace_id=workspace_id,
                checksum=(uuid4().hex * 2)[:64],
                source_system_hint="erp",
                file_count=1,
            )
        )
    await db_session.flush()

    app = FastAPI()
    app.include_router(readiness.router, prefix="/api/v1/readiness")

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

    assessment_ids: list[str] = []
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Two batches, and the first batch twice: the evidence page re-assesses on every load.
        for batch_id in (batch_ids[0], batch_ids[1], batch_ids[0]):
            response = await client.post(
                f"/api/v1/readiness/batches/{batch_id}", params={"workspace_id": workspace_id}
            )
            assert response.status_code == 200, response.text
            assessment_ids.append(response.json()["assessment_id"])

            fetched = await client.get(
                f"/api/v1/readiness/assessments/{assessment_ids[-1]}",
                params={"workspace_id": workspace_id},
            )
            assert fetched.status_code == 200, fetched.text
            assert fetched.json()["batch_id"] == batch_id

    assert len(set(assessment_ids)) == 3
    stored = (
        await db_session.scalars(
            select(ReadinessAssessment).where(ReadinessAssessment.workspace_id == workspace_id)
        )
    ).all()
    assert sorted(item.assessment_id for item in stored) == sorted(assessment_ids)
