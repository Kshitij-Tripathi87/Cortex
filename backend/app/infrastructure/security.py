"""Security infrastructure â€” auth context, authorization, and protective middleware.

This module provides the security primitives referenced by ``app/main.py`` and
``app/api/v1/graph.py``:

AuthN / AuthZ
-------------
* :class:`AuthContext` â€” the principal resolved from the request.
* :func:`get_current_user` â€” FastAPI dependency that resolves the principal
  from request headers. In non-production environments, an absent header set
  degrades to a permissive anonymous principal so local dev and tests work
  without explicit auth. In production (``CORTEX_ENV=prod`` or ``pilot``), the
  ``X-User-Id`` header is required.
* :func:`require_workspace_access` â€” enforces that the resolved principal may
  access the workspace named by the request. Raises 403 with a structured
  error envelope on denial.

Middleware (added by ``app/main.py``)
-------------------------------------
* :class:`SecurityHeadersMiddleware` â€” static response hardening headers.
* :class:`RateLimitHeadersMiddleware` â€” emits ``X-RateLimit-*`` headers for
  known expensive routes, backed by an in-memory token bucket per
  (workspace, route). Tracks state; does not reject by default (it reports),
  so it never blocks the request path on its own.
* :class:`CircuitBreakerMiddleware` â€” per (workspace, route) failure tracking.
  After ``threshold`` consecutive failures, opens for ``timeout`` seconds and
  short-circuits further calls with 503.

Decorators (available for future per-endpoint hardening)
--------------------------------------------------------
* :func:`rate_limit` â€” token-bucket gate on a route.
* :func:`circuit_breaker` â€” wrap a callable with a named circuit.

Entropy of randomness intentionally avoided â€” all security state is
deterministic given inputs, to preserve Cortex's replay guarantee.
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, cast

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.config import get_settings

__all__ = [
    "AuthContext",
    "get_current_user",
    "require_workspace_access",
    "require_role",
    "SecurityHeadersMiddleware",
    "RateLimitHeadersMiddleware",
    "CircuitBreakerMiddleware",
    "rate_limit",
    "circuit_breaker",
]


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Authorization
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


@dataclass
class AuthContext:
    """Resolved principal for the current request.

    Attributes:
        user_id: Stable identifier for the user (``None`` only for the dev
            anonymous principal).
        email: Optional email, used only for audit logging.
        roles: Granted roles, e.g. ``["analyst"]`` or ``["admin"]``.
        workspace_ids: Workspaces the principal may access. An empty list
            means "any workspace" â€” used by the dev anonymous principal.
        is_anonymous: Whether this is the degraded dev principal.
    """

    user_id: str | None
    email: str | None = None
    roles: list[str] = field(default_factory=list)
    workspace_ids: list[str] = field(default_factory=list)
    is_anonymous: bool = False

    def can_access(self, workspace_id: str) -> bool:
        """True if the principal may access ``workspace_id``.

        An empty ``workspace_ids`` list is the *any* policy â€” used by the dev
        anonymous principal. In production, the JWT middleware populates a
        non-empty list.
        """
        if not self.workspace_ids:
            return True
        return workspace_id in self.workspace_ids


def _is_strict_env() -> bool:
    """True when auth must be enforced (prod / pilot)."""
    settings = get_settings()
    return settings.cortex_env in {"prod", "pilot"}


def _header(request: Request, name: str) -> str | None:
    """Read a request header, trimmed, or None."""
    value = request.headers.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _comma_list(value: str | None) -> list[str]:
    """Parse a comma-separated header value into a clean list."""
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


async def get_current_user(request: Request) -> AuthContext:
    """Resolve verified Bearer-token identity in strict environments.

    Development and tests retain header identity solely as a local fixture.
    Pilot/production never trust caller-supplied identity headers.
    """
    if _is_strict_env():
        authorization = _header(request, "Authorization")
        if authorization is None or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Bearer token required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        from app.modules.identity.jwt_auth import verify_token

        try:
            claims = verify_token(authorization.removeprefix("Bearer ").strip())
        except PermissionError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(exc),
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
        roles = claims.get("roles", [])
        return AuthContext(
            user_id=str(claims["sub"]),
            email=str(claims.get("email") or "") or None,
            roles=[str(role) for role in roles] if isinstance(roles, list) else [],
            workspace_ids=[str(claims["workspace_id"])],
            is_anonymous=False,
        )

    from app.modules.identity.dependencies import get_current_user as resolve_user

    try:
        principal = await resolve_user(request)
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    return AuthContext(
        user_id=principal.user_id,
        email=principal.email,
        roles=principal.roles,
        workspace_ids=principal.workspace_ids,
        is_anonymous=principal.is_anonymous,
    )


def require_workspace_access(workspace_id: str, auth: AuthContext) -> None:
    """Enforce that ``auth`` may access ``workspace_id``.

    Raises:
        HTTPException(404): an absent or empty workspace id â€” surface the
            resource as not-found rather than leaking its existence.
        HTTPException(403): the principal is authenticated but not
            authorized for this workspace, with a structured error envelope.
    """
    if not workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )

    if auth.can_access(workspace_id):
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "error": "forbidden",
            "message": "You do not have access to this workspace",
            "workspace_id": workspace_id,
            "user_id": auth.user_id,
        },
    )


def require_role(role: str, auth: AuthContext) -> None:
    """Enforce that ``auth`` holds the specified ``role`` (or higher).

    Raises:
        HTTPException(403): the principal lacks the required role.
    """
    if role in auth.roles:
        return
    if "system_admin" in auth.roles:
        # system_admin is the highest role and implicitly has all roles
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "error": "forbidden",
            "message": f"Role '{role}' required",
            "user_id": auth.user_id,
            "required_role": role,
            "principal_roles": auth.roles,
        },
    )


# ═════════════════════════════════════════════════════════════════════════════════
# Security headers middleware
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": (
        "geolocation=(), microphone=(), camera=(), "
        "payment=(), usb=(), magnetometer=(), gyroscope=()"
    ),
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "X-DNS-Prefetch-Control": "off",
    "Cache-Control": "no-store",
}


class SecurityHeadersMiddleware:
    """ASGI middleware that applies static security response headers.

    Adds strict-transport-security only when the request was received over
    https. All other headers apply unconditionally to every response.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        is_https = scope.get("scheme") == "https"

        async def send_wrapper(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers: list[tuple[bytes, bytes]] = list(message.get("headers", []))
                for name, value in _SECURITY_HEADERS.items():
                    headers.append((name.encode("latin-1"), value.encode("latin-1")))
                if is_https:
                    headers.append(
                        (
                            b"Strict-Transport-Security",
                            b"max-age=31536000; includeSubDomains",
                        )
                    )
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Rate limit middleware (headers + per-(workspace,route) token bucket)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

# Heuristic: expensive routes are those whose second path segment is one of
# these markers. The RateLimitHeadersMiddleware reports X-RateLimit-* against
# a tighter bucket for these. The bucket is in-memory and per-process.
_EXPENSIVE_MARKERS = {"graph", "propagate", "scenarios", "recommendations"}


def _is_expensive(path: str) -> bool:
    parts = [p for p in path.split("/") if p]
    if len(parts) < 2:
        return False
    # /api/v1/<marker>/... â†’ parts[1] is the marker
    return parts[1] in _EXPENSIVE_MARKERS


def _workspace_id_from_scope(scope: Any) -> str:
    """Resolve the workspace id from an ASGI scope.

    Looks at the ``?workspace_id=`` query parameter first, then the
    ``X-Workspace-Id`` header, and falls back to ``"_global"``.
    """
    query = scope.get("query_string", b"")
    if isinstance(query, (bytes, bytearray)):
        query_str = query.decode("latin-1", errors="ignore")
    elif isinstance(query, str):
        query_str = query
    else:
        query_str = ""
    for pair in query_str.split("&"):
        if pair.startswith("workspace_id="):
            value: str = pair[len("workspace_id=") :]
            if value:
                return value
    headers = scope.get("headers", []) or []
    if isinstance(headers, list):
        for item in headers:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                continue
            name_b = cast(bytes, item[0])
            value_b = cast(bytes, item[1])
            if name_b == b"x-workspace-id":
                return value_b.decode("latin-1", errors="ignore")
    return "_global"


class _TokenBucket:
    """A minimal token bucket, deterministic given the clock."""

    __slots__ = ("capacity", "refill_per_s", "tokens", "last_refill")

    def __init__(self, capacity: float, refill_per_s: float, now: float) -> None:
        self.capacity = capacity
        self.refill_per_s = refill_per_s
        self.tokens = capacity
        self.last_refill = now

    def _refill(self, now: float) -> None:
        elapsed = max(0.0, now - self.last_refill)
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_per_s)
        self.last_refill = now

    def try_consume(self, now: float, cost: float = 1.0) -> bool:
        self._refill(now)
        if self.tokens >= cost:
            self.tokens -= cost
            return True
        return False

    def snapshots(self) -> tuple[int, int, int]:
        """Return (limit, remaining, reset_seconds) for headers."""
        remaining = int(self.tokens)
        # Seconds until the bucket is full again, conservatively.
        deficit = max(0.0, self.capacity - self.tokens)
        reset = int(deficit / self.refill_per_s) if self.refill_per_s > 0 else 0
        return int(self.capacity), remaining, reset


