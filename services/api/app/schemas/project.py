"""Project contracts."""

from datetime import date, datetime
from typing import ClassVar
from uuid import UUID

from app.models.enums import ProjectStatus
from app.schemas.common import (
    CodeText,
    IsoDate,
    LocationText,
    NameText,
    Page,
    PatchModel,
    RequestModel,
    ResponseModel,
)


class ProjectCreate(RequestModel):
    code: CodeText
    name: NameText
    location: LocationText | None = None
    status: ProjectStatus = ProjectStatus.PLANNING
    target_completion_date: IsoDate | None = None


class ProjectUpdate(PatchModel):
    """The project code is the natural key and cannot be changed."""

    not_nullable: ClassVar[frozenset[str]] = frozenset({"name", "status"})

    name: NameText | None = None
    location: LocationText | None = None
    status: ProjectStatus | None = None
    target_completion_date: IsoDate | None = None


class ProjectRead(ResponseModel):
    id: UUID
    workspace_id: UUID
    code: str
    name: str
    location: str | None
    status: ProjectStatus
    target_completion_date: date | None
    created_at: datetime
    updated_at: datetime


class ProjectListResponse(Page[ProjectRead]):
    """Projects ordered by code."""
