"""Notification pipeline models — durable, policy-gated deliveries (Day 25).

Every delivered notification is persisted: the phone's notification state is
reconstructible from this table after reconnect/backgrounding.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.common.ids import uuid7
from app.infrastructure.database import Base


def _now() -> datetime:
    return datetime.now(UTC)


class NotificationDB(Base):
    """A policy-gated notification delivery (durable, replayable)."""

    __tablename__ = "vanessa_notifications"

    notification_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uuid7)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    device_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    delivered_via: Mapped[str] = mapped_column(String(32), nullable=False)
    delivered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


__all__ = ["NotificationDB"]
