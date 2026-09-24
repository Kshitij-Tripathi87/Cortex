"""MAF-5 — workspace-scoped discovery source for the World State capabilities.

Bridges the typed capability contracts into the NexusCapabilityRegistry so
the vertical slice is discoverable through the governed discovery path.
Availability to a workspace is decided by an injected provisioning predicate;
the source itself never encodes tenant grants.
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from ..capability_registry import ResolvedCapability

_ROLE_BY_CAPABILITY = {
    "world.inventory.read": "INVENTORY",
    "world.supplier.read": "PROCUREMENT",
    "world.risk.analyze": "RISK",
    "world.inventory.adjust": "INVENTORY",
}


class WorldStateCapabilitySource:
    """Registry source exposing the real World State vertical slice."""

    def __init__(self, *, is_provisioned: Callable[[UUID, UUID], bool]) -> None:
        self._is_provisioned = is_provisioned

    async def list_capabilities(
        self,
        *,
        tenant_id: UUID,
        workspace_id: UUID,
    ) -> tuple[ResolvedCapability, ...]:
        if not self._is_provisioned(tenant_id, workspace_id):
            return ()
        from .descriptors import WORLD_STATE_CAPABILITY_CONTRACTS

        return tuple(
            ResolvedCapability(
                descriptor=contract.descriptor,
                agent_role=_ROLE_BY_CAPABILITY[capability_id],
            )
            for capability_id, contract in sorted(WORLD_STATE_CAPABILITY_CONTRACTS.items())
        )
