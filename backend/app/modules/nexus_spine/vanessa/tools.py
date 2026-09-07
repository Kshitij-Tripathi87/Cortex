"""Nexus Vanessa — Tool Registry.

Vanessa is grounded by deterministic tools, NOT by raw LLM generation. Every
question she answers flows through one of these tools; each tool has a
typed input/output schema, an authorization requirement, and a deterministic
implementation that reads from the WorldModelRepository, DemandEngine,
TruthLoop, and DecisionMemory.

The architecture:
    User → intent → permission check → tool call → grounded answer

LLM is used only for intent classification and natural-language rendering
of structured results. The LLM never invents facts; it only paraphrases
what the tools returned.

This is the pattern Palantir uses for AIP: scoped permissions, deterministic
operational logic, LLM as the reasoning interface on top.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ToolPermission(StrEnum):
    """Permission tier required to invoke a tool."""

    PUBLIC = "public"
    AUTHENTICATED = "authenticated"
    ANALYST = "analyst"
    OPERATOR = "operator"
    ADMIN = "admin"


@dataclass(frozen=True)
class ToolCall:
    """A single tool invocation request."""

    tool_name: str
    arguments: dict[str, Any]
    requester_role: str
    requester_id: str
    tenant_id: UUID
    workspace_id: UUID
    call_id: UUID = field(default_factory=uuid4)
    timestamp: datetime = field(default_factory=_utc_now)


@dataclass(frozen=True)
class ToolResult:
    """The structured result of a tool invocation.

    Always carries: ok flag, structured payload, and an evidence trail so
    Vanessa can cite exactly which tool produced which number.
    """

    call_id: UUID
    tool_name: str
    ok: bool
    payload: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    evidence: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_id": str(self.call_id),
            "tool_name": self.tool_name,
            "ok": self.ok,
            "payload": self.payload,
            "error": self.error,
            "evidence": list(self.evidence),
            "timestamp": self.timestamp.isoformat(),
        }


class Tool(ABC):
    """Base class for Vanessa's grounded tools."""

    name: str
    description: str
    permission: ToolPermission
    input_schema: type[BaseModel]

    @abstractmethod
    def invoke(self, call: ToolCall) -> ToolResult: ...


class ToolRegistry:
    """Catalog of all grounded tools available to Vanessa.

    Tools are registered by `name`. Each invocation enforces:
    - tool exists
    - caller's role meets the tool's permission tier
    - arguments conform to the tool's input schema
    - the tool's deterministic implementation runs against the live world
      model / demand engine / decision memory
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "permission": t.permission.value,
                "input_schema": t.input_schema.__name__,
            }
            for t in self._tools.values()
        ]

    def invoke(self, call: ToolCall) -> ToolResult:
        tool = self._tools.get(call.tool_name)
        if tool is None:
            return ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                ok=False,
                error=f"unknown tool: {call.tool_name}",
            )
        if not _role_meets(call.requester_role, tool.permission):
            return ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                ok=False,
                error=f"role '{call.requester_role}' insufficient for tool '{call.tool_name}' (requires {tool.permission.value})",
            )
        # Validate arguments against the schema
        try:
            tool.input_schema.model_validate(call.arguments)
        except Exception as exc:
            return ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                ok=False,
                error=f"invalid arguments: {exc}",
            )
        try:
            return tool.invoke(call)
        except Exception as exc:
            return ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                ok=False,
                error=f"tool execution failed: {exc}",
            )


_ROLE_ORDER = {
    ToolPermission.PUBLIC: 0,
    ToolPermission.AUTHENTICATED: 1,
    ToolPermission.ANALYST: 2,
    ToolPermission.OPERATOR: 3,
    ToolPermission.ADMIN: 4,
}


def _role_meets(role: str, required: ToolPermission) -> bool:
    """Map a requester role string to a permission tier.

    Roles: viewer/anonymous → PUBLIC, analyst → ANALYST, operator → OPERATOR,
    system_admin/admin → ADMIN. Unknown roles default to AUTHENTICATED.
    """
    role_lower = role.lower()
    if role_lower in {"system_admin", "admin", "tenant_admin"}:
        tier = ToolPermission.ADMIN
    elif role_lower in {"operator", "workspace_admin"}:
        tier = ToolPermission.OPERATOR
    elif role_lower in {"analyst", "planner"}:
        tier = ToolPermission.ANALYST
    elif role_lower in {"authenticated"}:
        tier = ToolPermission.AUTHENTICATED
    else:
        tier = ToolPermission.PUBLIC
    return _ROLE_ORDER[tier] >= _ROLE_ORDER[required]


def reset_tool_registry() -> ToolRegistry:
    """Reset the process-wide tool registry to a fresh default registry.

    This is useful for tests to ensure a clean state.
    """
    from app.modules.nexus_spine.vanessa.builtin_tools import get_tool_registry as _get_builtin_registry
    return _get_builtin_registry()


def build_default_registry() -> ToolRegistry:
    """Build a ToolRegistry with all built-in tools registered.

    This is a convenience function that creates a ToolRegistry and registers
    all built-in tools from the builtin_tools module.
    """
    return reset_tool_registry()
