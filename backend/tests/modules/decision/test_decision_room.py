"""Decision-1 acceptance tests — Decision Room as a projection of the runtime.

Flow under test:

    Durable task (MAF-4/MAF-5 records)
        -> DecisionRoomService.build_decision_view (read-only projection)
        -> view fields derived from PostgreSQL durable records only

The key invariant — the Decision Room is a projection, not a second state
machine — is asserted by rebuilding the view from fresh service instances
(worker restarts) and verifying zero drift, and by confirming the view
reflects durable state at every lifecycle phase without any writes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.decision.decision_room import DecisionRoomService
from app.modules.orchestration.capabilities.descriptors import (
    WORLD_STATE_CAPABILITY_CONTRACTS,
)
from app.modules.orchestration.capabilities.world_state_adapter import (
    WorldStateCapabilityExecutor,
)
from app.modules.orchestration.capability_registry import NexusCapabilityRegistry
from app.modules.orchestration.durable_runner import DurableTaskRunner
from app.modules.orchestration.task_intent import TaskIntent
from app.modules.orchestration.task_runtime_repository import TaskNotFound
from app.modules.orchestration.task_runtime_service import NexusTaskRuntime, TaskScope
from app.modules.world.world_service import WorldStateService

TENANT = uuid4()
WORKSPACE = uuid4()
ACTOR = uuid4()
APPROVER = uuid4()
SCOPE = TaskScope(tenant_id=TENANT, workspace_id=WORKSPACE)
OTHER_WORKSPACE = uuid4()
WORLD_ID = "wh-prod-main"
INVENTORY_VAR = "inventory.warehouse.comp_042.wh_001"

CAPABILITIES: dict[str, Any] = {
    capability_id: contract.descriptor
    for capability_id, contract in WORLD_STATE_CAPABILITY_CONTRACTS.items()
}


class SchemaLiteValidator:
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
    calls: dict[str, int] = field(default_factory=dict)


async def make_db(db_path: str, probe: RecordingProbe):
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
    async with factory() as session:
        service = WorldStateService(repository=state_repository.StateRepository(db=session))
        await service.initialize_world(
            workspace_id=str(WORKSPACE),
            world_id=WORLD_ID,
            initial_variables={INVENTORY_VAR: state_repository_state_variable(INVENTORY_VAR, 500)},
        )
    runner = DurableTaskRunner(
        session_factory=factory,
        capability_registry=NexusCapabilityRegistry(
            sources=(_world_state_source(lambda t, w: True),)
        ),
        capability_executor=WorldStateCapabilityExecutor(session_factory=factory),
        authorizer=AllowAuthorizer(),
        schema_validator=SchemaLiteValidator(),
    )
    del probe
    return runner, factory


def state_repository_state_variable(variable_id: str, value: int) -> Any:
    from app.modules.world.world_models import StateVariable, StateVariableType

    return StateVariable.from_raw_value(
        variable_id,
        StateVariableType.INVENTORY,
        "comp_042",
        "warehouse",
        value,
        unit="units",
    )


def _world_state_source(is_provisioned):
    from app.modules.orchestration.capabilities import WorldStateCapabilitySource

    return WorldStateCapabilitySource(is_provisioned=is_provisioned)


def read_task_context() -> Any:
    return _context(
        intent=TaskIntent(
            objective="Assess inventory exposure for SKU comp_042.",
            constraints={
                "required_capabilities": ("world.inventory.read",),
                "step_arguments": {"world.inventory.read": {"world_id": WORLD_ID}},
            },
        )
    )


def consequential_task_context() -> Any:
    return _context(
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
                        "quantity_change": -50,
                    },
                },
            },
        )
    )


def _context(*, intent: TaskIntent) -> Any:
    from app.modules.orchestration.contracts import TaskContext

    return TaskContext(
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


@pytest.mark.asyncio
async def test_decision_room_projects_read_only_task_from_durable_records(tmp_path):
    db_path = str(tmp_path / "t.sqlite3")
    runner, factory = await make_db(db_path, RecordingProbe())
    task_id = await runner.submit(context=read_task_context())
    assert await runner.resume(task_id, scope=SCOPE) == "COMPLETED"

    room = DecisionRoomService(session_factory=factory)
    view = await room.build_decision_view(task_id, scope=SCOPE)

    assert view["task"]["status"] == "COMPLETED"
    assert view["task"]["task_id"] == task_id
    assert view["task"]["world_state_version"] == 1
    # No human decision awaited; the run completed without one.
    assert view["pending_decision"] is None
    # Durable artifacts projected verbatim.
    assert view["plan"] is not None
    assert len(view["runs"]) == 1
    assert len(view["invocations"]) == 1
    assert len(view["evidence"]) == 1
    assert len(view["proposals"]) == 1
    assert view["outcome"]["status"] == "COMPLETED"
    assert view["consequential_capabilities"] == ()
    # Policy results are the durable authorization decisions, one per invocation.
    assert view["policy_results"][0]["capability_id"] == "world.inventory.read"
    assert view["policy_results"][0]["allowed"] is True
    assert view["policy_results"][0]["policy_id"] == "p-world-state"
    # Recommendation comes from the durable proposal, not a second engine.
    assert view["recommendation"]["source"] == "proposal"
    assert view["recommendation"]["statement"] == view["proposals"][0]["statement"]


@pytest.mark.asyncio
async def test_decision_room_projects_pending_decision_for_consequential_task(tmp_path):
    db_path = str(tmp_path / "t.sqlite3")
    runner, factory = await make_db(db_path, RecordingProbe())
    task_id = await runner.submit(context=consequential_task_context())
    assert await runner.resume(task_id, scope=SCOPE) == "AWAITING_APPROVAL"

    room = DecisionRoomService(session_factory=factory)
    view = await room.build_decision_view(task_id, scope=SCOPE)

    assert view["task"]["status"] == "AWAITING_APPROVAL"
    pending = view["pending_decision"]
    assert pending is not None
    assert pending["approval_required_for"] == ("world.inventory.adjust",)
    assert pending["reason"] is not None
    assert pending["awaited_since"] is not None
    # The consequential proposal is surfaced for the human decision.
    assert pending["consequential_proposals"]
    assert pending["consequential_proposals"][0]["actions"]
    assert view["consequential_capabilities"] == ("world.inventory.adjust",)
    assert view["outcome"] is None  # nothing executed yet


@pytest.mark.asyncio
async def test_decision_room_reflects_approval_execution_and_outcome(tmp_path):
    db_path = str(tmp_path / "t.sqlite3")
    runner, factory = await make_db(db_path, RecordingProbe())
    task_id = await runner.submit(context=consequential_task_context())
    await runner.resume(task_id, scope=SCOPE)
    await NexusTaskRuntime(session_factory=factory).decide_approval(
        task_id, scope=SCOPE, approved=True, approver_id=APPROVER
    )
    assert await runner.resume(task_id, scope=SCOPE) == "COMPLETED"

    room = DecisionRoomService(session_factory=factory)
    view = await room.build_decision_view(task_id, scope=SCOPE)

    assert view["task"]["status"] == "COMPLETED"
    assert view["pending_decision"] is None
    assert view["execution"]["status"] == "SUCCEEDED"
    assert view["outcome"]["status"] == "COMPLETED"
    # The full approval trail is projected: REQUESTED then APPROVED.
    assert [record["decision"] for record in view["approvals"]] == ["REQUESTED", "APPROVED"]
    assert view["approvals"][-1]["approver_id"] == str(APPROVER)


@pytest.mark.asyncio
async def test_decision_room_is_a_projection_with_zero_drift_on_restart(tmp_path):
    db_path = str(tmp_path / "t.sqlite3")
    runner, factory = await make_db(db_path, RecordingProbe())
    task_id = await runner.submit(context=consequential_task_context())
    await runner.resume(task_id, scope=SCOPE)

    first = DecisionRoomService(session_factory=factory)
    view_before = await first.build_decision_view(task_id, scope=SCOPE)

    # Worker restart: a fresh service over the same durable database.
    restarted = DecisionRoomService(session_factory=factory)
    view_after = await restarted.build_decision_view(task_id, scope=SCOPE)

    # The view is a pure projection of durable state: identical on rebuild.
    assert view_after == view_before
    # The projection owns no state machine: the service has no mutation API.
    public_methods = {
        name
        for name, value in vars(DecisionRoomService).items()
        if callable(value) and not name.startswith("_")
    }
    assert public_methods == {"build_decision_view"}


@pytest.mark.asyncio
async def test_decision_room_scope_isolation_hides_other_workspaces(tmp_path):
    db_path = str(tmp_path / "t.sqlite3")
    runner, factory = await make_db(db_path, RecordingProbe())
    task_id = await runner.submit(context=read_task_context())
    await runner.resume(task_id, scope=SCOPE)

    room = DecisionRoomService(session_factory=factory)
    other_scope = TaskScope(tenant_id=TENANT, workspace_id=OTHER_WORKSPACE)
    with pytest.raises(TaskNotFound):
        await room.build_decision_view(task_id, scope=other_scope)
