"""Workspace queries."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.workspace import Workspace


def get_by_id(session: Session, workspace_id: UUID) -> Workspace | None:
    return session.scalar(select(Workspace).where(Workspace.id == workspace_id))


def get_by_slug(session: Session, slug: str) -> Workspace | None:
    return session.scalar(select(Workspace).where(Workspace.slug == slug))


def add(session: Session, workspace: Workspace) -> Workspace:
    session.add(workspace)
    session.flush()
    return workspace
