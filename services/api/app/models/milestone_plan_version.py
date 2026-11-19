"""Planned-date history of a milestone. Append-only: rows are never updated."""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.db.base import Base
from app.models import limits
from app.models._columns import UUIDPrimaryKeyMixin


class MilestonePlanVersion(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "milestone_plan_versions"
    __table_args__ = (
        # Two writers can never allocate the same version number.
        UniqueConstraint(
            "milestone_id", "version_no", name="uq_milestone_plan_versions_milestone_id_version_no"
        ),
        CheckConstraint("version_no > 0", name="version_no_positive"),
    )

    milestone_id: Mapped[UUID] = mapped_column(ForeignKey("milestones.id"))
    version_no: Mapped[int] = mapped_column(Integer)
    planned_date: Mapped[date] = mapped_column(Date)
    source_ingestion_row_id: Mapped[UUID | None] = mapped_column(ForeignKey("ingestion_rows.id"))
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    recorded_by: Mapped[str] = mapped_column(String(limits.ACTOR_MAX))
