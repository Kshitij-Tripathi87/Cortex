"""Workspace scope — request-scoped context for multi-tenant isolation.

The MVP wedge is multi-tenant via a `workspace_id` column on every entity
table. Every query against workspace-scoped data must filter by the
context's workspace_id. This module exposes that context as a
`ContextVar` so the workspace-scoped repository (see
`app.modules.supply_chain.repositories.WorkspaceScopedRepository`) can read
the current workspace without threading it through every call signature.

Lifecycle:
- Unauthenticated entry: `current_workspace_id()` returns `None`.
- Auth dependency sets it via `set_workspace_scope(...)` at request entry
  and resets it at request exit via the returned `Token`.
- Background workers set it explicitly per task.
- Tests can wrap their code in `with_workspace_scope(...)` for ergonomics.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from uuid import UUID

_current_workspace_id: ContextVar[UUID | None] = ContextVar(
    "current_workspace_id",
    default=None,
)


def current_workspace_id() -> UUID | None:
    """Return the workspace_id bound to the current request/task, or None."""
    return _current_workspace_id.get()


def set_workspace_scope(workspace_id: UUID) -> Token[UUID | None]:
    """Bind a workspace_id to the current context; returns a reset Token."""
    return _current_workspace_id.set(workspace_id)


def reset_workspace_scope(token: Token[UUID | None]) -> None:
    """Reset the workspace context using the Token returned by set_workspace_scope."""
    _current_workspace_id.reset(token)


def require_workspace_id() -> UUID:
    """Return the current workspace_id or raise RuntimeError if unset.

    Use this in service/repository code paths where a missing workspace is a
    programming error, not a user error.
    """
    wid = _current_workspace_id.get()
    if wid is None:
        raise RuntimeError(
            "No workspace_id in context. Set it via set_workspace_scope(...) "
            "at request entry (typically in the auth dependency)."
        )
    return wid


@contextmanager
def with_workspace_scope(workspace_id: UUID) -> Iterator[None]:
    """Context manager that binds a workspace_id for the duration of the block.

    Convenience wrapper around set_workspace_scope/reset_workspace_scope.
    """
    token = set_workspace_scope(workspace_id)
    try:
        yield
    finally:
        reset_workspace_scope(token)
