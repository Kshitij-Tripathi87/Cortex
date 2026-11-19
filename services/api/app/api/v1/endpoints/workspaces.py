"""The configured workspace."""

from fastapi import APIRouter

from app.api.deps import SessionDep, WorkspaceDep
from app.schemas.workspace import WorkspaceRead
from app.services import workspace_service

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["workspaces"])


@router.get("", response_model=WorkspaceRead, summary="Retrieve the configured workspace")
def get_workspace(workspace: WorkspaceDep, session: SessionDep) -> WorkspaceRead:
    record = workspace_service.get_workspace(session, workspace.workspace_id)
    return WorkspaceRead.model_validate(record)
