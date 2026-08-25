"""Frozen error taxonomy — platform-wide error hierarchy per docs/17-error-taxonomy.md.

Every error maps to a frozen error.code and HTTP status.
Only the central exception handler formats these for wire responses.
"""

from __future__ import annotations

from typing import Any


class CortexError(Exception):
    """Root of all Cortex errors."""

    code: str = "internal_error"
    http_status: int = 500
    category: str = "system"  # client | server

    def __init__(
        self,
        message: str,
        *,
        details: list[dict[str, Any]] | None = None,
        target: str | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or []
        self.target = target
        self.request_id = request_id

    def to_wire(self) -> dict[str, Any]:
        """Convert to wire format per docs/05-api-standards.md §6."""
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
                "target": self.target,
                "request_id": self.request_id,
            }
        }


# ─────────────────────────────────────────────────────────────────────────────
# Client Errors (4xx)
# ─────────────────────────────────────────────────────────────────────────────


class ClientError(CortexError):
    category = "client"


class ValidationError(ClientError):
    """Schema or semantic validation failure."""

    code = "validation_error"
    http_status = 422


class SchemaValidationError(ValidationError):
    """Request body failed JSON schema validation."""

    code = "validation_error"


class SemanticsValidationError(ValidationError):
    """Request body passed schema but failed business rules."""

    code = "validation_error"


class ConflictError(ClientError):
    """State conflict — idempotency, version, duplicate."""

    code = "conflict"
    http_status = 409


class StateConflictError(ConflictError):
    """Invalid state transition."""

    code = "conflict"


class VersionConflictError(ConflictError):
    """Stale If-Match version."""

    code = "conflict"


class IdempotencyConflictError(ConflictError):
    """Concurrent idempotency key reuse."""

    code = "conflict"


class DuplicateConflictError(ConflictError):
    """Duplicate external id or identity."""

    code = "conflict"


class EvidenceError(ClientError):
    """Evidence contract violation — missing provenance, lineage cycle."""

    code = "validation_error"
    http_status = 422


class GraphError(ClientError):
    """Graph contract violation — type mismatch, self-loop, orphan ref."""

    code = "validation_error"
    http_status = 422


class ScenarioError(ClientError):
    """Scenario contract violation — mainline mutation, assumption without evidence."""

    code = "conflict"
    http_status = 409


class SecurityError(ClientError):
    """Authn/z failure."""

    code = "forbidden"
    http_status = 403


class PermissionError(SecurityError):
    """Explicit permission denied."""

    code = "forbidden"
    http_status = 403


class AuthenticationError(SecurityError):
    """Missing or invalid credentials."""

    code = "unauthenticated"
    http_status = 401


class NotFoundError(ClientError):
    """Resource not found."""

    code = "not_found"
    http_status = 404


class RateLimitError(ClientError):
    """Rate limit exceeded."""

    code = "rate_limited"
    http_status = 429


class QuotaError(ClientError):
    """Tenant/workspace quota exceeded."""

    code = "quota_exceeded"
    http_status = 429


# ─────────────────────────────────────────────────────────────────────────────
# Server Errors (5xx)
# ─────────────────────────────────────────────────────────────────────────────


class ServerError(CortexError):
    category = "server"


class SystemError(ServerError):
    """Unhandled exception or invariant violation."""

    code = "internal_error"
    http_status = 500


class InfrastructureError(ServerError):
    """Dependency unavailable — DB, Redis, S3."""

    code = "unavailable"
    http_status = 503


class DatabaseError(InfrastructureError):
    """Database operation failed."""

    code = "unavailable"
    http_status = 503


class StorageError(InfrastructureError):
    """Object storage operation failed."""

    code = "unavailable"
    http_status = 503


# ─────────────────────────────────────────────────────────────────────────────
# Anomaly Errors (always page on-call)
# ─────────────────────────────────────────────────────────────────────────────


class TamperAnomaly(ServerError):
    """Audit chain broken, evidence tampered, RLS violation."""

    code = "internal_error"
    http_status = 500


class DeterminismAnomaly(ServerError):
    """Replay drift detected."""

    code = "internal_error"
    http_status = 500
