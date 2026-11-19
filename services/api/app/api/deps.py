"""Request dependencies: settings, database session, workspace context, paging."""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Path, Query, Request
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import WorkspaceNotAvailableError
from app.db.session import Database
from app.models.limits import OFFSET_MAX

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_session(request: Request) -> Iterator[Session]:
    """One session per request. It is closed when the request ends, also on errors."""
    database: Database = request.app.state.database
    with database.session() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


@dataclass(frozen=True, slots=True)
class DevelopmentWorkspaceContext:
    """The workspace a request is allowed to act in.

    Local prototype only. There is no authentication in this release: the
    process serves the one workspace named by ``NEXUS_DEV_WORKSPACE_ID`` and
    nothing else. Before any exposure beyond loopback this dependency must be
    replaced by an authenticated principal with verified workspace membership.
    """

    workspace_id: UUID


def get_workspace_context(
    workspace_id: Annotated[UUID, Path(description="The workspace the request acts in.")],
    settings: SettingsDep,
) -> DevelopmentWorkspaceContext:
    configured = settings.nexus_dev_workspace_id
    # A workspace id in the URL is a name, not a credential. Any id other than
    # the configured one gets the same answer whether or not it exists.
    if configured is None or workspace_id != configured:
        raise WorkspaceNotAvailableError()
    return DevelopmentWorkspaceContext(workspace_id=configured)


WorkspaceDep = Annotated[DevelopmentWorkspaceContext, Depends(get_workspace_context)]


@dataclass(frozen=True, slots=True)
class Pagination:
    limit: int
    offset: int


def get_pagination(
    limit: Annotated[
        int, Query(ge=1, le=MAX_PAGE_SIZE, description="Maximum number of items to return.")
    ] = DEFAULT_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0, le=OFFSET_MAX, description="Number of items to skip.")] = 0,
) -> Pagination:
    return Pagination(limit=limit, offset=offset)


PaginationDep = Annotated[Pagination, Depends(get_pagination)]
