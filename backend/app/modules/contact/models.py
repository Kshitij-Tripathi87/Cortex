"""Requests sent through the public site.

The site has no mailbox behind it. A visitor's demo request or contact
message is saved here, and the team reads it with
``scripts/contact_requests.py``.

This is not customer data: the sender has no account, so the table carries no
``workspace_id`` and is never read through the API. The only write path is
``POST /api/v1/public/contact-requests``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.common.ids import uuid7
from app.infrastructure.database import Base

# What a request can be about. "demo" comes from the demo request form; the
# rest are the topics offered on the contact form.
TOPICS: tuple[str, ...] = (
    "demo",
    "general",
    "sales",
    "engineering",
    "security",
    "privacy",
    "legal",
)

STATUS_NEW = "new"
STATUS_HANDLED = "handled"


def _now() -> datetime:
    return datetime.now(UTC)


class ContactRequest(Base):
    """One saved request from the public site."""

    __tablename__ = "contact_requests"
    __table_args__ = (
        UniqueConstraint("reference", name="uq_contact_requests_reference"),
        Index("ix_contact_requests_status_created_at", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uuid7)
    # Shown to the sender and quoted in follow-ups, e.g. "REQ-7K3F9Q2M".
    reference: Mapped[str] = mapped_column(String(16), nullable=False)
    topic: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    company: Mapped[str | None] = mapped_column(String(200), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    # The extra answers of the demo request form (role, country, systems ...).
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # The sender agreed that the request is stored and answered.
    consent: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=STATUS_NEW)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    handled_note: Mapped[str | None] = mapped_column(String(500), nullable=True)


__all__ = ["STATUS_HANDLED", "STATUS_NEW", "TOPICS", "ContactRequest"]
