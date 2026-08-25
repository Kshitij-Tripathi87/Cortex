"""Workspace and user repositories.

These differ from `WorkspaceScopedRepository` because workspaces themselves
are not scoped to a workspace — they ARE the scope. Bootstrap helpers also
live here; they're called once per pilot customer to create the workspace
and the first admin user. See `scripts/bootstrap_workspace.py`.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.access.models import User, Workspace


class WorkspaceRepository:
    """CRUD for `core.workspaces`. Used by the bootstrap script and admin views."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, name: str, slug: str, metadata: dict | None = None) -> Workspace:
        ws = Workspace(name=name, slug=slug, metadata_=metadata or {})
        self._session.add(ws)
        await self._session.flush()
        return ws

    async def get(self, workspace_id: UUID) -> Workspace | None:
        stmt = select(Workspace).where(Workspace.id == workspace_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> Workspace | None:
        stmt = select(Workspace).where(Workspace.slug == slug)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()


class UserRepository:
    """CRUD for `core.users`. Not workspace-scoped at the base layer; callers
    must filter by workspace_id where required (admin queries cross-workspace)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        workspace_id: UUID,
        email: str,
        password_hash: str,
        role: str = "viewer",
    ) -> User:
        user = User(
            workspace_id=workspace_id,
            email=email,
            password_hash=password_hash,
            role=role,
        )
        self._session.add(user)
        await self._session.flush()
        return user

    async def get(self, user_id: UUID) -> User | None:
        stmt = select(User).where(User.id == user_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_email(self, workspace_id: UUID, email: str) -> User | None:
        stmt = select(User).where(
            User.workspace_id == workspace_id,
            User.email == email,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()


__all__ = ["UserRepository", "WorkspaceRepository"]
