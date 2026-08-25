"""Audit API v1 — read audit events."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database import get_db
from app.infrastructure.security import (
    AuthContext,
    get_current_user,
    require_workspace_access,
)
from app.modules.audit.service import list_events

router = APIRouter()


class AuditEventResponse(BaseModel):
    event_id: str
    event_type: str
    event_category: str
    workspace_id: str | None
    subject_type: str | None
    subject_id: str | None
    message: str | None
    occurred_at: str
    correlation_id: str | None = None
    payload: dict


@router.get("", response_model=list[AuditEventResponse])
async def list_audit_events(
    workspace_id: str = Query(..., description="Workspace id (UUID)"),
    event_type: str | None = Query(None),
    subject_id: str | None = Query(None, max_length=128),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> list[AuditEventResponse]:
    """List audit events for a workspace. Authorized to the requested workspace only."""
    require_workspace_access(workspace_id, auth)
    events = await list_events(
        db,
        workspace_id=workspace_id,
        event_type=event_type,
        subject_id=subject_id,
        limit=limit,
        offset=offset,
    )
    return [
        AuditEventResponse(
            event_id=e.event_id,
            event_type=e.event_type,
            event_category=e.event_category,
            workspace_id=e.workspace_id,
            subject_type=e.subject_type,
            subject_id=e.subject_id,
            message=e.message,
            occurred_at=e.occurred_at.isoformat(),
            correlation_id=getattr(e, "correlation_id", None),
            payload=e.payload,
        )
        for e in events
    ]
