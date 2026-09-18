"""Nexus first-class task orchestration boundary."""

from .capability_registry import (
    AuthorizedCapabilitySet,
    CapabilitySource,
    NexusCapabilityRegistry,
    ResolvedCapability,
    UnsupportedTaskCapabilityError,
)
from .contracts import (
    AgentContext,
    AgentProposal,
    CapabilityDescriptor,
    TaskContext,
    TaskPlan,
    TaskPlanStep,
    TaskResult,
)
from .executor import NexusTaskExecutor, StepOutcome
from .orchestrator import NexusOrchestrator
from .planner import NexusTaskPlanner
from .synthesis import DeterministicTaskSynthesizer, TaskSynthesizer
from .task_intent import EvidenceRequirement, RiskClass, TaskIntent, TimeHorizon
from .tool_gateway import (
    AuthorizationDecision,
    NexusToolGateway,
    ToolGateway,
    ToolInvocationResult,
    ToolProvenance,
)

__all__ = [
    "AgentContext",
    "AgentProposal",
    "AuthorizationDecision",
    "AuthorizedCapabilitySet",
    "CapabilityDescriptor",
    "CapabilitySource",
    "DeterministicTaskSynthesizer",
    "EvidenceRequirement",
    "NexusCapabilityRegistry",
    "NexusOrchestrator",
    "NexusTaskExecutor",
    "NexusTaskPlanner",
    "NexusToolGateway",
    "ResolvedCapability",
    "RiskClass",
    "StepOutcome",
    "TaskContext",
    "TaskIntent",
    "TaskPlan",
    "TaskPlanStep",
    "TaskResult",
    "TaskSynthesizer",
    "TimeHorizon",
    "ToolGateway",
    "ToolInvocationResult",
    "ToolProvenance",
    "UnsupportedTaskCapabilityError",
]
