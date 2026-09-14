"""Workspace-scoped capability registry for Nexus agents."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from .contracts import CapabilityDescriptor


@dataclass(frozen=True)
class AuthorizedCapabilitySet:
    """Capabilities available to one task after authorization filtering."""

    workspace_id: UUID
    capabilities: tuple[CapabilityDescriptor, ...]

    def get(self, capability_id: str) -> CapabilityDescriptor | None:
        return next((item for item in self.capabilities if item.capability_id == capability_id), None)


class NexusCapabilityRegistry:
    """Registry interface; persistence and connector discovery are added by MAF-3."""

    async def resolve_for_workspace(
        self,
        workspace_id: UUID,
        requested_capabilities: tuple[str, ...] = (),
    ) -> AuthorizedCapabilitySet:
        """Return only capabilities authorized for the workspace."""
        raise NotImplementedError("Capability persistence/discovery is MAF-3")
