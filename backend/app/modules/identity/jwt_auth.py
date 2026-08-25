"""MVP JWT and password primitives; no sessions, refresh tokens, or external IdP."""
from __future__ import annotations

import hashlib
import hmac
import os
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt
from jwt import InvalidTokenError

from app.config import Settings, get_settings

try:
    import bcrypt

    _HAS_BCRYPT = True
except ImportError:
    _HAS_BCRYPT = False


def hash_password(password: str) -> str:
    if _HAS_BCRYPT:
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    # Fallback standard PBKDF2 HMAC SHA-256
    salt = os.urandom(16).hex()
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()
    return f"pbkdf2_sha256${salt}${key}"


def verify_password(password: str, password_hash: str) -> bool:
    if _HAS_BCRYPT and password_hash.startswith(("$2a$", "$2b$", "$2y$")):
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    if password_hash.startswith("pbkdf2_sha256$"):
        parts = password_hash.split("$")
        if len(parts) == 3:
            salt = parts[1]
            expected_key = parts[2]
            key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()
            return hmac.compare_digest(key, expected_key)
    # Dev/test simple matching
    return hmac.compare_digest(password, password_hash)


def issue_token(*, user_id: UUID, workspace_id: UUID, role: str, email: str, settings: Settings | None = None) -> tuple[str, datetime]:
    s = settings or get_settings()
    if not s.jwt_secret:
        raise RuntimeError("CORTEX_JWT_SECRET must be configured to issue tokens")
    expires_at = datetime.now(UTC) + timedelta(minutes=s.jwt_expiry_minutes)
    payload = {"sub": str(user_id), "workspace_id": str(workspace_id), "roles": [role], "email": email, "aud": s.jwt_audience, "iat": datetime.now(UTC), "exp": expires_at}
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm), expires_at


def verify_token(token: str, settings: Settings | None = None) -> dict[str, Any]:
    s = settings or get_settings()
    if not s.jwt_secret:
        raise PermissionError("JWT authentication is not configured")
    try:
        claims = jwt.decode(token, s.jwt_secret, algorithms=["HS256"], audience=s.jwt_audience, options={"require": ["exp", "sub", "workspace_id"]})
    except InvalidTokenError as exc:
        raise PermissionError("Invalid or expired access token") from exc
    if not isinstance(claims.get("workspace_id"), str):
        raise PermissionError("Token missing workspace claim")
    return dict(claims)
