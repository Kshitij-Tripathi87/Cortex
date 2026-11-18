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


# ─────────────────────────────────────────────────────────────────────────────
# Sign-in is on unless the environment is EXPLICITLY dev or test.
#
# Regression: the rule used to be "strict if the name is on a list of
# production names". Any other value of CORTEX_ENV ("uat", a typo such as
# "prd") and a missing CORTEX_ENV (which defaulted to "dev") therefore ran the
# API with sign-in switched off. The open mode is now opt-in.
# ─────────────────────────────────────────────────────────────────────────────


def _settings_kwargs() -> dict[str, str]:
    return {
        "jwt_secret": SECRET,
        "llm_provider": "openai_compatible",
        "llm_model": "configured-model",
        "llm_api_key": "configured-key",
        "llm_base_url": "https://model-gateway.example/v1",
    }


def test_a_missing_environment_name_stops_the_server(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CORTEX_ENV", raising=False)

    with pytest.raises(ValueError, match="CORTEX_ENV must be set"):
        Settings(_env_file=None, **_settings_kwargs())  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "env", ["", "   ", "uat", "prd", "qa", "demo", "development", "local", "ci"]
)
def test_an_unknown_environment_name_stops_the_server(
    monkeypatch: pytest.MonkeyPatch, env: str
) -> None:
    """Never "unknown name, so run open": the server refuses to start."""
    monkeypatch.delenv("CORTEX_ENV", raising=False)

    with pytest.raises(ValueError, match="CORTEX_ENV"):
        Settings(_env_file=None, env=env, **_settings_kwargs())  # type: ignore[call-arg]


def test_the_environment_variable_is_read_and_normalised(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORTEX_ENV", "  Staging ")

    settings = Settings(_env_file=None, **_settings_kwargs())  # type: ignore[call-arg]

    assert settings.env == "staging"
    assert settings.is_deployed is True
    assert settings.is_local is False


@pytest.mark.parametrize(
    ("env", "local"),
    [
        ("dev", True),
        ("test", True),
        (" Dev ", True),
        ("staging", False),
        ("pilot", False),
        ("prod", False),
        ("production", False),
    ],
)
def test_only_dev_and_test_are_local(env: str, local: bool) -> None:
    settings = _settings(env)

    assert settings.is_local is local
    assert settings.is_deployed is (not local)


def test_a_deployed_environment_still_needs_its_signing_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Other test modules export a secret for the whole session; this test is
    # about its absence.
    monkeypatch.delenv("CORTEX_JWT_SECRET", raising=False)
    kwargs = {**_settings_kwargs(), "jwt_secret": ""}

    with pytest.raises(ValueError, match="CORTEX_JWT_SECRET must be set"):
        Settings(_env_file=None, env="staging", **kwargs)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("name", "local"),
    [
        ("dev", True),
        ("test", True),
        (" Test ", True),
        ("staging", False),
        ("prod", False),
        ("uat", False),
        ("", False),
        (None, False),
        (0, False),
        ("devil", False),
        ("dev,prod", False),
    ],
)
def test_is_local_environment_is_an_exact_opt_in(name: object, local: bool) -> None:
    from app.config import is_local_environment

    assert is_local_environment(name) is local


class _FakeSettings:
    """Stands in for a Settings object that somehow carries an odd name."""

    def __init__(self, env: Any) -> None:
        self.env = env


@pytest.mark.parametrize("env", ["uat", "prd", "", None, "developer", "testing", "PROD", " pilot "])
def test_the_request_guard_fails_closed_on_a_name_it_does_not_know(
    monkeypatch: pytest.MonkeyPatch, env: Any
) -> None:
    """Second line of defence, independent of Settings validation.

    If an unrecognised name ever reaches the request path, the guard treats
    it as deployed: no token, no service.
    """
    monkeypatch.setattr(security, "get_settings", lambda: _FakeSettings(env))

    assert security._is_strict_env() is True


@pytest.mark.parametrize("env", ["dev", "test", "Dev", " TEST "])
def test_the_request_guard_is_open_only_for_dev_and_test(
    monkeypatch: pytest.MonkeyPatch, env: str
) -> None:
    monkeypatch.setattr(security, "get_settings", lambda: _FakeSettings(env))

    assert security._is_strict_env() is False


async def test_an_unknown_name_on_the_request_path_refuses_anonymous_callers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(security, "get_settings", lambda: _FakeSettings("uat"))

    with pytest.raises(HTTPException) as refused:
        await security.get_current_user(
            _request({"X-User-Id": "attacker", "X-User-Roles": "admin"})
        )

    assert refused.value.status_code == 401
    assert refused.value.detail == "Bearer token required"
