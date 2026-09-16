from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from app.modules.multi_agent.runtime.agent_registry import (
    AgentDefinition,
    AgentHealth,
    AgentRegistry,
    AgentStatus,
    AgentType,
)
from app.modules.multi_agent.runtime.tool_registry import ToolDefinition, ToolRegistry
from app.modules.orchestration.capability_registry import (
    AuthorizedCapabilitySet,
    NexusCapabilityRegistry,
    ResolvedCapability,
    UnsupportedTaskCapabilityError,
)
from app.modules.orchestration.capability_sources import (
    AgentRegistryCapabilitySource,
    ManifestCapabilitySource,
    ToolRegistryCapabilitySource,
)
from app.modules.orchestration.contracts import CapabilityDescriptor
from app.modules.orchestration.task_intent import TaskIntent

TENANT_A = uuid4()
TENANT_B = uuid4()
WORKSPACE_A1 = uuid4()
WORKSPACE_A2 = uuid4()

SYNTHETIC_TOOL_NAMES = {
    "search_capacity",
    "get_carrier_rates",
    "get_lane_schedule",
    "check_cutoff",
    "search_alternate_carrier",
    "reprice_lane",
    "trigger_reroute_simulation",
}


def intent(**kwargs) -> TaskIntent:
    values = {"objective": "Analyze inventory exposure."}
    values.update(kwargs)
    return TaskIntent(**values)


def agent_source_for_tenant(tenant: UUID) -> AgentRegistry:
    registry = AgentRegistry()
    registry.register(
        AgentDefinition(
            agent_type=AgentType.INVENTORY,
            version="1.0.0",
            organization_id=str(tenant),
            workspace_id=None,
            capabilities=frozenset({"inventory.read"}),
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            config={"supported_entities": ["SKU", "LOCATION"]},
        )
    )
    registry.register(
        AgentDefinition(
            agent_type=AgentType.SOURCING,
            version="2.1.0",
            organization_id=str(tenant),
            workspace_id=str(WORKSPACE_A1),
            capabilities=frozenset({"sourcing.read"}),
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            config={},
        )
    )
    for registration in registry.list_agents(org_id=str(tenant)):
        registry.update_status(registration.agent_id, AgentStatus.ACTIVE)
        registry.update_health(registration.agent_id, AgentHealth.HEALTHY)
    return registry


def make_tool(name: str, required_capability: str) -> ToolDefinition:
    async def handler(
        input_data: dict[str, Any], context: Any
    ) -> dict[str, Any]:  # pragma: no cover - never executed by discovery
        return {"ok": True}

    return ToolDefinition(
        tool_id=name,
        name=name,
        description=f"Governed tool {name}.",
        required_capability=required_capability,
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        handler=handler,
    )


@pytest.mark.asyncio
async def test_resolution_unions_sources_deduped_and_sorted():
    first = ResolvedCapability(
        descriptor=CapabilityDescriptor(
            capability_id="zeta.read",
            name="Zeta",
            version="1",
            description="d",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            side_effect="READ",
        ),
        agent_role="ALPHA",
    )
    second = ResolvedCapability(
        descriptor=CapabilityDescriptor(
            capability_id="alpha.read",
            name="Alpha",
            version="1",
            description="d",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            side_effect="READ",
        ),
        agent_role="BETA",
    )
    duplicate = first

    class Source:
        def __init__(self, items: tuple[ResolvedCapability, ...]) -> None:
            self._items = items

        async def list_capabilities(self, *, tenant_id: UUID, workspace_id: UUID):
            return self._items

    registry = NexusCapabilityRegistry(sources=(Source((first,)), Source((second, duplicate))))
    actor = uuid4()
    result = await registry.resolve_for_workspace(
        tenant_id=TENANT_A,
        workspace_id=WORKSPACE_A1,
        actor_id=actor,
        task_intent=intent(),
    )
    assert result.capability_ids == ("alpha.read", "zeta.read")
    assert result.get("alpha.read") is second.descriptor
    assert result.get_resolved("zeta.read") is first
    assert result.descriptors == (second.descriptor, first.descriptor)
    assert result.tenant_id == TENANT_A
    assert result.workspace_id == WORKSPACE_A1
    assert result.actor_id == actor


