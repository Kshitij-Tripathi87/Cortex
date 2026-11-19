"""World State routes. The projection is assembled by the service; nothing is queried here."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, PaginationDep, SessionDep, WorkspaceDep
from app.models.limits import OFFSET_MAX
from app.schemas.world_state import ProjectWorldState, WorkspaceWorldState, WorldStateSummary
from app.services import world_state_service

router = APIRouter(prefix="/workspaces/{workspace_id}/world-state", tags=["world state"])

PageLimit = Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)]
PageOffset = Annotated[int, Query(ge=0, le=OFFSET_MAX)]


@router.get(
    "",
    response_model=WorkspaceWorldState,
    summary="Workspace World State",
    description=(
        "Counts, data quality and one page of projects, read from PostgreSQL on every call."
    ),
)
def get_workspace_world_state(
    workspace: WorkspaceDep, session: SessionDep, page: PaginationDep
) -> WorkspaceWorldState:
    return world_state_service.get_workspace_world_state(
        session, workspace.workspace_id, limit=page.limit, offset=page.offset
    )


@router.get(
    "/summary",
    response_model=WorldStateSummary,
    summary="Workspace counts and data-quality summary",
)
def get_workspace_world_state_summary(
    workspace: WorkspaceDep, session: SessionDep
) -> WorldStateSummary:
    return world_state_service.get_workspace_world_state_summary(session, workspace.workspace_id)


@router.get(
    "/projects/{project_id}",
    response_model=ProjectWorldState,
    summary="Project World State",
    description=(
        "A project with its equipment, purchase orders, line items, milestones and supplier "
        "commitments. Facts only: no score, no comparison of dates, no recommendation."
    ),
)
def get_project_world_state(
    workspace: WorkspaceDep,
    session: SessionDep,
    project_id: UUID,
    equipment_limit: PageLimit = DEFAULT_PAGE_SIZE,
    equipment_offset: PageOffset = 0,
    po_limit: PageLimit = DEFAULT_PAGE_SIZE,
    po_offset: PageOffset = 0,
    include_history: Annotated[
        bool, Query(description="Include plan and commitment version lists.")
    ] = False,
) -> ProjectWorldState:
    return world_state_service.get_project_world_state(
        session,
        workspace.workspace_id,
        project_id,
        equipment_limit=equipment_limit,
        equipment_offset=equipment_offset,
        po_limit=po_limit,
        po_offset=po_offset,
        include_history=include_history,
    )
