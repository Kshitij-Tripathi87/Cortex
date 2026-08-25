"""Identity dependencies — FastAPI dependency injection for identity resolution.

Every endpoint uses these dependencies instead of directly accessing
request headers or the old ``AuthContext`` class.

Usage::

    from app.modules.identity.dependencies import (
        get_current_user,
        require_workspace,
        require_permission,
    )

    @app.get("/graph/features")
    async def get_features(
        workspace_id: str = Query(...),
        principal: UserPrincipal = Depends(get_current_user),
    ) -> ...:
        require_workspace(principal, workspace_id)
        require_permission(principal, "graph.read")
        ...
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from fastapi import Depends, HTTPException, status

from app.config import get_settings
from app.modules.identity.models import UserPrincipal
from app.modules.identity.provider import (
    HeaderIdentityProvider,
    IdentityProvider,
    JWTIDProvider,
    JWTProviderConfig,
)


@lru_cache
def _get_provider() -> IdentityProvider:
    settings = get_settings()
    provider_type = getattr(settings, "identity_provider", "header")

    if provider_type == "jwt":
        return JWTIDProvider(
            config=JWTProviderConfig(
                issuer=settings.jwt_issuer,
                audience=settings.jwt_audience,
                jwks_uri=getattr(settings, "jwt_jwks_uri", None) or None,
            ),
        )

    return HeaderIdentityProvider()


async def get_current_user(request: Any) -> UserPrincipal:
    """FastAPI dependency — resolve the ``UserPrincipal`` from the request.

    Replaces the old ``AuthContext`` dependency in ``security.py``.

    In production, uses JWT verification. In dev, reads from headers.
    """
    provider = _get_provider()
    return await provider.resolve(request)


def require_workspace(
    principal: UserPrincipal,
    workspace_id: str,
) -> None:
    """Enforce that ``principal`` may access ``workspace_id``.

    Raises:
        HTTPException(404): empty workspace id — not found.
        HTTPException(403): authenticated but not authorized.
    """
    if not workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )

    if principal.can_access_workspace(workspace_id):
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "error": "forbidden",
            "message": "You do not have access to this workspace",
            "workspace_id": workspace_id,
            "user_id": principal.user_id,
        },
    )


def require_permission(
    principal: UserPrincipal,
    permission: str,
) -> None:
    """Enforce that ``principal`` holds ``permission``.

    Raises:
        HTTPException(403): authenticated but lacks permission.
    """
    if principal.has_permission(permission):
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "error": "forbidden",
            "message": f"You lack permission '{permission}'",
            "user_id": principal.user_id,
            "required_permission": permission,
        },
    )


def require_azure_role(role: str) -> Any:
    """FastAPI dependency that restricts to a specific role."""

    async def _enforce(principal: UserPrincipal = Depends(get_current_user)) -> UserPrincipal:
        if role not in principal.roles and "tenant.admin" not in principal.permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{role}' required",
            )
        return principal

    return Depends(_enforce)
