"""Execution context bound to user and agent operations.

Every significant operation must carry this context for telemetry, auditing, and multi-tenant isolation.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.common.capabilities import Capability, CapabilitySet
from app.common.errors import PermissionError
from app.common.ids import uuid7


@dataclass(frozen=True)
class ExecutionContext:
    """The execution context of a workflow or user action."""
    tenant_id: str
    organization_id: str
    workspace_id: str
    project_id: str | None
    user_id: str
    session_id: str | None
    correlation_id: str
    causation_id: str
    request_id: str
    agent_id: str | None
    capabilities: frozenset[str]
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_request(
        cls,
        principal: Any,
        workspace_id: str,
        organization_id: str,
        request_id: str | None = None,
        correlation_id: str | None = None,
        project_id: str | None = None,
    ) -> ExecutionContext:
        """Create an execution context directly from an incoming API request."""
        req_id = request_id or uuid7()
        corr_id = correlation_id or req_id
        caps = CapabilitySet.for_human_operator().to_list()

        user_id = getattr(principal, "user_id", None) or "usr_anonymous"
        tenant_id = getattr(principal, "tenant_id", None) or "default_tenant"
        session_id = getattr(principal, "session_id", None)

        return cls(
            tenant_id=tenant_id,
            organization_id=organization_id,
            workspace_id=workspace_id,
            project_id=project_id,
            user_id=user_id,
            session_id=session_id,
            correlation_id=corr_id,
            causation_id=req_id,
            request_id=req_id,
            agent_id=None,
            capabilities=frozenset(caps),
            metadata={},
        )

    @classmethod
    def create_system_context(
        cls,
        tenant_id: str = "default_tenant",
        organization_id: str = "default_org",
        workspace_id: str = "default_workspace",
        project_id: str | None = None,
        capabilities: frozenset[str] | None = None,
    ) -> ExecutionContext:
        """Create an execution context for system processes and internal tests."""
        req_id = uuid7()
        caps = capabilities or frozenset(CapabilitySet.for_human_operator().to_list())
        return cls(
            tenant_id=tenant_id,
            organization_id=organization_id,
            workspace_id=workspace_id,
            project_id=project_id,
            user_id="system_service",
            session_id="system_session",
            correlation_id=req_id,
            causation_id=req_id,
            request_id=req_id,
            agent_id=None,
            capabilities=caps,
            metadata={},
        )

    def child(self, causation_id: str) -> ExecutionContext:
        """Create a child execution context, preserving the overall correlation_id."""
        return ExecutionContext(
            tenant_id=self.tenant_id,
            organization_id=self.organization_id,
            workspace_id=self.workspace_id,
            project_id=self.project_id,
            user_id=self.user_id,
            session_id=self.session_id,
            correlation_id=self.correlation_id,
            causation_id=causation_id,
            request_id=uuid7(),
            agent_id=self.agent_id,
            capabilities=self.capabilities,
            metadata=dict(self.metadata),
        )

    def for_agent(self, agent_id: str, capabilities: frozenset[str]) -> ExecutionContext:
        """Derive an agent-scoped execution context restricted to certain capabilities."""
        return ExecutionContext(
            tenant_id=self.tenant_id,
            organization_id=self.organization_id,
            workspace_id=self.workspace_id,
            project_id=self.project_id,
            user_id=self.user_id,
            session_id=self.session_id,
            correlation_id=self.correlation_id,
            causation_id=self.request_id,
            request_id=uuid7(),
            agent_id=agent_id,
            capabilities=capabilities,
            metadata=dict(self.metadata),
        )

    def validate_capability(self, capability: Capability | str) -> None:
        """Raise PermissionError if context lacks the requested capability."""
        cap_str = capability.value if isinstance(capability, Capability) else capability
        if cap_str not in self.capabilities:
            raise PermissionError(f"Context lacks required capability: {cap_str}")

    def to_dict(self) -> dict[str, Any]:
        """Serialize the context to a standard dictionary format."""
        return {
            "tenant_id": self.tenant_id,
            "organization_id": self.organization_id,
            "workspace_id": self.workspace_id,
            "project_id": self.project_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "request_id": self.request_id,
            "agent_id": self.agent_id,
            "capabilities": list(self.capabilities),
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }


_current_execution_context: ContextVar[ExecutionContext | None] = ContextVar(
    "current_execution_context", default=None
)


def get_execution_context() -> ExecutionContext | None:
    """Return the currently bound ExecutionContext or None."""
    return _current_execution_context.get()


def require_execution_context() -> ExecutionContext:
    """Return the currently bound ExecutionContext or raise RuntimeError."""
    ctx = _current_execution_context.get()
    if ctx is None:
        raise RuntimeError("No execution context bound to the current context.")
    return ctx


def set_execution_context(ctx: ExecutionContext) -> Token[ExecutionContext | None]:
    """Bind an ExecutionContext to the current scope."""
    return _current_execution_context.set(ctx)


def reset_execution_context(token: Token[ExecutionContext | None]) -> None:
    """Reset the ExecutionContext based on a returned token."""
    _current_execution_context.reset(token)


@contextmanager
def with_execution_context(ctx: ExecutionContext) -> Iterator[None]:
    """Context manager for running operations within a specific ExecutionContext."""
    token = set_execution_context(ctx)
    try:
        yield
    finally:
        reset_execution_context(token)
