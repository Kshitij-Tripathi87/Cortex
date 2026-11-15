"""Nexus-owned contracts for framework-backed multi-agent orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from .task_intent import TaskIntent

SideEffectClass = Literal[
    "READ",
    "ANALYZE",
    "SIMULATE",
    "PROPOSE",
    "WRITE_REVERSIBLE",
    "WRITE_CONSEQUENTIAL",
]


@dataclass(frozen=True)
class CapabilityDescriptor:
    capability_id: str
    name: str
    version: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    side_effect: SideEffectClass
    authorization: tuple[str, ...] = ()
    timeout_seconds: float = 30.0
    budget_units: float = 1.0
    evidence_required: bool = True


@dataclass(frozen=True)
class AgentContext:
    workspace_id: UUID
    tenant_id: UUID
    task_id: UUID
    trace_id: UUID
    actor_id: UUID
    world_state_version: int
    entity_ids: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    allowed_capabilities: tuple[str, ...] = ()
    policy_context: dict[str, Any] = field(default_factory=dict)
    budget: float = 100.0
    deadline: datetime | None = None


@dataclass(frozen=True)
class TaskContext:
    task_id: UUID
    workspace_id: UUID
    tenant_id: UUID
    trace_id: UUID
    actor_id: UUID
    intent: TaskIntent
    objective: str
    constraints: dict[str, Any]
    world_state_version: int
    selected_entities: tuple[str, ...] = ()
    graph_context: dict[str, Any] = field(default_factory=dict)
    evidence_refs: tuple[str, ...] = ()
    capabilities: tuple[CapabilityDescriptor, ...] = ()
    policy_context: dict[str, Any] = field(default_factory=dict)
    scenario_context: dict[str, Any] = field(default_factory=dict)
    budget: float = 100.0
    deadline: datetime | None = None


@dataclass(frozen=True)
class TaskPlanStep:
    step_id: str
    title: str
    agent_role: str
    dependencies: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    expected_outputs: tuple[str, ...] = ()


@dataclass(frozen=True)
class TaskPlan:
    task_id: UUID
    objective: str
    steps: tuple[TaskPlanStep, ...]
    assumptions: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentProposal:
    agent_id: str
    agent_role: str
    statement: str
    actions: tuple[dict[str, Any], ...] = ()
    evidence_refs: tuple[str, ...] = ()
    confidence: float = 0.0
    assumptions: tuple[str, ...] = ()


@dataclass(frozen=True)
class TaskResult:
    task_id: UUID
    status: Literal["COMPLETED", "BLOCKED", "FAILED", "AWAITING_APPROVAL"]
    recommendation: str | None = None
    proposals: tuple[AgentProposal, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    trace_id: UUID | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
