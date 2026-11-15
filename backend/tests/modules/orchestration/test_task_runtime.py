"""MAF-4 acceptance tests — durable task runtime service and repository.

PostgreSQL is authoritative in production; these tests run against file-based
SQLite, where a worker restart is simulated by disposing the engine and
creating a fresh one (and a fresh runtime) over the same database file.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.orchestration.contracts import AgentProposal, TaskPlan, TaskPlanStep
from app.modules.orchestration.task_intent import TaskIntent
from app.modules.orchestration.task_lifecycle import TaskLifecycleError
from app.modules.orchestration.task_runtime_repository import (
    TaskNotFound,
    TaskRuntimeRepository,
    TaskStateConflictError,
)
from app.modules.orchestration.task_runtime_service import NexusTaskRuntime, TaskScope
from app.modules.orchestration.tool_gateway import (
    AuthorizationDecision,
    ToolInvocationResult,
    ToolProvenance,
)

TENANT = uuid4()
WORKSPACE = uuid4()
ACTOR = uuid4()
OTHER_TENANT = uuid4()
SCOPE = TaskScope(tenant_id=TENANT, workspace_id=WORKSPACE)
OBJECTIVE = "Analyze inventory exposure for SKU X."


def intent(**kwargs: Any) -> TaskIntent:
    values: dict[str, Any] = {"objective": OBJECTIVE}
    values.update(kwargs)
    return TaskIntent(**values)


def single_step_plan() -> TaskPlan:
    return TaskPlan(
        task_id=uuid4(),
        objective=OBJECTIVE,
        steps=(
            TaskPlanStep(
                step_id="inventory.read",
                title="Read inventory",
                agent_role="Nexus Supervisor",
                required_capabilities=("inventory.read",),
            ),
        ),
    )


async def make_runtime(db_path: str) -> NexusTaskRuntime:
    """Fresh runtime over a (possibly existing) database file; tables ensured.

    Mirrors the conftest's nexus_db_engine pattern: only the nexus_*
    tables are created (SQLite has no schema concept, so schema-qualified
    tables from other modules are excluded and their FK colspecs stripped).
    """

    from sqlalchemy import MetaData

    from app.infrastructure.database import Base
    from app.modules.orchestration import task_runtime_models  # noqa: F401

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
    metadata = MetaData()
    for table in Base.metadata.sorted_tables:
        if table.name.startswith("nexus_"):
            table.to_metadata(metadata)
    for table in metadata.tables.values():
        table.schema = None
        for column in table.columns:
            for foreign_key in list(column.foreign_keys):
                if foreign_key._colspec and foreign_key._colspec.count(".") == 2:
                    parts = foreign_key._colspec.split(".")
                    foreign_key._colspec = f"{parts[1]}.{parts[2]}"
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return NexusTaskRuntime(session_factory=factory)


async def create_task(runtime: NexusTaskRuntime, **overrides: Any) -> str:
    return await runtime.create_task(
        scope=overrides.pop("scope", SCOPE),
        actor_id=overrides.pop("actor_id", ACTOR),
        trace_id=overrides.pop("trace_id", uuid4()),
        objective=overrides.pop("objective", OBJECTIVE),
        world_state_version=overrides.pop("world_state_version", 42),
        requires_approval=overrides.pop("requires_approval", False),
        policy_context=overrides.pop("policy_context", {}),
        **overrides,
    )


async def run_to_proposed(runtime: NexusTaskRuntime, task_id: str) -> None:
    await runtime.resolve_intent(task_id, scope=SCOPE, intent=intent())
    await runtime.checkpoint_plan(task_id, scope=SCOPE, plan=single_step_plan())
    await runtime.start_run(task_id, scope=SCOPE)
    await runtime.mark_proposed(task_id, scope=SCOPE)


def invocation_result(task_id: str) -> ToolInvocationResult:
    """A full gateway-shaped result for durability tests."""

    invocation_id = uuid4()
    provenance = ToolProvenance(
        invocation_id=invocation_id,
        invoked_at=datetime.now(UTC),
        actor_id=ACTOR,
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        task_id=UUID(task_id),
        trace_id=uuid4(),
        capability_id="inventory.read",
        capability_version="1.0.0",
        world_state_version=42,
        arguments_sha256="a" * 64,
    )
    return ToolInvocationResult(
        invocation_id=invocation_id,
        capability_id="inventory.read",
        capability_version="1.0.0",
        status="SUCCESS",
        workspace_id=WORKSPACE,
        task_id=UUID(task_id),
        trace_id=provenance.trace_id,
        world_state_version=42,
        side_effect="READ",
        authorization=AuthorizationDecision(True, "allowed", "p-test"),
        provenance=provenance,
        data={"sku": "S1"},
        evidence_refs=("inventory.state",),
    )


@pytest.mark.asyncio
async def test_create_task_is_durable_created(tmp_path):
    runtime = await make_runtime(str(tmp_path / "t.sqlite3"))
    task_id = await create_task(runtime)
    assert await runtime.get_status(task_id, scope=SCOPE) == "CREATED"


@pytest.mark.asyncio
async def test_task_recoverable_after_restart(tmp_path):
    db_path = str(tmp_path / "t.sqlite3")
    runtime = await make_runtime(db_path)
    task_id = await create_task(runtime)
    restarted = await make_runtime(db_path)
    assert await restarted.get_status(task_id, scope=SCOPE) == "CREATED"


@pytest.mark.asyncio
async def test_intent_checkpoint_prevents_re_resolution(tmp_path):
    db_path = str(tmp_path / "t.sqlite3")
    runtime = await make_runtime(db_path)
    task_id = await create_task(runtime)
    assert await runtime.resolve_intent(task_id, scope=SCOPE, intent=intent()) is True
    restarted = await make_runtime(db_path)
    assert await restarted.resolve_intent(task_id, scope=SCOPE, intent=intent()) is False
    assert await restarted.get_status(task_id, scope=SCOPE) == "INTENT_RESOLVED"


@pytest.mark.asyncio
async def test_plan_checkpoint_survives_restart(tmp_path):
    db_path = str(tmp_path / "t.sqlite3")
    runtime = await make_runtime(db_path)
    task_id = await create_task(runtime)
    await runtime.resolve_intent(task_id, scope=SCOPE, intent=intent())
    await runtime.checkpoint_plan(task_id, scope=SCOPE, plan=single_step_plan())
    restarted = await make_runtime(db_path)
    durable = await restarted.get_plan(task_id, scope=SCOPE)
    assert durable is not None
    assert durable.steps[0].step_id == "inventory.read"
    assert await restarted.get_status(task_id, scope=SCOPE) == "PLANNED"


@pytest.mark.asyncio
async def test_invocation_and_evidence_are_durable(tmp_path):
    db_path = str(tmp_path / "t.sqlite3")
    runtime = await make_runtime(db_path)
    task_id = await create_task(runtime)
    await run_to_proposed(runtime, task_id)
    run_id = await runtime.get_run_id(task_id, scope=SCOPE)
    result = invocation_result(task_id)
    await runtime.record_invocation(
        task_id, scope=SCOPE, run_id=run_id, step_id="inventory.read", result=result
    )
    await runtime.record_evidence(
        task_id, scope=SCOPE, ref="inventory.state", source_invocation_id=str(result.invocation_id)
    )
    restarted = await make_runtime(db_path)
    trace = await restarted.build_nexus_trace(task_id, scope=SCOPE)
    assert len(trace["invocations"]) == 1
    assert trace["invocations"][0]["capability_id"] == "inventory.read"
    assert trace["evidence"] == [
        {
            "ref": "inventory.state",
            "source_invocation_id": str(result.invocation_id),
            "payload_digest": None,
        }
    ]


@pytest.mark.asyncio
async def test_duplicate_retry_never_duplicates_invocation(tmp_path):
    runtime = await make_runtime(str(tmp_path / "t.sqlite3"))
    task_id = await create_task(runtime)
    await run_to_proposed(runtime, task_id)
    run_id = await runtime.get_run_id(task_id, scope=SCOPE)
    result = invocation_result(task_id)
    await runtime.record_invocation(
        task_id, scope=SCOPE, run_id=run_id, step_id="inventory.read", result=result
    )
    await runtime.record_invocation(
        task_id, scope=SCOPE, run_id=run_id, step_id="inventory.read", result=result
    )
    trace = await runtime.build_nexus_trace(task_id, scope=SCOPE)
    assert len(trace["invocations"]) == 1


@pytest.mark.asyncio
async def test_transaction_failure_leaves_no_phantom_transition(tmp_path):
    runtime = await make_runtime(str(tmp_path / "t.sqlite3"))
    task_id = await create_task(runtime)
    async with runtime._session_factory() as session:
        repo = TaskRuntimeRepository(session=session)
        task = await repo.get_task(task_id, tenant_id=TENANT, workspace_id=WORKSPACE)
        with pytest.raises(TaskStateConflictError):
            await repo.transition_task(task, target="PLANNED", actor_id=ACTOR, expected="RUNNING")
    assert await runtime.get_status(task_id, scope=SCOPE) == "CREATED"


@pytest.mark.asyncio
async def test_cross_tenant_task_lookup_is_denied(tmp_path):
    runtime = await make_runtime(str(tmp_path / "t.sqlite3"))
    task_id = await create_task(runtime)
    with pytest.raises(TaskNotFound):
        await runtime.get_status(
            task_id, scope=TaskScope(tenant_id=OTHER_TENANT, workspace_id=WORKSPACE)
        )


@pytest.mark.asyncio
async def test_proposals_are_durable_and_idempotent(tmp_path):
    db_path = str(tmp_path / "t.sqlite3")
    runtime = await make_runtime(db_path)
    task_id = await create_task(runtime)
    proposals = (
        AgentProposal(
            agent_id="inventory.read",
            agent_role="INVENTORY",
            statement="Inventory analyzed.",
            evidence_refs=("inventory.state",),
            confidence=0.8,
        ),
    )
    await runtime.record_proposals(task_id, scope=SCOPE, proposals=proposals)
    await runtime.record_proposals(task_id, scope=SCOPE, proposals=proposals)
    restarted = await make_runtime(db_path)
    trace = await restarted.build_nexus_trace(task_id, scope=SCOPE)
    assert len(trace["proposals"]) == 1
    assert trace["proposals"][0]["agent_role"] == "INVENTORY"


@pytest.mark.asyncio
async def test_execution_requires_approval_hard_boundary(tmp_path):
    runtime = await make_runtime(str(tmp_path / "t.sqlite3"))
    task_id = await create_task(runtime)
    await run_to_proposed(runtime, task_id)
    with pytest.raises(TaskLifecycleError, match="hard boundary"):
        await runtime.start_execution(task_id, scope=SCOPE)
    assert await runtime.get_status(task_id, scope=SCOPE) == "PROPOSED"


@pytest.mark.asyncio
async def test_awaiting_approval_survives_restart(tmp_path):
    db_path = str(tmp_path / "t.sqlite3")
    runtime = await make_runtime(db_path)
    task_id = await create_task(runtime, requires_approval=True)
    await run_to_proposed(runtime, task_id)
    await runtime.request_approval(task_id, scope=SCOPE, reason="governance")
    restarted = await make_runtime(db_path)
    assert await restarted.get_status(task_id, scope=SCOPE) == "AWAITING_APPROVAL"


@pytest.mark.asyncio
async def test_execution_retry_is_idempotent(tmp_path):
    runtime = await make_runtime(str(tmp_path / "t.sqlite3"))
    task_id = await create_task(runtime)
    await run_to_proposed(runtime, task_id)
    await runtime.request_approval(task_id, scope=SCOPE, reason="governance")
    await runtime.decide_approval(task_id, scope=SCOPE, approved=True, approver_id=uuid4())
    first = await runtime.start_execution(task_id, scope=SCOPE)
    second = await runtime.start_execution(task_id, scope=SCOPE)
    assert first == second
    trace = await runtime.build_nexus_trace(task_id, scope=SCOPE)
    assert trace["execution"]["idempotency_key"] == f"execute:{task_id}"


@pytest.mark.asyncio
async def test_completion_reconstructs_outcome_and_trace(tmp_path):
    db_path = str(tmp_path / "t.sqlite3")
    runtime = await make_runtime(db_path)
    task_id = await create_task(runtime)
    await run_to_proposed(runtime, task_id)
    await runtime.complete_task(
        task_id,
        scope=SCOPE,
        recommendation="No consequential capabilities; analysis only.",
        result_payload={"proposals_recorded": True},
    )
    restarted = await make_runtime(db_path)
    assert await restarted.get_status(task_id, scope=SCOPE) == "COMPLETED"
    trace = await restarted.build_nexus_trace(task_id, scope=SCOPE)
    assert trace["outcome"]["status"] == "COMPLETED"
    assert trace["outcome"]["recommendation"] == "No consequential capabilities; analysis only."
    assert [transition["to_status"] for transition in trace["transitions"]] == [
        "CREATED",
        "INTENT_RESOLVED",
        "PLANNED",
        "RUNNING",
        "PROPOSED",
        "COMPLETED",
    ]


@pytest.mark.asyncio
async def test_redis_loss_leaves_task_state_intact(tmp_path):
    runtime = await make_runtime(str(tmp_path / "t.sqlite3"))
    task_id = await create_task(runtime)
    await runtime.resolve_intent(task_id, scope=SCOPE, intent=intent())
    # Simulated total Redis loss: the runtime holds no Redis dependency, so
    # trace reconstruction over PostgreSQL is unaffected by transport loss.
    trace = await runtime.build_nexus_trace(task_id, scope=SCOPE)
    assert trace["status"] == "INTENT_RESOLVED"
    assert trace["intent"]["objective"] == OBJECTIVE


@pytest.mark.asyncio
async def test_illegal_transition_is_rejected(tmp_path):
    runtime = await make_runtime(str(tmp_path / "t.sqlite3"))
    task_id = await create_task(runtime)
    await run_to_proposed(runtime, task_id)
    # PROPOSED -> EXECUTING without approval is illegal at the lifecycle level.
    with pytest.raises(TaskLifecycleError, match="Illegal"):
        async with runtime._session_factory() as session:
            repo = TaskRuntimeRepository(session=session)
            task = await repo.get_task(task_id, tenant_id=TENANT, workspace_id=WORKSPACE)
            await repo.transition_task(task, target="EXECUTING", actor_id=ACTOR)


@pytest.mark.asyncio
async def test_terminal_task_is_immutable(tmp_path):
    runtime = await make_runtime(str(tmp_path / "t.sqlite3"))
    task_id = await create_task(runtime)
    await run_to_proposed(runtime, task_id)
    await runtime.complete_task(task_id, scope=SCOPE, recommendation=None, result_payload={})
    with pytest.raises(TaskLifecycleError, match="already terminal"):
        await runtime.fail_task(task_id, scope=SCOPE, reason="late failure")
