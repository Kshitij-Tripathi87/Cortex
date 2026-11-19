"""Milestone and plan-history contracts.

Plan versions are history, not editable resources: they can be appended and
read, never changed.
"""

from datetime import date, datetime
from typing import ClassVar, Self
from uuid import UUID

from pydantic import Field, model_validator
from pydantic_core import PydanticCustomError

from app.models.enums import MilestoneStatus, MilestoneType
from app.schemas.common import ActorText, IsoDate, Page, PatchModel, RequestModel, ResponseModel


def _check_actual_date(status: MilestoneStatus | None, actual_date: date | None) -> None:
    if actual_date is not None and status is not None and status != MilestoneStatus.COMPLETED:
        raise PydanticCustomError(
            "INCONSISTENT_MILESTONE_STATE",
            "An actual date can be recorded only on a completed milestone.",
        )


class MilestoneCreate(RequestModel):
    milestone_type: MilestoneType
    sequence_no: int = Field(default=1, gt=0)
    planned_date: IsoDate
    actual_date: IsoDate | None = None
    status: MilestoneStatus | None = Field(
        default=None,
        description="Defaults to COMPLETED when an actual date is given, otherwise PENDING.",
    )
    recorded_by: ActorText | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        _check_actual_date(self.status, self.actual_date)
        return self


class MilestoneUpdate(PatchModel):
    """Record the actual state. The planned date changes only through a new plan version."""

    not_nullable: ClassVar[frozenset[str]] = frozenset({"status"})

    status: MilestoneStatus | None = None
    actual_date: IsoDate | None = None


class PlanVersionCreate(RequestModel):
    planned_date: IsoDate
    recorded_by: ActorText | None = None


class PlanVersionRead(ResponseModel):
    id: UUID
    version_no: int
    planned_date: date
    recorded_at: datetime
    recorded_by: str
    source_ingestion_row_id: UUID | None


class MilestoneRead(ResponseModel):
    id: UUID
    purchase_order_id: UUID
    milestone_type: MilestoneType
    sequence_no: int
    status: MilestoneStatus
    actual_date: date | None
    plan_version_count: int
    current_plan: PlanVersionRead | None = Field(
        description="The plan version with the greatest version number."
    )
    plan_versions: list[PlanVersionRead] = Field(
        description="Plan history, oldest first; at most the latest 50 versions."
    )
    created_at: datetime
    updated_at: datetime


class MilestoneListResponse(Page[MilestoneRead]):
    """Milestones in lifecycle order of their type, then by sequence number."""
