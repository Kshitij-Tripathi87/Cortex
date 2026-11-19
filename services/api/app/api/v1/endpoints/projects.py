"""Project routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import PaginationDep, SessionDep, WorkspaceDep
from app.models.enums import ProjectStatus
from app.schemas.project import ProjectCreate, ProjectListResponse, ProjectRead, ProjectUpdate
from app.services import project_service

router = APIRouter(prefix="/workspaces/{workspace_id}/projects", tags=["projects"])


@router.get("", response_model=ProjectListResponse, summary="List projects")
def list_projects(
    workspace: WorkspaceDep,
    session: SessionDep,
    page: PaginationDep,
    project_status: Annotated[ProjectStatus | None, Query(alias="status")] = None,
) -> ProjectListResponse:
    result = project_service.list_projects(
        session, workspace.workspace_id, limit=page.limit, offset=page.offset, status=project_status
    )
    return ProjectListResponse(
        items=[ProjectRead.model_validate(item) for item in result.items],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )


@router.post(
    "", response_model=ProjectRead, status_code=status.HTTP_201_CREATED, summary="Create a project"
)
def create_project(
    workspace: WorkspaceDep, session: SessionDep, payload: ProjectCreate
) -> ProjectRead:
    project = project_service.create_project(session, workspace.workspace_id, payload)
    return ProjectRead.model_validate(project)


@router.get("/{project_id}", response_model=ProjectRead, summary="Retrieve a project")
def get_project(workspace: WorkspaceDep, session: SessionDep, project_id: UUID) -> ProjectRead:
    project = project_service.get_project(session, workspace.workspace_id, project_id)
    return ProjectRead.model_validate(project)


@router.patch("/{project_id}", response_model=ProjectRead, summary="Update a project")
def update_project(
    workspace: WorkspaceDep, session: SessionDep, project_id: UUID, payload: ProjectUpdate
) -> ProjectRead:
    project = project_service.update_project(session, workspace.workspace_id, project_id, payload)
    return ProjectRead.model_validate(project)
