from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

import pytest

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
class Trace:
    results: list[object] = field(default_factory=list)

    async def record_tool_invocation(self, *, result) -> None:
        self.results.append(result)


def make_adapter(**kwargs):
    executor = kwargs.pop("executor", Executor())
    trace = kwargs.pop("trace", Trace())
    gateway = NexusToolGateway(
        authorizer=kwargs.pop("authorizer", Authorizer()),
        executor=executor,
        schema_validator=Validator(),
        trace_writer=trace,
    )
    return AgentFrameworkOrchestrator(gateway=gateway), executor, trace


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
