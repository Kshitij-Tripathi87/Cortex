"""Project rules and transactions.

Public functions own one transaction each. ``apply_source_record`` is the
import path: it writes inside the transaction of the ingestion commit and
never commits itself.
"""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.db.session import transaction
from app.models.enums import (
    CanonicalEntityType,
    IngestionEntityType,
    ProjectStatus,
    RowOutcome,
)
from app.models.field_policy import SOURCE_OWNED_FIELDS, changed_fields
from app.models.project import Project
from app.repositories import project_repository
from app.schemas.project import ProjectCreate, ProjectUpdate
from app.services import workspace_service
from app.services._support import apply_changes, duplicate_key_error, unique_key_guard
from app.services.results import Applied, Page

_SOURCE_OWNED = SOURCE_OWNED_FIELDS[IngestionEntityType.PROJECT]


def _not_found() -> NotFoundError:
    return NotFoundError("The project was not found.")


def create_project(session: Session, workspace_id: UUID, payload: ProjectCreate) -> Project:
    with transaction(session):
        workspace_service.require_active_workspace(session, workspace_id)
        if project_repository.get_by_code(session, workspace_id, payload.code) is not None:
            raise duplicate_key_error("project", "code")
        project = Project(
            workspace_id=workspace_id,
            code=payload.code,
            name=payload.name,
            location=payload.location,
            status=payload.status,
            target_completion_date=payload.target_completion_date,
        )
        with unique_key_guard(session, "project", "code"):
            project_repository.add(session, project)
        return project


def get_project(session: Session, workspace_id: UUID, project_id: UUID) -> Project:
    workspace_service.require_active_workspace(session, workspace_id)
    project = project_repository.get_by_id(session, workspace_id, project_id)
    if project is None:
        raise _not_found()
    return project


def list_projects(
    session: Session,
    workspace_id: UUID,
    *,
    limit: int,
    offset: int,
    status: ProjectStatus | None = None,
) -> Page[Project]:
    workspace_service.require_active_workspace(session, workspace_id)
    items, total = project_repository.list_for_workspace(
        session, workspace_id, limit=limit, offset=offset, status=status
    )
    return Page(items=items, total=total, limit=limit, offset=offset)


def update_project(
    session: Session, workspace_id: UUID, project_id: UUID, patch: ProjectUpdate
) -> Project:
    with transaction(session):
        workspace_service.require_active_workspace(session, workspace_id)
        project = project_repository.get_by_id(session, workspace_id, project_id)
        if project is None:
            raise _not_found()
        apply_changes(project, patch.changes())
        session.flush()
        return project


def apply_source_record(
    session: Session, workspace_id: UUID, *, existing: Project | None, values: Mapping[str, Any]
) -> Applied:
    """Create the project, or change its source-owned fields. Does not commit."""
    if existing is None:
        project = Project(
            workspace_id=workspace_id,
            code=values["code"],
            name=values["name"],
            location=values.get("location"),
            status=values.get("status", ProjectStatus.PLANNING),
            target_completion_date=values.get("target_completion_date"),
        )
        project_repository.add(session, project)
        return Applied(CanonicalEntityType.PROJECT, project.id, RowOutcome.CREATED)

    current = {name: getattr(existing, name) for name in _SOURCE_OWNED}
    changed = changed_fields(current, values, _SOURCE_OWNED)
    apply_changes(existing, {name: values[name] for name in changed})
    session.flush()
    outcome = RowOutcome.UPDATED if changed else RowOutcome.UNCHANGED
    return Applied(CanonicalEntityType.PROJECT, existing.id, outcome)
