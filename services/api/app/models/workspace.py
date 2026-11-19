"""Workspace: the data boundary every other record belongs to."""

from sqlalchemy import CheckConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models import limits
from app.models._columns import TimestampMixin, UUIDPrimaryKeyMixin, enum_type
from app.models.enums import WorkspaceStatus


class Workspace(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workspaces"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_workspaces_slug"),
        CheckConstraint("slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name="slug_format"),
        CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
    )

    name: Mapped[str] = mapped_column(String(limits.WORKSPACE_NAME_MAX))
    slug: Mapped[str] = mapped_column(String(limits.SLUG_MAX))
    status: Mapped[WorkspaceStatus] = mapped_column(
        enum_type(WorkspaceStatus, "status"), default=WorkspaceStatus.ACTIVE
    )
