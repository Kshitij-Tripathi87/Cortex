"""Project: the container of equipment and purchase orders."""

from datetime import date
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models import limits
from app.models._columns import TimestampMixin, UUIDPrimaryKeyMixin, enum_type
from app.models.enums import ProjectStatus


class Project(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("workspace_id", "code", name="uq_projects_workspace_id_code"),
        # Target of the composite foreign keys that tie a child to a project
        # of its own workspace.
        UniqueConstraint("workspace_id", "id", name="uq_projects_workspace_id_id"),
        CheckConstraint("length(btrim(code)) > 0", name="code_not_blank"),
        CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
    )

    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id"))
    code: Mapped[str] = mapped_column(String(limits.CODE_MAX))
    name: Mapped[str] = mapped_column(String(limits.NAME_MAX))
    location: Mapped[str | None] = mapped_column(String(limits.LOCATION_MAX))
    status: Mapped[ProjectStatus] = mapped_column(
        enum_type(ProjectStatus, "status"), default=ProjectStatus.PLANNING
    )
    target_completion_date: Mapped[date | None] = mapped_column(Date)
