"""Test Security Boundary & Agent Capabilities — Program P.11.7 & P.11.8.

Verifies:
- Architectural enforcement of agent capability matrix (READ + PROPOSE vs EXECUTE: NONE)
- Blocking of direct external system execution attempts by autonomous agents
- Zero-trust cross-workspace tenant isolation
"""

from __future__ import annotations

from app.modules.multi_agent.agent_models import AgentRole
from app.modules.production_validation.security_boundary import (
    AgentCapability,
    AgentCapabilityGuard,
    TenantIsolationValidator,
)


class TestSecurityAndCapabilities:
    def test_agent_capabilities_and_execution_lock(self) -> None:
        """Specialist agents have READ and PROPOSE capabilities, but direct EXECUTE is locked."""
        guard = AgentCapabilityGuard()

        # 1. Sourcing Agent can read and propose
        can_read, msg_read = guard.verify_permission(
            AgentRole.SOURCING_SPECIALIST, AgentCapability.READ_WORLD_STATE
        )
        assert can_read is True

        can_propose, msg_prop = guard.verify_permission(
            AgentRole.SOURCING_SPECIALIST, AgentCapability.PROPOSE_MITIGATION
        )
        assert can_propose is True

        # 2. Sourcing Agent CANNOT directly execute external transactions
        can_exec, msg_exec = guard.verify_permission(
            AgentRole.SOURCING_SPECIALIST, AgentCapability.EXECUTE_EXTERNAL_SYSTEM
        )
        assert can_exec is False
        assert "Architectural Boundary Violation" in msg_exec
        assert "Execution must flow through ExecutionService" in msg_exec

        # 3. All other specialist roles have the same execution lock
        for role in [
            AgentRole.LOGISTICS_SPECIALIST,
            AgentRole.INVENTORY_SPECIALIST,
            AgentRole.PRODUCTION_SPECIALIST,
            AgentRole.EXECUTIVE_COORDINATOR,
        ]:
            can_e, _ = guard.verify_permission(role, AgentCapability.EXECUTE_EXTERNAL_SYSTEM)
            assert can_e is False

    def test_tenant_isolation_boundary(self) -> None:
        """Cross-tenant workspace access is strictly denied."""
        validator = TenantIsolationValidator()

        # Same workspace -> Valid
        assert validator.validate_isolation("ws_customer_a", "ws_customer_a") is True

        # Cross-workspace -> Denied
        assert validator.validate_isolation("ws_customer_a", "ws_customer_b") is False
        assert validator.validate_isolation("", "ws_customer_a") is False
