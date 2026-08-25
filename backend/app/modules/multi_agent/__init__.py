"""Multi-Agent Module — Autonomous Specialist Agents & Consensus Coordination.

Program M:
- M.1: Base Specialist Agent & Protocol (SpecialistAgent, AgentRole)
- M.2: Specialist Agents (SourcingAgent, InventoryAgent, LogisticsAgent, ProductionAgent)
- M.3: Deliberation & Consensus Engine (MultiAgentConsensusEngine)
- M.4: Multi-Agent Service (MultiAgentService)
"""

from app.modules.multi_agent.agent_models import (
    AgentCritique,
    AgentProposal,
    AgentRole,
    CoordinatedMitigationPlan,
)
from app.modules.multi_agent.agent_service import MultiAgentService
from app.modules.multi_agent.agents.inventory_agent import InventoryAgent
from app.modules.multi_agent.agents.logistics_agent import LogisticsAgent
from app.modules.multi_agent.agents.production_agent import ProductionAgent
from app.modules.multi_agent.agents.sourcing_agent import SourcingAgent
from app.modules.multi_agent.base_agent import SpecialistAgent
from app.modules.multi_agent.consensus_engine import MultiAgentConsensusEngine

__all__ = [
    # Models
    "AgentCritique",
    "AgentProposal",
    "AgentRole",
    "CoordinatedMitigationPlan",
    # Agents
    "InventoryAgent",
    "LogisticsAgent",
    "MultiAgentConsensusEngine",
    # Service & Engine
    "MultiAgentService",
    "ProductionAgent",
    "SourcingAgent",
    "SpecialistAgent",
]
