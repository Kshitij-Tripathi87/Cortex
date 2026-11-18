"""Bad or foreign input is refused with a clear answer, never a server error.

Regressions fixed together:

* ``/execution/*``: a plan sent back by the caller was read with unchecked
  ``plan["action"]``-style lookups in five handlers. Any missing or wrong
  field raised inside the handler and surfaced as a 500.
* ``/ingest``: the workspace was passed to the access check as a ``UUID``
  object. The caller's workspaces are strings, so the check never matched:
  every signed-in upload was refused, and the refusal could not be written
  as JSON, so the caller saw a 500.
* ``/mobile/push/register``, ``/mobile/sessions``, ``/voice/token`` and
  ``/voice/sessions`` accepted any device id, including one registered to
  another user.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.devices import router as devices_router
from app.api.v1.execution import _plan_from_body
from app.api.v1.execution import router as execution_router
from app.api.v1.ingestion import _user_uuid
from app.api.v1.mobile import router as mobile_router
from app.api.v1.voice import router as voice_router
from app.infrastructure.database import get_db
from app.infrastructure.security import AuthContext, get_current_user, require_workspace_access

WORKSPACE = "ws-hardening"
WORLD = "world-hardening"


def _plan(**changes: Any) -> dict[str, Any]:
    """A plan exactly as POST /execution/plan returns it."""
    plan: dict[str, Any] = {
        "plan_id": "plan_1",
        "workspace_id": WORKSPACE,
        "world_id": WORLD,
        "objective": "Compress lead time by 3 days",
        "action": {
            "action_type": "expedite_supplier",
            "entity_id": "sup_1",
            "quantity": 3.0,
            "target_entity_id": None,
            "cost_usd": 4500.0,
            "rationale": "",
            "metadata": {},
        },
        "target_system": "erp",
        "expected_cost_usd": 4500.0,
        "expected_benefit_usd": 30000.0,
        "expected_risk_score": 0.2,
        "affected_entities": ["sup_1"],
        "prerequisites": [],
        "policy_version": "v1",
        "simulation_id": None,
        "status": "approved",
        "violations": [],
        "created_at": "2026-11-18T00:00:00+00:00",
    }
    plan.update(changes)
    return plan


def _without(plan: dict[str, Any], key: str) -> dict[str, Any]:
    return {k: v for k, v in plan.items() if k != key}


# ─────────────────────────────────────────────────────────────────────────────
# /execution/*: the plan a caller sends back
# ─────────────────────────────────────────────────────────────────────────────


class TestPlanBody:
    def test_a_plan_as_issued_round_trips(self) -> None:
        plan = _plan_from_body(_plan(), workspace_id=WORKSPACE, world_id=WORLD)

        assert plan.plan_id == "plan_1"
        assert plan.action.action_type.value == "expedite_supplier"
        assert plan.target_system.value == "erp"
        assert plan.status.value == "approved"
        # It serialises again without loss of the fields that matter.
        assert plan.to_dict()["action"]["cost_usd"] == 4500.0

    @pytest.mark.parametrize(
        "body",
        [
            {},
            {"plan_id": "only-an-id"},
            _without(_plan(), "action"),
            _without(_plan(), "status"),
            _without(_plan(), "workspace_id"),
            _plan(action="not-an-object"),
            _plan(action={}),
            _plan(action={"action_type": "launch_missiles", "entity_id": "x"}),
            _plan(action={"action_type": "expedite_supplier"}),
            _plan(status="definitely_approved"),
            _plan(target_system="mainframe"),
            _plan(expected_cost_usd="a lot"),
            _plan(affected_entities="sup_1"),
            _plan(plan_id=""),
            _plan(plan_id=None),
        ],
    )
    def test_a_malformed_plan_is_a_422_that_names_the_field(self, body: dict[str, Any]) -> None:
        with pytest.raises(HTTPException) as refused:
            _plan_from_body(body, workspace_id=WORKSPACE, world_id=WORLD)

        assert refused.value.status_code == 422
        detail = refused.value.detail
        assert isinstance(detail, list) and detail
        assert all(error["loc"][:2] == ["body", "plan"] for error in detail)
        # The answer must be writable as JSON (it is what the caller receives).
        json.dumps(detail)

    def test_a_plan_for_another_workspace_or_world_is_refused(self) -> None:
        with pytest.raises(HTTPException) as other_workspace:
            _plan_from_body(_plan(workspace_id="ws-someone-else"), workspace_id=WORKSPACE)
        assert other_workspace.value.status_code == 422
        assert "different workspace" in str(other_workspace.value.detail)

        with pytest.raises(HTTPException) as other_world:
            _plan_from_body(_plan(world_id="world-x"), workspace_id=WORKSPACE, world_id=WORLD)
        assert other_world.value.status_code == 422
        assert "different world" in str(other_world.value.detail)


@pytest.fixture
async def execution_client() -> AsyncIterator[AsyncClient]:
    app = FastAPI()
    app.include_router(execution_router, prefix="/api/v1/execution")

    async def _user() -> AuthContext:
        return AuthContext(user_id="operator_01", roles=["operator"], workspace_ids=[WORKSPACE])

    app.dependency_overrides[get_current_user] = _user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


class TestExecutionRoutes:
    @pytest.mark.parametrize(
        ("path", "extra"),
        [
            ("/api/v1/execution/decide", {"world_id": WORLD, "decision": "approve"}),
            ("/api/v1/execution/dispatch", {}),
            ("/api/v1/execution/close-loop", {"world_id": WORLD, "operator_decision": "approve"}),
        ],
    )
    @pytest.mark.parametrize(
        "plan",
        [{}, {"plan_id": "p"}, _plan(action=None), _plan(status="nope")],
        ids=["empty", "id-only", "no-action", "bad-status"],
    )
    async def test_a_malformed_plan_answers_422_not_500(
        self, execution_client: AsyncClient, path: str, extra: dict[str, Any], plan: dict[str, Any]
    ) -> None:
        answer = await execution_client.post(
            path, json={"workspace_id": WORKSPACE, "plan": plan, **extra}
        )

        assert answer.status_code == 422, answer.text
        assert answer.json()["detail"][0]["loc"][:2] == ["body", "plan"]

    async def test_a_well_formed_plan_is_still_dispatched(
        self, execution_client: AsyncClient
    ) -> None:
        answer = await execution_client.post(
            "/api/v1/execution/dispatch", json={"workspace_id": WORKSPACE, "plan": _plan()}
        )

        assert answer.status_code == 200, answer.text
        assert answer.json()["success"] is True

    async def test_a_plan_from_another_workspace_is_not_run_under_this_one(
        self, execution_client: AsyncClient
    ) -> None:
        answer = await execution_client.post(
            "/api/v1/execution/dispatch",
            json={"workspace_id": WORKSPACE, "plan": _plan(workspace_id="ws-someone-else")},
        )

        assert answer.status_code == 422
        assert "different workspace" in answer.json()["detail"]

    async def test_the_workspace_check_still_comes_first(
        self, execution_client: AsyncClient
    ) -> None:
        answer = await execution_client.post(
            "/api/v1/execution/dispatch",
            json={"workspace_id": "ws-someone-else", "plan": _plan(workspace_id="ws-someone-else")},
        )

        assert answer.status_code == 403


# ─────────────────────────────────────────────────────────────────────────────
# Workspace check accepts a UUID object
# ─────────────────────────────────────────────────────────────────────────────


class TestWorkspaceAccessWithUuid:
    def test_a_uuid_object_matches_the_callers_workspace(self) -> None:
        workspace = uuid4()
        member = AuthContext(user_id=str(uuid4()), workspace_ids=[str(workspace)])

        # Used to be refused: UUID(...) != "..." for every member.
        require_workspace_access(workspace, member)
        require_workspace_access(str(workspace), member)

    def test_a_refusal_can_be_written_as_json(self) -> None:
        member = AuthContext(user_id=str(uuid4()), workspace_ids=[str(uuid4())])

        with pytest.raises(HTTPException) as refused:
            require_workspace_access(uuid4(), member)

        assert refused.value.status_code == 403
        # Used to raise TypeError (a UUID object in the detail) -> HTTP 500.
        json.dumps(refused.value.detail)

    def test_no_workspace_is_not_found(self) -> None:
        member = AuthContext(user_id="u", workspace_ids=["ws"])
        for missing in (None, ""):
            with pytest.raises(HTTPException) as refused:
                require_workspace_access(missing, member)
            assert refused.value.status_code == 404

    def test_a_development_identity_without_a_uuid_uploads_without_a_user(self) -> None:
        real = uuid4()
        assert _user_uuid(AuthContext(user_id=str(real))) == real
        # Used to raise ValueError (-> 500) for the local development identity.
        assert _user_uuid(AuthContext(user_id="local-dev")) is None
        assert _user_uuid(AuthContext(user_id="anonymous", is_anonymous=True)) is None
        assert _user_uuid(AuthContext(user_id=None)) is None


# ─────────────────────────────────────────────────────────────────────────────
# Devices: push, voice and sessions only for the caller's own device
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
async def device_app(db_session: AsyncSession) -> FastAPI:
    app = FastAPI()
    for router in (devices_router, mobile_router, voice_router):
        app.include_router(router, prefix="/api/v1")

    async def _db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = _db
    return app


def _as(app: FastAPI, user_id: str, workspace_id: str = "ws-a") -> AsyncClient:
    """A client signed in as ``user_id`` (identity is fixed per request below)."""

    async def _user() -> AuthContext:
        return AuthContext(user_id=user_id, roles=["analyst"], workspace_ids=[workspace_id])

    app.dependency_overrides[get_current_user] = _user
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _register(app: FastAPI, user_id: str, device_id: str) -> None:
    async with _as(app, user_id) as client:
        created = await client.post(
            "/api/v1/devices",
            json={"device_id": device_id, "platform": "android", "capabilities": ["voice"]},
        )
    assert created.status_code == 201, created.text


class TestDeviceOwnership:
    async def test_push_voice_and_sessions_work_for_the_callers_own_device(
        self, device_app: FastAPI, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CORTEX_JWT_SECRET", "device-test-secret-0123456789abcdef0123456789")
        from app.config import get_settings

        get_settings.cache_clear()
        phone = f"phone-{uuid4().hex[:8]}"
        await _register(device_app, "alice", phone)

        async with _as(device_app, "alice") as alice:
            push = await alice.post(
                "/api/v1/mobile/push/register",
                json={"device_id": phone, "provider": "stub", "push_token": "tok-alice"},
            )
            token = await alice.post("/api/v1/voice/token", json={"device_id": phone})
            voice = await alice.post(
                "/api/v1/voice/sessions", json={"device_id": phone, "workspace_id": "ws-a"}
            )
            session = await alice.post(
                "/api/v1/mobile/sessions",
                json={"session_type": "voice"},
                headers={"X-Device-Id": phone},
            )
            no_device = await alice.post("/api/v1/mobile/sessions", json={"session_type": "user"})
        get_settings.cache_clear()

        assert push.status_code == 201, push.text
        assert token.status_code == 200, token.text
        assert token.json()["data"]["device_id"] == phone
        assert voice.status_code == 201, voice.text
        assert session.status_code == 201, session.text
        assert session.json()["data"]["device_id"] == phone
        # No device named: allowed, recorded with the placeholder.
        assert no_device.status_code == 201
        assert no_device.json()["data"]["device_id"] == "unknown"

    async def test_another_users_device_is_refused_everywhere(self, device_app: FastAPI) -> None:
        phone = f"phone-{uuid4().hex[:8]}"
        await _register(device_app, "alice", phone)

        async with _as(device_app, "mallory", workspace_id="ws-m") as mallory:
            answers = {
                "push": await mallory.post(
                    "/api/v1/mobile/push/register",
                    json={"device_id": phone, "provider": "stub", "push_token": "tok-mallory"},
                ),
                "voice token": await mallory.post("/api/v1/voice/token", json={"device_id": phone}),
                "voice session": await mallory.post(
                    "/api/v1/voice/sessions", json={"device_id": phone}
                ),
                "session": await mallory.post(
                    "/api/v1/mobile/sessions",
                    json={"session_type": "voice"},
                    headers={"X-Device-Id": phone},
                ),
            }
            unknown = await mallory.post(
                "/api/v1/voice/token", json={"device_id": "phone-that-does-not-exist"}
            )

        for name, answer in answers.items():
            assert answer.status_code == 404, f"{name}: {answer.status_code} {answer.text}"
            # Same answer as for a device that does not exist: ids cannot be probed.
            assert answer.json() == unknown.json(), name
            assert "token" not in answer.json()

    async def test_a_voice_session_cannot_name_a_foreign_workspace(
        self, device_app: FastAPI
    ) -> None:
        phone = f"phone-{uuid4().hex[:8]}"
        await _register(device_app, "alice", phone)

        async with _as(device_app, "alice", workspace_id="ws-a") as alice:
            foreign = await alice.post(
                "/api/v1/voice/sessions", json={"device_id": phone, "workspace_id": "ws-other"}
            )
            token = await alice.post(
                "/api/v1/voice/token", json={"device_id": phone, "workspace_id": "ws-other"}
            )

        assert foreign.status_code == 403
        assert token.status_code == 403
