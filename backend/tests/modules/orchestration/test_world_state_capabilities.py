"""MAF-5 acceptance tests — real capability vertical slice end-to-end.

Flow under test:

    Initialize authoritative World State (PostgreSQL-shaped store)
        -> submit durable task -> resume -> execute real capabilities
        through the Tool Gateway -> approval boundary -> governed
        consequential write -> outcome -> NexusTrace reconstruction

Every invocation is routed through the NexusToolGateway; the real adapters
read and write only through WorldStateService, the sole authoritative write
path. No synthetic operational facts appear anywhere in this slice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.orchestration.capabilities import (
    WorldStateCapabilityExecutor,
    WorldStateCapabilitySource,
)
from app.modules.orchestration.capabilities.descriptors import (
    WORLD_STATE_CAPABILITY_CONTRACTS,
)
from app.modules.orchestration.capability_registry import NexusCapabilityRegistry
from app.modules.orchestration.durable_runner import DurableTaskRunner
from app.modules.orchestration.task_intent import TaskIntent
from app.modules.orchestration.task_runtime_service import NexusTaskRuntime, TaskScope
from app.modules.world.state_repository import StateRepository
from app.modules.world.world_models import StateVariable, StateVariableType
from app.modules.world.world_service import WorldStateService

TENANT = uuid4()
WORKSPACE = uuid4()
ACTOR = uuid4()
APPROVER = uuid4()
SCOPE = TaskScope(tenant_id=TENANT, workspace_id=WORKSPACE)
WORLD_ID = "wh-prod-main"
INVENTORY_VAR = "inventory.warehouse.comp_042.wh_001"
DEMAND_VAR = "demand.component.comp_042"
LEAD_TIME_VAR = "lead_time.supplier.sup_009"

CAPABILITIES: dict[str, Any] = {
    capability_id: contract.descriptor
    for capability_id, contract in WORLD_STATE_CAPABILITY_CONTRACTS.items()
}


class SchemaLiteValidator:
    """Minimal JSON-schema enforcement for capability input contracts."""

    _TYPES: dict[str, Any] = {
        "object": dict,
        "string": str,
        "integer": int,
        "boolean": bool,
        "array": list,
        "number": (int, float),
    }

    def validate(self, *, schema: dict[str, Any], arguments: dict[str, Any]) -> None:
        if not isinstance(arguments, dict):
            raise ValueError("arguments must be a dict")
        for name in schema.get("required", []):
            if name not in arguments:
                raise ValueError(f"missing required argument: {name}")
        properties = schema.get("properties", {})
        for key, value in arguments.items():
            prop = properties.get(key)
            if not isinstance(prop, dict):
                continue
            expected = self._TYPES.get(prop.get("type"))
            if expected is None:
                continue
            if prop.get("type") == "integer" and isinstance(value, bool):
                raise ValueError(f"argument '{key}' must be an integer")
            if not isinstance(value, expected):
                raise ValueError(f"argument '{key}' has the wrong type")


class AllowAuthorizer:
    async def authorize(self, *, capability, context) -> Any:
        from app.modules.orchestration.tool_gateway import AuthorizationDecision

        return AuthorizationDecision(True, "allowed by workspace scopes", "p-world-state")


@dataclass
class RecordingProbe:
    """Counts real adapter executions without replacing the adapter."""

    calls: dict[str, int] = field(default_factory=dict)

    def record(self, capability_id: str) -> None:
        self.calls[capability_id] = self.calls.get(capability_id, 0) + 1


def make_executor(session_factory, probe: RecordingProbe) -> WorldStateCapabilityExecutor:
    inner = WorldStateCapabilityExecutor(session_factory=session_factory)

    class ProbingExecutor:
        def __init__(self, wrapped: WorldStateCapabilityExecutor) -> None:
            self._wrapped = wrapped

        def __getattr__(self, name: str) -> Any:
            return getattr(self._wrapped, name)

        async def execute(self, *, capability, arguments, context) -> dict[str, Any]:
            probe.record(capability.capability_id)
            return await self._wrapped.execute(
                capability=capability, arguments=arguments, context=context
            )

    return ProbingExecutor(inner)  # type: ignore[return-value]


async def make_runner(db_path: str, probe: RecordingProbe, *, provisioned: bool = True):
    from sqlalchemy import MetaData

    from app.infrastructure.database import Base
    from app.modules.orchestration import task_runtime_models  # noqa: F401
    from app.modules.world import state_repository  # noqa: F401

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
    metadata = MetaData()
    for table in Base.metadata.sorted_tables:
        if table.name.startswith(("nexus_", "world_")):
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
    await init_world(factory, WORLD_ID, inventory_qty=500)
    runner = DurableTaskRunner(
        session_factory=factory,
        capability_registry=NexusCapabilityRegistry(
            sources=(WorldStateCapabilitySource(is_provisioned=lambda t, w: provisioned),)
        ),
        capability_executor=make_executor(factory, probe),
        authorizer=AllowAuthorizer(),
        schema_validator=SchemaLiteValidator(),
    )
    return runner, factory


async def init_world(factory, world_id: str, *, inventory_qty: int) -> None:
    async with factory() as session:
        service = WorldStateService(repository=StateRepository(db=session))
        await service.initialize_world(
            workspace_id=str(WORKSPACE),
            world_id=world_id,
            initial_variables={
                INVENTORY_VAR: StateVariable.from_raw_value(
                    INVENTORY_VAR,
                    StateVariableType.INVENTORY,
                    "comp_042",
                    "warehouse",
                    inventory_qty,
                    unit="units",
                ),
                DEMAND_VAR: StateVariable.from_raw_value(
                    DEMAND_VAR,
                    StateVariableType.DEMAND,
                    "comp_042",
                    "component",
                    25,
                    unit="units/day",
                ),
                LEAD_TIME_VAR: StateVariable.from_raw_value(
                    LEAD_TIME_VAR,
                    StateVariableType.LEAD_TIME,
                    "sup_009",
                    "supplier",
                    10,
                    unit="days",
                ),
            },
        )


def task_context(**kwargs: Any):
    from app.modules.orchestration.contracts import TaskContext

    objective = kwargs.pop(
        "objective", "Assess inventory exposure and adjust stock for SKU comp_042."
    )
    intent = kwargs.pop(
        "intent",
        TaskIntent(
            objective=objective,
            constraints={
                "required_capabilities": ("world.inventory.read",),
                "step_arguments": {"world.inventory.read": {"world_id": WORLD_ID}},
            },
        ),
    )
    values: dict[str, Any] = dict(
        task_id=uuid4(),
        workspace_id=WORKSPACE,
        tenant_id=TENANT,
        trace_id=uuid4(),
        actor_id=ACTOR,
        intent=intent,
        objective=intent.objective,
        constraints=dict(intent.constraints),
        world_state_version=1,
        capabilities=(),
        policy_context={},
        budget=100.0,
    )
    values.update(kwargs)
    return TaskContext(**values)


async def latest_world_version(factory, world_id: str = WORLD_ID) -> int:
    async with factory() as session:
        repo = StateRepository(db=session)
        state = await repo.get_latest(world_id=world_id, workspace_id=str(WORKSPACE))
        assert state is not None
        return state.version  # type: ignore[no-any-return]


async def world_variable_value(factory, world_id: str, version: int, variable_id: str) -> Any:
    async with factory() as session:
        repo = StateRepository(db=session)
        state = await repo.get(world_id=world_id, workspace_id=str(WORKSPACE), version=version)
        assert state is not None
        variable = state.get_variable(variable_id)
        assert variable is not None
        return variable.raw_value


# ─────────────────────────────────────────────────────────────────────────────
# READ capabilities: reasoning against authoritative data
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_inventory_read_serves_real_world_state_with_provenance(tmp_path):
    db_path = str(tmp_path / "t.sqlite3")
    probe = RecordingProbe()
    runner, factory = await make_runner(db_path, probe)
    task_id = await runner.submit(context=task_context())

    status = await runner.resume(task_id, scope=SCOPE)
    assert status == "COMPLETED"

    runtime = NexusTaskRuntime(session_factory=factory)
    trace = await runtime.build_nexus_trace(task_id, scope=SCOPE)
    invocation = trace["invocations"][0]
    assert invocation["capability_id"] == "world.inventory.read"
    assert invocation["capability_version"] == "1.0.0"
    assert invocation["status"] == "SUCCESS"
    assert invocation["side_effect"] == "READ"
    assert invocation["world_state_version"] == 1

    outputs = trace["steps"][0]["evidence_refs"]
    assert outputs == [f"world-state:{WORLD_ID}:v1:{INVENTORY_VAR}"]

    # The read value came from the authoritative store, not synthetic data.
    step_output = trace["steps"][0]
    assert probe.calls == {"world.inventory.read": 1}
    assert step_output["status"] == "SUCCESS"
    value = await world_variable_value(factory, WORLD_ID, 1, INVENTORY_VAR)
    assert value == 500


@pytest.mark.asyncio
async def test_risk_analysis_derives_from_real_state_values(tmp_path):
    db_path = str(tmp_path / "t.sqlite3")
    probe = RecordingProbe()
    runner, factory = await make_runner(db_path, probe)
    await init_world(factory, "wh-low-cover", inventory_qty=150)
    context = task_context(
        intent=TaskIntent(
            objective="Assess stockout risk for SKU comp_042 at warehouse wh_001.",
            constraints={
                "required_capabilities": ("world.risk.analyze",),
                "step_arguments": {
                    "world.risk.analyze": {
                        "world_id": "wh-low-cover",
                        "warehouse_id": "wh_001",
                        "component_id": "comp_042",
                        "supplier_id": "sup_009",
                    }
                },
            },
        ),
        world_state_version=1,
    )
    task_id = await runner.submit(context=context)
    status = await runner.resume(task_id, scope=SCOPE)
    assert status == "COMPLETED"

    runtime = NexusTaskRuntime(session_factory=factory)
    trace = await runtime.build_nexus_trace(task_id, scope=SCOPE)
    assert trace["status"] == "COMPLETED"
    # 150 units at 25/day = 6 days of cover, below the 10-day lead time.
    evidence = trace["evidence"]
    assert len(evidence) == 3  # inventory, demand, lead_time all established
    assert probe.calls == {"world.risk.analyze": 1}


@pytest.mark.asyncio
async def test_supplier_read_serves_lead_time_and_health(tmp_path):
    db_path = str(tmp_path / "t.sqlite3")
    probe = RecordingProbe()
    runner, _ = await make_runner(db_path, probe)
    context = task_context(
        intent=TaskIntent(
            objective="Check supplier lead time for sup_009.",
            constraints={
                "required_capabilities": ("world.supplier.read",),
                "step_arguments": {
                    "world.supplier.read": {"world_id": WORLD_ID, "supplier_id": "sup_009"}
                },
            },
        ),
        world_state_version=1,
    )
    task_id = await runner.submit(context=context)
    assert await runner.resume(task_id, scope=SCOPE) == "COMPLETED"
    assert probe.calls == {"world.supplier.read": 1}


# ─────────────────────────────────────────────────────────────────────────────
# CONSEQUENTIAL WRITE: approval boundary, idempotency, real new version
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_consequential_adjust_requires_approval_then_writes_real_version_once(tmp_path):
    db_path = str(tmp_path / "t.sqlite3")
    probe = RecordingProbe()
    runner, factory = await make_runner(db_path, probe)
    context = task_context(
        intent=TaskIntent(
            objective="Adjust stock for SKU comp_042 after the supply disruption.",
            risk_class="HIGH",
            constraints={
                "required_capabilities": ("world.inventory.read", "world.inventory.adjust"),
                "step_arguments": {
                    "world.inventory.read": {"world_id": WORLD_ID},
                    "world.inventory.adjust": {
                        "world_id": WORLD_ID,
                        "warehouse_id": "wh_001",
                        "component_id": "comp_042",
                        "quantity_change": -150,
                        "reason": "task_execution",
                    },
                },
            },
        ),
        world_state_version=1,
    )
    task_id = await runner.submit(context=context)

    status = await runner.resume(task_id, scope=SCOPE)
    assert status == "AWAITING_APPROVAL"
    # Nothing consequential executed pre-approval; production state untouched.
    assert probe.calls.get("world.inventory.adjust", 0) == 0
    assert await latest_world_version(factory) == 1

    # Human approval; the governed write creates exactly one new version.
    await NexusTaskRuntime(session_factory=factory).decide_approval(
        task_id, scope=SCOPE, approved=True, approver_id=APPROVER
    )
    assert await runner.resume(task_id, scope=SCOPE) == "COMPLETED"

    assert probe.calls.get("world.inventory.adjust", 0) == 1
    assert await latest_world_version(factory) == 2
    assert await world_variable_value(factory, WORLD_ID, 2, INVENTORY_VAR) == 350  # 500 + (-150)

    # DB-level evidence: one append-only event, deterministic idempotency key,
    # lineage through submit_event.
    async with factory() as session:
        repo = StateRepository(db=session)
        events = await repo.get_events(WORLD_ID, str(WORKSPACE))
        adjust_events = [event for event in events if event.event_type == "inventory_changed"]
        assert len(adjust_events) == 1
        assert adjust_events[0].idempotency_key.startswith(f"task:{task_id}:capability:")
        versions = await repo.get_versions(WORLD_ID, str(WORKSPACE))
        assert [version.source for version in versions] == ["genesis", "submit_event"]

    runtime = NexusTaskRuntime(session_factory=factory)
    trace = await runtime.build_nexus_trace(task_id, scope=SCOPE)
    assert trace["execution"]["status"] == "SUCCEEDED"
    adjust_invocation = [
        record
        for record in trace["invocations"]
        if record["capability_id"] == "world.inventory.adjust"
    ]
    # The trace holds both sides of the approval boundary: the pre-approval
    # APPROVAL_REQUIRED block (the durable governance signal) and the
    # post-approval SUCCESS with the same arguments digest.
    assert len(adjust_invocation) == 2
    assert adjust_invocation[0]["side_effect"] == "WRITE_CONSEQUENTIAL"
    assert adjust_invocation[0]["status"] == "BLOCKED"
    assert adjust_invocation[0]["error"] == "APPROVAL_REQUIRED"
    assert adjust_invocation[1]["side_effect"] == "WRITE_CONSEQUENTIAL"
    assert adjust_invocation[1]["status"] == "SUCCESS"
    assert adjust_invocation[1]["arguments_sha256"] == adjust_invocation[0]["arguments_sha256"]


@pytest.mark.asyncio
async def test_consequential_adjust_blocked_for_low_risk_intent_by_gateway(tmp_path):
    db_path = str(tmp_path / "t.sqlite3")
    probe = RecordingProbe()
    runner, factory = await make_runner(db_path, probe)
    context = task_context(
        intent=TaskIntent(
            objective="Adjust stock for SKU comp_042.",
            risk_class="MEDIUM",
            constraints={
                "required_capabilities": ("world.inventory.adjust",),
                "step_arguments": {
                    "world.inventory.adjust": {
                        "world_id": WORLD_ID,
                        "warehouse_id": "wh_001",
                        "component_id": "comp_042",
                        "quantity_change": -10,
                    }
                },
            },
        ),
        world_state_version=1,
    )
    task_id = await runner.submit(context=context)

    # The gateway's APPROVAL_REQUIRED block is the authoritative governance
    # signal even when the intent risk class alone would not demand it.
    assert await runner.resume(task_id, scope=SCOPE) == "AWAITING_APPROVAL"
    assert probe.calls.get("world.inventory.adjust", 0) == 0
    assert await latest_world_version(factory) == 1


@pytest.mark.asyncio
async def test_write_idempotency_replays_original_version_without_new_rows(tmp_path):
    db_path = str(tmp_path / "t.sqlite3")
    probe = RecordingProbe()
    runner, factory = await make_runner(db_path, probe)
    executor = WorldStateCapabilityExecutor(session_factory=factory)
    from app.modules.orchestration.contracts import AgentContext

    context = AgentContext(
        workspace_id=WORKSPACE,
        tenant_id=TENANT,
        task_id=uuid4(),
        trace_id=uuid4(),
        actor_id=ACTOR,
        world_state_version=1,
        policy_context={"execution_approved": True},
    )
    arguments = {
        "world_id": WORLD_ID,
        "warehouse_id": "wh_001",
        "component_id": "comp_042",
        "quantity_change": -50,
    }

    first = await executor.execute(
        capability=CAPABILITIES["world.inventory.adjust"],
        arguments=arguments,
        context=context,
    )
    assert first["is_duplicate"] is False
    assert first["world_state_version"] == 2

    second = await executor.execute(
        capability=CAPABILITIES["world.inventory.adjust"],
        arguments=arguments,
        context=context,
    )
    # Adapter-level idempotency: same arguments replay the original version.
    assert second["is_duplicate"] is True
    assert second["world_state_version"] == 2
    assert second["event_id"] == first["event_id"]
    assert await latest_world_version(factory) == 2


@pytest.mark.asyncio
async def test_unprovisioned_workspace_fails_closed_without_invocations(tmp_path):
    db_path = str(tmp_path / "t.sqlite3")
    probe = RecordingProbe()
    runner, factory = await make_runner(db_path, probe, provisioned=False)
    task_id = await runner.submit(context=task_context())

    status = await runner.resume(task_id, scope=SCOPE)
    assert status == "BLOCKED"
    runtime = NexusTaskRuntime(session_factory=factory)
    task = await runtime.get_task(task_id, scope=SCOPE)
    assert "world.inventory.read" in (task.blocked_reason or "")
    assert probe.calls == {}
    assert await latest_world_version(factory) == 1


@pytest.mark.asyncio
async def test_missing_required_argument_fails_closed_with_explicit_error(tmp_path):
    db_path = str(tmp_path / "t.sqlite3")
    probe = RecordingProbe()
    runner, factory = await make_runner(db_path, probe)
    context = task_context(
        intent=TaskIntent(
            objective="Assess inventory exposure and adjust stock for SKU comp_042.",
            constraints={
                "required_capabilities": ("world.inventory.read",),
                "step_arguments": {"world.inventory.read": {}},  # world_id missing
            },
        ),
    )
    task_id = await runner.submit(context=context)

    status = await runner.resume(task_id, scope=SCOPE)
    assert status == "BLOCKED"
    runtime = NexusTaskRuntime(session_factory=factory)
    trace = await runtime.build_nexus_trace(task_id, scope=SCOPE)
    invocation = trace["invocations"][0]
    assert invocation["status"] == "BLOCKED"
    assert invocation["error"] == "INVALID_ARGUMENTS"
    assert probe.calls == {}


@pytest.mark.asyncio
async def test_unknown_capability_is_rejected_by_the_adapter(tmp_path):
    db_path = str(tmp_path / "t.sqlite3")
    probe = RecordingProbe()
    _, factory = await make_runner(db_path, probe)
    executor = WorldStateCapabilityExecutor(session_factory=factory)
    from app.modules.orchestration.capabilities import CapabilityExecutionError
    from app.modules.orchestration.contracts import AgentContext, CapabilityDescriptor

    context = AgentContext(
        workspace_id=WORKSPACE,
        tenant_id=TENANT,
        task_id=uuid4(),
        trace_id=uuid4(),
        actor_id=ACTOR,
        world_state_version=1,
    )
    nonsense = CapabilityDescriptor(
        capability_id="world.nonsense",
        name="Not a capability",
        version="1.0.0",
        description="Unknown capability.",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        side_effect="READ",
        evidence_required=False,
    )
    with pytest.raises(CapabilityExecutionError, match="UNKNOWN_CAPABILITY"):
        await executor.execute(capability=nonsense, arguments={}, context=context)


# ─────────────────────────────────────────────────────────────────────
# Failure-atomicity invariant (RC): a failed governed write must never
# leave the durable task/run marked SUCCEEDED.
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_failed_governed_write_fails_task_and_never_records_success(tmp_path, monkeypatch):
    """World State transaction failure during the approved execution.

    The durable invocation records the FAILED attempt; the execution
    record, task status, and outcome must agree — never a false SUCCEEDED
    task over a failed write, and never a new World State version.
    """
    db_path = str(tmp_path / "t.sqlite3")
    probe = RecordingProbe()
    runner, factory = await make_runner(db_path, probe)
    context = task_context(
        intent=TaskIntent(
            objective="Adjust stock for SKU comp_042 after the supply disruption.",
            risk_class="HIGH",
            constraints={
                "required_capabilities": ("world.inventory.read", "world.inventory.adjust"),
                "step_arguments": {
                    "world.inventory.read": {"world_id": WORLD_ID},
                    "world.inventory.adjust": {
                        "world_id": WORLD_ID,
                        "warehouse_id": "wh_001",
                        "component_id": "comp_042",
                        "quantity_change": -150,
                        "reason": "task_execution",
                    },
                },
            },
        ),
        world_state_version=1,
    )
    task_id = await runner.submit(context=context)
    assert await runner.resume(task_id, scope=SCOPE) == "AWAITING_APPROVAL"
    assert probe.calls.get("world.inventory.adjust", 0) == 0

    # Inject World State transaction failure: the sole write path itself
    # fails at the database boundary after human approval.
    async def failing_submit(self, event, **kwargs):
        raise RuntimeError("simulated World State transaction failure")

    monkeypatch.setattr(WorldStateService, "submit_event", failing_submit)

    await NexusTaskRuntime(session_factory=factory).decide_approval(
        task_id, scope=SCOPE, approved=True, approver_id=APPROVER
    )
    status = await runner.resume(task_id, scope=SCOPE)

    # The invariant: task != COMPLETED, execution != SUCCEEDED, an explicit
    # FAILED outcome, and no false success anywhere in the trace.
    assert status == "FAILED"
    runtime = NexusTaskRuntime(session_factory=factory)
    trace = await runtime.build_nexus_trace(task_id, scope=SCOPE)
    assert trace["status"] == "FAILED"
    assert trace["execution"] is not None
    assert trace["execution"]["status"] == "FAILED"
    # The gateway masks the underlying exception into its durable error
    # semantics; the execution record carries the capability error code.
    assert "CAPABILITY_EXECUTION_FAILED" in (trace["execution"]["failure_reason"] or "")
    assert trace["outcome"] is not None
    assert trace["outcome"]["status"] == "FAILED"

    # The capability failure is recorded, and no consequential SUCCESS exists.
    adjust_invocations = [
        record
        for record in trace["invocations"]
        if record["capability_id"] == "world.inventory.adjust"
    ]
    assert any(record["status"] == "FAILED" for record in adjust_invocations)
    assert not any(record["status"] == "SUCCESS" for record in adjust_invocations)
    # The executed step is not marked SUCCESS either.
    adjust_steps = [
        record for record in trace["steps"] if record["step_id"] == "world.inventory.adjust"
    ]
    assert all(record["status"] != "SUCCESS" for record in adjust_steps)

    # No write reached production.
    assert probe.calls.get("world.inventory.adjust", 0) == 1  # attempted, then failed
    assert await latest_world_version(factory) == 1
