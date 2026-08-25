"""Multi-Agent Service Layer.

Program M (Multi-Agent Coordination & Autonomous Specialist Agents):
Provides the unified service facade for multi-agent coordination, deliberation,
and consensus plan generation.
"""

from __future__ import annotations

from typing import Any

from app.modules.multi_agent.agent_models import (
    CoordinatedMitigationPlan,
)
from app.modules.multi_agent.consensus_engine import MultiAgentConsensusEngine
from app.modules.world.world_models import WorldState


class MultiAgentService:
    """Service orchestrator for autonomous specialist agents."""

    def __init__(self, consensus_engine: MultiAgentConsensusEngine | None = None):
        self.consensus_engine = consensus_engine or MultiAgentConsensusEngine()

    def coordinate_mitigation(
        self,
        world_state: WorldState,
    ) -> CoordinatedMitigationPlan:
        """Run 3-round deliberation across specialist agents to produce a consensus plan."""
        return self.consensus_engine.deliberate(world_state)

    def list_active_agents(self) -> list[dict[str, Any]]:
        """Return list of active specialist agents and their capabilities."""
        return [
            {
                "role": agent.role.value,
                "name": agent.name,
                "domain": agent.role.name,
            }
            for agent in self.consensus_engine.specialists
        ]
