"""Deterministic synthesis of specialist proposals from gateway-governed steps.

Synthesis is Nexus-owned: proposals aggregate only the outputs and evidence
that survived the tool gateway, so an agent can never fabricate a proposal
from data it was not authorized to see. The Decision Room (later slice) owns
recommendation language; this layer produces grounded, attributable
proposals.
"""

from __future__ import annotations

from typing import Protocol

from .capability_registry import AuthorizedCapabilitySet
from .contracts import AgentProposal, TaskPlan
from .executor import StepOutcome

_CONFIDENCE_BY_AVAILABILITY = {"AVAILABLE": 0.8, "DEGRADED": 0.6, "UNAVAILABLE": 0.3}


class TaskSynthesizer(Protocol):
    """Turn executed plan step outcomes into grounded specialist proposals."""

    def synthesize(
        self,
        *,
        plan: TaskPlan,
        outcomes: dict[str, StepOutcome],
        capabilities: AuthorizedCapabilitySet | None,
    ) -> tuple[AgentProposal, ...]:
        """Return one proposal per successfully executed specialist step."""


class DeterministicTaskSynthesizer:
    """Framework-independent synthesis from gateway-governed step outcomes."""

    def synthesize(
        self,
        *,
        plan: TaskPlan,
        outcomes: dict[str, StepOutcome],
        capabilities: AuthorizedCapabilitySet | None,
    ) -> tuple[AgentProposal, ...]:
        proposals: list[AgentProposal] = []
        for step in plan.steps:
            outcome = outcomes[step.step_id]
            if outcome.status != "SUCCESS":
                continue
            resolved = capabilities.get_resolved(step.step_id) if capabilities else None
            agent_role = resolved.agent_role if resolved is not None else step.agent_role
            availability = resolved.availability if resolved is not None else "AVAILABLE"
            confidence = _CONFIDENCE_BY_AVAILABILITY.get(availability, 0.3)
            outputs = outcome.outputs
            proposals.append(
                AgentProposal(
                    agent_id=step.step_id,
                    agent_role=agent_role,
                    statement=(
                        f"{step.title} completed with {len(outputs)} governed capability "
                        "result(s) under Nexus authorization."
                    ),
                    actions=outputs,
                    evidence_refs=outcome.evidence_refs,
                    confidence=confidence,
                    assumptions=(
                        f"Availability at execution was {availability}.",
                        "Outputs were produced exclusively through the Nexus tool gateway.",
                    ),
                )
            )
        return tuple(proposals)
