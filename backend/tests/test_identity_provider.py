"""Identity-provider JWT security regression tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import jwt
import pytest

from app.modules.identity.provider import JWTIDProvider, JWTProviderConfig, ServiceTokenFactory


def _settings(secret: str) -> SimpleNamespace:
    return SimpleNamespace(jwt_service_signing_key=secret)


@pytest.mark.asyncio
async def test_oidc_provider_verifies_hs256_token(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "test-only-cortex-jwt-secret-which-is-long-enough"
    monkeypatch.setattr("app.modules.identity.provider.get_settings", lambda: _settings(secret))
    token = jwt.encode(
        {
            "sub": "user-123",
            "iss": "cortex-test-issuer",
            "aud": "cortex-test-api",
            "workspace_ids": ["workspace-1"],
            "roles": ["operator"],
        },
        secret,
        algorithm="HS256",
    )
    provider = JWTIDProvider(
        JWTProviderConfig(issuer="cortex-test-issuer", audience="cortex-test-api")
    )

    principal = await provider.verify_token(token)

    assert principal.user_id == "user-123"
    assert principal.roles == ["operator"]
    assert principal.workspace_ids == ["workspace-1"]
    assert principal.is_anonymous is False


@pytest.mark.asyncio
async def test_oidc_provider_rejects_invalid_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.modules.identity.provider.get_settings",
        lambda: _settings("expected-secret"),
    )
    token = jwt.encode(
        {"sub": "attacker", "iss": "cortex-test-issuer", "aud": "cortex-test-api"},
        "wrong-secret",
        algorithm="HS256",
    )
    provider = JWTIDProvider(
        JWTProviderConfig(issuer="cortex-test-issuer", audience="cortex-test-api")
    )

    with pytest.raises(PermissionError, match="Token verification failed"):
        await provider.verify_token(token)


@pytest.mark.asyncio
async def test_service_tokens_use_restricted_hs256(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "test-only-service-signing-key"
    monkeypatch.setattr("app.modules.identity.provider.get_settings", lambda: _settings(secret))

    token = await ServiceTokenFactory.issue("test-agent", "workspace-1", ["decision.read"])
    claims: dict[str, Any] = await ServiceTokenFactory.verify(token)

    assert claims["sub"] == "test-agent"
    assert claims["workspace_id"] == "workspace-1"
    assert claims["scp"] == "decision.read"
