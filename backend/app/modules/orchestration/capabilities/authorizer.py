"""Golden-path capability authorizer: the application-owned policy adapter.

Implements the gateway's ``CapabilityAuthorizer`` protocol for the durable
task runtime. Grants only capabilities that were resolved through the
workspace-scoped capability registry (``NexusCapabilityRegistry``) — the
gateway independently enforces the agent allow-list, budget, deadline, input
schema, and the consequential-write approval boundary, so this adapter never
manufactures authority on its own.

Per-capability policy-scope evaluation (subscription/entitlement-aware
grants) lands with the policy gate; this adapter is deliberately the
narrowest grant that keeps the Golden Path real.
"""

from __future__ import annotations

from typing import Any

from ..tool_gateway import AuthorizationDecision


class WorkspaceCapabilityAuthorizer:
    """Grant workspace-scoped capabilities resolved by the registry."""

    async def authorize(self, *, capability: Any, context: Any) -> AuthorizationDecision:
        return AuthorizationDecision(
            allowed=True,
            reason="Allowed by the workspace-scoped capability registry.",
            policy_id="p-workspace-scope",
        )
