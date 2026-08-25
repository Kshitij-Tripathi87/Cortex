"""Identity providers — adapter protocol + concrete implementations.

Every provider adapter implements the ``IdentityProvider`` protocol:

    - ``resolve(request) → UserPrincipal`` — for HTTP request identity resolution
    - ``verify_token(token) → UserPrincipal`` — for JWT/OIDC providers
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any, Protocol

from app.config import get_settings
from app.modules.identity.models import UserPrincipal


class IdentityProvider(Protocol):
    """Protocol that any identity adapter must satisfy."""

    async def resolve(self, request: Any) -> UserPrincipal: ...

    async def verify_token(self, token: str) -> UserPrincipal: ...


# ─────────────────────────────────────────────────────────────────────────────
# Header-based development provider
# ─────────────────────────────────────────────────────────────────────────────


class HeaderIdentityProvider:
    """Provider for local dev and tests — reads identity from HTTP headers.

    This is the default in ``CORTEX_IDENTITY_PROVIDER=header``.
    Production deploys MUST switch to a JWT-based provider.
    """

    async def resolve(self, request: Any) -> UserPrincipal:
        headers = request.headers if hasattr(request, "headers") else {}

        user_id = _h(headers, "X-User-Id")
        if user_id is None:
            return UserPrincipal(
                user_id="anonymous",
                is_anonymous=True,
            )

        return UserPrincipal(
            user_id=user_id,
            email=_h(headers, "X-User-Email"),
            roles=_cl(_h(headers, "X-User-Roles")),
            workspace_ids=_cl(_h(headers, "X-User-Workspaces")),
            tenant_id=_h(headers, "X-Tenant-Id"),
            groups=_cl(_h(headers, "X-User-Groups")),
            is_anonymous=False,
        )

    async def verify_token(self, token: str) -> UserPrincipal:
        raise NotImplementedError("HeaderIdentityProvider does not support token verification")


# ─────────────────────────────────────────────────────────────────────────────
# JWT-based OIDC provider
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class JWTProviderConfig:
    """Configuration for a single OIDC identity provider."""

    issuer: str
    audience: str
    jwks_uri: str | None = None
    name: str = "oidc"


class JWTIDProvider:
    """Generic JWT / OpenID Connect identity provider.

    Supports any OIDC-compliant issuer (Entra, Keycloak, Auth0, Okta).
    """

    def __init__(self, config: JWTProviderConfig) -> None:
        self.config = config

    async def resolve(self, request: Any) -> UserPrincipal:
        auth = _h(request.headers if hasattr(request, "headers") else {}, "authorization")
        if not auth or not auth.startswith("Bearer "):
            return UserPrincipal(
                user_id="anonymous",
                is_anonymous=True,
            )

        token = auth[len("Bearer ") :].strip()
        return await self.verify_token(token)

    async def verify_token(self, token: str) -> UserPrincipal:
        from jose import jwt
        from jose.exceptions import JWTError

        key: Any = None
        if self.config.jwks_uri:
            key = _jwks_key(self.config.jwks_uri)
        else:
            settings = get_settings()
            key = getattr(settings, "jwt_service_signing_key", None)

        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256", "HS256", "EdDSA"],
                audience=self.config.audience,
                issuer=self.config.issuer,
                options={"verify_exp": True, "verify_iss": True, "verify_aud": True},
                leeway=30,
            )
        except JWTError as e:
            raise PermissionError(f"Token verification failed: {e}") from e

        user_id = str(claims.get("sub", ""))
        if not user_id:
            raise PermissionError("Token missing 'sub' claim")

        expires_at: datetime | None = None
        exp = claims.get("exp")
        if isinstance(exp, (int, float)):
            expires_at = datetime.fromtimestamp(float(exp), tz=UTC)

        authenticated_at: datetime = datetime.now(UTC)
        iat = claims.get("iat")
        if isinstance(iat, (int, float)):
            authenticated_at = datetime.fromtimestamp(float(iat), tz=UTC)

        return UserPrincipal(
            user_id=user_id,
            email=_claims_email(claims),
            roles=_claims_roles(claims),
            groups=_claims_groups(claims),
            workspace_ids=_claims_workspaces(claims),
            tenant_id=str(claims.get("tid") or ""),
            issuer=str(claims.get("iss", "")),
            session_id=str(claims.get("sid") or ""),
            scopes=_claims_scopes(claims),
            is_anonymous=False,
            authenticated_at=authenticated_at,
            expires_at=expires_at,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _h(headers: Any, name: str) -> str | None:
    value = headers.get(name, None)
    return value.strip() if isinstance(value, str) and value else None


def _cl(value: str | None) -> list[str]:
    if not value:
        return []
    return [p.strip() for p in value.split(",") if p.strip()]


def _claims_email(claims: dict[str, Any]) -> str | None:
    email = claims.get("email") or claims.get("preferred_username") or claims.get("upn")
    if isinstance(email, str) and "@" in email:
        return email
    return None


def _claims_roles(claims: dict[str, Any]) -> list[str]:
    roles = claims.get("roles") or claims.get("Role")
    if isinstance(roles, list):
        return [str(r) for r in roles if isinstance(r, str)]
    if isinstance(roles, str):
        return [r.strip() for r in roles.split(",") if r.strip()]
    return []


def _claims_groups(claims: dict[str, Any]) -> list[str]:
    groups = claims.get("groups")
    if isinstance(groups, list):
        return [str(g) for g in groups if isinstance(g, str)]
    if isinstance(groups, str):
        return [g.strip() for g in groups.split(",") if g.strip()]
    return []


def _claims_workspaces(claims: dict[str, Any]) -> list[str]:
    ws = claims.get("workspace_ids") or claims.get("workspaces")
    if isinstance(ws, list):
        return [str(w) for w in ws]
    if isinstance(ws, str):
        return [w.strip() for w in ws.split(",") if w.strip()]
    return []


def _claims_scopes(claims: dict[str, Any]) -> list[str]:
    scp = claims.get("scp") or claims.get("scopes") or ""
    if isinstance(scp, str):
        return [s.strip() for s in scp.split(" ") if s.strip()]
    if isinstance(scp, list):
        return [str(s) for s in scp if isinstance(s, str)]
    return []


@lru_cache(maxsize=1)
def _jwks_key(jwks_uri: str) -> Any:
    import httpx

    resp = httpx.get(jwks_uri, timeout=10.0)
    resp.raise_for_status()
    return resp.json()


# ─────────────────────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────────────────────


@lru_cache
def create_identity_provider() -> IdentityProvider:
    """Create the appropriate provider based on environment config."""
    settings = get_settings()
    provider_type = getattr(settings, "identity_provider", "header")

    if provider_type == "jwt":
        return JWTIDProvider(
            config=JWTProviderConfig(
                issuer=settings.jwt_issuer,
                audience=settings.jwt_audience,
                jwks_uri=getattr(settings, "jwt_jwks_uri", None) or None,
            ),
        )

    return HeaderIdentityProvider()


# ─────────────────────────────────────────────────────────────────────────────
# Service token factory
# ─────────────────────────────────────────────────────────────────────────────


class ServiceTokenFactory:
    """Issues short-lived service tokens for agents.

    Signed with the Cortex internal signing key. Limited scopes.
    """

    KEY_ATTR = "jwt_service_signing_key"

    @classmethod
    def signing_key(cls) -> str:
        settings = get_settings()
        key = getattr(settings, cls.KEY_ATTR, "")
        if not key:
            raise RuntimeError(f"Settings.{cls.KEY_ATTR} must be set to issue service tokens")
        return key

    @classmethod
    async def issue(
        cls, service_name: str, workspace_id: str, scopes: list[str], *, ttl: int = 900
    ) -> str:
        from jose import jwt

        now = int(datetime.now(UTC).timestamp())
        claims = {
            "sub": service_name,
            "iss": "cortex-agent",
            "aud": "cortex-backend",
            "workspace_id": workspace_id,
            "scp": " ".join(scopes),
            "iat": now,
            "exp": now + ttl,
        }
        return str(jwt.encode(claims, cls.signing_key(), algorithm="HS256"))

    @classmethod
    async def verify(cls, token: str) -> dict[str, Any]:
        from jose import JWTError, jwt

        try:
            return dict(
                jwt.decode(
                    token,
                    cls.signing_key(),
                    algorithms=["HS256"],
                    audience="cortex-backend",
                    issuer="cortex-agent",
                )
            )
        except JWTError as e:
            raise PermissionError(f"Service token verification failed: {e}") from e
