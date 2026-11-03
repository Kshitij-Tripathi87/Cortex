from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from uuid import UUID, uuid4

import pytest

from app.modules.orchestration.capability_registry import (
    NexusCapabilityRegistry,
    ResolvedCapability,
)
from app.modules.orchestration.contracts import CapabilityDescriptor, TaskContext
from app.modules.orchestration.framework.agent_framework_adapter import AgentFrameworkOrchestrator
from app.modules.orchestration.task_intent import EvidenceRequirement, TaskIntent
from app.modules.orchestration.tool_gateway import AuthorizationDecision, NexusToolGateway


def cap(capability_id: str) -> CapabilityDescriptor:
    return CapabilityDescriptor(
        capability_id=capability_id,
        name=f"Capability {capability_id}",
        version="1.0.0",
        description="Test capability.",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        side_effect="READ",
        budget_units=1.0,
        evidence_required=True,
    )


def task_context(**kwargs) -> TaskContext:
    objective = kwargs.pop("objective", "Analyze inventory exposure.")
    intent = kwargs.pop("intent", TaskIntent(objective=objective))
    values = dict(
        task_id=uuid4(),
        workspace_id=uuid4(),
        tenant_id=uuid4(),
        trace_id=uuid4(),
        actor_id=uuid4(),
        intent=intent,
        objective=objective,
        constraints={},
        world_state_version=42,
        capabilities=(cap("inventory.read"), cap("supply.read")),
        budget=100.0,
    )
    values.update(kwargs)
    return TaskContext(**values)


@dataclass
class Authorizer:
    async def authorize(self, *, capability, context) -> AuthorizationDecision:
        return AuthorizationDecision(True, "allowed", "p-test")


class Validator:
    def validate(self, *, schema, arguments) -> None:
        if not isinstance(arguments, dict):
            raise ValueError("arguments must be a dict")


@dataclass
class Executor:
    calls: int = 0

    async def execute(self, *, capability, arguments, context) -> dict[str, object]:
        self.calls += 1
        return {"evidence_refs": (f"e:{capability.capability_id}",)}


@dataclass
class TimedExecutor(Executor):
    events: list[tuple[str, float, float]] = field(default_factory=list)

    async def execute(self, *, capability, arguments, context) -> dict[str, object]:
        start = time.monotonic()
        await asyncio.sleep(0.03)
        end = time.monotonic()
        self.events.append((capability.capability_id, start, end))
        return await super().execute(capability=capability, arguments=arguments, context=context)


@dataclass
class Trace:
    results: list[object] = field(default_factory=list)

    async def record_tool_invocation(self, *, result) -> None:
        self.results.append(result)


@dataclass
class StubSource:
    resolved: tuple[ResolvedCapability, ...]

    async def list_capabilities(self, *, tenant_id: UUID, workspace_id: UUID):
        return self.resolved


DEFAULT_RESOLVED = (
    ResolvedCapability(
        descriptor=cap("inventory.read"), agent_role="INVENTORY", availability="AVAILABLE"
    ),
    ResolvedCapability(
        descriptor=cap("supply.read"), agent_role="PROCUREMENT", availability="DEGRADED"
    ),
)


def make_adapter(**kwargs):
    executor = kwargs.pop("executor", Executor())
    trace = kwargs.pop("trace", Trace())
    registry = kwargs.pop("capability_registry", None)
    gateway = NexusToolGateway(
        authorizer=kwargs.pop("authorizer", Authorizer()),
        executor=executor,
        schema_validator=Validator(),
        trace_writer=trace,
    )
    return (
        AgentFrameworkOrchestrator(gateway=gateway, capability_registry=registry),
        executor,
        trace,
    )


def registry_adapter(**kwargs):
    registry = NexusCapabilityRegistry(sources=(StubSource(DEFAULT_RESOLVED),))
    return make_adapter(capability_registry=registry, **kwargs)


