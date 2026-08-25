"""Multi-Agent Models — Immutable Data Contracts for Specialist Autonomous Agents.

Program M (Multi-Agent Coordination & Autonomous Specialist Agents):
- M.1: Agent Roles & Capabilities
- M.2: Proposals & Critique Messages
- M.3: Deliberation Rounds & Consensus Plans
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from app.modules.rl.rl_models import MitigationAction


class AgentRole(StrEnum):
    """Specialized functional domain roles for agents."""

    SOURCING_SPECIALIST = "sourcing_specialist"
    LOGISTICS_SPECIALIST = "logistics_specialist"
    INVENTORY_SPECIALIST = "inventory_specialist"
    PRODUCTION_SPECIALIST = "production_specialist"
    EXECUTIVE_COORDINATOR = "executive_coordinator"


@dataclass(frozen=True)
class AgentProposal:
    """A mitigation proposal formulated by a domain specialist agent."""

    proposal_id: str
    agent_role: AgentRole
    agent_name: str
    proposed_action: MitigationAction
    estimated_cost_usd: float
    estimated_revenue_protected_usd: float
    confidence_score: float  # 0.0 - 1.0
    domain_rationale: str
    supporting_evidence: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "agent_role": self.agent_role.value,
            "agent_name": self.agent_name,
            "proposed_action": self.proposed_action.to_dict(),
            "estimated_cost_usd": self.estimated_cost_usd,
            "estimated_revenue_protected_usd": self.estimated_revenue_protected_usd,
            "confidence_score": round(self.confidence_score, 4),
            "domain_rationale": self.domain_rationale,
            "supporting_evidence": list(self.supporting_evidence),
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass(frozen=True)
class AgentCritique:
    """Peer review critique from one specialist agent regarding another agent's proposal."""

    critique_id: str
    target_proposal_id: str
    reviewer_role: AgentRole
    supports_proposal: bool
    risk_objections: list[str] = field(default_factory=list)
    suggested_modifications: dict[str, Any] = field(default_factory=dict)
    feasibility_score: float = 1.0  # 0.0 - 1.0
    critique_rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "critique_id": self.critique_id,
            "target_proposal_id": self.target_proposal_id,
            "reviewer_role": self.reviewer_role.value,
            "supports_proposal": self.supports_proposal,
            "risk_objections": list(self.risk_objections),
            "suggested_modifications": dict(self.suggested_modifications),
            "feasibility_score": round(self.feasibility_score, 4),
            "critique_rationale": self.critique_rationale,
        }


@dataclass(frozen=True)
class CoordinatedMitigationPlan:
    """Final consensus plan synthesized by the Executive Coordinator."""

    plan_id: str
    workspace_id: str
    world_id: str
    selected_actions: list[MitigationAction]
    total_cost_usd: float
    total_protected_revenue_usd: float
    consensus_score: float  # 0.0 - 1.0
    participating_agents: list[AgentRole]
    proposals_evaluated: list[AgentProposal]
    peer_critiques: list[AgentCritique]
    coordination_summary: str
    trade_off_analysis: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "workspace_id": self.workspace_id,
            "world_id": self.world_id,
            "selected_actions": [a.to_dict() for a in self.selected_actions],
            "total_cost_usd": round(self.total_cost_usd, 2),
            "total_protected_revenue_usd": round(self.total_protected_revenue_usd, 2),
            "consensus_score": round(self.consensus_score, 4),
            "participating_agents": [r.value for r in self.participating_agents],
            "proposals_evaluated": [p.to_dict() for p in self.proposals_evaluated],
            "peer_critiques": [c.to_dict() for c in self.peer_critiques],
            "coordination_summary": self.coordination_summary,
            "trade_off_analysis": self.trade_off_analysis,
            "created_at": self.created_at.isoformat(),
        }
