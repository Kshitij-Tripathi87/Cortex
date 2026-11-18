"""Audit service — the only writer of audit events."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.ids import uuid7
from app.modules.audit.models import AuditEvent


def _workspace_db_id(workspace_id: str) -> UUID | None:
    """Convert an authenticated workspace identifier for UUID-backed access models.

    The public API and audit row retain string IDs, while access.Workspace.id
    is SQLAlchemy UUID(as_uuid=True). Passing the raw string to that column
    raises AttributeError during bind processing instead of producing a
    normal scoped lookup.
    """
    try:
        return UUID(str(workspace_id))
    except (TypeError, ValueError):
        return None


def _has_access_tables(db: AsyncSession) -> bool:
    """Whether this database holds the ``core`` tables that say who owns a workspace.

    They exist only on PostgreSQL. The SQLite engines used for local
    development and by the unit-test fixtures hold schema-less tables only,
    so there is no organization to look up there. Same dialect guard as
    ``acquire_world_write_lock`` and the outbox publisher's advisory locks.
    """
    return db.get_bind().dialect.name == "postgresql"


async def _workspace_tenant(db: AsyncSession, workspace_id: str) -> str | None:
    """Resolve the organization (tenant root) that owns ``workspace_id``."""
    from app.modules.access.models import Organization, Workspace

    row = await db.execute(
        select(Organization.id)
        .join(Workspace, Workspace.organization_id == Organization.id)
        .where(Workspace.id == _workspace_db_id(workspace_id))
    )
    org = row.scalar()
    return str(org) if org is not None else None


async def emit(
    db: AsyncSession,
    *,
    event_type: str,
    workspace_id: str | None = None,
    tenant_id: str | None = None,
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
    """Emit a single immutable audit event. INSERT-only — never returns an UPDATE path.

    Every event records the organization it belongs to in ``tenant_id``: the
    caller's value, else the organization that owns the workspace (looked up
    in the same transaction, on PostgreSQL), else "system" for events without
    a workspace.

    The row-level security policies that used to sit on this table were
    removed by migration 026; nothing reads a session setting any more, so
    none is written. What keeps one customer's log from another is the
    workspace check on the request and the workspace filter in ``list_events``
    (``docs/architecture/TENANT_ISOLATION.md``).
    """

    effective_tenant = tenant_id
    if effective_tenant is None and workspace_id is not None and _has_access_tables(db):
        effective_tenant = await _workspace_tenant(db, workspace_id)
    if effective_tenant is None:
        effective_tenant = "system"

    event = AuditEvent(
        event_id=uuid7(),
        workspace_id=workspace_id,
        tenant_id=effective_tenant,
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
    """Read audit events scoped by workspace. Newest first.

    The workspace filter below is what scopes the read. The caller must have
    checked that the signed-in user may read this workspace.
    """

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
