"""Identity abstraction layer — vendor-neutral OIDC/JWT identity.

This module provides the building blocks for Cortex's identity architecture:

*   ``UserPrincipal`` — the canonical resolved identity object consumed by
    every downstream service. Never contains raw JWTs — always verified
    claims flattened into a single dataclass.

*   ``IdentityProvider`` — protocol that adapters implement. Each provider
    (Entra ID, Keycloak, Auth0, Okta, local JWT, header-based dev) is a
    single adapter class.

*   ``IdentityMiddleware`` — ASGI middleware that plugs into ``main.py``
    before route handling. Verifies tokens (where applicable), resolves
    identities, and attaches ``UserPrincipal`` to ``request.state``.

*   ``WorkspaceResolver`` — resolves a ``UserPrincipal`` and route
    parameters (query ``workspace_id``, path param, header) into the
    tenant/workspace context the request operates on.

*   ``PolicyEngine`` — RBAC engine with ABAC architecture readiness.
    Enforces ``permission → role → user`` predicates.

*   ``FastAPI dependencies`` — ``get_current_user``, ``require_workspace``,
    ``require_permission``. These are the API-facing entry points.

Usage::

    # middleware registration (in app/main.py)
    from app.modules.identity.middleware import IdentityMiddleware
    app.add_middleware(IdentityMiddleware)

    # endpoint dependency
    async def my_handler(
        db: AsyncSession = Depends(get_db),
        principal: UserPrincipal = Depends(get_current_user),
    ) -> ...:
        require_permission(principal, "graph.read")
        ...

All service-to-service and agent tokens go through this same layer, with
short-lived scoped tokens that never inherit user admin privileges.
"""