class RateLimitHeadersMiddleware:
    """ASGI middleware that emits ``X-RateLimit-*`` headers.

    Uses an in-memory per-(workspace, route) token bucket. For expensive
    routes it uses the tighter budget from settings. The middleware never
    rejects a request on its own (it reports), keeping the request path safe
    for dev/testing; per-route rejection is left to :func:`rate_limit`
    decorators or the upstream gateway.
    """

    def __init__(self, app: Any) -> None:
        self.app = app
        settings = get_settings()
        self._default_capacity = float(settings.rate_limit_default_burst)
        self._default_refill = settings.rate_limit_default_rps
        self._expensive_capacity = float(settings.rate_limit_expensive_burst)
        self._expensive_refill = settings.rate_limit_expensive_rps
        self._buckets: dict[tuple[str, str], _TokenBucket] = {}

    def _bucket(self, key: tuple[str, str], now: float, expensive: bool) -> _TokenBucket:
        bucket = self._buckets.get(key)
        if bucket is None:
            if expensive:
                bucket = _TokenBucket(self._expensive_capacity, self._expensive_refill, now)
            else:
                bucket = _TokenBucket(self._default_capacity, self._default_refill, now)
            self._buckets[key] = bucket
        return bucket

    def _workspace_id(self, scope: Any) -> str:
        return _workspace_id_from_scope(scope)

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope["path"]
        expensive = _is_expensive(path)
        ws_id = self._workspace_id(scope)
        route_key = path.split("?")[0]
        bucket_key = (ws_id, route_key)
        now = time.monotonic()
        bucket = self._bucket(bucket_key, now, expensive)
        # Consume one token for the request; report remaining regardless.
        bucket.try_consume(now, cost=1.0)
        limit, remaining, reset = bucket.snapshots()

        async def send_wrapper(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers: list[tuple[bytes, bytes]] = list(message.get("headers", []))
                headers.append((b"X-RateLimit-Limit", str(limit).encode("latin-1")))
                headers.append((b"X-RateLimit-Remaining", str(remaining).encode("latin-1")))
                headers.append((b"X-RateLimit-Reset", str(reset).encode("latin-1")))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Circuit breaker middleware
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


@dataclass
class _CircuitState:
    failures: int = 0
    opened_until: float = 0.0

    def is_open(self, now: float) -> bool:
        return self.opened_until > now

    def record_failure(self, now: float, timeout: float, threshold: int) -> None:
        self.failures += 1
        if self.failures >= threshold:
            self.opened_until = now + timeout

    def record_success(self) -> None:
        self.failures = 0
        self.opened_until = 0.0


class CircuitBreakerMiddleware:
    """ASGI middleware implementing a per-(workspace, route) circuit breaker.

    A circuit is *closed* normally. After ``threshold`` consecutive failures
    (any 5xx response, or an exception propagating from the downstream app),
    the circuit *opens* for ``timeout`` seconds. While open, matching
    requests are short-circuited with a 503 before the downstream app runs.

    States are in-memory and per-process. Boxes fail *closed* (reject when
    in doubt) for the expensive routes; non-expensive routes pass through.
    """

    def __init__(self, app: Any) -> None:
        self.app = app
        settings = get_settings()
        self._threshold = settings.circuit_breaker_failure_threshold
        self._timeout = settings.circuit_breaker_timeout
        self._states: dict[tuple[str, str], _CircuitState] = defaultdict(_CircuitState)

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope["path"]
        # Only the expensive routes are protected by this circuit breaker.
        if not _is_expensive(path):
            await self.app(scope, receive, send)
            return

        ws_id = self._workspace_id(scope)
        route_key = path.split("?")[0]
        key = (ws_id, route_key)
        now = time.monotonic()
        state = self._states[key]

        if state.is_open(now):
            response = JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={
                    "error": "circuit_open",
                    "message": "Service temporarily unavailable; circuit breaker open",
                    "retry_after": f"{self._timeout:.0f}",
                },
            )
            await response(scope, receive, send)
            return

        status_code = {"value": 500}
        failed = {"value": False}

        async def send_wrapper(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                code = message["status"]
                status_code["value"] = code
                if code >= 500:
                    failed["value"] = True
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
            if failed["value"]:
                state.record_failure(now, self._timeout, self._threshold)
            else:
                state.record_success()
        except Exception:
            state.record_failure(now, self._timeout, self._threshold)
            raise

    @staticmethod
    def _workspace_id(scope: Any) -> str:
        return _workspace_id_from_scope(scope)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Per-call decorators (available for future per-endpoint hardening)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def rate_limit(
    *,
    capacity: int | None = None,
    refill_per_s: float | None = None,
    key: Callable[..., str] | None = None,
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """Decorator that gates a coroutine with an in-memory token bucket.

    ``key`` extracts the rate-limit key (e.g. workspace id) from the
    decorated function's call args. Defaults to a single global bucket.

    Raises:
        HTTPException(429): when no token is available.
    """
    settings = get_settings()
    cap = float(capacity if capacity is not None else settings.rate_limit_default_burst)
    rate = refill_per_s if refill_per_s is not None else settings.rate_limit_default_rps
    buckets: dict[str, _TokenBucket] = {}

    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            k = key(*args, **kwargs) if key else "_global"
            now = time.monotonic()
            bucket = buckets.get(k)
            if bucket is None:
                bucket = _TokenBucket(cap, rate, now)
                buckets[k] = bucket
            if not bucket.try_consume(now, cost=1.0):
                _, _, reset = bucket.snapshots()
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limit exceeded",
                    headers={"Retry-After": str(max(1, reset))},
                )
            return await func(*args, **kwargs)

        return wrapper

    return decorator


def circuit_breaker(
    *,
    failure_threshold: int | None = None,
    timeout: float | None = None,
    name: str | None = None,
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """Decorator that wraps a coroutine with a named circuit breaker.

    Raises:
        HTTPException(503): when the named circuit is currently open.
    """
    settings = get_settings()
    threshold = failure_threshold or settings.circuit_breaker_failure_threshold
    cb_timeout = timeout if timeout is not None else settings.circuit_breaker_timeout
    states: dict[str, _CircuitState] = defaultdict(_CircuitState)

    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        cb_name = name or func.__name__

        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            state = states[cb_name]
            now = time.monotonic()
            if state.is_open(now):
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=f"Circuit '{cb_name}' is open",
                    headers={"Retry-After": f"{cb_timeout:.0f}"},
                )
            try:
                result = await func(*args, **kwargs)
            except HTTPException:
                state.record_failure(now, cb_timeout, threshold)
                raise
            except Exception:
                state.record_failure(now, cb_timeout, threshold)
                raise
            state.record_success()
            return result

        return wrapper

    return decorator
