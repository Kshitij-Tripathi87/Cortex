"""Milestone: identity and actual state of one step of a purchase order.

The planned date is not a column here. Every plan, the first one included, is
a row of MilestonePlanVersion, so a re-plan never overwrites what was planned
before.
"""

from datetime import date
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, ForeignKeyConstraint, Index, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models._columns import TimestampMixin, UUIDPrimaryKeyMixin, enum_type
from app.models.enums import MilestoneStatus, MilestoneType

if TYPE_CHECKING:
    from app.models.milestone_plan_version import MilestonePlanVersion


class Milestone(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "milestones"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "purchase_order_id"],
            ["purchase_orders.workspace_id", "purchase_orders.id"],
            name="fk_milestones_workspace_purchase_order",
        ),
        UniqueConstraint(
            "purchase_order_id",
            "milestone_type",
            "sequence_no",
            name="uq_milestones_purchase_order_id_type_sequence_no",
        ),
        CheckConstraint("sequence_no > 0", name="sequence_no_positive"),
        # An actual date is the record of a completion.
        CheckConstraint(
            "actual_date IS NULL OR status = 'COMPLETED'", name="actual_date_requires_completed"
        ),
        Index("ix_milestones_workspace_id_purchase_order_id", "workspace_id", "purchase_order_id"),
    )

    workspace_id: Mapped[UUID] = mapped_column()
    purchase_order_id: Mapped[UUID] = mapped_column()
    milestone_type: Mapped[MilestoneType] = mapped_column(
        enum_type(MilestoneType, "milestone_type")
    )
    sequence_no: Mapped[int] = mapped_column(Integer, default=1)
    actual_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[MilestoneStatus] = mapped_column(
        enum_type(MilestoneStatus, "status"), default=MilestoneStatus.PENDING
    )

    plan_versions: Mapped[list["MilestonePlanVersion"]] = relationship(
        primaryjoin="Milestone.id == MilestonePlanVersion.milestone_id",
        foreign_keys="MilestonePlanVersion.milestone_id",
        viewonly=True,
        lazy="raise",
        order_by="MilestonePlanVersion.version_no",
    )
