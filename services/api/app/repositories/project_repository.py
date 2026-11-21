"""Project queries. Every function is scoped to one workspace."""

from collections.abc import Collection
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import ProjectStatus
from app.models.project import Project
from app.repositories._pagination import fetch_page


def get_by_id(
    session: Session, workspace_id: UUID, project_id: UUID, *, for_update: bool = False
) -> Project | None:
    """The project; with ``for_update`` its row stays locked until the transaction ends."""
    statement = select(Project).where(
        Project.workspace_id == workspace_id, Project.id == project_id
    )
    if for_update:
        statement = statement.with_for_update()
    return session.scalar(statement)


def get_by_code(session: Session, workspace_id: UUID, code: str) -> Project | None:
    return session.scalar(
        select(Project).where(Project.workspace_id == workspace_id, Project.code == code)
    )


def get_by_codes(
    session: Session, workspace_id: UUID, codes: Collection[str], *, for_update: bool = False
) -> dict[str, Project]:
    """Projects with the given codes, keyed by code; locked in code order when asked."""
    if not codes:
        return {}
    statement = (
        select(Project)
        .where(Project.workspace_id == workspace_id, Project.code.in_(codes))
        .order_by(Project.code)
    )
    if for_update:
        statement = statement.with_for_update()
    return {project.code: project for project in session.scalars(statement)}


def list_for_workspace(
    session: Session,
    workspace_id: UUID,
    *,
    limit: int,
    offset: int,
    status: ProjectStatus | None = None,
) -> tuple[list[Project], int]:
    statement = select(Project).where(Project.workspace_id == workspace_id)
    if status is not None:
        statement = statement.where(Project.status == status)
    return fetch_page(
        session, statement, order_by=(Project.code, Project.id), limit=limit, offset=offset
    )


def add(session: Session, project: Project) -> Project:
    session.add(project)
    session.flush()
    return project
