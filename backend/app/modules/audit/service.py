"""Audit service — the only writer of audit events."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.ids import uuid7
from app.modules.audit.models import AuditEvent


async def emit(
    db: AsyncSession,
    *,
    event_type: str,
    workspace_id: str | None = None,
    event_category: str = "audit",
    actor_id: str | None = None,
    actor_type: str = "system",
    subject_type: str | None = None,
    subject_id: str | None = None,
    correlation_id: str | None = None,
    request_id: str | None = None,
    payload: dict[str, Any] | None = None,
    message: str | None = None,
) -> AuditEvent:
    """Emit a single immutable audit event. INSERT-only — never returns an UPDATE path."""
    event = AuditEvent(
        event_id=uuid7(),
        workspace_id=workspace_id,
        event_type=event_type,
        event_category=event_category,
        actor_id=actor_id,
        actor_type=actor_type,
        subject_type=subject_type,
        subject_id=subject_id,
        correlation_id=correlation_id,
        request_id=request_id,
        payload=payload or {},
        message=message,
        occurred_at=datetime.now(UTC),
    )
    db.add(event)
    await db.flush()
    return event


async def list_events(
    db: AsyncSession,
    *,
    workspace_id: str,
    event_type: str | None = None,
    subject_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[AuditEvent]:
    """Read audit events scoped by workspace. Newest first."""
    stmt = (
        select(AuditEvent)
        .where(AuditEvent.workspace_id == workspace_id)
        .order_by(AuditEvent.occurred_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if event_type:
        stmt = stmt.where(AuditEvent.event_type == event_type)
    if subject_id:
        stmt = stmt.where(AuditEvent.subject_id == subject_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())
