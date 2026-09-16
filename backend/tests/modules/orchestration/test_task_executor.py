from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from uuid import uuid4

import pytest

from app.modules.orchestration.contracts import CapabilityDescriptor, TaskContext
from app.modules.orchestration.executor import NexusTaskExecutor
from app.modules.orchestration.planner import NexusTaskPlanner
from app.modules.orchestration.task_intent import TaskIntent
from app.modules.orchestration.tool_gateway import (
    AuthorizationDecision,
    NexusToolGateway,
)

SLEEP = 0.03


def cap(capability_id: str, *, side_effect: str = "READ") -> CapabilityDescriptor:
    return CapabilityDescriptor(
        capability_id=capability_id,
        name=f"Capability {capability_id}",
        version="1.0.0",
        description="Test capability.",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        side_effect=side_effect,  # type: ignore[arg-type]
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
    denied: tuple[str, ...] = ()

    async def authorize(self, *, capability, context) -> AuthorizationDecision:
        allowed = capability.capability_id not in self.denied
        return AuthorizationDecision(allowed, "ok" if allowed else "denied", "p-test")


class Validator:
    def validate(self, *, schema, arguments) -> None:
        if not isinstance(arguments, dict):
            raise ValueError("arguments must be a dict")


@dataclass
class RecordingExecutor:
    events: list[tuple[str, float, float]] = field(default_factory=list)
    arguments_seen: dict[str, dict[str, object]] = field(default_factory=dict)
    fail_capability: str | None = None
    evidence: bool = True
    payload: dict[str, object] = field(default_factory=dict)

    async def execute(self, *, capability, arguments, context) -> dict[str, object]:
        start = time.monotonic()
        await asyncio.sleep(SLEEP)
        end = time.monotonic()
        self.events.append((capability.capability_id, start, end))
        self.arguments_seen[capability.capability_id] = dict(arguments)
        if capability.capability_id == self.fail_capability:
            raise RuntimeError("capability exploded")
        payload = dict(self.payload)
        if self.evidence:
            payload.setdefault("evidence_refs", (f"e:{capability.capability_id}",))
        return payload


@dataclass
class Trace:
    results: list[object] = field(default_factory=list)

    async def record_tool_invocation(self, *, result) -> None:
        self.results.append(result)


def make_gateway(*, authorizer=None, executor=None, trace=None):
    ex = executor or RecordingExecutor()
    tr = trace or Trace()
    gw = NexusToolGateway(
        authorizer=authorizer or Authorizer(),
        executor=ex,
        schema_validator=Validator(),
        trace_writer=tr,
    )
    return gw, ex, tr


async def plan_for(context: TaskContext):
    return await NexusTaskPlanner().plan(context)


@pytest.mark.asyncio
async def test_default_execution_is_sequential_in_plan_order():
    context = task_context()
    plan = await plan_for(context)
    gw, ex, _ = make_gateway()
    result = await NexusTaskExecutor(gateway=gw).execute(plan=plan, context=context)

    assert result.status == "COMPLETED"
    assert [event[0] for event in ex.events] == ["inventory.read", "supply.read"]
    first, second = ex.events
    assert second[1] >= first[2]
    assert result.evidence_refs == ("e:inventory.read", "e:supply.read")
    assert result.trace_id == context.trace_id
    assert result.recommendation is None
    assert result.metadata["steps"]["inventory.read"]["status"] == "SUCCESS"


@pytest.mark.asyncio
async def test_independent_steps_run_concurrently():
    context = task_context(constraints={"dependencies": {}})
    plan = await plan_for(context)
    gw, ex, _ = make_gateway()
    result = await NexusTaskExecutor(gateway=gw).execute(plan=plan, context=context)

    assert result.status == "COMPLETED"
    first, second = ex.events
    assert first[1] < second[2] and second[1] < first[2]


@pytest.mark.asyncio
async def test_dependent_step_waits_for_prerequisite():
    context = task_context(constraints={"dependencies": {"supply.read": ["inventory.read"]}})
    plan = await plan_for(context)
    gw, ex, _ = make_gateway()
    result = await NexusTaskExecutor(gateway=gw).execute(plan=plan, context=context)

    assert result.status == "COMPLETED"
    by_id = {event[0]: event for event in ex.events}
    assert by_id["supply.read"][1] >= by_id["inventory.read"][2]


@pytest.mark.asyncio
async def test_every_capability_call_is_routed_through_gateway():
    context = task_context()
    plan = await plan_for(context)
    trace = Trace()
    gw, ex, _ = make_gateway(trace=trace)
    await NexusTaskExecutor(gateway=gw).execute(plan=plan, context=context)

    assert len(trace.results) == len(ex.events) == 2
    for result in trace.results:
        assert result.status == "SUCCESS"
        assert result.trace_id == context.trace_id
        assert result.world_state_version == 42


@pytest.mark.asyncio
async def test_gateway_block_halts_dependent_steps():
    context = task_context(constraints={"dependencies": {"supply.read": ["inventory.read"]}})
    plan = await plan_for(context)
    trace = Trace()
    gw, ex, _ = make_gateway(authorizer=Authorizer(denied=("inventory.read",)), trace=trace)
    result = await NexusTaskExecutor(gateway=gw).execute(plan=plan, context=context)

    assert result.status == "BLOCKED"
    assert ex.events == []
    assert result.metadata["steps"]["inventory.read"]["error"] == "POLICY_DENIED"
    assert result.metadata["steps"]["supply.read"]["status"] == "SKIPPED"
    assert len(trace.results) == 1


@pytest.mark.asyncio
async def test_consequential_step_yields_awaiting_approval():
    context = task_context(
        capabilities=(
            cap("inventory.read"),
            cap("inventory.adjust", side_effect="WRITE_CONSEQUENTIAL"),
        )
    )
    plan = await plan_for(context)
    gw, ex, _ = make_gateway()
    result = await NexusTaskExecutor(gateway=gw).execute(plan=plan, context=context)

    assert result.status == "AWAITING_APPROVAL"
    assert result.metadata["steps"]["inventory.adjust"]["error"] == "APPROVAL_REQUIRED"
    assert [event[0] for event in ex.events] == ["inventory.read"]


@pytest.mark.asyncio
async def test_capability_failure_marks_task_failed_and_skips_dependents():
    context = task_context(constraints={"dependencies": {"supply.read": ["inventory.read"]}})
    plan = await plan_for(context)
    gw, ex, _ = make_gateway(executor=RecordingExecutor(fail_capability="inventory.read"))
    result = await NexusTaskExecutor(gateway=gw).execute(plan=plan, context=context)

    assert result.status == "FAILED"
    assert result.metadata["steps"]["inventory.read"]["error"] == "CAPABILITY_EXECUTION_FAILED"
    assert result.metadata["steps"]["supply.read"]["status"] == "SKIPPED"


@pytest.mark.asyncio
async def test_missing_evidence_cannot_complete_task():
    context = task_context()
    plan = await plan_for(context)
    gw, ex, _ = make_gateway(executor=RecordingExecutor(evidence=False, payload={"ok": True}))
    result = await NexusTaskExecutor(gateway=gw).execute(plan=plan, context=context)

    assert result.status == "FAILED"
    assert result.metadata["steps"]["inventory.read"]["error"] == "EVIDENCE_REQUIRED"
    assert result.evidence_refs == ()


@pytest.mark.asyncio
async def test_step_arguments_come_from_frozen_context():
    context = task_context(constraints={"step_arguments": {"inventory.read": {"sku": "S1"}}})
    plan = await plan_for(context)
    gw, ex, _ = make_gateway()
    result = await NexusTaskExecutor(gateway=gw).execute(plan=plan, context=context)

    assert result.status == "COMPLETED"
    assert ex.arguments_seen["inventory.read"] == {"sku": "S1"}
    assert ex.arguments_seen["supply.read"] == {}


@pytest.mark.asyncio
async def test_unknown_step_arguments_are_rejected():
    context = task_context(constraints={"step_arguments": {"nope": {"x": 1}}})
    plan = await plan_for(context)
    gw, _, _ = make_gateway()
    with pytest.raises(ValueError, match="unknown step"):
        await NexusTaskExecutor(gateway=gw).execute(plan=plan, context=context)
