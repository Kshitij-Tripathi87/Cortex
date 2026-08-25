"""Readiness API v1 — compute and retrieve readiness assessments."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database import get_db
from app.infrastructure.security import (
    AuthContext,
    get_current_user,
    require_workspace_access,
)
from app.modules.compiler.models import ReadinessAssessment
from app.modules.compiler.service import compute_readiness

router = APIRouter()

# StrUUID-ish pattern. Loose: 1-64 chars from a safe set. UUIDs accepted,
# but other opaque-looking workspace ids also pass (e.g. "workspace-default"
# used in dev defaults).
_SAFE_WS_ID = r"^[A-Za-z0-9._\-:]{1,64}$"


class ReadinessResponse:
    """Placeholder kept for type-compatibility; real model defined below."""

    pass


from pydantic import BaseModel  # noqa: E402


class ReadinessResponse(BaseModel):  # noqa: F811
    assessment_id: str
    workspace_id: str
    batch_id: str
    state: str
    blocking_conflict_count: int
    open_conflict_count: int
    accepted_claim_count: int
    pending_claim_count: int
    assumptions: list[str]
    explanation: str


@router.post("/batches/{batch_id}", response_model=ReadinessResponse)
async def compute_readiness_endpoint(
    batch_id: str,
    workspace_id: str = Query(..., min_length=1, max_length=64, pattern=_SAFE_WS_ID),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> ReadinessResponse:
    """Compute readiness for a batch. Caller is authorized for `workspace_id`."""
    require_workspace_access(workspace_id, auth)
    from app.modules.sources.service import get_batch

    batch = await get_batch(db, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    if batch.workspace_id != workspace_id:
        # Workspace mismatch: do not leak the batch's existence to other workspaces.
        raise HTTPException(status_code=404, detail="Batch not found")

    result = await compute_readiness(db, batch.workspace_id, batch_id)

    assessment = ReadinessAssessment(
        assessment_id="temp",
        workspace_id=batch.workspace_id,
        batch_id=batch_id,
        state=result.state,
        blocking_conflict_count=result.blocking_conflict_count,
        open_conflict_count=result.open_conflict_count,
        accepted_claim_count=result.accepted_claim_count,
        pending_claim_count=result.pending_claim_count,
        assumptions=result.assumptions,
        explanation=result.explanation,
    )
    db.add(assessment)
    await db.flush()
    await db.commit()

    return ReadinessResponse(
        assessment_id=assessment.assessment_id,
        batch_id=assessment.batch_id,
        workspace_id=assessment.workspace_id,
        state=assessment.state,
        blocking_conflict_count=assessment.blocking_conflict_count,
        open_conflict_count=assessment.open_conflict_count,
        accepted_claim_count=assessment.accepted_claim_count,
        pending_claim_count=assessment.pending_claim_count,
        assumptions=assessment.assumptions,
        explanation=assessment.explanation,
    )


@router.get("/assessments/{assessment_id}", response_model=ReadinessResponse)
async def get_readiness(
    assessment_id: str,
    workspace_id: str = Query(..., min_length=1, max_length=64, pattern=_SAFE_WS_ID),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> ReadinessResponse:
    """Get a readiness assessment by ID, scoped to the requested workspace."""
    require_workspace_access(workspace_id, auth)
    stmt = (
        select(ReadinessAssessment)
        .where(ReadinessAssessment.assessment_id == assessment_id)
        .where(ReadinessAssessment.workspace_id == workspace_id)
    )
    result = await db.execute(stmt)
    assessment = result.scalar_one_or_none()
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    return ReadinessResponse(
        assessment_id=assessment.assessment_id,
        batch_id=assessment.batch_id,
        workspace_id=assessment.workspace_id,
        state=assessment.state,
        blocking_conflict_count=assessment.blocking_conflict_count,
        open_conflict_count=assessment.open_conflict_count,
        accepted_claim_count=assessment.accepted_claim_count,
        pending_claim_count=assessment.pending_claim_count,
        assumptions=assessment.assumptions,
        explanation=assessment.explanation,
    )
