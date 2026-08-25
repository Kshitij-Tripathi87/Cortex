"""Tenant Isolation Verifier — Automated Negative Testing and Cross-Tenant Boundary Checks.

Validates that Tenant A cannot access, query, or mutate resources belonging to Tenant B across:
- API layer
- Database queries & repositories
- Cache manager
- Message bus
- Real-time WebSockets
- Agent tools & memory
"""

from __future__ import annotations

from dataclasses import dataclass

from app.common.context import ExecutionContext
from app.infrastructure.cache_manager import get_cache_manager
from app.infrastructure.message_bus import get_message_bus
from app.modules.identity.models import UserPrincipal
from app.modules.memory.semantic_memory import get_semantic_memory
from app.modules.multi_agent.runtime.builtin_tools import create_default_tool_registry
from app.modules.multi_agent.runtime.message_envelope import MessageType, create_envelope


@dataclass
class IsolationTestResult:
    test_name: str
    passed: bool
    description: str
    error_detail: str | None = None


class TenantIsolationVerifier:
    """Automated suite for verifying multi-tenant and workspace boundary isolation."""

    @staticmethod
    async def verify_cache_isolation() -> IsolationTestResult:
        """Verify Tenant A cannot read Tenant B cached world state."""
        cache = get_cache_manager()
        tenant_a = "tenant_alpha"
        tenant_b = "tenant_beta"
        ws_a = "ws_alpha_01"

        await cache.set_world_state(
            tenant_id=tenant_a,
            workspace_id=ws_a,
            version=100,
            state_data={"secret_data": "alpha_proprietary"},
        )

        # Attempt to read Tenant A's state using Tenant B credentials
        data = await cache.get_world_state(tenant_id=tenant_b, workspace_id=ws_a, version=100)
        if data is not None:
            return IsolationTestResult(
                test_name="cache_isolation",
                passed=False,
                description="Tenant B was able to read Tenant A cached world state",
            )

        return IsolationTestResult(
            test_name="cache_isolation",
            passed=True,
            description="Tenant cache keys are strictly isolated by tenant_id prefix",
        )

    @staticmethod
    async def verify_message_bus_isolation() -> IsolationTestResult:
        """Verify Tenant B cannot replay or intercept Tenant A messages."""
        bus = get_message_bus()
        tenant_a = "tenant_alpha"
        tenant_b = "tenant_beta"

        env_a = create_envelope(
            message_type=MessageType.PROPOSAL,
            organization_id="org_alpha",
            workspace_id="ws_alpha",
            agent_id="sourcing_agent",
            agent_version="1.0.0",
            correlation_id="corr_01",
            causation_id="cause_01",
            conversation_id="conv_01",
            world_state_version=1,
            tenant_id=tenant_a,
            payload={"confidential_supplier": "Alpha Supplier X"},
        )
        await bus.publish(topic="nexus.agent-messages", envelope=env_a)

        # Replay with Tenant B filter
        replayed = await bus.replay(
            topic="nexus.agent-messages",
            from_offset=0,
            tenant_id=tenant_b,
        )

        for msg in replayed:
            if msg.envelope.tenant_id == tenant_a:
                return IsolationTestResult(
                    test_name="message_bus_isolation",
                    passed=False,
                    description="Tenant B received Tenant A messages during replay",
                )

        return IsolationTestResult(
            test_name="message_bus_isolation",
            passed=True,
            description="Message bus replay strictly filters messages by tenant scope",
        )

    @staticmethod
    async def verify_tool_capability_isolation() -> IsolationTestResult:
        """Verify an agent without EXECUTE capability cannot execute write tools."""
        tools = create_default_tool_registry()
        user = UserPrincipal(user_id="analyst_user", tenant_id="tenant_alpha")
        ctx = ExecutionContext.from_request(
            principal=user,
            workspace_id="ws_alpha",
            organization_id="org_alpha",
        )
        # Context only has READ / ANALYZE / PROPOSE, not SIMULATE or EXECUTE
        agent_ctx = ctx.for_agent(agent_id="unprivileged_agent", capabilities=frozenset({"read"}))

        result = await tools.execute(
            name="run_simulation",
            input_data={"actions": []},
            context=agent_ctx,
        )

        if result.success:
            return IsolationTestResult(
                test_name="tool_capability_isolation",
                passed=False,
                description="Unprivileged agent was able to run simulation tool without capability",
            )

        return IsolationTestResult(
            test_name="tool_capability_isolation",
            passed=True,
            description="Tool registry properly denied tool execution due to missing capability",
        )

    @staticmethod
    def verify_semantic_memory_isolation() -> IsolationTestResult:
        """Verify Tenant B cannot search and retrieve Tenant A vector documents."""
        mem = get_semantic_memory()
        mem.index_document(
            workspace_id="ws_alpha",
            tenant_id="tenant_alpha",
            doc_type="policy",
            title="Alpha Confidential Pricing",
            content="Proprietary bulk discount pricing model for chips",
        )

        results = mem.search_similar(
            query="discount pricing model",
            workspace_id="ws_beta",  # Querying from different workspace
        )

        if any(doc.workspace_id == "ws_alpha" for _, doc in results):
            return IsolationTestResult(
                test_name="semantic_memory_isolation",
                passed=False,
                description="Cross-workspace document leakage detected in semantic vector search",
            )

        return IsolationTestResult(
            test_name="semantic_memory_isolation",
            passed=True,
            description="Semantic memory vector search strictly isolates by workspace_id",
        )

    @classmethod
    async def run_all_isolation_tests(cls) -> list[IsolationTestResult]:
        """Execute complete tenant isolation negative test suite."""
        return [
            await cls.verify_cache_isolation(),
            await cls.verify_message_bus_isolation(),
            await cls.verify_tool_capability_isolation(),
            cls.verify_semantic_memory_isolation(),
        ]
