"""Billing gate acceptance — server-side subscription/entitlement enforcement.

Covers the billing/entitlements launch blocker:

    active subscription        → ALLOW
    expired subscription       → DENY  (402)
    quota exhausted            → DENY  (429)
    unentitled capability      → DENY  (403)
    unprovisioned workspace    → DENY  (403)
    concurrent creation race   → deterministic (org-row serialization)

Requires real PostgreSQL (core + nexus_* + world_* tables); skips when
unavailable. AuthN is exercised through REAL JWTs (minted by the same
``issue_token`` the login path uses); tests run with CORTEX_ENV=pilot so
``get_current_user`` takes the strict JWT path.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import UTC, datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import MetaData, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateSchema

import app.modules.orchestration.task_runtime_models as _task_models  # noqa: F401
import app.modules.world.state_repository as _world_models  # noqa: F401
from app.api.v1 import nexus_persistent
from app.common.ids import uuid7_uuid
from app.config import get_settings
from app.infrastructure.database import Base
from app.modules.billing import PLAN_CONCURRENT_TASK_LIMITS
from app.modules.identity.jwt_auth import issue_token
from app.modules.orchestration.task_runtime_models import TaskDB
from app.modules.world.state_repository import StateRepository
from app.modules.world.world_models import StateVariable, StateVariableType
from app.modules.world.world_service import WorldStateService

JWT_SECRET = "test-secret-0123456789abcdef0123456789"


# World ids are globally unique per (world_id, version) on the
# migration-created schema — each test provisions its own world.
def _world_id() -> str:
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
    """Real-PostgreSQL engine with core + nexus_* + world_* tables created."""
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
        or t.name in ("organizations", "workspaces", "users")
    ]
    if not tables:
        pytest.skip("nexus/world tables not registered on Base.metadata")
    async with engine.begin() as conn:
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


async def _identity(
    maker, *, plan: str = "trial", trial_days: int | None = 7, role: str = "admin"
) -> dict[str, str]:
    """Provision an organization + workspace with a specific plan state and
    mint a REAL JWT. ``trial_days=None`` means a never-expiring trial."""
    from app.modules.access.models import Organization, Workspace

    user_id = uuid7_uuid()
    workspace_id = uuid7_uuid()
    org_id = uuid7_uuid()
    slug = f"billing-{uuid.uuid4().hex[:8]}"
    now = datetime.now(UTC)
    trial_ends_at = now + timedelta(days=trial_days) if trial_days is not None else None
    async with maker() as session:
        session.add(
            Organization(
                id=org_id,
                name=f"Billing Org {slug}",
                slug=slug,
                plan=plan,
                trial_ends_at=trial_ends_at,
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()
        session.add(
            Workspace(
                id=workspace_id,
                organization_id=org_id,
                name=f"Billing WS {slug}",
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
        email=f"billing-{uuid.uuid4().hex[:8]}@example.com",
    )
    return {
        "token": token,
        "user_id": str(user_id),
        "workspace_id": str(workspace_id),
        "org_id": str(org_id),
    }


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _read_only_body(workspace_id: str, world_id: str) -> dict:
    return {
        "workspace_id": workspace_id,
        "objective": "Assess inventory exposure for SKU comp_042.",
        "world_state_version": 1,
        "risk_class": "MEDIUM",
        "required_capabilities": ["world.inventory.read"],
        "step_arguments": {"world.inventory.read": {"world_id": world_id}},
    }


def _consequential_body(workspace_id: str, world_id: str) -> dict:
    return {
        "workspace_id": workspace_id,
        "objective": "Adjust stock for SKU comp_042 after the supply disruption.",
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
    }


async def init_world(maker, workspace_id: str, world_id: str, *, inventory_qty: int = 500) -> None:
    """Ingest inventory data through the sole World State write path."""
    async with maker() as session:
        service = WorldStateService(repository=StateRepository(db=session))
        await service.initialize_world(
            workspace_id=workspace_id,
            world_id=world_id,
            initial_variables={
                "inventory.warehouse.comp_042.wh_001": StateVariable.from_raw_value(
                    "inventory.warehouse.comp_042.wh_001",
                    StateVariableType.INVENTORY,
                    "comp_042",
                    "warehouse",
                    inventory_qty,
                    unit="units",
                ),
            },
        )


async def _seed_active_tasks(maker, workspace_id: str, count: int) -> None:
    """Seed durable tasks in a non-terminal state (they count against the
    concurrent-task quota)."""
    async with maker() as session:
        for i in range(count):
            session.add(
                TaskDB(
                    tenant_id="billing-seed",
                    workspace_id=workspace_id,
                    actor_id="billing-seed",
                    trace_id=str(uuid7_uuid()),
                    status="RUNNING",
                    objective=f"Seeded active task {i}",
                    world_state_version=1,
                    requires_approval=False,
                    policy_context={},
                )
            )
        await session.commit()


# ─────────────────────────────────────────────────────────────────────
# Positive: active subscription → ALLOW
# ─────────────────────────────────────────────────────────────────────


class TestAllowed:
    async def test_active_trial_allows_golden_path(self, api_client) -> None:
        client, maker = api_client
        me = await _identity(maker)  # live trial (7 days out)
        wid = _world_id()
        await init_world(maker, me["workspace_id"], wid)

        created = await client.post(
            "/api/v1/nexus/tasks",
            json=_read_only_body(me["workspace_id"], wid),
            headers=_h(me["token"]),
        )
        assert created.status_code == 201, created.text
        assert created.json()["data"]["status"] == "COMPLETED"

    async def test_paid_plan_allows_consequential_capabilities(self, api_client) -> None:
        client, maker = api_client
        me = await _identity(maker, plan="pro", trial_days=None)
        wid = _world_id()
        await init_world(maker, me["workspace_id"], wid)

        created = await client.post(
            "/api/v1/nexus/tasks",
            json=_consequential_body(me["workspace_id"], wid),
            headers=_h(me["token"]),
        )
        assert created.status_code == 201, created.text
        assert created.json()["data"]["status"] == "AWAITING_APPROVAL"


# ─────────────────────────────────────────────────────────────────────
# Denial: expired subscription → 402
# ─────────────────────────────────────────────────────────────────────


class TestExpiredSubscription:
    async def test_expired_trial_denies_task_creation_402(self, api_client) -> None:
        client, maker = api_client
        me = await _identity(maker, trial_days=-1)  # expired yesterday
        wid = _world_id()

        resp = await client.post(
            "/api/v1/nexus/tasks",
            json=_read_only_body(me["workspace_id"], wid),
            headers=_h(me["token"]),
        )
        assert resp.status_code == 402, resp.text

    async def test_expired_trial_denies_run_and_approvals_402(self, api_client) -> None:
        client, maker = api_client
        me = await _identity(maker)  # live trial at creation
        wid = _world_id()
        await init_world(maker, me["workspace_id"], wid)
        created = await client.post(
            "/api/v1/nexus/tasks",
            json=_consequential_body(me["workspace_id"], wid),
            headers=_h(me["token"]),
        )
        assert created.status_code == 201, created.text
        task_id = created.json()["data"]["task_id"]

        # Expire the subscription before any expensive/consequential work.
        from sqlalchemy import update

        from app.modules.access.models import Organization

        async with maker() as session:
            await session.execute(
                update(Organization)
                .where(Organization.id == uuid.UUID(me["org_id"]))
                .values(trial_ends_at=datetime.now(UTC) - timedelta(days=1))
            )
            await session.commit()

        run_resp = await client.post(
            f"/api/v1/nexus/tasks/{task_id}/run",
            params={"workspace_id": me["workspace_id"]},
            headers=_h(me["token"]),
        )
        assert run_resp.status_code == 402, run_resp.text

        approval_resp = await client.post(
            f"/api/v1/nexus/tasks/{task_id}/approvals",
            json={"workspace_id": me["workspace_id"], "approved": True},
            headers=_h(me["token"]),
        )
        assert approval_resp.status_code == 402, approval_resp.text

        # The durable approval row was never written: no governed write.
        trace = await client.get(
            f"/api/v1/nexus/tasks/{task_id}/trace",
            params={"workspace_id": me["workspace_id"]},
            headers=_h(me["token"]),
        )
        view = trace.json()["data"]["trace"]
        assert all(record["decision"] != "APPROVED" for record in view["approvals"])


# ─────────────────────────────────────────────────────────────────────
# Denial: unprovisioned workspace → 403
# ─────────────────────────────────────────────────────────────────────


class TestUnprovisioned:
    async def test_workspace_without_organization_denies_403(self, api_client) -> None:
        client, _ = api_client
        user_id = uuid7_uuid()
        workspace_id = uuid7_uuid()
        token, _ = issue_token(
            user_id=user_id,
            workspace_id=workspace_id,
            role="admin",
            email=f"unprovisioned-{uuid.uuid4().hex[:8]}@example.com",
        )

        resp = await client.post(
            "/api/v1/nexus/tasks",
            json=_read_only_body(str(workspace_id), "wh-unprovisioned"),
            headers=_h(token),
        )
        assert resp.status_code == 403, resp.text
        assert "provisioned" in resp.json()["detail"].lower()


# ─────────────────────────────────────────────────────────────────────
# Denial: unentitled capability → 403
# ─────────────────────────────────────────────────────────────────────


class TestCapabilityEntitlement:
    async def test_free_plan_cannot_require_consequential_capability(self, api_client) -> None:
        client, maker = api_client
        me = await _identity(maker, plan="free", trial_days=None)
        wid = _world_id()

        denied = await client.post(
            "/api/v1/nexus/tasks",
            json=_consequential_body(me["workspace_id"], wid),
            headers=_h(me["token"]),
        )
        assert denied.status_code == 403, denied.text
        assert "world.inventory.adjust" in denied.json()["detail"]

        # Reads stay entitled on the free plan (positive control).
        allowed = await client.post(
            "/api/v1/nexus/tasks",
            json=_read_only_body(me["workspace_id"], wid),
            headers=_h(me["token"]),
        )
        assert allowed.status_code == 201, allowed.text


# ─────────────────────────────────────────────────────────────────────
# Quota exhaustion → 429
# ─────────────────────────────────────────────────────────────────────


class TestQuota:
    async def test_concurrent_task_limit_exhaustion_denies_429(self, api_client) -> None:
        client, maker = api_client
        me = await _identity(maker)  # trial: 25 concurrent tasks
        wid = _world_id()
        limit = PLAN_CONCURRENT_TASK_LIMITS["trial"]

        await _seed_active_tasks(maker, me["workspace_id"], limit)
        denied = await client.post(
            "/api/v1/nexus/tasks",
            json=_read_only_body(me["workspace_id"], wid),
            headers=_h(me["token"]),
        )
        assert denied.status_code == 429, denied.text
        assert str(limit) in denied.json()["detail"]

        # Freeing one slot allows creation again.
        from sqlalchemy import update

        async with maker() as session:
            await session.execute(
                update(TaskDB)
                .where(TaskDB.workspace_id == me["workspace_id"])
                .values(status="COMPLETED")
            )
            await session.commit()
        allowed = await client.post(
            "/api/v1/nexus/tasks",
            json=_read_only_body(me["workspace_id"], wid),
            headers=_h(me["token"]),
        )
        assert allowed.status_code == 201, allowed.text

    async def test_concurrent_creation_race_is_deterministic(self, api_client, monkeypatch) -> None:
        """Simultaneous creations serialize on the organization row: the
        quota boundary is crossed exactly once, never by a race."""
        client, maker = api_client
        monkeypatch.setitem(PLAN_CONCURRENT_TASK_LIMITS, "trial", 3)
        me = await _identity(maker)
        wid = _world_id()
        # The world must exist so each task reaches AWAITING_APPROVAL
        # (non-terminal) rather than failing early and freeing its slot.
        await init_world(maker, me["workspace_id"], wid)

        # Six simultaneous HIGH-risk tasks; each reaches AWAITING_APPROVAL
        # (non-terminal, so every committed creation counts against the
        # quota for the ones that follow).
        responses = await asyncio.gather(
            *[
                client.post(
                    "/api/v1/nexus/tasks",
                    json=_consequential_body(me["workspace_id"], wid),
                    headers=_h(me["token"]),
                )
                for _ in range(6)
            ]
        )
        statuses = [resp.status_code for resp in responses]
        assert statuses.count(201) == 3, statuses
        assert statuses.count(429) == 3, statuses

        # Exactly three durable tasks exist, all awaiting approval.
        async with maker() as session:
            rows = (
                (
                    await session.execute(
                        select(TaskDB).where(TaskDB.workspace_id == me["workspace_id"])
                    )
                )
                .scalars()
                .all()
            )
        assert len(rows) == 3
        assert all(row.status == "AWAITING_APPROVAL" for row in rows)
