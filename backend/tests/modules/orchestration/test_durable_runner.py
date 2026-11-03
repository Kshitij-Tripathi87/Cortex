"""MAF-4 acceptance tests — durable runner end-to-end definition of done.

Flow under test:

    Create task -> persist -> restart -> resume -> execute MAF-3
        -> persist proposals -> restart -> approval -> restart
        -> execute -> persist outcome -> reconstruct NexusTrace

A worker crash is simulated by a fresh DurableTaskRunner (new engine) over the
same database file; a mid-run crash by an injected synthesizer that raises
after gateway invocations were durably persisted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.orchestration.capability_registry import (
    NexusCapabilityRegistry,
    ResolvedCapability,
)
from app.modules.orchestration.contracts import CapabilityDescriptor
from app.modules.orchestration.durable_runner import DurableTaskRunner
from app.modules.orchestration.task_intent import TaskIntent
from app.modules.orchestration.task_runtime_service import NexusTaskRuntime, TaskScope
from app.modules.orchestration.tool_gateway import AuthorizationDecision

TENANT = uuid4()
WORKSPACE = uuid4()
ACTOR = uuid4()
APPROVER = uuid4()
SCOPE = TaskScope(tenant_id=TENANT, workspace_id=WORKSPACE)


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


RESOLVED = (
    ResolvedCapability(descriptor=cap("inventory.read"), agent_role="INVENTORY"),
    ResolvedCapability(descriptor=cap("supply.read"), agent_role="PROCUREMENT"),
)
CONSEQUENTIAL_RESOLVED = (
    ResolvedCapability(descriptor=cap("inventory.read"), agent_role="INVENTORY"),
    ResolvedCapability(
        descriptor=cap("inventory.adjust", side_effect="WRITE_CONSEQUENTIAL"),
        agent_role="INVENTORY",
    ),
)


@dataclass
class RecordingExecutor:
    """The injected 'real capability' adapter; records every execution."""

    calls: dict[str, int] = field(default_factory=dict)

    async def execute(self, *, capability, arguments, context) -> dict[str, object]:
        self.calls[capability.capability_id] = self.calls.get(capability.capability_id, 0) + 1
        return {"evidence_refs": (f"e:{capability.capability_id}",)}


@dataclass
class DenyAllAuthorizer:
    async def authorize(self, *, capability, context) -> AuthorizationDecision:
        return AuthorizationDecision(False, "policy denied", "p-deny")


class AllowAuthorizer:
    async def authorize(self, *, capability, context) -> AuthorizationDecision:
        return AuthorizationDecision(True, "allowed", "p-test")


class DictValidator:
    def validate(self, *, schema, arguments) -> None:
        if not isinstance(arguments, dict):
            raise ValueError("arguments must be a dict")


@dataclass
class StubSource:
    resolved: tuple[ResolvedCapability, ...]

    async def list_capabilities(self, *, tenant_id: UUID, workspace_id: UUID):
        return self.resolved


@dataclass
class ExplodingSynthesizer:
    async def __call__(self) -> None:  # pragma: no cover
        raise AssertionError("never called directly")

    def synthesize(self, **kwargs) -> tuple:  # pragma: no cover - crash path
        raise RuntimeError("simulated worker crash after invocations were persisted")


async def make_runner(db_path: str, executor: RecordingExecutor, resolved=RESOLVED):
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
    runner = DurableTaskRunner(
        session_factory=factory,
        capability_registry=NexusCapabilityRegistry(sources=(StubSource(resolved),)),
        capability_executor=executor,
        authorizer=AllowAuthorizer(),
        schema_validator=DictValidator(),
    )
    return runner, factory


def task_context(**kwargs: Any):
    values: dict[str, Any] = dict(
        task_id=uuid4(),
        workspace_id=WORKSPACE,
        tenant_id=TENANT,
        trace_id=uuid4(),
        actor_id=ACTOR,
        intent=TaskIntent(objective="Analyze inventory exposure for SKU X."),
        objective="Analyze inventory exposure for SKU X.",
        constraints={},
        world_state_version=42,
        capabilities=(),
        policy_context={},
        budget=100.0,
    )
    values.update(kwargs)
    from app.modules.orchestration.contracts import TaskContext

    return TaskContext(**values)


@pytest.mark.asyncio
async def test_read_only_task_completes_end_to_end_with_trace(tmp_path):
    db_path = str(tmp_path / "t.sqlite3")
    executor = RecordingExecutor()
    runner, factory = await make_runner(db_path, executor)
    task_id = await runner.submit(context=task_context())

    # Restart: a fresh runner over the same durable database.
    restarted, _ = await make_runner(db_path, executor)
    status = await restarted.resume(task_id, scope=SCOPE)
    assert status == "COMPLETED"

    runtime = NexusTaskRuntime(session_factory=factory)
    trace = await runtime.build_nexus_trace(task_id, scope=SCOPE)
    assert trace["status"] == "COMPLETED"
    assert trace["outcome"]["status"] == "COMPLETED"
    assert len(trace["steps"]) == 2
    assert all(step["status"] == "SUCCESS" for step in trace["steps"])
    assert len(trace["invocations"]) == 2
    assert len(trace["evidence"]) == 2
    assert len(trace["proposals"]) == 2
    assert [t["to_status"] for t in trace["transitions"]] == [
        "CREATED",
        "INTENT_RESOLVED",
        "PLANNED",
        "RUNNING",
        "PROPOSED",
        "COMPLETED",
    ]
    assert executor.calls == {"inventory.read": 1, "supply.read": 1}


@pytest.mark.asyncio
async def test_consequential_task_requires_approval_then_executes_once(tmp_path):
    db_path = str(tmp_path / "t.sqlite3")
    executor = RecordingExecutor()
    runner, factory = await make_runner(db_path, executor, resolved=CONSEQUENTIAL_RESOLVED)
    task_id = await runner.submit(context=task_context())

    status = await runner.resume(task_id, scope=SCOPE)
    assert status == "AWAITING_APPROVAL"
    runtime = NexusTaskRuntime(session_factory=factory)
    assert await runtime.get_status(task_id, scope=SCOPE) == "AWAITING_APPROVAL"
    assert executor.calls.get("inventory.adjust", 0) == 0  # nothing executed pre-approval

    # Restart between proposal and approval; still awaiting.
    restarted, factory2 = await make_runner(db_path, executor, resolved=CONSEQUENTIAL_RESOLVED)
    assert await restarted.resume(task_id, scope=SCOPE) == "AWAITING_APPROVAL"

    # Human approval; restart; execution completes exactly once.
    await NexusTaskRuntime(session_factory=factory2).decide_approval(
        task_id, scope=SCOPE, approved=True, approver_id=APPROVER
    )
    final, _ = await make_runner(db_path, executor, resolved=CONSEQUENTIAL_RESOLVED)
    assert await final.resume(task_id, scope=SCOPE) == "COMPLETED"

    runtime2 = NexusTaskRuntime(session_factory=factory2)
    trace = await runtime2.build_nexus_trace(task_id, scope=SCOPE)
    assert trace["outcome"]["status"] == "COMPLETED"
    assert trace["execution"]["status"] == "SUCCEEDED"
    approvals = [record["decision"] for record in trace["approvals"]]
    assert approvals == ["REQUESTED", "APPROVED"]
    # The consequential capability executed exactly once across all phases.
    assert executor.calls.get("inventory.adjust", 0) == 1
    # The gateway's durable invocation store deduplicates the post-approval retry.
    assert executor.calls.get("inventory.read", 0) == 1


@pytest.mark.asyncio
async def test_worker_crash_mid_run_resumes_without_replaying_work(tmp_path):
    db_path = str(tmp_path / "t.sqlite3")
    executor = RecordingExecutor()
    runner, _ = await make_runner(db_path, executor)
    task_id = await runner.submit(context=task_context())

    # Simulate a crash after gateway invocations were persisted but before
    # proposals were recorded: the first runner's synthesizer raises.
    runner._synthesizer = ExplodingSynthesizer()
    with pytest.raises(RuntimeError, match="simulated worker crash"):
        await runner.resume(task_id, scope=SCOPE)

    # A fresh worker resumes from the last committed checkpoint.
    restarted, factory = await make_runner(db_path, executor)
    assert await restarted.resume(task_id, scope=SCOPE) == "COMPLETED"

    trace = await NexusTaskRuntime(session_factory=factory).build_nexus_trace(task_id, scope=SCOPE)
    assert trace["status"] == "COMPLETED"
    # Consequential work was NOT replayed: each capability ran exactly once.
    assert executor.calls == {"inventory.read": 1, "supply.read": 1}
    assert len(trace["proposals"]) == 2


@pytest.mark.asyncio
async def test_unauthorized_capability_fails_closed_explicitly(tmp_path):
    db_path = str(tmp_path / "t.sqlite3")
    executor = RecordingExecutor()
    runner, factory = await make_runner(db_path, executor)
    runner._authorizer = DenyAllAuthorizer()
    task_id = await runner.submit(context=task_context())

    status = await runner.resume(task_id, scope=SCOPE)
    assert status == "BLOCKED"
    runtime = NexusTaskRuntime(session_factory=factory)
    task = await runtime.get_task(task_id, scope=SCOPE)
    assert task.status == "BLOCKED"
    assert task.blocked_reason == "POLICY_DENIED"
    # Fail closed: the capability adapter was never reached.
    assert executor.calls == {}


@pytest.mark.asyncio
async def test_resume_after_completion_is_terminal(tmp_path):
    db_path = str(tmp_path / "t.sqlite3")
    executor = RecordingExecutor()
    runner, _ = await make_runner(db_path, executor)
    task_id = await runner.submit(context=task_context())
    await runner.resume(task_id, scope=SCOPE)

    restarted, _ = await make_runner(db_path, executor)
    assert await restarted.resume(task_id, scope=SCOPE) == "COMPLETED"
    # No duplicate execution on a terminal resume.
    assert executor.calls == {"inventory.read": 1, "supply.read": 1}
