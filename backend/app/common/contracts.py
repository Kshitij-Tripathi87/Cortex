"""Service contracts defining boundaries between Cortex modules.

Standardizes request, response, and error formatting for internal module messaging.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class ResponseStatus(StrEnum):
    """The outcome status of a service operation."""

    SUCCESS = "success"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    ERROR = "error"


@dataclass(frozen=True)
class ServiceRequest:
    """Base standard structure for every service request."""

    request_id: str
    correlation_id: str
    causation_id: str
    tenant_id: str
    workspace_id: str
    idempotency_key: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    schema_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary form."""
        return {
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "tenant_id": self.tenant_id,
            "workspace_id": self.workspace_id,
            "idempotency_key": self.idempotency_key,
            "timestamp": self.timestamp.isoformat(),
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class ServiceResponse:
    """Base standard structure for every service response."""

    request_id: str
    correlation_id: str
    status: ResponseStatus
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    duration_ms: float = 0.0
    schema_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary form."""
        return {
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
            "status": self.status.value,
            "timestamp": self.timestamp.isoformat(),
            "duration_ms": self.duration_ms,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class ServiceError:
    """Standardized error output form within service responses."""

    code: str
    message: str
    details: list[dict[str, Any]] = field(default_factory=list)
    target: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary form."""
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
            "target": self.target,
        }


@dataclass(frozen=True)
class PaginatedResponse:
    """Response envelope for paginated sets of items."""

    items: list[Any]
    cursor: str | None
    has_more: bool
    total_count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary form."""
        return {
            "items": [item.to_dict() if hasattr(item, "to_dict") else item for item in self.items],
            "cursor": self.cursor,
            "has_more": self.has_more,
            "total_count": self.total_count,
        }


@dataclass(frozen=True)
class VersionedPayload:
    """Explicitly versioned payload wrapper for data contracts."""

    schema_version: str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary form."""
        return {
            "schema_version": self.schema_version,
            "payload": self.payload,
        }


@dataclass(frozen=True)
class IdempotencyRecord:
    """Persisted outcome used for evaluating idempotent retries."""

    idempotency_key: str
    tenant_id: str
    workspace_id: str
    response_payload: dict[str, Any]
    status_code: int
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary form."""
        return {
            "idempotency_key": self.idempotency_key,
            "tenant_id": self.tenant_id,
            "workspace_id": self.workspace_id,
            "response_payload": self.response_payload,
            "status_code": self.status_code,
            "created_at": self.created_at.isoformat(),
        }
