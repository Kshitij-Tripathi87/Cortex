"""Mobile API — authoritative bootstrap snapshot + session separation (Day 25).

On first launch / login / reconnect / app resume the phone reconstructs its
state from GET /mobile/bootstrap — the authoritative snapshot. The phone
never treats a local UI state as authoritative; server state wins.

Session separation (do not collapse these):

    user session   the authenticated principal (JWT)
    voice session  a vanessa_voice_sessions row (voice state machine)
    task session   a vanessa_sessions row (session_type="task", ref_id=task)

Reconnecting the voice client must never create a new task — the task
session is a separate record.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database import get_db
from app.infrastructure.security import AuthContext, get_current_user
from app.modules.devices.models import MobileSessionDB
from app.modules.devices.service import DeviceMeshService

router = APIRouter()

ACTIVE_TASK_STATUSES = {"PENDING", "PLANNING", "EXECUTING", "VERIFYING", "AWAITING_APPROVAL"}


class MobileSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_type: str = Field(min_length=1, max_length=16)  # user|voice|task
    ref_id: str | None = Field(default=None, max_length=64)
    ttl_s: int = Field(default=86400, ge=60, le=7 * 86400)


class PushRegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str = Field(min_length=1, max_length=64)
    provider: str = Field(default="stub", max_length=32)  # fcm|apns|stub
    push_token: str = Field(min_length=1, max_length=512)


@router.get("/mobile/bootstrap")
async def mobile_bootstrap(
    request: Request,
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Authoritative snapshot: user, devices, active_tasks, pending_approvals,
    recent_events. The phone's state is reconstructible from this response."""
    user_id = str(auth.user_id or "anonymous")

    # Devices the principal owns.
    devices = await DeviceMeshService(session).list_devices(owner_id=user_id)

    # Active tasks owned by the principal.
    from app.modules.orchestration.task_runtime_models import TaskDB

    task_rows = await session.execute(
        select(TaskDB)
        .where(TaskDB.actor_id == user_id, TaskDB.status.in_(ACTIVE_TASK_STATUSES))
        .order_by(TaskDB.created_at.desc())
        .limit(20)
    )
    active_tasks = [
        {
            "task_id": t.task_id,
            "status": t.status,
            "objective": t.objective,
            "workspace_id": t.workspace_id,
            "world_state_version": t.world_state_version,
            "requires_approval": t.requires_approval,
            "blocked_reason": t.blocked_reason,
            "created_at": t.created_at.isoformat(),
        }
        for t in task_rows.scalars().all()
    ]

    # Pending approvals on the principal's tasks (REQUESTED = awaiting human).
    from app.modules.orchestration.task_runtime_models import TaskApprovalDB

    approval_rows = await session.execute(
        select(TaskApprovalDB, TaskDB)
        .join(TaskDB, TaskDB.task_id == TaskApprovalDB.task_id)
        .where(
            TaskApprovalDB.decision == "REQUESTED",
            TaskDB.actor_id == user_id,
        )
        .order_by(TaskApprovalDB.created_at.desc())
        .limit(20)
    )
    pending_approvals = [
        {
            "approval_id": a.approval_id,
            "task_id": a.task_id,
            "task_status": t.status,
            "reason": a.reason,
            "created_at": a.created_at.isoformat(),
        }
        for a, t in approval_rows.all()
    ]

    # Recent durable events for the principal's workspaces.
    from app.modules.nexus_spine.persistence.repositories import get_event_repository

    recent_events: list[dict[str, Any]] = []
    repo = get_event_repository()
    for device_ws in {t["workspace_id"] for t in active_tasks if t["workspace_id"]}:
        try:
            env = await _recent_for_workspace(
                repo, session, workspace_id=str(device_ws), user_id=user_id
            )
            recent_events.extend(env)
        except Exception:  # noqa: BLE001, S112 — bootstrap must not fail on one ws
            continue
    recent_events = recent_events[:50]

    return {
        "data": {
            "user": {
                "user_id": user_id,
                "email": auth.email,
                "roles": list(auth.roles or []),
            },
            "devices": devices,
            "active_tasks": active_tasks,
            "pending_approvals": pending_approvals,
            "recent_events": recent_events,
            "bootstrap_at": datetime.now(UTC).isoformat(),
        }
    }


