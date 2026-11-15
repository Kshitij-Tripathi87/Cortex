"""Notification pipeline — policy-gated, provider-agnostic (Day 25).

    Vanessa Event -> Notification Policy -> Notification Service
                  -> Push Provider -> Phone

The policy is the gate: do NOT notify on every agent/tool event. Only the
operationally significant event types fan out to the push provider.

The provider is pluggable (same pattern as the S3 swap): the local
StubPushProvider records the delivery durably so the phone's notification
state is reconstructible; real providers (FCM/APNs) wire in later via
config without touching this module's contract.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.models import NotificationDB

logger = logging.getLogger("nexus.notifications")

# The policy: notify ONLY on these. Everything else (agent activity, tool
# events, intermediate task steps) is intentionally silent.
NOTIFY_EVENT_TYPES = {
    "TASK_COMPLETED",
    "TASK_FAILED",
    "TASK_BLOCKED",
    "APPROVAL_REQUIRED",
    "DEVICE_OFFLINE",
    "DEVICE_RECONNECTED",
    "IMPORTANT_RESULT",
}

# Human-readable titles per event type.
_TITLES = {
    "TASK_COMPLETED": "Task completed",
    "TASK_FAILED": "Task failed",
    "TASK_BLOCKED": "Task blocked",
    "APPROVAL_REQUIRED": "Approval required",
    "DEVICE_OFFLINE": "Device offline",
    "DEVICE_RECONNECTED": "Device reconnected",
    "IMPORTANT_RESULT": "Result",
}


@dataclass
class Delivery:
    """One provider delivery (what the stub records / a real provider sends)."""

    user_id: str
    device_id: str | None
    event_type: str
    title: str
    body: str | None
    payload: dict[str, Any] = field(default_factory=dict)


class PushProvider(Protocol):
    """Provider-agnostic push delivery contract."""

    name: str

    async def send(self, delivery: Delivery) -> bool:
        """Deliver one notification; return True when accepted."""
        ...


class StubPushProvider:
    """Local provider: records deliveries durably (no external service).

    The delivery row IS the phone-visible state — the bootstrap and
    /notifications reads reconstruct from it, so the reconnection contract
    holds without a real push service.
    """

    name = "stub"

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def send(self, delivery: Delivery) -> bool:
        rec = NotificationDB(
            tenant_id=delivery.payload.get("tenant_id", ""),
            user_id=delivery.user_id,
            device_id=delivery.device_id,
            event_type=delivery.event_type,
            title=delivery.title,
            body=delivery.body,
            payload=delivery.payload,
            delivered_via=self.name,
            delivered_at=datetime.now(UTC),
        )
        self.session.add(rec)
        await self.session.flush()
        logger.info(
            "notification delivered ev=%s user=%s device=%s via=%s",
            delivery.event_type,
            delivery.user_id,
            delivery.device_id,
            self.name,
        )
        return True


class NotificationService:
    """Policy gate + fan-out to the registered provider."""

    def __init__(self, provider: PushProvider) -> None:
        self.provider = provider

    async def notify(
        self,
        session: AsyncSession,
        *,
        event_type: str,
        user_id: str,
        tenant_id: str,
        device_id: str | None = None,
        body: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Fan out ONE event through the policy. Returns the delivery info
        when the policy allowed it; None when suppressed (agent/tool noise)."""
        if event_type not in NOTIFY_EVENT_TYPES:
            logger.info("notification suppressed ev=%s (not policy-significant)", event_type)
            return None

        full_payload = {"tenant_id": tenant_id, **(payload or {})}
        delivery = Delivery(
            user_id=user_id,
            device_id=device_id,
            event_type=event_type,
            title=_TITLES.get(event_type, event_type),
            body=body,
            payload=full_payload,
        )
        ok = await self.provider.send(delivery)
        return {
            "event_type": event_type,
            "user_id": user_id,
            "device_id": device_id,
            "delivered_via": self.provider.name,
            "delivered": ok,
        }

    async def list_notifications(
        self,
        session: AsyncSession,
        *,
        user_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        rows = await session.execute(
            select(NotificationDB)
            .where(NotificationDB.user_id == user_id)
            .order_by(NotificationDB.delivered_at.desc())
            .limit(limit)
        )
        return [
            {
                "notification_id": r.notification_id,
                "event_type": r.event_type,
                "title": r.title,
                "body": r.body,
                "payload": r.payload,
                "delivered_via": r.delivered_via,
                "delivered_at": r.delivered_at.isoformat(),
                "read_at": r.read_at.isoformat() if r.read_at else None,
            }
            for r in rows.scalars().all()
        ]


def get_notification_service(session: AsyncSession) -> NotificationService:
    """Build the service with the configured provider (stub locally)."""
    return NotificationService(StubPushProvider(session))


__all__ = [
    "NOTIFY_EVENT_TYPES",
    "Delivery",
    "NotificationService",
    "PushProvider",
    "StubPushProvider",
    "get_notification_service",
]
