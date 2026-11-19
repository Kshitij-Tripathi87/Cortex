"""Workspace lookups shared by every service.

Each service operation starts by requiring the active workspace inside its own
transaction, so "the workspace exists and is active" is checked against the
same database state the operation works on.
"""

from uuid import UUID

from sqlalchemy.orm import Session

from app.core.errors import ConflictError, WorkspaceNotAvailableError
from app.db.session import transaction
from app.models.enums import WorkspaceStatus
from app.models.workspace import Workspace
from app.repositories import workspace_repository


def require_active_workspace(session: Session, workspace_id: UUID) -> Workspace:
    """The workspace, or WORKSPACE_NOT_AVAILABLE when it is missing or disabled.

    Does not open or close a transaction: the calling service owns it.
    """
    workspace = workspace_repository.get_by_id(session, workspace_id)
    if workspace is None or workspace.status != WorkspaceStatus.ACTIVE:
        raise WorkspaceNotAvailableError()
    return workspace


def get_workspace(session: Session, workspace_id: UUID) -> Workspace:
    """The configured workspace whatever its status, so a disabled one can be inspected."""
    workspace = workspace_repository.get_by_id(session, workspace_id)
    if workspace is None:
        raise WorkspaceNotAvailableError()
    return workspace


def ensure_development_workspace(
    session: Session, workspace_id: UUID, *, name: str, slug: str
) -> tuple[Workspace, bool]:
    """Create the development workspace with the configured id, or return the existing one.

    The only way a workspace comes into being in this release; used by the
    demo seed and by tests. Returns the workspace and whether it was created.
    """
    with transaction(session):
        existing = workspace_repository.get_by_id(session, workspace_id)
        if existing is not None:
            return existing, False
        if workspace_repository.get_by_slug(session, slug) is not None:
            raise ConflictError(
                "Another workspace already uses this slug.", code="DUPLICATE_NATURAL_KEY"
            )
        workspace = Workspace(id=workspace_id, name=name, slug=slug, status=WorkspaceStatus.ACTIVE)
        workspace_repository.add(session, workspace)
        return workspace, True