async def _recent_for_workspace(
    repo: Any, session: AsyncSession, *, workspace_id: str, user_id: str
) -> list[dict[str, Any]]:
    head, _ = await repo.get_head(session, tenant_id=user_id, workspace_id=workspace_id)
    after = max(0, head - 20)
    rows = await repo.get_since_seq(
        session, workspace_id=workspace_id, since_seq=after, tenant_id=user_id, limit=20
    )
    return [
        {
            "workspace_id": workspace_id,
            "seq": r.seq,
            "event_type": getattr(r, "event_type", "event"),
            "entity_type": getattr(r, "entity_type", None),
            "entity_id": getattr(r, "entity_id", None),
        }
        for r in rows
    ]


@router.post("/mobile/sessions", status_code=201)
async def create_mobile_session(
    body: MobileSessionRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Create a session row (user | voice | task). Task sessions carry the
    task ref — voice reconnects never create tasks."""
    if body.session_type not in {"user", "voice", "task"}:
        raise HTTPException(status_code=422, detail="invalid session_type")
    user_id = str(auth.user_id or "anonymous")
    rec = MobileSessionDB(
        session_id=f"sess-{uuid.uuid4().hex[:20]}",
        tenant_id=user_id,
        user_id=user_id,
        device_id=request.headers.get("X-Device-Id") or "unknown",
        session_type=body.session_type,
        ref_id=body.ref_id,
        expires_at=datetime.now(UTC) + timedelta(seconds=body.ttl_s),
    )
    session.add(rec)
    await session.commit()
    return {
        "data": {
            "session_id": rec.session_id,
            "session_type": rec.session_type,
            "ref_id": rec.ref_id,
            "device_id": rec.device_id,
            "expires_at": rec.expires_at.isoformat() if rec.expires_at else None,
        }
    }


@router.get("/mobile/sessions")
async def list_mobile_sessions(
    request: Request,
    session_type: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    user_id = str(auth.user_id or "anonymous")
    stmt = (
        select(MobileSessionDB)
        .where(
            MobileSessionDB.user_id == user_id,
            MobileSessionDB.revoked_at.is_(None),
        )
        .order_by(MobileSessionDB.created_at.desc())
        .limit(50)
    )
    if session_type:
        stmt = stmt.where(MobileSessionDB.session_type == session_type)
    rows = await session.execute(stmt)
    return {
        "data": {
            "sessions": [
                {
                    "session_id": r.session_id,
                    "session_type": r.session_type,
                    "ref_id": r.ref_id,
                    "device_id": r.device_id,
                    "created_at": r.created_at.isoformat(),
                    "expires_at": r.expires_at.isoformat() if r.expires_at else None,
                }
                for r in rows.scalars().all()
            ]
        }
    }


@router.post("/mobile/push/register", status_code=201)
async def register_push(
    body: PushRegisterRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Enroll a push token: one device, one provider, one token."""
    from app.modules.devices.models import PushRegistrationDB

    user_id = str(auth.user_id or "anonymous")
    rec = PushRegistrationDB(
        registration_id=f"push-{uuid.uuid4().hex[:20]}",
        tenant_id=user_id,
        user_id=user_id,
        device_id=body.device_id,
        provider=body.provider,
        push_token=body.push_token,
        active=True,
    )
    session.add(rec)
    await session.commit()
    return {
        "data": {
            "registration_id": rec.registration_id,
            "device_id": rec.device_id,
            "provider": rec.provider,
            "active": rec.active,
        }
    }


@router.get("/mobile/notifications")
async def list_notifications(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """The phone's durable notification state (reconstructed on reconnect)."""
    from app.modules.notifications.service import get_notification_service

    user_id = str(auth.user_id or "anonymous")
    notifications = await get_notification_service(session).list_notifications(
        session, user_id=user_id, limit=limit
    )
    return {"data": {"notifications": notifications, "count": len(notifications)}}
