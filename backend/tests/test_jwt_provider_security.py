from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.modules.identity.provider import JWTIDProvider, JWTProviderConfig, ServiceTokenFactory


@pytest.mark.asyncio
async def test_jwks_free_oidc_provider_is_hs256_only(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "test-only-service-signing-secret-with-sufficient-entropy"
    monkeypatch.setattr(
        "app.modules.identity.provider.get_settings",
        lambda: SimpleNamespace(jwt_service_signing_key=secret),
    )
    provider = JWTIDProvider(JWTProviderConfig(issuer="https://issuer.example", audience="cortex"))

    now = datetime.now(UTC)
    claims = {
        "sub": "user-1",
        "iss": "https://issuer.example",
        "aud": "cortex",
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "roles": ["admin"],
        "workspace_ids": ["workspace-1"],
    }
    valid = jwt.encode(claims, secret, algorithm="HS256")
    principal = await provider.verify_token(valid)
    assert principal.user_id == "user-1"
    assert principal.roles == ["admin"]
    assert principal.workspace_ids == ["workspace-1"]

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    asymmetric = jwt.encode(claims, private_pem, algorithm="RS256")

    with pytest.raises(PermissionError, match="Token verification failed"):
        await provider.verify_token(asymmetric)


@pytest.mark.asyncio
async def test_service_token_factory_pyjwt_round_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "test-only-service-token-secret-with-sufficient-entropy"
    monkeypatch.setattr(
        ServiceTokenFactory, "signing_key", classmethod(lambda cls: secret)
    )

    token = await ServiceTokenFactory.issue(
        "nexus-worker",
        "workspace-1",
        ["graph:read", "decision:simulate"],
        ttl=300,
    )
    claims = await ServiceTokenFactory.verify(token)

    assert claims["sub"] == "nexus-worker"
    assert claims["workspace_id"] == "workspace-1"
    assert claims["scp"] == "graph:read decision:simulate"
    assert claims["iss"] == "cortex-agent"
    assert claims["aud"] == "cortex-backend"


@pytest.mark.asyncio
async def test_service_token_factory_rejects_wrong_signing_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ServiceTokenFactory, "signing_key", classmethod(lambda cls: "correct-secret")
    )
    token = jwt.encode(
        {
            "sub": "nexus-worker",
            "iss": "cortex-agent",
            "aud": "cortex-backend",
            "workspace_id": "workspace-1",
            "exp": datetime.now(UTC) + timedelta(minutes=5),
        },
        "different-secret",
        algorithm="HS256",
    )
    with pytest.raises(PermissionError, match="Service token verification failed"):
        await ServiceTokenFactory.verify(token)
