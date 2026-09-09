"""Nexus v1.0 P0 — Authorization (AuthZ) system.

Chain: User → Tenant → Organization → Workspace → Role → Tool permission → Data permission.

Roles:
    viewer    — query/inspect only; no approve, no execute
    analyst   — analyze/simulate/compare; no execute
    operator  — approve/execute (full operational authority)
    admin     — manage users, roles, configuration (not used by LLM)

CRITICAL INVARIANT: The LLM (Vanessa) NEVER manufactures authority. Every
tool call is resolved against the authenticated principal's permissions
before any side-effect is allowed. If the LLM claims permission that
the principal does not have, the tool raises PermissionDenied and the
response reflects that denial — the LLM is never told "go ahead."
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

# ─────────────────────────────────────────────────────────────────────
# Roles and permissions
# ─────────────────────────────────────────────────────────────────────


class NexusRole(StrEnum):
    VIEWER = "viewer"
    ANALYST = "analyst"
    OPERATOR = "operator"
    ADMIN = "admin"


# Tool-level permissions
TOOL_PERMISSIONS: dict[str, set[NexusRole]] = {
    # Read
    "nexus.state.read": {NexusRole.VIEWER, NexusRole.ANALYST, NexusRole.OPERATOR, NexusRole.ADMIN},
    "nexus.ontology.read": {
        NexusRole.VIEWER,
        NexusRole.ANALYST,
        NexusRole.OPERATOR,
        NexusRole.ADMIN,
    },
    "nexus.decision.list": {
        NexusRole.VIEWER,
        NexusRole.ANALYST,
        NexusRole.OPERATOR,
        NexusRole.ADMIN,
    },
    "nexus.decision.get": {
        NexusRole.VIEWER,
        NexusRole.ANALYST,
        NexusRole.OPERATOR,
        NexusRole.ADMIN,
    },
    "nexus.forecast.read": {
        NexusRole.VIEWER,
        NexusRole.ANALYST,
        NexusRole.OPERATOR,
        NexusRole.ADMIN,
    },
    "nexus.cockpit.read": {
        NexusRole.VIEWER,
        NexusRole.ANALYST,
        NexusRole.OPERATOR,
        NexusRole.ADMIN,
    },
    "nexus.explain": {NexusRole.VIEWER, NexusRole.ANALYST, NexusRole.OPERATOR, NexusRole.ADMIN},
    "nexus.trace.get": {NexusRole.VIEWER, NexusRole.ANALYST, NexusRole.OPERATOR, NexusRole.ADMIN},
    # Analyze / simulate (no operational side effects)
    "nexus.demand.run": {NexusRole.ANALYST, NexusRole.OPERATOR, NexusRole.ADMIN},
    "nexus.gnn.analyze": {NexusRole.ANALYST, NexusRole.OPERATOR, NexusRole.ADMIN},
    "nexus.rl.simulate": {NexusRole.ANALYST, NexusRole.OPERATOR, NexusRole.ADMIN},
    "nexus.simulate.compare": {NexusRole.ANALYST, NexusRole.OPERATOR, NexusRole.ADMIN},
    "nexus.whatif.run": {NexusRole.ANALYST, NexusRole.OPERATOR, NexusRole.ADMIN},
    "nexus.recommend": {NexusRole.ANALYST, NexusRole.OPERATOR, NexusRole.ADMIN},
    # Operational decisions
    "nexus.decision.create": {NexusRole.OPERATOR, NexusRole.ADMIN},
    "nexus.decision.approve": {NexusRole.OPERATOR, NexusRole.ADMIN},
    "nexus.decision.execute": {NexusRole.OPERATOR, NexusRole.ADMIN},
    "nexus.outcome.record": {NexusRole.OPERATOR, NexusRole.ADMIN},
    "nexus.observation.record": {NexusRole.OPERATOR, NexusRole.ADMIN},
    "nexus.policy.approve": {NexusRole.OPERATOR, NexusRole.ADMIN},
    # Truth loop / audit
    "nexus.truth.read": {NexusRole.VIEWER, NexusRole.ANALYST, NexusRole.OPERATOR, NexusRole.ADMIN},
    "nexus.audit.read": {NexusRole.VIEWER, NexusRole.ANALYST, NexusRole.OPERATOR, NexusRole.ADMIN},
    # Model Governance & Inference (v0.8.4)
    "nexus.model.read": {NexusRole.VIEWER, NexusRole.ANALYST, NexusRole.OPERATOR, NexusRole.ADMIN},
    "nexus.model.register": {NexusRole.ANALYST, NexusRole.OPERATOR, NexusRole.ADMIN},
    "nexus.model.evaluate": {NexusRole.ANALYST, NexusRole.OPERATOR, NexusRole.ADMIN},
    "nexus.model.promote": {NexusRole.OPERATOR, NexusRole.ADMIN},
    "nexus.model.rollback": {NexusRole.OPERATOR, NexusRole.ADMIN},
    "nexus.forecast.create": {NexusRole.ANALYST, NexusRole.OPERATOR, NexusRole.ADMIN},
    "nexus.inference.run": {NexusRole.ANALYST, NexusRole.OPERATOR, NexusRole.ADMIN},
    # v0.8.5-B3 — golden-path registries (risks / signals / scenarios /
    # evidence / approvals). Reads are viewer-open like the other registry
    # reads; recording is analyst work; risk triage is operational.
    "nexus.risk.read": {NexusRole.VIEWER, NexusRole.ANALYST, NexusRole.OPERATOR, NexusRole.ADMIN},
    "nexus.risk.record": {NexusRole.ANALYST, NexusRole.OPERATOR, NexusRole.ADMIN},
    "nexus.risk.triage": {NexusRole.OPERATOR, NexusRole.ADMIN},
    "nexus.signal.read": {
        NexusRole.VIEWER,
        NexusRole.ANALYST,
        NexusRole.OPERATOR,
        NexusRole.ADMIN,
    },
    "nexus.scenario.read": {
        NexusRole.VIEWER,
        NexusRole.ANALYST,
        NexusRole.OPERATOR,
        NexusRole.ADMIN,
    },
    "nexus.scenario.create": {NexusRole.ANALYST, NexusRole.OPERATOR, NexusRole.ADMIN},
    "nexus.scenario.simulate": {NexusRole.ANALYST, NexusRole.OPERATOR, NexusRole.ADMIN},
    "nexus.evidence.read": {
        NexusRole.VIEWER,
        NexusRole.ANALYST,
        NexusRole.OPERATOR,
        NexusRole.ADMIN,
    },
    "nexus.evidence.append": {NexusRole.ANALYST, NexusRole.OPERATOR, NexusRole.ADMIN},
    "nexus.approval.read": {
        NexusRole.VIEWER,
        NexusRole.ANALYST,
        NexusRole.OPERATOR,
        NexusRole.ADMIN,
    },
    # Admin
    "nexus.admin.configure": {NexusRole.ADMIN},
    "nexus.admin.roles": {NexusRole.ADMIN},
}


# Data-level scopes (what entities / tenancy a principal can see)
@dataclass
class DataScope:
    tenant_id: str
    organization_id: str | None = None
    workspace_ids: set[str] = field(default_factory=set)
    sku_patterns: set[str] = field(default_factory=set)  # empty = all in workspace
    supplier_ids: set[str] = field(default_factory=set)


@dataclass
class Principal:
    """Authenticated principal (resolved from JWT / session)."""

    user_id: str
    tenant_id: str
    organization_id: str | None
    workspace_id: str | None
    role: NexusRole
    display_name: str = ""

    def scope(self) -> DataScope:
        ws = {self.workspace_id} if self.workspace_id else set()
        return DataScope(
            tenant_id=self.tenant_id,
            organization_id=self.organization_id,
            workspace_ids=ws,
        )


class PermissionDenied(Exception):
    def __init__(self, tool: str, principal: Principal, reason: str = ""):
        self.tool = tool
        self.principal = principal
        self.reason = reason
        super().__init__(
            f"Permission denied: principal '{principal.user_id}' "
            f"(role={principal.role.value}) cannot use tool '{tool}'. {reason}"
        )


class AuthorizationService:
    """Checks tool + data permissions. Stateless. In-memory role registry
    for v0.8; will move to PG-backed roles table for v0.95 enterprise beta.
    """

    def __init__(self) -> None:
        # Override store (for tenant-specific custom roles in future)
        self._overrides: dict[str, dict[str, set[NexusRole]]] = {}
        self._lock = threading.RLock()

    def check(
        self,
        principal: Principal,
        tool: str,
        *,
        workspace_id: str | None = None,
        data_tenant: str | None = None,
    ) -> None:
        """Raise PermissionDenied if principal cannot use `tool` in this scope."""
        # Tenant isolation: data must be in principal's tenant
        if data_tenant and data_tenant != principal.tenant_id:
            raise PermissionDenied(
                tool,
                principal,
                f"Tenant mismatch: principal in {principal.tenant_id}, data in {data_tenant}",
            )

        # Workspace isolation (admin can cross-workspace within tenant)
        if (
            workspace_id
            and principal.workspace_id
            and workspace_id != principal.workspace_id
            and principal.role != NexusRole.ADMIN
        ):
            raise PermissionDenied(tool, principal, "Workspace mismatch")

        # Tool permission
        allowed = TOOL_PERMISSIONS.get(tool, set())
        if principal.role not in allowed:
            raise PermissionDenied(
                tool,
                principal,
                f"Role '{principal.role.value}' not in allowed roles {sorted(r.value for r in allowed)}",
            )

    def can(self, principal: Principal, tool: str, **kwargs: Any) -> bool:
        try:
            self.check(principal, tool, **kwargs)
            return True
        except PermissionDenied:
            return False

    def list_tools_for(self, principal: Principal) -> list[str]:
        return [t for t, roles in TOOL_PERMISSIONS.items() if principal.role in roles]


_singleton: AuthorizationService | None = None


def get_authz() -> AuthorizationService:
    global _singleton
    if _singleton is None:
        _singleton = AuthorizationService()
    return _singleton


# System principal — used ONLY for internal background jobs (e.g., RL
# candidate generation that has no external user). NEVER passed to
# LLM-initiated tool calls.
SYSTEM_PRINCIPAL = Principal(
    user_id="system",
    tenant_id="system",
    organization_id=None,
    workspace_id=None,
    role=NexusRole.ADMIN,
    display_name="Nexus System",
)
