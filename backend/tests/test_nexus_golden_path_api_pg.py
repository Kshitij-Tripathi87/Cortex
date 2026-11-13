"""v0.8.6 — Golden-path API on REAL PostgreSQL (P0: Real PostgreSQL Golden Path).

Runs the exact canonical task API flow proven on the SQLite acceptance
store against real PostgreSQL:

    POST /nexus/tasks  -> durable task creation -> MAF runtime -> proposal
        -> Decision Room -> approval -> consequential World State write
        -> outcome -> NexusTrace

Requires real PostgreSQL (nexus_* + world_* tables); skips when
unavailable. AuthN is exercised through REAL JWTs (minted by the same
``issue_token`` the login path uses); tests run with CORTEX_ENV=pilot so
``get_current_user`` takes the strict JWT path (no dependency overrides
for identity).

Also covered:
  - no consequential write without approval (run-before-approval is a no-op)
  - rejection records its reason and never writes
  - unprovisioned capability discovery fails closed (explicit BLOCKED)
  - cross-workspace isolation on every task endpoint (403/404, real JWT)
  - role-gated tools: viewer can neither create, run, nor approve
"""

from __future__ import annotations

import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import MetaData, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.modules.orchestration.task_runtime_models as _task_models  # noqa: F401
import app.modules.world.state_repository as _world_models  # noqa: F401
from app.api.v1 import nexus_persistent
from app.common.ids import uuid7_uuid
from app.config import get_settings
from app.infrastructure.database import Base
from app.modules.identity.jwt_auth import issue_token
from app.modules.world.state_repository import StateRepository
from app.modules.world.world_models import StateVariable, StateVariableType
from app.modules.world.world_service import WorldStateService

JWT_SECRET = "test-secret-0123456789abcdef0123456789"

INVENTORY_VAR = "inventory.warehouse.comp_042.wh_001"