@pytest.mark.asyncio
async def test_unprovisioned_workspace_receives_no_manifest_capabilities():
    source = ManifestCapabilitySource(
        is_provisioned=lambda t, w: t == TENANT_A and w == WORKSPACE_A1
    )
    registry = NexusCapabilityRegistry(sources=(source,))
    denied = await registry.resolve_for_workspace(
        tenant_id=TENANT_B,
        workspace_id=WORKSPACE_A1,
        actor_id=uuid4(),
        task_intent=intent(),
    )
    granted = await registry.resolve_for_workspace(
        tenant_id=TENANT_A,
        workspace_id=WORKSPACE_A1,
        actor_id=uuid4(),
        task_intent=intent(),
    )
    assert denied.capabilities == ()
    assert len(granted.capabilities) > 0


@pytest.mark.asyncio
async def test_agent_source_enforces_tenant_isolation():
    registry = NexusCapabilityRegistry(
        sources=(AgentRegistryCapabilitySource(registry=agent_source_for_tenant(TENANT_A)),)
    )
    other_tenant = await registry.resolve_for_workspace(
        tenant_id=TENANT_B,
        workspace_id=WORKSPACE_A1,
        actor_id=uuid4(),
        task_intent=intent(),
    )
    assert other_tenant.capability_ids == ()


@pytest.mark.asyncio
async def test_agent_source_enforces_workspace_scoping():
    source = AgentRegistryCapabilitySource(registry=agent_source_for_tenant(TENANT_A))
    workspace_one = await source.list_capabilities(tenant_id=TENANT_A, workspace_id=WORKSPACE_A1)
    workspace_two = await source.list_capabilities(tenant_id=TENANT_A, workspace_id=WORKSPACE_A2)
    one_ids = {item.descriptor.capability_id for item in workspace_one}
    two_ids = {item.descriptor.capability_id for item in workspace_two}
    assert "agent.inventory" in one_ids
    assert "agent.sourcing" in one_ids
    assert "agent.inventory" in two_ids
    assert "agent.sourcing" not in two_ids


@pytest.mark.asyncio
async def test_unhealthy_agent_is_excluded_from_allow_list():
    tenant = uuid4()
    raw_registry = agent_source_for_tenant(tenant)
    for registration in raw_registry.list_agents(org_id=str(tenant)):
        if registration.agent_type is AgentType.SOURCING:
            raw_registry.update_health(registration.agent_id, AgentHealth.UNHEALTHY)
    source = AgentRegistryCapabilitySource(registry=raw_registry)
    result = await source.list_capabilities(tenant_id=tenant, workspace_id=WORKSPACE_A1)
    ids = {item.descriptor.capability_id for item in result}
    assert "agent.inventory" in ids
    assert "agent.sourcing" not in ids


@pytest.mark.asyncio
async def test_degraded_agent_is_marked_degraded_not_excluded():
    tenant = uuid4()
    raw_registry = agent_source_for_tenant(tenant)
    for registration in raw_registry.list_agents(org_id=str(tenant)):
        if registration.agent_type is AgentType.INVENTORY:
            raw_registry.update_health(registration.agent_id, AgentHealth.DEGRADED)
    source = AgentRegistryCapabilitySource(registry=raw_registry)
    result = await source.list_capabilities(tenant_id=tenant, workspace_id=WORKSPACE_A1)
    resolved = {item.descriptor.capability_id: item for item in result}
    assert resolved["agent.inventory"].availability == "DEGRADED"
    assert resolved["agent.inventory"].supported_entities == ("SKU", "LOCATION")
    assert resolved["agent.inventory"].agent_role == "INVENTORY"


@pytest.mark.asyncio
async def test_required_capabilities_present_in_workspace_resolve():
    source = AgentRegistryCapabilitySource(registry=agent_source_for_tenant(TENANT_A))
    registry = NexusCapabilityRegistry(sources=(source,))
    result = await registry.resolve_for_workspace(
        tenant_id=TENANT_A,
        workspace_id=WORKSPACE_A1,
        actor_id=uuid4(),
        task_intent=intent(
            constraints={"required_capabilities": ["agent.inventory", "agent.sourcing"]}
        ),
    )
    assert set(result.capability_ids) >= {"agent.inventory", "agent.sourcing"}


