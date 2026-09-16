"""Workspace-scoped capability registry for Nexus orchestration.

Resolves the dynamic capability allow-list for one task from injected,
tenant/workspace-scoped sources. This is the only discovery path for the
orchestration layer: synthetic domain toolkits are not sources and can never
appear in a resolved set. Persistence and connector-backed discovery are added
by later slices; sources are application-owned adapters.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from .contracts import CapabilityDescriptor
from .task_intent import TaskIntent

AvailabilityClass = Literal["AVAILABLE", "DEGRADED", "UNAVAILABLE"]

_REQUIRED_CAPABILITIES_KEY = "required_capabilities"


class UnsupportedTaskCapabilityError(ValueError):
    """Raised when a task intent requires capabilities the workspace cannot provide."""


@dataclass(frozen=True)
class ResolvedCapability:
    """A capability with the dispatch metadata orchestration needs."""

    descriptor: CapabilityDescriptor
    agent_role: str
    availability: AvailabilityClass = "AVAILABLE"
    supported_entities: tuple[str, ...] = ()


@dataclass(frozen=True)
class AuthorizedCapabilitySet:
    """Capabilities available to one task after tenant/workspace authorization."""

    tenant_id: UUID
    workspace_id: UUID
    actor_id: UUID
    capabilities: tuple[ResolvedCapability, ...] = ()

    @property
    def descriptors(self) -> tuple[CapabilityDescriptor, ...]:
        return tuple(item.descriptor for item in self.capabilities)

    @property
    def capability_ids(self) -> tuple[str, ...]:
        return tuple(item.descriptor.capability_id for item in self.capabilities)

    def get(self, capability_id: str) -> CapabilityDescriptor | None:
        for item in self.capabilities:
            if item.descriptor.capability_id == capability_id:
                return item.descriptor
        return None

    def get_resolved(self, capability_id: str) -> ResolvedCapability | None:
        for item in self.capabilities:
            if item.descriptor.capability_id == capability_id:
                return item
        return None


class CapabilitySource(Protocol):
    """Application-owned, tenant/workspace-scoped capability provider."""

    async def list_capabilities(
        self,
        *,
        tenant_id: UUID,
        workspace_id: UUID,
    ) -> tuple[ResolvedCapability, ...]:
        """Return only capabilities provisioned for the tenant and workspace."""


class NexusCapabilityRegistry:
    """Workspace-scoped discovery boundary for the Nexus orchestration layer."""

    def __init__(self, *, sources: tuple[CapabilitySource, ...] = ()) -> None:
        self._sources = sources

    async def resolve_for_workspace(
        self,
        *,
        tenant_id: UUID,
        workspace_id: UUID,
        actor_id: UUID,
        task_intent: TaskIntent,
    ) -> AuthorizedCapabilitySet:
        """Resolve the authorized capability set for one task intent.

        Fails closed: if the intent declares required capabilities that the
        workspace cannot provide, resolution raises instead of returning a
        partial allow-list.
        """
        resolved: list[ResolvedCapability] = []
        seen: set[str] = set()
        for source in self._sources:
            for item in await source.list_capabilities(
                tenant_id=tenant_id, workspace_id=workspace_id
            ):
                capability_id = item.descriptor.capability_id
                if capability_id in seen:
                    continue
                seen.add(capability_id)
                resolved.append(item)
        resolved.sort(key=lambda item: item.descriptor.capability_id)
        capability_set = AuthorizedCapabilitySet(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            actor_id=actor_id,
            capabilities=tuple(resolved),
        )
        self._enforce_required_capabilities(capability_set, task_intent)
        return capability_set

    @staticmethod
    def _enforce_required_capabilities(
        capability_set: AuthorizedCapabilitySet,
        task_intent: TaskIntent,
    ) -> None:
        raw = task_intent.constraints.get(_REQUIRED_CAPABILITIES_KEY)
        if raw is None:
            return
        if isinstance(raw, str):
            requested: tuple[str, ...] = (raw,)
        elif isinstance(raw, (list, tuple)):
            requested = tuple(raw)
        else:
            raise ValueError(
                "constraints['required_capabilities'] must be a list of capability ids."
            )
        if not all(isinstance(item, str) and item for item in requested):
            raise ValueError(
                "constraints['required_capabilities'] must contain non-empty capability ids."
            )
        authorized = set(capability_set.capability_ids)
        missing = tuple(item for item in requested if item not in authorized)
        if missing:
            raise UnsupportedTaskCapabilityError(
                "Task requires capabilities the workspace cannot provide: " + ", ".join(missing)
            )