def _world_id() -> str:
    """World ids are globally unique per (world_id, version) on the
    migration-created schema — each test provisions its own world."""
    return f"wh-prod-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def strict_auth_env(monkeypatch):
    """Run with CORTEX_ENV=pilot so identity resolves via real JWT verify."""
    monkeypatch.setenv("CORTEX_ENV", "pilot")
    monkeypatch.setenv("CORTEX_JWT_SECRET", JWT_SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def pg_engine(request):
    """Real-PostgreSQL engine with nexus_* + world_* tables created."""
    postgres_url = request.config.postgres_url
    try:
        engine = create_async_engine(postgres_url, echo=False)
        async with engine.begin() as conn:
            await conn.execute(select(1))
    except Exception as exc:
        pytest.skip(f"PostgreSQL not available: {exc}")

    tables = [
        t
        for t in Base.metadata.sorted_tables
        if t.name.startswith(("nexus_", "world_"))
        # Billing gate resolves entitlements through core.organizations.
        or t.name in ("organizations", "workspaces", "users")
    ]
    if not tables:
        pytest.skip("nexus/world tables not registered on Base.metadata")
    async with engine.begin() as conn:
        from sqlalchemy.schema import CreateSchema

        await conn.execute(CreateSchema("core", if_not_exists=True))
        meta = MetaData()
        for table in tables:
            table.to_metadata(meta)
        await conn.run_sync(meta.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def api_client(pg_engine, strict_auth_env, monkeypatch):
    """ASGI client with REAL JWT identity and the real-PG durable runtime."""
    maker = async_sessionmaker(pg_engine, class_=AsyncSession, expire_on_commit=False)
    test_app = FastAPI()
    test_app.include_router(nexus_persistent.router, prefix="/api/v1")
    monkeypatch.setattr(nexus_persistent, "get_session_factory", lambda: maker)
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, maker


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


async def _identity(maker, role: str = "admin") -> dict[str, str]:
    """Provision an organization + workspace (plan defaults to a live
    trial) and mint a REAL JWT (verify_token checks the signature;
    require_workspace_access checks the token's workspace claim). The
    billing gate resolves entitlements through core.organizations via the
    workspace row, so the fixtures provision them directly; tests that
    exercise DENY paths mutate the org row before minting."""
    from datetime import UTC, datetime, timedelta

    from app.modules.access.models import Organization, Workspace

    user_id = uuid7_uuid()
    workspace_id = uuid7_uuid()
    org_id = uuid7_uuid()
    slug = f"golden-pg-{uuid.uuid4().hex[:8]}"
    now = datetime.now(UTC)
    async with maker() as session:
        session.add(
            Organization(
                id=org_id,
                name=f"Golden Org {slug}",
                slug=slug,
                plan="trial",
                trial_ends_at=now + timedelta(days=7),
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()
        session.add(
            Workspace(
                id=workspace_id,
                organization_id=org_id,
                name=f"Golden WS {slug}",
                slug=slug,
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()
    token, _ = issue_token(
        user_id=user_id,
        workspace_id=workspace_id,
        role=role,
        email=f"golden-pg-{uuid.uuid4().hex[:8]}@example.com",
    )
    return {
        "token": token,
        "user_id": str(user_id),
        "workspace_id": str(workspace_id),
        "org_id": str(org_id),
    }


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def init_world(maker, workspace_id: str, world_id: str, *, inventory_qty: int = 500) -> None:
    """Ingest inventory data through the sole World State write path."""
    async with maker() as session:
        service = WorldStateService(repository=StateRepository(db=session))
        await service.initialize_world(
            workspace_id=workspace_id,
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
            },
        )


def _submit_body(workspace_id: str, world_id: str, **kw) -> dict:
    return {
        "workspace_id": workspace_id,
        "objective": "Assess inventory exposure and adjust stock for SKU comp_042.",
        "world_state_version": 1,
        "risk_class": "HIGH",
        "required_capabilities": ["world.inventory.read", "world.inventory.adjust"],
        "step_arguments": {
            "world.inventory.read": {"world_id": world_id},
            "world.inventory.adjust": {
                "world_id": world_id,
                "warehouse_id": "wh_001",
                "component_id": "comp_042",
                "quantity_change": -150,
                "reason": "task_execution",
            },
        },
        **kw,
    }


async def _latest_world_version(maker, workspace_id: str, world_id: str) -> int:
    async with maker() as session:
        repo = StateRepository(db=session)
        state = await repo.get_latest(world_id=world_id, workspace_id=workspace_id)
        assert state is not None
        return state.version  # type: ignore[no-any-return]


async def _adjust_events(maker, workspace_id: str, world_id: str) -> list:
    async with maker() as session:
        repo = StateRepository(db=session)
        events = await repo.get_events(world_id, workspace_id)
        return [event for event in events if event.event_type == "inventory_changed"]


# ─────────────────────────────────────────────────────────────────────
# Golden flow on real PostgreSQL
# ─────────────────────────────────────────────────────────────────────


class TestGoldenFlowOnPostgres:
    async def test_submit_approve_execute_outcome_end_to_end(self, api_client) -> None:
        client, maker = api_client
        me = await _identity(maker)
        ws = me["workspace_id"]
        wid = _world_id()
        await init_world(maker, ws, wid)

        created = await client.post(
            "/api/v1/nexus/tasks", json=_submit_body(ws, wid), headers=_h(me["token"])
        )
        assert created.status_code == 201, created.text
        data = created.json()["data"]
        assert data["status"] == "AWAITING_APPROVAL"
        assert data["requires_approval"] is True
        assert data["trace_id"]
        task_id = data["task_id"]

        # Pre-approval: nothing consequential executed; production untouched.
        assert await _latest_world_version(maker, ws, wid) == 1
        assert await _adjust_events(maker, ws, wid) == []

        # Durable task record.
        got = await client.get(
            f"/api/v1/nexus/tasks/{task_id}",
            params={"workspace_id": ws},
            headers=_h(me["token"]),
        )
        assert got.status_code == 200, got.text
        assert got.json()["data"]["task"]["status"] == "AWAITING_APPROVAL"

        # Decision Room projection shows the pending decision.
        room = await client.get(
            f"/api/v1/nexus/tasks/{task_id}/decision-room",
            params={"workspace_id": ws},
            headers=_h(me["token"]),
        )
        assert room.status_code == 200, room.text
        view = room.json()["data"]["decision_room"]
        assert view["pending_decision"] is not None
        assert "world.inventory.adjust" in view["pending_decision"]["approval_required_for"]

        # Re-running before approval never executes the consequential write.
        rerun = await client.post(
            f"/api/v1/nexus/tasks/{task_id}/run",
            params={"workspace_id": ws},
            headers=_h(me["token"]),
        )
        assert rerun.status_code == 200, rerun.text
        assert rerun.json()["data"]["status"] == "AWAITING_APPROVAL"
        assert await _latest_world_version(maker, ws, wid) == 1
        assert await _adjust_events(maker, ws, wid) == []

        # Human approval → governed write → outcome.
        decided = await client.post(
            f"/api/v1/nexus/tasks/{task_id}/approvals",
            json={"workspace_id": ws, "approved": True, "reason": "reviewed"},
            headers=_h(me["token"]),
        )
        assert decided.status_code == 200, decided.text
        assert decided.json()["data"]["status"] == "COMPLETED"

        assert await _latest_world_version(maker, ws, wid) == 2
        events = await _adjust_events(maker, ws, wid)
        assert len(events) == 1
        assert events[0].idempotency_key.startswith(f"task:{task_id}:capability:")

        # Trace: both sides of the approval boundary + the durable outcome.
        trace_resp = await client.get(
            f"/api/v1/nexus/tasks/{task_id}/trace",
            params={"workspace_id": ws},
            headers=_h(me["token"]),
        )
        assert trace_resp.status_code == 200, trace_resp.text
        trace = trace_resp.json()["data"]["trace"]
        assert trace["status"] == "COMPLETED"
        assert trace["execution"]["status"] == "SUCCEEDED"
        assert trace["outcome"] is not None
        adjust_invocations = [
            record
            for record in trace["invocations"]
            if record["capability_id"] == "world.inventory.adjust"
        ]
        assert len(adjust_invocations) == 2
        assert adjust_invocations[0]["status"] == "BLOCKED"
        assert adjust_invocations[0]["error"] == "APPROVAL_REQUIRED"
        assert adjust_invocations[1]["status"] == "SUCCESS"
        assert (
            adjust_invocations[1]["arguments_sha256"] == adjust_invocations[0]["arguments_sha256"]
        )

        # The approval trail pins the authenticated approver's identity.
        approvals = {record["decision"]: record for record in trace["approvals"]}
        assert approvals["APPROVED"]["approver_id"] == me["user_id"]

        # Post-terminal run is a durable no-op (no new version, no new event).
        after = await client.post(
            f"/api/v1/nexus/tasks/{task_id}/run",
            params={"workspace_id": ws},
            headers=_h(me["token"]),
        )
        assert after.status_code == 200
        assert after.json()["data"]["status"] == "COMPLETED"
        assert await _latest_world_version(maker, ws, wid) == 2
        assert len(await _adjust_events(maker, ws, wid)) == 1

    async def test_low_risk_read_only_task_completes_without_approval(self, api_client) -> None:
        client, maker = api_client
        me = await _identity(maker)
        ws = me["workspace_id"]
        wid = _world_id()
        await init_world(maker, ws, wid)

        created = await client.post(
            "/api/v1/nexus/tasks",
            json=_submit_body(
                ws,
                wid,
                risk_class="MEDIUM",
                required_capabilities=["world.inventory.read"],
                step_arguments={"world.inventory.read": {"world_id": wid}},
            ),
            headers=_h(me["token"]),
        )
        assert created.status_code == 201, created.text
        data = created.json()["data"]
        assert data["status"] == "COMPLETED"
        assert data["requires_approval"] is False

        # Reads served real World State values through the durable trace.
        trace_resp = await client.get(
            f"/api/v1/nexus/tasks/{data['task_id']}/trace",
            params={"workspace_id": ws},
            headers=_h(me["token"]),
        )
        trace = trace_resp.json()["data"]["trace"]
        invocation = trace["invocations"][0]
        assert invocation["capability_id"] == "world.inventory.read"
        assert invocation["status"] == "SUCCESS"
        assert invocation["world_state_version"] == 1
        assert trace["steps"][0]["evidence_refs"] == [f"world-state:{wid}:v1:{INVENTORY_VAR}"]
        assert await _latest_world_version(maker, ws, wid) == 1

    async def test_rejection_records_reason_and_never_writes(self, api_client) -> None:
        client, maker = api_client
        me = await _identity(maker)
        ws = me["workspace_id"]
        wid = _world_id()
        await init_world(maker, ws, wid)

        created = await client.post(
            "/api/v1/nexus/tasks", json=_submit_body(ws, wid), headers=_h(me["token"])
        )
        task_id = created.json()["data"]["task_id"]

        decided = await client.post(
            f"/api/v1/nexus/tasks/{task_id}/approvals",
            json={"workspace_id": ws, "approved": False, "reason": "too risky"},
            headers=_h(me["token"]),
        )
        assert decided.status_code == 200, decided.text
        assert decided.json()["data"]["status"] == "REJECTED"

        assert await _latest_world_version(maker, ws, wid) == 1
        assert await _adjust_events(maker, ws, wid) == []

        trace_resp = await client.get(
            f"/api/v1/nexus/tasks/{task_id}/trace",
            params={"workspace_id": ws},
            headers=_h(me["token"]),
        )
        trace = trace_resp.json()["data"]["trace"]
        assert trace["status"] == "REJECTED"
        approvals = {record["decision"]: record for record in trace["approvals"]}
        assert approvals["REJECTED"]["reason"] == "too risky"
        assert approvals["REJECTED"]["approver_id"] == me["user_id"]


# ─────────────────────────────────────────────────────────────────────
# Fail-closed + isolation on real PostgreSQL
# ─────────────────────────────────────────────────────────────────────


class TestFailClosedOnPostgres:
    async def test_unknown_capability_fails_closed_with_explicit_block(self, api_client) -> None:
        client, maker = api_client
        me = await _identity(maker)
        ws = me["workspace_id"]
        wid = _world_id()
        await init_world(maker, ws, wid)

        created = await client.post(
            "/api/v1/nexus/tasks",
            json=_submit_body(ws, wid, required_capabilities=["world.nonsense.read"]),
            headers=_h(me["token"]),
        )
        assert created.status_code == 201, created.text
        assert created.json()["data"]["status"] == "BLOCKED"
        task_id = created.json()["data"]["task_id"]

        got = await client.get(
            f"/api/v1/nexus/tasks/{task_id}",
            params={"workspace_id": ws},
            headers=_h(me["token"]),
        )
        assert "world.nonsense.read" in (got.json()["data"]["task"]["blocked_reason"] or "")

        trace_resp = await client.get(
            f"/api/v1/nexus/tasks/{task_id}/trace",
            params={"workspace_id": ws},
            headers=_h(me["token"]),
        )
        assert trace_resp.json()["data"]["trace"]["invocations"] == []
        assert await _latest_world_version(maker, ws, wid) == 1


class TestIsolationOnPostgres:
    async def test_tenant_b_cannot_touch_tenant_a_task(self, api_client) -> None:
        client, maker = api_client
        a = await _identity(maker)
        b = await _identity(maker)
        wid_a = _world_id()
        await init_world(maker, a["workspace_id"], wid_a)

        created = await client.post(
            "/api/v1/nexus/tasks",
            json=_submit_body(a["workspace_id"], wid_a),
            headers=_h(a["token"]),
        )
        assert created.status_code == 201, created.text
        task_id = created.json()["data"]["task_id"]

        # B in A's workspace: 403 (workspace gate) — every endpoint.
        assert (
            await client.get(
                f"/api/v1/nexus/tasks/{task_id}",
                params={"workspace_id": a["workspace_id"]},
                headers=_h(b["token"]),
            )
        ).status_code == 403
        assert (
            await client.post(
                f"/api/v1/nexus/tasks/{task_id}/run",
                params={"workspace_id": a["workspace_id"]},
                headers=_h(b["token"]),
            )
        ).status_code == 403
        assert (
            await client.post(
                f"/api/v1/nexus/tasks/{task_id}/approvals",
                json={"workspace_id": a["workspace_id"], "approved": True},
                headers=_h(b["token"]),
            )
        ).status_code == 403
        assert (
            await client.get(
                f"/api/v1/nexus/tasks/{task_id}/trace",
                params={"workspace_id": a["workspace_id"]},
                headers=_h(b["token"]),
            )
        ).status_code == 403
        assert (
            await client.get(
                f"/api/v1/nexus/tasks/{task_id}/decision-room",
                params={"workspace_id": a["workspace_id"]},
                headers=_h(b["token"]),
            )
        ).status_code == 403
        assert (
            await client.post(
                "/api/v1/nexus/tasks",
                json=_submit_body(a["workspace_id"], wid_a),
                headers=_h(b["token"]),
            )
        ).status_code == 403

        # B in B's workspace for A's task id: 404 (no existence oracle).
        assert (
            await client.get(
                f"/api/v1/nexus/tasks/{task_id}",
                params={"workspace_id": b["workspace_id"]},
                headers=_h(b["token"]),
            )
        ).status_code == 404
        assert (
            await client.post(
                f"/api/v1/nexus/tasks/{task_id}/run",
                params={"workspace_id": b["workspace_id"]},
                headers=_h(b["token"]),
            )
        ).status_code == 404

        # A's task is untouched: still awaiting approval, world unchanged.
        assert await _latest_world_version(maker, a["workspace_id"], wid_a) == 1

    async def test_viewer_cannot_create_run_or_approve(self, api_client) -> None:
        client, maker = api_client
        viewer = await _identity(maker, "viewer")
        ws = viewer["workspace_id"]
        wid = _world_id()
        await init_world(maker, ws, wid)

        assert (
            await client.post(
                "/api/v1/nexus/tasks", json=_submit_body(ws, wid), headers=_h(viewer["token"])
            )
        ).status_code == 403
        assert (
            await client.post(
                "/api/v1/nexus/tasks/some-task/run",
                params={"workspace_id": ws},
                headers=_h(viewer["token"]),
            )
        ).status_code == 403
        assert (
            await client.post(
                "/api/v1/nexus/tasks/some-task/approvals",
                json={"workspace_id": ws, "approved": True},
                headers=_h(viewer["token"]),
            )
        ).status_code == 403
