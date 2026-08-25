"""Workspace resolver — resolves workspace context from a ``UserPrincipal``.

The resolver handles the mapping::

    Tenant
      ↓
    Workspace
      ↓
    Project

Every request resolves through this chain. No endpoint ever takes a raw
``workspace_id`` from a query string without verifying it against the
principal's workspace list.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.identity.models import UserPrincipal


@dataclass(frozen=True)
class WorkspaceContext:
    """Resolved tenant + workspace + project for a request."""

    tenant_id: str
    workspace_id: str
    project_id: str | None = None
    source: str = "query"  # "query", "path", "header", "jwt"


def resolve_workspace(
    principal: UserPrincipal,
    workspace_id: str,
    *,
    tenant_id: str | None = None,
) -> WorkspaceContext:
    """Resolve a ``WorkspaceContext`` from a principal and request params.

    Validation rules:

    1.  ``workspace_id`` must be non-empty.
    2.  If the principal lists explicit workspace IDs, ``workspace_id``
        must be in that list (unless the principal holds
        ``workspace.admin``).
    3.  If ``tenant_id`` is provided, it becomes the tenant; otherwise
        it falls back to the principal's ``tenant_id``.

    Raises:
        ValueError: resolution fails (should be surfaced as 403/404).
    """
    if not workspace_id:
        raise PermissionError("Workspace ID required")

    if not principal.can_access_workspace(workspace_id):
        raise PermissionError(
            f"Principal {principal.user_id} cannot access workspace {workspace_id}"
        )

    return WorkspaceContext(
        tenant_id=tenant_id or principal.tenant_id or "default",
        workspace_id=workspace_id,
    )