@pytest.mark.asyncio
async def test_unsupported_required_capability_fails_closed():
    source = AgentRegistryCapabilitySource(registry=agent_source_for_tenant(TENANT_A))
    registry = NexusCapabilityRegistry(sources=(source,))
    with pytest.raises(UnsupportedTaskCapabilityError, match="inventory.adjust"):
        await registry.resolve_for_workspace(
            tenant_id=TENANT_A,
            workspace_id=WORKSPACE_A1,
            actor_id=uuid4(),
            task_intent=intent(constraints={"required_capabilities": ["inventory.adjust"]}),
        )


@pytest.mark.asyncio
async def test_malformed_required_capabilities_are_rejected():
    registry = NexusCapabilityRegistry()
    with pytest.raises(ValueError, match="required_capabilities"):
        await registry.resolve_for_workspace(
            tenant_id=TENANT_A,
            workspace_id=WORKSPACE_A1,
            actor_id=uuid4(),
            task_intent=intent(constraints={"required_capabilities": 42}),
        )


@pytest.mark.asyncio
async def test_synthetic_domain_tools_are_never_exposed():
    source = ManifestCapabilitySource(is_provisioned=lambda t, w: t == TENANT_A)
    registry = NexusCapabilityRegistry(sources=(source,))
    result = await registry.resolve_for_workspace(
        tenant_id=TENANT_A,
        workspace_id=WORKSPACE_A1,
        actor_id=uuid4(),
        task_intent=intent(),
    )
    assert SYNTHETIC_TOOL_NAMES.isdisjoint(result.capability_ids)
    for capability in result.capabilities:
        assert capability.descriptor.evidence_required is True


@pytest.mark.asyncio
async def test_tool_source_maps_side_effects_and_honors_actor_capabilities():
    tool_registry = ToolRegistry()
    tool_registry.register(make_tool("read_inventory", "read"))
    tool_registry.register(make_tool("propose_reorder", "propose"))
    tool_registry.register(make_tool("apply_adjustment", "execute"))
    source = ToolRegistryCapabilitySource(
        registry=tool_registry, actor_capabilities=frozenset({"read", "propose"})
    )
    result = await source.list_capabilities(tenant_id=TENANT_A, workspace_id=WORKSPACE_A1)
    by_id = {item.descriptor.capability_id: item.descriptor for item in result}
    assert "apply_adjustment" not in by_id
    assert by_id["read_inventory"].side_effect == "READ"
    assert by_id["propose_reorder"].side_effect == "PROPOSE"
    executing = ToolRegistryCapabilitySource(
        registry=tool_registry, actor_capabilities=frozenset({"execute"})
    )
    elevated = await executing.list_capabilities(tenant_id=TENANT_A, workspace_id=WORKSPACE_A1)
    elevated_by_id = {item.descriptor.capability_id: item.descriptor for item in elevated}
    assert elevated_by_id["apply_adjustment"].side_effect == "WRITE_CONSEQUENTIAL"


@pytest.mark.asyncio
async def test_resolved_descriptors_are_framework_independent():
    sources = (
        ManifestCapabilitySource(is_provisioned=lambda t, w: t == TENANT_A),
        AgentRegistryCapabilitySource(registry=agent_source_for_tenant(TENANT_A)),
        ToolRegistryCapabilitySource(
            registry=_tool_registry(), actor_capabilities=frozenset({"read"})
        ),
    )
    registry = NexusCapabilityRegistry(sources=sources)
    result: AuthorizedCapabilitySet = await registry.resolve_for_workspace(
        tenant_id=TENANT_A,
        workspace_id=WORKSPACE_A1,
        actor_id=uuid4(),
        task_intent=intent(),
    )
    allowed_effects = {
        "READ",
        "ANALYZE",
        "SIMULATE",
        "PROPOSE",
        "WRITE_REVERSIBLE",
        "WRITE_CONSEQUENTIAL",
    }
    for item in result.capabilities:
        assert isinstance(item.descriptor, CapabilityDescriptor)
        assert item.descriptor.side_effect in allowed_effects
        assert item.availability in {"AVAILABLE", "DEGRADED"}
        assert not any(callable(value) for value in vars(item.descriptor).values()), (
            "descriptors must not carry executable handlers"
        )


def _tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(make_tool("read_inventory", "read"))
    return registry
