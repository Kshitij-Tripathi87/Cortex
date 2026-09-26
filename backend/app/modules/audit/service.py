"""Audit service — the only writer of audit events."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.ids import uuid7
from app.infrastructure.tenant import TenantContext, set_tenant_context
from app.modules.audit.models import AuditEvent


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

    RLS gate (migration 002): the tenant_isolation/audit_workspace_isolation
    policies require the session GUCs (app.tenant_id / app.workspace_id) to
    name the tenant/workspace the row declares, and NULL-tenant rows are
    unwritable under FORCEd RLS. The tenant defaults to the workspace's
    organization (the tenant root, resolved in the same transaction) or
    "system" for workspace-less events; the GUCs are then set from the
    row's own server-validated values via SET LOCAL — scoped to this
    transaction and auto-unset at commit/rollback.
    """

    from app.modules.access.models import Organization, Workspace

    effective_tenant = tenant_id
    if effective_tenant is None and workspace_id is not None:
        row = await db.execute(
            select(Organization.id)
            .join(Workspace, Workspace.organization_id == Organization.id)
            .where(Workspace.id == workspace_id)
        )
        org = row.scalar()
        effective_tenant = str(org) if org is not None else None
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
    await set_tenant_context(
        db, TenantContext(tenant_id=effective_tenant, workspace_id=workspace_id or "")
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

    RLS: the workspace's organization is set as the session tenant so the
    tenant_isolation policy returns exactly that org's rows (and no other
    tenant's — the default-deny applies when unset).
    """

    from app.modules.access.models import Organization, Workspace

    row = await db.execute(
        select(Organization.id)
        .join(Workspace, Workspace.organization_id == Organization.id)
        .where(Workspace.id == workspace_id)
    )
    org = row.scalar()
    tenant = str(org) if org is not None else "system"
    await set_tenant_context(db, TenantContext(tenant_id=tenant, workspace_id=workspace_id))
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
