from __future__ import annotations

from uuid import uuid4

import pytest

from app.modules.orchestration.contracts import CapabilityDescriptor, TaskContext
from app.modules.orchestration.planner import NexusTaskPlanner
from app.modules.orchestration.task_intent import EvidenceRequirement, TaskIntent


def cap(capability_id: str, *, budget: float = 1.0) -> CapabilityDescriptor:
    return CapabilityDescriptor(
        capability_id=capability_id,
        name=f"Capability {capability_id}",
        version="1.0.0",
        description="Test capability.",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        side_effect="READ",
        budget_units=budget,
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


@pytest.mark.asyncio
async def test_plan_has_one_step_per_capability_in_declared_order():
    context = task_context()
    plan = await NexusTaskPlanner().plan(context)
    assert [step.step_id for step in plan.steps] == ["inventory.read", "supply.read"]
    assert plan.task_id == context.task_id
    assert plan.objective == context.intent.objective
    for step in plan.steps:
        assert step.required_capabilities == (step.step_id,)
    assert plan.steps[0].dependencies == ()
    assert plan.steps[1].dependencies == (plan.steps[0].step_id,)


@pytest.mark.asyncio
async def test_missing_required_evidence_blocks_planning():
    intent = TaskIntent(
        objective="Analyze inventory exposure.",
        required_evidence=(
            EvidenceRequirement(
                key="inventory.state", description="Authoritative inventory state."
            ),
        ),
    )
    with pytest.raises(ValueError, match="inventory.state"):
        await NexusTaskPlanner().plan(task_context(intent=intent))


@pytest.mark.asyncio
async def test_established_required_evidence_allows_planning():
    intent = TaskIntent(
        objective="Analyze inventory exposure.",
        required_evidence=(
            EvidenceRequirement(
                key="inventory.state", description="Authoritative inventory state."
            ),
        ),
    )
    context = task_context(intent=intent, evidence_refs=("inventory.state",))
    plan = await NexusTaskPlanner().plan(context)
    assert len(plan.steps) == 2


@pytest.mark.asyncio
async def test_missing_capabilities_are_rejected():
    with pytest.raises(ValueError, match="no capabilities"):
        await NexusTaskPlanner().plan(task_context(capabilities=()))


@pytest.mark.asyncio
async def test_duplicate_capabilities_are_rejected():
    with pytest.raises(ValueError, match="Duplicate"):
        await NexusTaskPlanner().plan(task_context(capabilities=(cap("a"), cap("a"))))


@pytest.mark.asyncio
async def test_budget_infeasible_plan_is_rejected():
    with pytest.raises(ValueError, match="exceed the task budget"):
        await NexusTaskPlanner().plan(
            task_context(capabilities=(cap("a", budget=60.0), cap("b", budget=60.0)))
        )


@pytest.mark.asyncio
async def test_dependency_constraints_are_applied():
    context = task_context(constraints={"dependencies": {"supply.read": ["inventory.read"]}})
    plan = await NexusTaskPlanner().plan(context)
    by_id = {step.step_id: step for step in plan.steps}
    assert by_id["supply.read"].dependencies == ("inventory.read",)
    assert by_id["inventory.read"].dependencies == ()


@pytest.mark.asyncio
async def test_unknown_dependency_target_is_rejected():
    with pytest.raises(ValueError, match="Unknown step reference"):
        await NexusTaskPlanner().plan(task_context(constraints={"dependencies": {"nope": []}}))


@pytest.mark.asyncio
async def test_unknown_prerequisite_is_rejected():
    with pytest.raises(ValueError, match="Unknown step reference"):
        await NexusTaskPlanner().plan(
            task_context(constraints={"dependencies": {"supply.read": ["inventory.missing"]}})
        )


@pytest.mark.asyncio
async def test_self_dependency_is_rejected():
    with pytest.raises(ValueError, match="depend on itself"):
        await NexusTaskPlanner().plan(
            task_context(constraints={"dependencies": {"inventory.read": ["inventory.read"]}})
        )


@pytest.mark.asyncio
async def test_concurrent_default_produces_no_dependencies_when_map_absent():
    plan = await NexusTaskPlanner(default_execution="concurrent").plan(task_context())
    assert all(step.dependencies == () for step in plan.steps)


@pytest.mark.asyncio
async def test_unknown_default_execution_mode_is_rejected():
    with pytest.raises(ValueError, match="Unknown default execution mode"):
        NexusTaskPlanner(default_execution="bogus")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_dependency_cycle_is_rejected():
    with pytest.raises(ValueError, match="cycle"):
        await NexusTaskPlanner().plan(
            task_context(
                constraints={
                    "dependencies": {
                        "inventory.read": ["supply.read"],
                        "supply.read": ["inventory.read"],
                    }
                }
            )
        )
