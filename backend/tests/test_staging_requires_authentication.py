"""Staging enforces Bearer-token authentication, like pilot and production.

Regression: only ``prod``, ``production`` and ``pilot`` were treated as strict.
With ``CORTEX_ENV=staging`` a request without a token fell through to the
development identity path, so a deployed, shared environment served API calls
to anonymous callers and trusted caller-supplied identity headers.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.config import Settings
from app.infrastructure import security
from app.modules.identity import jwt_auth

SECRET = "staging-test-secret-0123456789abcdef0123456789"


def _settings(env: str) -> Settings:
    if env.strip().lower() in {"dev", "test"}:
        return Settings(env=env, jwt_secret=SECRET)
    return Settings(
        env=env,
        jwt_secret=SECRET,
        llm_provider="openai_compatible",
        llm_model="configured-model",
        llm_api_key="configured-key",
        llm_base_url="https://model-gateway.example/v1",
    )


def _request(headers: dict[str, str] | None = None) -> Request:
    raw = [(name.lower().encode(), value.encode()) for name, value in (headers or {}).items()]
    scope: dict[str, Any] = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/graph/nodes",
        "headers": raw,
        "query_string": b"",
    }
    return Request(scope)


@pytest.fixture
def environment(monkeypatch: pytest.MonkeyPatch) -> Any:
    def use(env: str) -> None:
        settings = _settings(env)
        monkeypatch.setattr(security, "get_settings", lambda: settings)
        monkeypatch.setattr(jwt_auth, "get_settings", lambda: settings)

    return use


@pytest.mark.parametrize("env", ["staging", "pilot", "prod", "production", "Staging", " STAGING "])
async def test_request_without_a_token_is_refused(environment: Any, env: str) -> None:
    environment(env)

    with pytest.raises(HTTPException) as refused:
        await security.get_current_user(_request())

    assert refused.value.status_code == 401
    assert refused.value.detail == "Bearer token required"


@pytest.mark.parametrize("env", ["staging", "pilot", "prod"])
async def test_identity_headers_are_not_trusted(environment: Any, env: str) -> None:
    environment(env)
    # The headers the development identity path reads.
    headers = {
        "X-User-Id": "attacker",
        "X-User-Email": "attacker@example.com",
        "X-User-Roles": "admin",
        "X-User-Workspaces": "any-workspace",
        "X-Tenant-Id": "any-tenant",
    }

    with pytest.raises(HTTPException) as refused:
        await security.get_current_user(_request(headers))

    assert refused.value.status_code == 401


async def test_staging_accepts_a_verified_token_and_rejects_a_forged_one(environment: Any) -> None:
    environment("staging")
    user_id, workspace_id = uuid4(), uuid4()
    token, _expires_at = jwt_auth.issue_token(
        user_id=user_id, workspace_id=workspace_id, role="analyst", email="user@example.com"
    )

    auth = await security.get_current_user(_request({"Authorization": f"Bearer {token}"}))
    assert auth.user_id == str(user_id)
    assert auth.workspace_ids == [str(workspace_id)]
    assert auth.roles == ["analyst"]
    assert auth.is_anonymous is False

    with pytest.raises(HTTPException) as forged:
        await security.get_current_user(_request({"Authorization": f"Bearer {token}x"}))
    assert forged.value.status_code == 401


@pytest.mark.parametrize("env", ["dev", "test"])
async def test_development_and_test_keep_the_local_identity_path(
    environment: Any, env: str
) -> None:
    environment(env)

    # No token is required locally: identity headers resolve to a principal.
    auth = await security.get_current_user(
        _request({"X-User-Id": "local-dev", "X-User-Roles": "admin"})
    )

    assert auth.user_id == "local-dev"
    assert auth.roles == ["admin"]
