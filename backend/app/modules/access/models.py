"""Access module — workspace and user ORM tables (core.* schema).

The MVP wedge is multi-tenant via `core.workspaces`. Every other MVP table
carries `workspace_id` FK back to `core.workspaces.id`. Users belong to
exactly one workspace (ADR-0001 default: one workspace per user).

The existing `app.modules.identity` module remains the canonical home for
in-memory principal dataclasses (UserPrincipal, ServicePrincipal). The
tables here are the DB-backed records that those principals are hydrated
from.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.enums import UserRole
from app.common.ids import uuid7_uuid
from app.infrastructure.database import Base


def _now() -> datetime:
    return datetime.now(UTC)


class Workspace(Base):
    """Tenant root. Per-ADR-0006 every workspace-scoped row FKs to this table."""

    __tablename__ = "workspaces"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_workspaces_slug"),
        {"schema": "core"},
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid7_uuid)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)


class User(Base):
    """User record. One workspace per user in MVP (ADR-0001 Question A default)."""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("workspace_id", "email", name="uq_users_workspace_email"),
        Index("ix_users_workspace_id", "workspace_id"),
        {"schema": "core"},
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid7_uuid)
    workspace_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("core.workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False, comment="bcrypt hash")
    role: Mapped[UserRole] = mapped_column(String(32), nullable=False, default=UserRole.VIEWER)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)


__all__ = ["User", "Workspace"]
