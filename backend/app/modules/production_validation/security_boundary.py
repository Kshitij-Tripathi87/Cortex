"""Security Boundary & Agent Capability Guard — Program P.11.7 & P.11.8.

Enforces:
- Architectural separation between agent reasoning and external execution
- Capability Matrix: Specialist Agents have READ and PROPOSE capabilities, but EXECUTE is locked
- Execution permissions restricted strictly to authorized ExecutionService
- Zero-trust multi-tenant workspace isolation
"""

from __future__ import annotations

from enum import StrEnum

from app.modules.multi_agent.agent_models import AgentRole


class AgentCapability(StrEnum):
    """Granular action permissions in the multi-agent system."""

    READ_WORLD_STATE = "read_world_state"
    READ_EVIDENCE = "read_evidence"
    READ_SIMULATION = "read_simulation"
    PROPOSE_MITIGATION = "propose_mitigation"
    CRITIQUE_PROPOSAL = "critique_proposal"
    EXECUTE_EXTERNAL_SYSTEM = "execute_external_system"


class AgentCapabilityGuard:
    """Architecturally enforces that Specialist Agents cannot directly execute enterprise transactions."""

    # Explicit capability matrix per role
    _CAPABILITY_MATRIX: dict[AgentRole, set[AgentCapability]] = {
        AgentRole.SOURCING_SPECIALIST: {
            AgentCapability.READ_WORLD_STATE,
            AgentCapability.READ_EVIDENCE,
            AgentCapability.READ_SIMULATION,
            AgentCapability.PROPOSE_MITIGATION,
            AgentCapability.CRITIQUE_PROPOSAL,
        },
        AgentRole.LOGISTICS_SPECIALIST: {
            AgentCapability.READ_WORLD_STATE,
            AgentCapability.READ_EVIDENCE,
            AgentCapability.READ_SIMULATION,
            AgentCapability.PROPOSE_MITIGATION,
            AgentCapability.CRITIQUE_PROPOSAL,
        },
        AgentRole.INVENTORY_SPECIALIST: {
            AgentCapability.READ_WORLD_STATE,
            AgentCapability.READ_EVIDENCE,
            AgentCapability.READ_SIMULATION,
            AgentCapability.PROPOSE_MITIGATION,
            AgentCapability.CRITIQUE_PROPOSAL,
        },
        AgentRole.PRODUCTION_SPECIALIST: {
            AgentCapability.READ_WORLD_STATE,
            AgentCapability.READ_EVIDENCE,
            AgentCapability.READ_SIMULATION,
            AgentCapability.PROPOSE_MITIGATION,
            AgentCapability.CRITIQUE_PROPOSAL,
        },
        AgentRole.EXECUTIVE_COORDINATOR: {
            AgentCapability.READ_WORLD_STATE,
            AgentCapability.READ_EVIDENCE,
            AgentCapability.READ_SIMULATION,
            AgentCapability.PROPOSE_MITIGATION,
            AgentCapability.CRITIQUE_PROPOSAL,
        },
    }

    def verify_permission(
        self,
        agent_role: AgentRole,
        capability: AgentCapability,
    ) -> tuple[bool, str]:
        """Verify whether an agent role is authorized for a capability."""
        allowed_caps = self._CAPABILITY_MATRIX.get(agent_role, set())

        if capability not in allowed_caps:
            if capability == AgentCapability.EXECUTE_EXTERNAL_SYSTEM:
                return (
                    False,
                    f"Architectural Boundary Violation: Agent '{agent_role.value}' is strictly forbidden from direct execution. Execution must flow through ExecutionService -> PolicyEngine -> Human Approval.",
                )
            return (
                False,
                f"Permission Denied: Agent '{agent_role.value}' lacks capability '{capability.value}'.",
            )

        return True, f"Capability '{capability.value}' authorized for '{agent_role.value}'."


class TenantIsolationValidator:
    """Enforces zero-trust cross-workspace isolation."""

    @staticmethod
    def validate_isolation(current_workspace_id: str, target_workspace_id: str) -> bool:
        """Verify that a request operates strictly within its tenant boundary."""
        if not current_workspace_id or not target_workspace_id:
            return False
        return current_workspace_id == target_workspace_id
