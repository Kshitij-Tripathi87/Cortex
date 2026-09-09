"""Access module — organization, workspace, user and password-reset ORM tables (core.* schema).

The MVP wedge is multi-tenant via `core.workspaces`. Every other MVP table
carries `workspace_id` FK back to `core.workspaces.id`. Users belong to
exactly one workspace (ADR-0001 default: one workspace per user).

v0.8.5-B (launch onboarding): `core.organizations` is the commercial tenant
root (one workspace per org at launch). Signup creates organization +
workspace + admin user atomically. `core.password_resets` backs the
self-serve reset flow; delivery is dev/test-inline until Day-15 email
(admn-assisted via scripts/admin_users.py in the interim).

The existing `app.modules.identity` module remains the canonical home for
in-memory principal dataclasses (UserPrincipal, ServicePrincipal). The
tables here are the DB-backed records that those principals are hydrated
from.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.enums import UserRole
from app.common.ids import uuid7_uuid
from app.infrastructure.database import Base


def _now() -> datetime:
    return datetime.now(UTC)


class Organization(Base):
    """Commercial tenant root. One workspace per org at launch (v0.8.5 scope freeze).

    `plan` / `trial_ends_at` are the Day-15 billing seam: signup seeds a
    trial; the billing slice promotes these to real subscription state.
    """

    __tablename__ = "organizations"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_organizations_slug"),
        {"schema": "core"},
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid7_uuid)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    plan: Mapped[str] = mapped_column(String(32), nullable=False, default="trial")
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)


class Workspace(Base):
    """Tenant root. Per-ADR-0006 every workspace-scoped row FKs to this table."""

    __tablename__ = "workspaces"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_workspaces_slug"),
        {"schema": "core"},
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid7_uuid)
    organization_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("core.organizations.id", ondelete="CASCADE"),
        nullable=True,
        comment="Tenant org; NULL only for pre-v0.8.5 rows, signup always sets it",
    )
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
    full_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False, comment="bcrypt hash")
    role: Mapped[UserRole] = mapped_column(String(32), nullable=False, default=UserRole.VIEWER)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    password_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)


class PasswordResetToken(Base):
    """Single-use password-reset token. Only the SHA-256 hash is stored."""

    __tablename__ = "password_resets"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_password_resets_token_hash"),
        Index("ix_password_resets_user_id", "user_id"),
        {"schema": "core"},
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid7_uuid)
    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("core.users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )


__all__ = ["Organization", "PasswordResetToken", "User", "Workspace"]
