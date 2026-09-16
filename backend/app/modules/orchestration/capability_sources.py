"""Application-owned capability sources for the Nexus capability registry.

Each source maps an existing, governed Nexus component into framework-
independent capability descriptors, scoped to one tenant and workspace.
Synthetic domain toolkits (multi_agent.tools.domain_toolkits) are
deliberately not a source: their hardcoded rates, carriers, and entities are
test/fixture material and must never be exposed as production capabilities.
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from app.common.capabilities import Capability
from app.modules.multi_agent.runtime.agent_registry import (
    AgentHealth,
    AgentRegistration,
    AgentRegistry,
    AgentStatus,
)
from app.modules.multi_agent.runtime.tool_registry import ToolDefinition, ToolRegistry
from app.modules.multi_agent.tools.manifests import CAPABILITY_MANIFESTS, AgentCapabilityManifest

from .capability_registry import AvailabilityClass, ResolvedCapability
from .contracts import CapabilityDescriptor, SideEffectClass

_SIDE_EFFECT_CLASSES: frozenset[SideEffectClass] = frozenset(
    {"READ", "ANALYZE", "SIMULATE", "PROPOSE", "WRITE_REVERSIBLE", "WRITE_CONSEQUENTIAL"}
)


def _side_effect_from_manifest(manifest: AgentCapabilityManifest) -> SideEffectClass:
    if manifest.can_execute:
        return "WRITE_CONSEQUENTIAL"
    if manifest.propose_scopes:
        return "PROPOSE"
    if manifest.simulate_scopes:
        return "SIMULATE"
    return "READ"


def _descriptor_from_manifest(manifest: AgentCapabilityManifest) -> CapabilityDescriptor:
    authorization = tuple(manifest.read_scopes)
    if manifest.can_block_execution:
        authorization = authorization + ("can_block_execution",)
    return CapabilityDescriptor(
        capability_id=manifest.agent_id,
        name=manifest.agent_name,
        version=manifest.version,
        description=f"{manifest.domain_group} capability from the canonical agent manifest.",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        side_effect=_side_effect_from_manifest(manifest),
        authorization=authorization,
        evidence_required=True,
    )


class ManifestCapabilitySource:
    """Canonical capability catalog derived from agent capability manifests.

    Availability to a workspace is decided by an injected provisioning
    predicate so the catalog itself never encodes tenant grants.
    """

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
        return tuple(
            ResolvedCapability(
                descriptor=_descriptor_from_manifest(manifest),
                agent_role=manifest.domain_group,
            )
            for manifest in CAPABILITY_MANIFESTS.values()
        )


class AgentRegistryCapabilitySource:
    """Bridges the multi-agent runtime AgentRegistry into capability descriptors."""

    def __init__(self, *, registry: AgentRegistry) -> None:
        self._registry = registry

    async def list_capabilities(
        self,
        *,
        tenant_id: UUID,
        workspace_id: UUID,
    ) -> tuple[ResolvedCapability, ...]:
        resolved: list[ResolvedCapability] = []
        seen: set[str] = set()
        for workspace_scope in (str(workspace_id), None):
            registrations = self._registry.list_agents(
                org_id=str(tenant_id),
                workspace_id=workspace_scope,
                status=AgentStatus.ACTIVE,
            )
            for registration in registrations:
                if workspace_scope is None and registration.workspace_id is not None:
                    continue
                if not self._registry.is_available(registration.agent_id):
                    continue
                resolved_item = self._to_resolved(registration)
                capability_id = resolved_item.descriptor.capability_id
                if capability_id in seen:
                    continue
                seen.add(capability_id)
                resolved.append(resolved_item)
        return tuple(resolved)

    @staticmethod
    def _to_resolved(registration: AgentRegistration) -> ResolvedCapability:
        side_effect: SideEffectClass = "READ"
        configured = registration.config.get("side_effect")
        if isinstance(configured, str) and configured in _SIDE_EFFECT_CLASSES:
            side_effect = configured
        supported_entities: tuple[str, ...] = ()
        configured_entities = registration.config.get("supported_entities")
        if isinstance(configured_entities, (list, tuple)) and all(
            isinstance(item, str) for item in configured_entities
        ):
            supported_entities = tuple(configured_entities)
        availability: AvailabilityClass = (
            "DEGRADED" if registration.health == AgentHealth.DEGRADED else "AVAILABLE"
        )
        return ResolvedCapability(
            descriptor=CapabilityDescriptor(
                capability_id=f"agent.{registration.agent_type.value.lower()}",
                name=f"{registration.agent_type.value} agent {registration.version}",
                version=registration.version,
                description=f"Runtime-registered {registration.agent_type.value} agent.",
                input_schema=dict(registration.input_schema),
                output_schema=dict(registration.output_schema),
                side_effect=side_effect,
                authorization=tuple(sorted(registration.capabilities)),
                evidence_required=True,
            ),
            agent_role=registration.agent_type.value,
            availability=availability,
            supported_entities=supported_entities,
        )


def _side_effect_from_tool(tool: ToolDefinition) -> SideEffectClass:
    try:
        capability = Capability(tool.required_capability)
    except ValueError:
        return "READ"
    if capability is Capability.EXECUTE:
        return "WRITE_CONSEQUENTIAL"
    if capability is Capability.PROPOSE:
        return "PROPOSE"
    if capability is Capability.SIMULATE:
        return "SIMULATE"
    if capability is Capability.ANALYZE:
        return "ANALYZE"
    return "READ"


class ToolRegistryCapabilitySource:
    """Bridges the governed multi-agent ToolRegistry into capability descriptors.

    Only the metadata of tools the actor may already access under its base
    capabilities is exposed; the executable handlers remain behind the tool
    registry and the Nexus tool gateway, never inside the descriptor.
    """

    def __init__(self, *, registry: ToolRegistry, actor_capabilities: frozenset[str]) -> None:
        self._registry = registry
        self._actor_capabilities = actor_capabilities

    async def list_capabilities(
        self,
        *,
        tenant_id: UUID,
        workspace_id: UUID,
    ) -> tuple[ResolvedCapability, ...]:
        tools = self._registry.list_available(self._actor_capabilities)
        return tuple(
            ResolvedCapability(
                descriptor=CapabilityDescriptor(
                    capability_id=tool.name,
                    name=tool.name,
                    version="1.0.0",
                    description=tool.description,
                    input_schema=dict(tool.input_schema),
                    output_schema=dict(tool.output_schema),
                    side_effect=_side_effect_from_tool(tool),
                    authorization=(tool.required_capability,),
                    evidence_required=True,
                ),
                agent_role="TOOL",
            )
            for tool in sorted(tools, key=lambda item: item.name)
        )
