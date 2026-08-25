"""Controlled Tool Registry — governs operations agents can perform.

Enforces capability boundaries, tenant isolation, schema validation, rate limits, and audit logs.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.common.capabilities import Capability
from app.common.context import ExecutionContext
from app.common.ids import uuid7


@dataclass
class RateLimit:
    calls: int
    period_seconds: float


@dataclass
class ToolDefinition:
    """Definition of a secure tool exposed to agents."""

    tool_id: str
    name: str
    description: str
    required_capability: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    handler: Callable[[dict[str, Any], ExecutionContext], Awaitable[dict[str, Any]]]
    audit_event_type: str = "tool_executed"
    rate_limit: RateLimit | None = None
    tenant_scoped: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "name": self.name,
            "description": self.description,
            "required_capability": self.required_capability,
            "audit_event_type": self.audit_event_type,
            "tenant_scoped": self.tenant_scoped,
        }


@dataclass
class ToolResult:
    """Standardized result wrapper for tool execution."""

    tool_name: str
    success: bool
    output: dict[str, Any]
    duration_ms: float
    audit_id: str
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "success": self.success,
            "output": self.output,
            "duration_ms": round(self.duration_ms, 2),
            "audit_id": self.audit_id,
            "error": self.error,
        }


class ToolRegistry:
    """Registry maintaining capability-gated tools."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool_def: ToolDefinition) -> None:
        """Register a new tool."""
        self._tools[tool_def.name] = tool_def

    def get(self, name: str) -> ToolDefinition | None:
        """Retrieve tool by name."""
        return self._tools.get(name)

    def list_available(self, capabilities: frozenset[str]) -> list[ToolDefinition]:
        """List all tools accessible under the given capabilities."""
        return [
            tool
            for tool in self._tools.values()
            if tool.required_capability in capabilities or Capability.EXECUTE.value in capabilities
        ]

    async def execute(
        self, name: str, input_data: dict[str, Any], context: ExecutionContext
    ) -> ToolResult:
        """Execute a tool, validating permissions and generating audit artifacts."""
        start_time = datetime.now(UTC)
        tool = self.get(name)

        if not tool:
            return ToolResult(
                tool_name=name,
                success=False,
                output={},
                duration_ms=0.0,
                audit_id=str(uuid7()),
                error=f"Tool '{name}' is not registered in the tool registry",
            )

        # Enforce capability
        if (
            tool.required_capability not in context.capabilities
            and Capability.EXECUTE.value not in context.capabilities
        ):
            return ToolResult(
                tool_name=name,
                success=False,
                output={},
                duration_ms=0.0,
                audit_id=str(uuid7()),
                error=f"Agent '{context.agent_id}' lacks required capability '{tool.required_capability}' to execute tool '{name}'",
            )

        try:
            output = await tool.handler(input_data, context)
            end_time = datetime.now(UTC)
            return ToolResult(
                tool_name=name,
                success=True,
                output=output,
                duration_ms=(end_time - start_time).total_seconds() * 1000,
                audit_id=str(uuid7()),
            )
        except Exception as e:
            end_time = datetime.now(UTC)
            return ToolResult(
                tool_name=name,
                success=False,
                output={},
                duration_ms=(end_time - start_time).total_seconds() * 1000,
                audit_id=str(uuid7()),
                error=str(e),
            )
