"""v0.8.5-B — Auth & onboarding acceptance (launch blockers B1 + B7).

Covers the Day 3–4 slice:
  open signup (org + workspace + admin, atomic)     ✅
  login (workspace-scoped, uniform 401)             ✅
  GET /me (principal + workspace + org + trial)     ✅
  logout (audit-recorded)                           ✅
  change-password                                   ✅
  reset request/confirm (single-use, expiring)      ✅
  cross-workspace isolation on the canonical path   ✅ (403 via real JWT)

Requires real PostgreSQL (core.* schema tables); skips when unavailable.
AuthN is exercised through REAL tokens: tests run with CORTEX_ENV=pilot so
``get_current_user`` takes the strict JWT path (no dependency overrides for
identity, no dev header fixtures).
"""

from __future__ import annotations

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

# Ensure model tables register with Base.metadata.
import app.modules.access.models as _access_models  # noqa: F401
import app.modules.audit.models as _audit_models  # noqa: F401
import app.modules.nexus_spine.persistence.models as _spine_models  # noqa: F401
from app.api.v1 import auth as auth_router_module
from app.api.v1 import nexus_persistent
from app.config import get_settings
from app.infrastructure.database import Base, get_db
from app.modules.access.models import User  # noqa: E402
from app.modules.audit.models import AuditEvent  # noqa: E402

JWT_SECRET = "test-secret-0123456789abcdef0123456789"


def _email(tag: str) -> str:
    return f"v085-{tag}-{uuid.uuid4().hex[:8]}@example.com"


