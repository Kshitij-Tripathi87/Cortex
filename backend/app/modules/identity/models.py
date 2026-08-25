"""Identity models — canonical ``UserPrincipal``, roles, permissions, tenants.

These are the *only* identity types that downstream services import. Nothing
in ``app/modules/graph/``, ``app/api/v1/``, or ``app/modules/ml/`` should
ever reference raw JWTs, provider-specific claims, or HTTP header names.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

# ─────────────────────────────────────────────────────────────────────────────
# Roles (closed vocabulary)
# ─────────────────────────────────────────────────────────────────────────────


class Role(StrEnum):
    """Authorised roles within a tenant.

    The ordering is intentional (most privileged first) and is used by
    ``PolicyEngine`` for hierarchy resolution.
    """

    SYSTEM_ADMIN = "system_admin"
    WORKSPACE_ADMIN = "workspace_admin"
    OPERATIONS_MANAGER = "operations_manager"
    PLANNER = "planner"
    ANALYST = "analyst"
    VIEWER = "viewer"
    AUDITOR = "auditor"
    ML_ENGINEER = "ml_engineer"

    @property
    def rank(self) -> int:
        _order = {
            Role.SYSTEM_ADMIN: 0,
            Role.WORKSPACE_ADMIN: 1,
            Role.OPERATIONS_MANAGER: 2,
            Role.PLANNER: 3,
            Role.ANALYST: 4,
            Role.ML_ENGINEER: 5,
            Role.AUDITOR: 6,
            Role.VIEWER: 7,
        }
        return _order[self]


_ROLE_PERMISSION_MAP: dict[Role, set[str]] = {
    Role.SYSTEM_ADMIN: {
        "graph.read",
        "graph.write",
        "signals.read",
        "signals.execute",
        "scenario.execute",
        "recommendation.read",
        "recommendation.approve",
        "decision.create",
        "decision.approve",
        "model.deploy",
        "simulation.execute",
        "simulation.create",
        "agent.deploy",
        "agent.manage",
        "workspace.admin",
        "audit.read",
        "tenant.admin",
    },
    Role.WORKSPACE_ADMIN: {
        "graph.read",
        "graph.write",
        "signals.read",
        "signals.execute",
        "scenario.execute",
        "recommendation.read",
        "recommendation.approve",
        "decision.create",
        "decision.approve",
        "simulation.execute",
        "simulation.create",
        "workspace.admin",
        "audit.readonly",
    },
    Role.OPERATIONS_MANAGER: {
        "graph.read",
        "signals.read",
        "scenario.execute",
        "recommendation.read",
        "decision.create",
        "decision.approve",
        "simulation.execute",
    },
    Role.PLANNER: {
        "graph.read",
        "signals.read",
        "scenario.execute",
        "recommendation.read",
        "decision.create",
        "simulation.execute",
        "simulation.create",
    },
    Role.ANALYST: {
        "graph.read",
        "signals.read",
        "scenario.execute",
        "recommendation.read",
        "simulation.execute",
    },
    Role.ML_ENGINEER: {
        "graph.read",
        "signals.read",
        "recommendation.read",
        "model.deploy",
        "simulation.execute",
    },
    Role.AUDITOR: {
        "audit.readonly",
        "graph.read",
        "signals.read",
        "recommendation.read",
    },
    Role.VIEWER: {
        "graph.read",
        "signals.read",
        "recommendation.read",
    },
}


def permissions_for(roles: list[Role]) -> set[str]:
    """Return the union of permissions granted by a set of roles."""
    perms: set[str] = set()
    for r in roles:
        perms.update(_RULE_PERMISSION_MAP.get(r, set()))
    return perms


# Convenience alias for the lookup table — matches the internal name.
_RULE_PERMISSION_MAP: dict[str, set[str]] = {r.value: set(_ROLE_PERMISSION_MAP[r]) for r in Role}


# ─────────────────────────────────────────────────────────────────────────────
# UserPrincipal — the single canonical identity object
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class UserPrincipal:
    """The canonical identity object consumed by all downstream services.

    Never contains a raw JWT. All claims are verified by the
    ``IdentityProvider`` and flattened into this dataclass.
    """

    user_id: str
    workspace_ids: list[str] = field(default_factory=list)
    tenant_id: str | None = None
    email: str | None = None
    roles: list[str] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)
    issuer: str | None = None
    session_id: str | None = None
    authenticated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    is_anonymous: bool = False
    scopes: list[str] = field(default_factory=list)
    delegated_by: str | None = None

    @property
    def permissions(self) -> set[str]:
        """Derived set of permission strings from the principal's roles."""
        return permissions_for_role_set(self.roles)

    def has_permission(self, permission: str) -> bool:
        """Check whether the principal holds a specific permission."""
        return permission in self.permissions or "tenant.admin" in self.permissions

    def can_access_workspace(self, workspace_id: str) -> bool:
        """True if the principal may access ``workspace_id``.

        An empty ``workspace_id`` list is the *any* policy (dev/anonymous).
        The ``workspace.admin`` permission overrides the list check.
        """
        if "workspace.admin" in self.permissions:
            return True
        if not self.workspace_ids:
            return True
        return workspace_id in self.workspace_ids

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
            "email": self.email,
            "roles": list(self.roles),
            "groups": list(self.groups),
            "issuer": self.issuer,
            "is_anonymous": self.is_anonymous,
        }


def permissions_for_role_set(roles: list[str]) -> set[str]:
    """Return the union of permissions for a list of role *strings*."""
    perms: set[str] = set()
    for name in roles:
        perms.update(_RULE_PERMISSION_MAP.get(name, set()))
    return perms


# ─────────────────────────────────────────────────────────────────────────────
# Service identity
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ServicePrincipal:
    """Short-lived service/agent identity.

    Worker agents use ``ServicePrincipal`` rather than ``UserPrincipal``.
    Tokens are scoped to the operations an agent is allowed to perform
    and never inherit the delegating user's full permissions.
    """

    service_id: str
    workspace_id: str
    tenant_id: str
    scopes: list[str] = field(default_factory=list)
    delegated_by: str | None = None
    expires_at: datetime | None = None
    token_id: str | None = None

    def can_execute(self, scope: str) -> bool:
        """Check if this service principal is authorised for ``scope``."""
        return scope in self.scopes or "*" in self.scopes


# ─────────────────────────────────────────────────────────────────────────────
# Tenant / Workspace context
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RequestContext:
    """The fully resolved identity + workspace context for a request.

    This is the only object that API endpoints consume — never raw
    principals or workspace strings.
    """

    principal: UserPrincipal
    tenant_id: str
    workspace_id: str
    permissions: set[str] = field(default_factory=set)
    trace_id: str | None = None
    request_id: str | None = None

    def require(self, permission: str) -> None:
        """Raise ``PermissionError`` if the context lacks ``permission``."""
        if not self.principal.can_access_workspace(self.workspace_id):
            raise PermissionError(
                f"Principal {self.principal.user_id} cannot access workspace {self.workspace_id}"
            )
        if permission not in self.permissions:
            raise PermissionError(
                f"Principal {self.principal.user_id} lacks permission '{permission}'"
            )
