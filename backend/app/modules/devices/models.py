"""Device Mesh models — capability-bearing Vanessa devices (Day 25).

The phone is a first-class mesh node, not a UI client:

    MobileDeviceDB        device identity, capabilities, presence
    MobileSessionDB       User / Voice / Task session separation
    VoiceSessionDB        the voice state machine (provider-agnostic)
    PushRegistrationDB    push-token enrollment per device + provider

Fresh databases are owned by init_db/create_all; existing databases are
migrated by 020_device_mesh. IDs are String(64) with the domain prefixes
(usr_/dev_/voice_/sess_/push_ + uuid).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.common.ids import uuid7
from app.infrastructure.database import Base


def _now() -> datetime:
    return datetime.now(UTC)


class MobileDeviceDB(Base):
    """A capability-bearing device in the mesh (phone, laptop, server...)."""

    __tablename__ = "vanessa_devices"

    device_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uuid7)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    public_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    agent_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1.0")
    capabilities: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="OFFLINE", index=True)
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )

    __table_args__ = (Index("ix_vanessa_devices_owner_status", "owner_id", "status"),)


class MobileSessionDB(Base):
    """Session separation: user | voice | task sessions are distinct rows.

    Reconnecting the voice client must never create a new task — the task
    session is a separate record (session_type="task", ref_id=task_id).
    """

    __tablename__ = "vanessa_sessions"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uuid7)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    device_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    session_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    ref_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_vanessa_sessions_type_user", "session_type", "user_id"),)


class VoiceSessionDB(Base):
    """The voice state machine — user-visible, provider-agnostic.

    IDLE → CONNECTING → LISTENING → THINKING → SPEAKING → EXECUTING → LISTENING
    Failure: DISCONNECTED → RECONNECTING → RESYNCING → CONNECTED
    """

    __tablename__ = "vanessa_voice_sessions"

    voice_session_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uuid7)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    workspace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    device_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="IDLE", index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="stub")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PushRegistrationDB(Base):
    """Push-token enrollment: one device, one provider, one token."""

    __tablename__ = "vanessa_push_registrations"

    registration_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uuid7)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    device_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="stub")
    push_token: Mapped[str] = mapped_column(String(512), nullable=False)
    active: Mapped[bool] = mapped_column(nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )


__all__ = [
    "MobileDeviceDB",
    "MobileSessionDB",
    "PushRegistrationDB",
    "VoiceSessionDB",
]