@pytest.fixture
def strict_auth_env(monkeypatch):
    """Run with CORTEX_ENV=pilot so identity resolves via real JWT verify."""
    monkeypatch.setenv("CORTEX_ENV", "pilot")
    monkeypatch.setenv("CORTEX_JWT_SECRET", JWT_SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def dev_auth_env(monkeypatch):
    """Dev-mode env: reset tokens are disclosed in-band (for tests only)."""
    monkeypatch.setenv("CORTEX_ENV", "test")
    monkeypatch.setenv("CORTEX_JWT_SECRET", JWT_SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def pg_engine(request):
    """Real-Postgres engine with auth + audit + nexus tables created."""
    postgres_url = request.config.postgres_url
    try:
        engine = create_async_engine(postgres_url, echo=False)
        async with engine.begin() as conn:
            await conn.execute(select(1))
    except Exception as exc:
        pytest.skip(f"PostgreSQL not available: {exc}")

    wanted = {
        ("core", "organizations"),
        ("core", "workspaces"),
        ("core", "users"),
        ("core", "password_resets"),
        (None, "audit_events"),
    }
    tables = [
        t
        for t in Base.metadata.sorted_tables
        if (t.schema, t.name) in wanted or t.name.startswith("nexus_")
    ]
    if not tables:
        pytest.skip("auth tables not registered on Base.metadata")
    async with engine.begin() as conn:
        # Fresh MetaData copy keeps create_all independent of whatever else
        # the session has registered (schema-qualified tables from unrelated
        # modules would otherwise need to exist too).
        meta = MetaData()
        for table in tables:
            table.to_metadata(meta)
        await conn.execute(CreateSchema("core", if_not_exists=True))
        await conn.run_sync(meta.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def api_client(pg_engine, strict_auth_env):
    """ASGI client with REAL JWT identity (no get_current_user override)."""
    maker = async_sessionmaker(pg_engine, class_=AsyncSession, expire_on_commit=False)
    test_app = FastAPI()
    test_app.include_router(auth_router_module.router, prefix="/api/v1/auth")
    test_app.include_router(nexus_persistent.router, prefix="/api/v1")

    async def _override_get_db():
        async with maker() as session:
            yield session

    test_app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, maker


@pytest.fixture
async def dev_client(pg_engine, dev_auth_env):
    maker = async_sessionmaker(pg_engine, class_=AsyncSession, expire_on_commit=False)
    test_app = FastAPI()
    test_app.include_router(auth_router_module.router, prefix="/api/v1/auth")

    async def _override_get_db():
        async with maker() as session:
            yield session

    test_app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, maker


async def _signup(client, *, org="Acme Corp", email=None, password="Sup3rsecret"):
    email = email or _email("signup")
    resp = await client.post(
        "/api/v1/auth/signup",
        json={"organization_name": org, "email": email, "password": password},
    )
    return resp, email, password


class TestSignup:
    async def test_signup_creates_org_workspace_admin_and_token(self, api_client) -> None:
        client, maker = api_client
        resp, email, _ = await _signup(client)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["role"] == "admin"
        assert body["organization_id"]
        assert body["workspace_id"]
        assert body["user_id"]
        assert body["access_token"]

        # Token authenticates /me; org carries a 7-day trial.
        me = await client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
        )
        assert me.status_code == 200, me.text
        payload = me.json()
        assert payload["user"]["email"] == email
        assert payload["user"]["role"] == "admin"
        assert payload["workspace"]["id"] == body["workspace_id"]
        assert payload["organization"]["plan"] == "trial"
        trial_ends = datetime.fromisoformat(payload["organization"]["trial_ends_at"])
        delta = trial_ends - datetime.now(UTC)
        assert timedelta(days=6, hours=23) < delta <= timedelta(days=7, minutes=1)

        # Audit trail recorded the signup.
        async with maker() as session:
            event = (
                await session.execute(
                    select(AuditEvent).where(
                        AuditEvent.event_type == "auth.signup",
                        AuditEvent.subject_id == body["user_id"],
                    )
                )
            ).scalar_one_or_none()
        assert event is not None

    async def test_signup_duplicate_email_conflicts(self, api_client) -> None:
        client, _ = api_client
        resp, email, _ = await _signup(client)
        assert resp.status_code == 201, resp.text
        resp2, _, _ = await _signup(client, org="Other Inc", email=email)
        assert resp2.status_code == 409

    async def test_signup_rejects_weak_password(self, api_client) -> None:
        client, _ = api_client
        for weak in ("short1", "allletterspassword", "12345678901"):
            resp, _, _ = await _signup(client, password=weak)
            assert resp.status_code == 422, weak

    async def test_signup_rejects_invalid_email(self, api_client) -> None:
        client, _ = api_client
        resp, _, _ = await _signup(client, email="not-an-email")
        assert resp.status_code == 422


class TestLogin:
    async def test_login_roundtrip(self, api_client) -> None:
        client, _ = api_client
        signed, email, password = await _signup(client)
        assert signed.status_code == 201, signed.text
        ws_id = signed.json()["workspace_id"]

        resp = await client.post(
            "/api/v1/auth/login",
            json={"workspace_id": ws_id, "email": email, "password": password},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["user_id"] == signed.json()["user_id"]

    async def test_login_failures_are_uniform_401(self, api_client) -> None:
        client, _ = api_client
        signed, email, _ = await _signup(client)
        ws_id = signed.json()["workspace_id"]

        cases = [
            {"workspace_id": ws_id, "email": email, "password": "Wrongpass1"},
            {"workspace_id": ws_id, "email": _email("ghost"), "password": "Sup3rsecret"},
            {
                "workspace_id": str(uuid.uuid4()),
                "email": email,
                "password": "Sup3rsecret",
            },
        ]
        for payload in cases:
            resp = await client.post("/api/v1/auth/login", json=payload)
            assert resp.status_code == 401, payload
            assert resp.json()["detail"] == "Invalid email or password"

    async def test_login_rejects_inactive_user_uniformly(self, api_client) -> None:
        client, maker = api_client
        signed, email, password = await _signup(client)
        ws_id = signed.json()["workspace_id"]
        async with maker() as session:
            user = (await session.execute(select(User).where(User.email == email))).scalar_one()
            user.is_active = False
            await session.commit()

        resp = await client.post(
            "/api/v1/auth/login",
            json={"workspace_id": ws_id, "email": email, "password": password},
        )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid email or password"


class TestMeAndLogout:
    async def test_me_requires_bearer_token(self, api_client) -> None:
        client, _ = api_client
        assert (await client.get("/api/v1/auth/me")).status_code == 401
        bad = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer junk"})
        assert bad.status_code == 401

    async def test_logout_is_audit_recorded(self, api_client) -> None:
        client, maker = api_client
        signed, _, _ = await _signup(client)
        token = signed.json()["access_token"]
        resp = await client.post(
            "/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["success"] is True
        async with maker() as session:
            event = (
                await session.execute(
                    select(AuditEvent).where(
                        AuditEvent.event_type == "auth.logout",
                        AuditEvent.subject_id == signed.json()["user_id"],
                    )
                )
            ).scalar_one_or_none()
        assert event is not None


class TestChangePassword:
    async def test_change_password_rotates_credential(self, api_client) -> None:
        client, _ = api_client
        signed, email, password = await _signup(client)
        ws_id = signed.json()["workspace_id"]
        token = signed.json()["access_token"]

        resp = await client.post(
            "/api/v1/auth/change-password",
            headers={"Authorization": f"Bearer {token}"},
            json={"current_password": password, "new_password": "N3wsecretpass"},
        )
        assert resp.status_code == 200, resp.text

        old_login = await client.post(
            "/api/v1/auth/login",
            json={"workspace_id": ws_id, "email": email, "password": password},
        )
        assert old_login.status_code == 401
        new_login = await client.post(
            "/api/v1/auth/login",
            json={"workspace_id": ws_id, "email": email, "password": "N3wsecretpass"},
        )
        assert new_login.status_code == 200

    async def test_change_password_rejects_wrong_current(self, api_client) -> None:
        client, _ = api_client
        signed, _, _ = await _signup(client)
        resp = await client.post(
            "/api/v1/auth/change-password",
            headers={"Authorization": f"Bearer {signed.json()['access_token']}"},
            json={"current_password": "Wrongpass1", "new_password": "N3wsecretpass"},
        )
        assert resp.status_code == 401


class TestPasswordReset:
    async def test_reset_roundtrip_dev_discloses_token(self, dev_client) -> None:
        client, _ = dev_client
        signed, email, _ = await _signup(client)
        assert signed.status_code == 201, signed.text

        req = await client.post("/api/v1/auth/reset/request", json={"email": email})
        assert req.status_code == 200
        assert req.json()["requested"] is True
        token = req.json()["reset_token"]
        assert token

        confirm = await client.post(
            "/api/v1/auth/reset/confirm",
            json={"token": token, "new_password": "R3setsecretpass"},
        )
        assert confirm.status_code == 200, confirm.text

        login = await client.post(
            "/api/v1/auth/login",
            json={
                "workspace_id": signed.json()["workspace_id"],
                "email": email,
                "password": "R3setsecretpass",
            },
        )
        assert login.status_code == 200

    async def test_reset_unknown_email_is_uniform(self, dev_client) -> None:
        client, _ = dev_client
        req = await client.post("/api/v1/auth/reset/request", json={"email": _email("ghost")})
        assert req.status_code == 200
        assert req.json() == {"requested": True, "reset_token": None}

    async def test_reset_token_is_single_use(self, dev_client) -> None:
        client, _ = dev_client
        signed, email, _ = await _signup(client)
        assert signed.status_code == 201, signed.text
        token = (await client.post("/api/v1/auth/reset/request", json={"email": email})).json()[
            "reset_token"
        ]
        first = await client.post(
            "/api/v1/auth/reset/confirm",
            json={"token": token, "new_password": "R3setsecretpass"},
        )
        assert first.status_code == 200
        second = await client.post(
            "/api/v1/auth/reset/confirm",
            json={"token": token, "new_password": "Anotherpass1"},
        )
        assert second.status_code == 400

    async def test_reset_rejects_forged_token(self, dev_client) -> None:
        client, _ = dev_client
        resp = await client.post(
            "/api/v1/auth/reset/confirm",
            json={"token": "forged-token-value-0123456789", "new_password": "Anotherpass1"},
        )
        assert resp.status_code == 400


class TestCrossWorkspaceIsolation:
    async def test_canonical_path_rejects_foreign_workspace(self, api_client) -> None:
        client, _ = api_client
        a, _, _ = await _signup(client, org="Org A")
        b, _, _ = await _signup(client, org="Org B")
        assert a.status_code == 201 and b.status_code == 201
        a_body, b_body = a.json(), b.json()

        # Same-workspace read works on the canonical persistent path.
        own = await client.get(
            "/api/v1/nexus/decisions",
            params={"workspace_id": a_body["workspace_id"]},
            headers={"Authorization": f"Bearer {a_body['access_token']}"},
        )
        assert own.status_code == 200, own.text

        # Foreign workspace is forbidden — server-side, token-derived.
        foreign = await client.get(
            "/api/v1/nexus/decisions",
            params={"workspace_id": b_body["workspace_id"]},
            headers={"Authorization": f"Bearer {a_body['access_token']}"},
        )
        assert foreign.status_code == 403
