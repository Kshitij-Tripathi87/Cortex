"""Audit module — immutable append-only audit event writer.

This is a lightweight Phase 2 implementation: audit events are stored in PostgreSQL
with INSERT-only semantics. The hash-chain from docs/04 will be added in a later phase.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.common.ids import uuid7
from app.infrastructure.database import Base


class AuditEvent(Base):
    """Append-only audit event record. INSERT only — never UPDATE or DELETE."""

    __tablename__ = "audit_events"

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    workspace_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    event_category: Mapped[str] = mapped_column(String(32), nullable=False, default="audit")
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False, default="system")
    subject_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    subject_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    correlation_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    request_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(nullable=False, default=lambda: datetime.now(UTC))
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
