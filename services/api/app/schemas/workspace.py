"""Workspace read contract."""

from datetime import datetime
from uuid import UUID

from app.models.enums import WorkspaceStatus
from app.schemas.common import ResponseModel


class WorkspaceRead(ResponseModel):
    id: UUID
    name: str
    slug: str
    status: WorkspaceStatus
    created_at: datetime
    updated_at: datetime
