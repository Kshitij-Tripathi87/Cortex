"""Tests for World State REST APIs — Program J Milestone J.2.8.

Covers:
1. POST /api/v1/world/state — genesis initialization
2. GET /api/v1/world/state — current state query
3. POST /api/v1/world/event — domain event submission
4. GET /api/v1/world/history — lineage versions query
5. GET /api/v1/world/diff — semantic diff comparison
6. POST /api/v1/world/replay — time-travel reconstruction
7. POST /api/v1/world/rollback — append-only state rollback
8. POST /api/v1/world/validate — invariant rules engine validation
9. Workspace security and multi-tenant access control
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1.world import router as world_router
from app.common.ids import uuid7
from app.infrastructure.database import get_db
from app.infrastructure.security import AuthContext, get_current_user


@pytest.fixture
def auth_user() -> AuthContext:
    return AuthContext(
        user_id="user_test_01",
        email="operator@cortex.internal",
        roles=["operator"],
        workspace_ids=[],
        is_anonymous=False,
    )


@pytest.fixture
async def client(db_session, auth_user: AuthContext) -> AsyncClient:
    test_app = FastAPI()
    test_app.include_router(world_router, prefix="/api/v1")

    async def _override_get_db():
        yield db_session

    async def _override_get_user():
        return auth_user

    test_app.dependency_overrides[get_db] = _override_get_db
    test_app.dependency_overrides[get_current_user] = _override_get_user

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestWorldStateEndpoints:
    async def test_full_world_api_lifecycle(self, client: AsyncClient) -> None:
        workspace_id = f"ws_{uuid7()}"
        world_id = f"world_{uuid7()}"

        # 1. Initialize genesis state
        init_res = await client.post(
            "/api/v1/world/state",
            json={
                "workspace_id": workspace_id,
                "world_id": world_id,
                "graph_version": 1,
                "initial_variables": {},
                "metadata": {"env": "test"},
            },
        )
        assert init_res.status_code == 201, init_res.text
        init_data = init_res.json()
        assert init_data["version"] == 1
        assert init_data["world_id"] == world_id

        # 2. Get current state
        get_res = await client.get(
            f"/api/v1/world/state?workspace_id={workspace_id}&world_id={world_id}"
        )
        assert get_res.status_code == 200
        get_data = get_res.json()
        assert get_data["version"] == 1

        # 3. Submit an event (InventoryChanged)
        event_res1 = await client.post(
            "/api/v1/world/event",
            json={
                "workspace_id": workspace_id,
                "world_id": world_id,
                "entity_type": "warehouse",
                "entity_id": "wh_1",
                "event_type": "inventory_changed",
                "payload": {
                    "warehouse_id": "wh_1",
                    "component_id": "comp_1",
                    "quantity_change": 500,
                },
                "idempotency_key": "api_key_1",
            },
        )
        assert event_res1.status_code == 201, event_res1.text
        e1_data = event_res1.json()
        assert e1_data["version"] == 2
        assert e1_data["is_duplicate"] is False
        assert e1_data["state"]["version"] == 2

        # 4. Duplicate event submission (Idempotency test)
        dup_res = await client.post(
            "/api/v1/world/event",
            json={
                "workspace_id": workspace_id,
                "world_id": world_id,
                "entity_type": "warehouse",
                "entity_id": "wh_1",
                "event_type": "inventory_changed",
                "payload": {
                    "warehouse_id": "wh_1",
                    "component_id": "comp_1",
                    "quantity_change": 500,
                },
                "idempotency_key": "api_key_1",
            },
        )
        assert dup_res.status_code == 201
        dup_data = dup_res.json()
        assert dup_data["is_duplicate"] is True
        assert dup_data["version"] == 2

        # 5. Submit second event (SupplierDelayed)
        event_res2 = await client.post(
            "/api/v1/world/event",
            json={
                "workspace_id": workspace_id,
                "world_id": world_id,
                "entity_type": "supplier",
                "entity_id": "sup_1",
                "event_type": "supplier_delayed",
                "payload": {
                    "delay_days": 14,
                    "disruption_type": "strike",
                },
            },
        )
        assert event_res2.status_code == 201
        assert event_res2.json()["version"] == 3

        # 6. Get history
        hist_res = await client.get(
            f"/api/v1/world/history?workspace_id={workspace_id}&world_id={world_id}"
        )
        assert hist_res.status_code == 200
        hist_data = hist_res.json()
        assert hist_data["version_count"] == 3
        assert [v["version"] for v in hist_data["versions"]] == [3, 2, 1]

        # 7. Get state diff
        diff_res = await client.get(
            f"/api/v1/world/diff?workspace_id={workspace_id}&world_id={world_id}&from_version=1&to_version=3"
        )
        assert diff_res.status_code == 200
        diff_data = diff_res.json()
        assert diff_data["from_version"] == 1
        assert diff_data["to_version"] == 3
        assert len(diff_data["variables_added"]) == 2

        # 8. Replay / Time-travel to version 2
        replay_res = await client.post(
            "/api/v1/world/replay",
            json={
                "workspace_id": workspace_id,
                "world_id": world_id,
                "target_version": 2,
            },
        )
        assert replay_res.status_code == 200
        rep_data = replay_res.json()
        assert rep_data["version"] == 2

        # 9. Rollback to version 2
        rollback_res = await client.post(
            "/api/v1/world/rollback",
            json={
                "workspace_id": workspace_id,
                "world_id": world_id,
                "target_version": 2,
                "reason": "Reverting supplier delay",
            },
        )
        assert rollback_res.status_code == 200
        rb_data = rollback_res.json()
        assert rb_data["new_version"] == 4
        assert rb_data["rolled_back_to_version"] == 2
        assert rb_data["events_appended"] == 1

        # 10. Validate state
        val_res = await client.post(
            "/api/v1/world/validate",
            json={
                "workspace_id": workspace_id,
                "world_id": world_id,
            },
        )
        assert val_res.status_code == 200
        val_data = val_res.json()
        assert val_data["is_valid"] is True
        assert val_data["rules_checked"] >= 14

    async def test_cross_workspace_isolation_denied(self, db_session) -> None:
        """User restricted to ws_tenant_a cannot access ws_tenant_b."""
        restricted_user = AuthContext(
            user_id="user_tenant_a",
            roles=["operator"],
            workspace_ids=["ws_tenant_a"],
        )

        test_app = FastAPI()
        test_app.include_router(world_router, prefix="/api/v1")

        async def _override_get_db():
            yield db_session

        async def _override_get_user():
            return restricted_user

        test_app.dependency_overrides[get_db] = _override_get_db
        test_app.dependency_overrides[get_current_user] = _override_get_user

        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            res = await c.get("/api/v1/world/state?workspace_id=ws_tenant_b&world_id=world_b")
            assert res.status_code == 403
            err = res.json()
            assert err["detail"]["error"] == "forbidden"

    async def test_invalid_event_type_rejected(self, client: AsyncClient) -> None:
        """Invalid event_type returns 400 Bad Request."""
        res = await client.post(
            "/api/v1/world/event",
            json={
                "workspace_id": "ws_test_api",
                "world_id": "world_test",
                "entity_type": "supplier",
                "entity_id": "sup_1",
                "event_type": "unknown_invalid_event",
                "payload": {},
            },
        )
        assert res.status_code == 400
        assert "Unsupported event_type" in res.json()["detail"]
