"""Agent Registry — tracks available agents and their status in the runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from app.common.ids import uuid7


class AgentType(StrEnum):
    """Types of specialist and generalist agents available."""

    SOURCING = "SOURCING"
    INVENTORY = "INVENTORY"
    LOGISTICS = "LOGISTICS"
    PRODUCTION = "PRODUCTION"
    SUPERVISOR = "SUPERVISOR"
    CUSTOM = "CUSTOM"


class AgentStatus(StrEnum):
    """Lifecycle status of a registered agent."""

    REGISTERED = "REGISTERED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class AgentHealth(StrEnum):
    """Health status of an agent."""

    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"
    UNKNOWN = "UNKNOWN"


@dataclass
class AgentDefinition:
    """Blueprint for registering a new agent."""

    agent_type: AgentType
    version: str
    organization_id: str
    workspace_id: str | None
    capabilities: frozenset[str]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    config: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentRegistration:
    """Registered agent instance in the runtime."""

    agent_id: str
    agent_type: AgentType
    version: str
    organization_id: str
    workspace_id: str | None
    capabilities: frozenset[str]
    status: AgentStatus
    health: AgentHealth
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    config: dict[str, Any]
    registered_at: datetime
    last_heartbeat: datetime | None
    metadata: dict[str, Any]


class AgentRegistry:
    """In-memory registry of runtime agents (to be DB-backed later)."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentRegistration] = {}

    def register(self, agent_def: AgentDefinition) -> AgentRegistration:
        """Register a new agent in the system."""
        agent_id = str(uuid7())
        reg = AgentRegistration(
            agent_id=agent_id,
            agent_type=agent_def.agent_type,
            version=agent_def.version,
            organization_id=agent_def.organization_id,
            workspace_id=agent_def.workspace_id,
            capabilities=agent_def.capabilities,
            status=AgentStatus.REGISTERED,
            health=AgentHealth.UNKNOWN,
            input_schema=agent_def.input_schema,
            output_schema=agent_def.output_schema,
            config=agent_def.config,
            registered_at=datetime.now(UTC),
            last_heartbeat=None,
            metadata=agent_def.metadata,
        )
        self._agents[agent_id] = reg
        return reg

    def deregister(self, agent_id: str) -> None:
        """Remove an agent from the registry."""
        self._agents.pop(agent_id, None)

    def get(self, agent_id: str) -> AgentRegistration | None:
        """Retrieve an agent by ID."""
        return self._agents.get(agent_id)

    def list_agents(
        self,
        org_id: str,
        workspace_id: str | None = None,
        status: AgentStatus | None = None,
    ) -> list[AgentRegistration]:
        """List agents matching criteria."""
        res = []
        for reg in self._agents.values():
            if (
                reg.organization_id == org_id
                and (workspace_id is None or reg.workspace_id == workspace_id)
                and (status is None or reg.status == status)
            ):
                res.append(reg)
        return res

    def update_health(self, agent_id: str, health: AgentHealth) -> None:
        """Update the health status of an agent."""
        if agent_id in self._agents:
            self._agents[agent_id].health = health
            self._agents[agent_id].last_heartbeat = datetime.now(UTC)

    def update_status(self, agent_id: str, status: AgentStatus) -> None:
        """Update the lifecycle status of an agent."""
        if agent_id in self._agents:
            self._agents[agent_id].status = status

    def is_available(self, agent_id: str) -> bool:
        """Check if an agent is active and healthy."""
        reg = self.get(agent_id)
        if not reg:
            return False
        return reg.status == AgentStatus.ACTIVE and reg.health in {
            AgentHealth.HEALTHY,
            AgentHealth.DEGRADED,
        }
