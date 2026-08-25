"""Policy engine — RBAC with ABAC architecture readiness.

Currently implements role-based access control with a permission →
role → user hierarchy. The engine is structured so attribute-based
access can be plugged in later without changing API signatures.

Example ABAC policy (future):

    Planner
    AND
    Region == "Europe"
    AND
    Supplier Owner == User
    ↓
    Can modify

Today only the RBAC path is active::

    Planner
    ↓
    Allow (graph.read, signals.read, scenario.execute, ...)
"""

from __future__ import annotations

from enum import StrEnum

from app.modules.identity.models import UserPrincipal


class Decision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"


def evaluate(
    principal: UserPrincipal,
    permission: str,
    *,
    resource_type: str | None = None,
    attributes: dict[str, str] | None = None,
) -> Decision:
    """Evaluate whether ``principal`` may perform ``permission``.

    Currently implements plain RBAC. When ABAC is needed the
    ``resource_type`` and ``attributes`` parameters provide the hooks.

    Args:
        principal: The resolved ``UserPrincipal``.
        permission: A permission string (e.g. ``"graph.read"``).
        resource_type: Optional resource type for ABAC routing.
        attributes: Optional key-value context for ABAC predicates.

    Returns:
        ``Decision.ALLOW`` if permitted, ``Decision.DENY`` otherwise.
    """
    # Tenant admins bypass all checks
    if "tenant.admin" in principal.permissions:
        return Decision.ALLOW

    if permission in principal.permissions:
        return Decision.ALLOW

    return Decision.DENY


def require(
    principal: UserPrincipal,
    permission: str,
    *,
    resource_type: str | None = None,
    attributes: dict[str, str] | None = None,
) -> None:
    """Same as ``evaluate`` but raises on denial."""
    if (
        evaluate(principal, permission, resource_type=resource_type, attributes=attributes)
        == Decision.DENY
    ):
        raise PermissionError(f"Principal {principal.user_id} lacks permission '{permission}'")
