"""Nexus-owned capability invocation boundary.

The gateway is the only callable surface that framework agents receive for
business capabilities. Framework implementations must not receive direct
repository, database, HTTP, or arbitrary Python-callable access.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4

from .contracts import AgentContext, CapabilityDescriptor, SideEffectClass

ToolInvocationStatus = Literal["SUCCESS", "BLOCKED", "FAILED"]


@dataclass(frozen=True)
class AuthorizationDecision:
    """Policy decision captured for every capability invocation."""

    allowed: bool
    reason: str
    policy_id: str | None = None
    approver_id: UUID | None = None


@dataclass(frozen=True)
class ToolProvenance:
    """Tamper-evident metadata describing the invocation inputs and scope."""

    invocation_id: UUID
    invoked_at: datetime
    actor_id: UUID
    tenant_id: UUID
    workspace_id: UUID
    task_id: UUID
    trace_id: UUID
    capability_id: str
    capability_version: str
    world_state_version: int
    arguments_sha256: str


@dataclass(frozen=True)
class ToolInvocationResult:
    """Stable result envelope consumed by orchestration and NexusTrace."""

    invocation_id: UUID
    capability_id: str
    capability_version: str
    status: ToolInvocationStatus
    workspace_id: UUID
    task_id: UUID
    trace_id: UUID
    world_state_version: int
    side_effect: SideEffectClass
    authorization: AuthorizationDecision
    provenance: ToolProvenance
    data: dict[str, Any] | None = None
    evidence_refs: tuple[str, ...] = ()
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class CapabilityAuthorizer(Protocol):
    """Application-owned policy adapter; never implemented by an agent."""

    async def authorize(
        self,
        *,
        capability: CapabilityDescriptor,
        context: AgentContext,
    ) -> AuthorizationDecision:
        """Return the policy decision for one invocation."""


class CapabilityExecutor(Protocol):
    """Adapter for an already-authorized concrete business capability."""

    async def execute(
        self,
        *,
        capability: CapabilityDescriptor,
        arguments: dict[str, Any],
        context: AgentContext,
    ) -> dict[str, Any]:
        """Execute one capability without bypassing the gateway."""


class InvocationSchemaValidator(Protocol):
    """Injected schema validator for capability input contracts."""

    def validate(
        self,
        *,
        schema: dict[str, Any],
        arguments: dict[str, Any],
    ) -> None:
        """Raise ValueError when arguments violate the declared schema."""


class NexusTraceWriter(Protocol):
    """Application-owned provenance sink."""

    async def record_tool_invocation(
        self,
        *,
        result: ToolInvocationResult,
    ) -> None:
        """Persist the invocation/result trace."""


class ToolGateway(ABC):
    """Safe capability invocation surface exposed to agents."""

    @abstractmethod
    async def invoke(
        self,
        *,
        capability: CapabilityDescriptor,
        arguments: dict[str, Any],
        context: AgentContext,
    ) -> ToolInvocationResult:
        """Validate, authorize, execute, and trace one capability invocation."""
        raise NotImplementedError


def _arguments_digest(arguments: dict[str, Any]) -> str:
    """Create a stable digest without persisting raw arguments in the envelope."""

    payload = json.dumps(arguments, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(payload.encode("utf-8")).hexdigest()


class NexusToolGateway(ToolGateway):
    """Reference gateway with mechanical pre-execution safety checks.

    Business capabilities remain injected adapters. This class deliberately has
    no database, HTTP client, filesystem, or arbitrary callable access of its own.
    """

    def __init__(
        self,
        *,
        authorizer: CapabilityAuthorizer,
        executor: CapabilityExecutor,
        schema_validator: InvocationSchemaValidator,
        trace_writer: NexusTraceWriter,
    ) -> None:
        self._authorizer = authorizer
        self._executor = executor
        self._schema_validator = schema_validator
        self._trace_writer = trace_writer

    async def invoke(
        self,
        *,
        capability: CapabilityDescriptor,
        arguments: dict[str, Any],
        context: AgentContext,
    ) -> ToolInvocationResult:
        invocation_id = uuid4()
        provenance = ToolProvenance(
            invocation_id=invocation_id,
            invoked_at=datetime.now(UTC),
            actor_id=context.actor_id,
            tenant_id=context.tenant_id,
            workspace_id=context.workspace_id,
            task_id=context.task_id,
            trace_id=context.trace_id,
            capability_id=capability.capability_id,
            capability_version=capability.version,
            world_state_version=context.world_state_version,
            arguments_sha256=_arguments_digest(arguments),
        )

        authorization = AuthorizationDecision(
            allowed=False,
            reason="Capability is not present in the agent allow-list.",
        )

        if capability.capability_id not in context.allowed_capabilities:
            result = ToolInvocationResult(
                invocation_id=invocation_id,
                capability_id=capability.capability_id,
                capability_version=capability.version,
                status="BLOCKED",
                workspace_id=context.workspace_id,
                task_id=context.task_id,
                trace_id=context.trace_id,
                world_state_version=context.world_state_version,
                side_effect=capability.side_effect,
                authorization=authorization,
                provenance=provenance,
                error="CAPABILITY_NOT_ALLOWED",
            )
            await self._trace_writer.record_tool_invocation(result=result)
            return result

        if capability.budget_units > context.budget:
            authorization = AuthorizationDecision(
                allowed=False,
                reason="Capability budget exceeds the task budget.",
            )
            result = ToolInvocationResult(
                invocation_id=invocation_id,
                capability_id=capability.capability_id,
                capability_version=capability.version,
                status="BLOCKED",
                workspace_id=context.workspace_id,
                task_id=context.task_id,
                trace_id=context.trace_id,
                world_state_version=context.world_state_version,
                side_effect=capability.side_effect,
                authorization=authorization,
                provenance=provenance,
                error="BUDGET_EXCEEDED",
            )
            await self._trace_writer.record_tool_invocation(result=result)
            return result

        if context.deadline is not None and datetime.now(UTC) >= context.deadline:
            authorization = AuthorizationDecision(
                allowed=False,
                reason="Invocation deadline has elapsed.",
            )
            result = ToolInvocationResult(
                invocation_id=invocation_id,
                capability_id=capability.capability_id,
                capability_version=capability.version,
                status="BLOCKED",
                workspace_id=context.workspace_id,
                task_id=context.task_id,
                trace_id=context.trace_id,
                world_state_version=context.world_state_version,
                side_effect=capability.side_effect,
                authorization=authorization,
                provenance=provenance,
                error="DEADLINE_EXCEEDED",
            )
            await self._trace_writer.record_tool_invocation(result=result)
            return result

        if not isinstance(arguments, dict):
            raise TypeError("Capability arguments must be a dictionary.")

        try:
            self._schema_validator.validate(schema=capability.input_schema, arguments=arguments)
        except ValueError as exc:
            authorization = AuthorizationDecision(
                allowed=False,
                reason="Capability arguments violate the declared input schema.",
            )
            result = ToolInvocationResult(
                invocation_id=invocation_id,
                capability_id=capability.capability_id,
                capability_version=capability.version,
                status="BLOCKED",
                workspace_id=context.workspace_id,
                task_id=context.task_id,
                trace_id=context.trace_id,
                world_state_version=context.world_state_version,
                side_effect=capability.side_effect,
                authorization=authorization,
                provenance=provenance,
                error="INVALID_ARGUMENTS",
                metadata={"validation_error": str(exc)},
            )
            await self._trace_writer.record_tool_invocation(result=result)
            return result

        authorization = await self._authorizer.authorize(
            capability=capability,
            context=context,
        )
        if not authorization.allowed:
            result = ToolInvocationResult(
                invocation_id=invocation_id,
                capability_id=capability.capability_id,
                capability_version=capability.version,
                status="BLOCKED",
                workspace_id=context.workspace_id,
                task_id=context.task_id,
                trace_id=context.trace_id,
                world_state_version=context.world_state_version,
                side_effect=capability.side_effect,
                authorization=authorization,
                provenance=provenance,
                error="POLICY_DENIED",
            )
            await self._trace_writer.record_tool_invocation(result=result)
            return result

        if (
            capability.side_effect == "WRITE_CONSEQUENTIAL"
            and context.policy_context.get("execution_approved") is not True
        ):
            authorization = AuthorizationDecision(
                allowed=False,
                reason="Consequential execution requires an explicit approval checkpoint.",
                policy_id=authorization.policy_id,
                approver_id=authorization.approver_id,
            )
            result = ToolInvocationResult(
                invocation_id=invocation_id,
                capability_id=capability.capability_id,
                capability_version=capability.version,
                status="BLOCKED",
                workspace_id=context.workspace_id,
                task_id=context.task_id,
                trace_id=context.trace_id,
                world_state_version=context.world_state_version,
                side_effect=capability.side_effect,
                authorization=authorization,
                provenance=provenance,
                error="APPROVAL_REQUIRED",
            )
            await self._trace_writer.record_tool_invocation(result=result)
            return result

        try:
            data = await self._executor.execute(
                capability=capability,
                arguments=arguments,
                context=context,
            )
            evidence_refs = tuple(data.pop("evidence_refs", ())) if isinstance(data, dict) else ()
            if capability.evidence_required and not evidence_refs:
                result = ToolInvocationResult(
                    invocation_id=invocation_id,
                    capability_id=capability.capability_id,
                    capability_version=capability.version,
                    status="FAILED",
                    workspace_id=context.workspace_id,
                    task_id=context.task_id,
                    trace_id=context.trace_id,
                    world_state_version=context.world_state_version,
                    side_effect=capability.side_effect,
                    authorization=authorization,
                    provenance=provenance,
                    error="EVIDENCE_REQUIRED",
                )
            else:
                result = ToolInvocationResult(
                    invocation_id=invocation_id,
                    capability_id=capability.capability_id,
                    capability_version=capability.version,
                    status="SUCCESS",
                    workspace_id=context.workspace_id,
                    task_id=context.task_id,
                    trace_id=context.trace_id,
                    world_state_version=context.world_state_version,
                    side_effect=capability.side_effect,
                    authorization=authorization,
                    provenance=provenance,
                    data=data,
                    evidence_refs=evidence_refs,
                )
        except Exception as exc:  # noqa: BLE001 - gateway must trace adapter failures.
            result = ToolInvocationResult(
                invocation_id=invocation_id,
                capability_id=capability.capability_id,
                capability_version=capability.version,
                status="FAILED",
                workspace_id=context.workspace_id,
                task_id=context.task_id,
                trace_id=context.trace_id,
                world_state_version=context.world_state_version,
                side_effect=capability.side_effect,
                authorization=authorization,
                provenance=provenance,
                error="CAPABILITY_EXECUTION_FAILED",
                metadata={"exception_type": type(exc).__name__, "error_detail": str(exc)},
            )

        await self._trace_writer.record_tool_invocation(result=result)
        return result