@pytest.mark.asyncio
async def test_adapter_plan_returns_bounded_planner_plan():
    adapter, _, _ = make_adapter()
    context = task_context()
    plan = await adapter.plan(context)
    assert [step.step_id for step in plan.steps] == ["inventory.read", "supply.read"]
    assert plan.task_id == context.task_id


@pytest.mark.asyncio
async def test_adapter_runs_read_only_workflow_to_completion():
    adapter, executor, trace = make_adapter()
    context = task_context(constraints={"dependencies": {}})
    result = await adapter.run_task(context)

    assert result.status == "COMPLETED"
    assert result.evidence_refs == ("e:inventory.read", "e:supply.read")
    assert result.trace_id == context.trace_id
    assert executor.calls == 2
    assert len(trace.results) == 2


@pytest.mark.asyncio
async def test_adapter_returns_blocked_when_plan_infeasible():
    adapter, executor, trace = make_adapter()
    context = task_context(budget=0.5)
    result = await adapter.run_task(context)

    assert result.status == "BLOCKED"
    assert "planning_error" in result.metadata
    assert executor.calls == 0
    assert trace.results == []


@pytest.mark.asyncio
async def test_adapter_returns_blocked_when_required_evidence_missing():
    adapter, executor, _ = make_adapter()
    intent = TaskIntent(
        objective="Analyze inventory exposure.",
        required_evidence=(
            EvidenceRequirement(
                key="inventory.state", description="Authoritative inventory state."
            ),
        ),
    )
    result = await adapter.run_task(task_context(intent=intent))

    assert result.status == "BLOCKED"
    assert "inventory.state" in result.metadata["planning_error"]
    assert executor.calls == 0


@pytest.mark.asyncio
async def test_adapter_discovers_capabilities_when_context_has_none():
    adapter, executor, trace = registry_adapter()
    result = await adapter.run_task(task_context(capabilities=()))

    assert result.status == "COMPLETED"
    assert executor.calls == 2
    assert len(trace.results) == 2


@pytest.mark.asyncio
async def test_adapter_blocks_capabilities_the_workspace_never_authorized():
    adapter, executor, _ = registry_adapter()
    rogue = cap("inventory.adjust")
    context = task_context(capabilities=(cap("inventory.read"), rogue))
    result = await adapter.run_task(context)

    assert result.status == "BLOCKED"
    assert "inventory.adjust" in result.metadata["planning_error"]
    assert executor.calls == 0


@pytest.mark.asyncio
async def test_adapter_runs_independent_specialists_concurrently():
    adapter, executor, _ = registry_adapter(executor=TimedExecutor())
    result = await adapter.run_task(task_context())

    assert result.status == "COMPLETED"
    first, second = executor.events
    assert first[1] < second[2] and second[1] < first[2]


@pytest.mark.asyncio
async def test_adapter_synthesizes_proposals_with_roles_evidence_and_availability():
    adapter, executor, _ = registry_adapter()
    context = task_context()
    result = await adapter.run_task(context)

    assert result.status == "COMPLETED"
    assert len(result.proposals) == 2
    by_role = {proposal.agent_role: proposal for proposal in result.proposals}
    inventory = by_role["INVENTORY"]
    supply = by_role["PROCUREMENT"]
    assert inventory.agent_id == "inventory.read"
    assert inventory.evidence_refs == ("e:inventory.read",)
    assert inventory.confidence == 0.8
    assert supply.confidence == 0.6
    assert all(proposal.actions == ({},) for proposal in result.proposals)
    assert result.evidence_refs == ("e:inventory.read", "e:supply.read")


@pytest.mark.asyncio
async def test_adapter_omits_proposal_for_blocked_specialist():
    @dataclass
    class DenyOne:
        async def authorize(self, *, capability, context) -> AuthorizationDecision:
            allowed = capability.capability_id != "supply.read"
            return AuthorizationDecision(allowed, "ok" if allowed else "denied", "p-test")

    adapter, executor, _ = registry_adapter(authorizer=DenyOne())
    result = await adapter.run_task(task_context())

    assert result.status == "BLOCKED"
    assert len(result.proposals) == 1
    assert result.proposals[0].agent_role == "INVENTORY"
