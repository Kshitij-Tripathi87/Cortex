"""Base Specialist Agent Architecture.

Program M.1 (Specialist Agent Abstraction):
Provides the standard protocol for:
- Domain state situational assessment
- Mitigation action proposal generation
- Peer review and critique formulation
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.modules.multi_agent.agent_models import (
    AgentCritique,
    AgentProposal,
    AgentRole,
)
from app.modules.world.world_models import WorldState


class SpecialistAgent(ABC):
    """Abstract base class for all specialist agents."""

    def __init__(self, role: AgentRole, name: str):
        self.role = role
        self.name = name

    @abstractmethod
    def evaluate_and_propose(
        self,
        world_state: WorldState,
    ) -> list[AgentProposal]:
        """Analyze the domain-specific world state and produce candidate proposals."""
        pass

    @abstractmethod
    def critique_proposal(
        self,
        proposal: AgentProposal,
        world_state: WorldState,
    ) -> AgentCritique:
        """Review another agent's proposal from this specialist's domain lens."""
        pass
