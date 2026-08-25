"""Integration Events — outbox pattern for external system boundaries.

Integration events cross external system boundaries (ERP, WMS, TMS, partners).
They use the transactional outbox pattern for exactly-once-effect semantics.

Outbox table stores events atomically with the state change that caused them.
A background dispatcher reads the outbox and delivers to external systems.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.common.ids import uuid7
from app.infrastructure.database import Base


@dataclass(frozen=True)
class IntegrationEvent:
    """Integration event — crosses external system boundary."""

    event_id: str = field(default_factory=uuid7)
    event_type: str = ""
    workspace_id: str = ""
    partner_id: str | None = None
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    payload: dict[str, Any] = field(default_factory=dict)
    correlation_id: str | None = None


class IntegrationOutbox(Base):
    """Transactional outbox for integration events.

    Written in the same DB transaction as the state change.
    Dispatched by background worker after commit.
    """

    __tablename__ = "integration_outbox"

    outbox_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    partner_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending"
    )  # pending|dispatched|failed
    attempts: Mapped[int] = mapped_column(default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=lambda: datetime.now(UTC))
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# Frozen integration event types (per docs/16-event-taxonomy.md §3.4)


class IntegrationEventTypes:
    UPLOAD_RECEIVED = "integration.upload.received"
    UPLOAD_REJECTED = "integration.upload.rejected"
    OUTBOUND_DISPATCHED = "integration.outbound.dispatched"
    DELIVERY_CONFIRMED = "integration.delivery.confirmed"
    PARTNER_ERROR = "integration.partner.error"
