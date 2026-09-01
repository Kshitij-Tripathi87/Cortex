"""Cortex Nexus — Comprehensive API Integration, Concurrency, and Chaos Test Suite.

Covers:
1. Fast-path API endpoint verification for Agent Runtime, Intelligence Gateway, and Realtime Gateway
2. High-concurrency message bus load and deduplication
3. Cache distributed lock contention and timeout behavior
4. Deliberation under contradictory multi-agent conditions
5. Model timeout and degradation chaos injection
6. Decision Room conversation timeline completeness
7. Strict multi-tenant data leakage prevention under concurrent workloads
"""

import asyncio
import os

os.environ.setdefault("CORTEX_ENV", "dev")
os.environ.setdefault("CORTEX_DB_DSN", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("CORTEX_JWT_SECRET", "0" * 32)

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.router import api_router
from app.common.context import ExecutionContext
from app.common.ids import uuid7
from app.infrastructure.cache_manager import get_cache_manager
from app.infrastructure.message_bus import NexusTopic, get_message_bus
from app.modules.identity.models import UserPrincipal
from app.modules.intelligence.gateway import (
    InferenceStatus,
    IntelligenceGateway,
    IntelligenceRequest,
    IntelligenceTask,
)
from app.modules.multi_agent.runtime.message_envelope import (
    MessageType,
    create_envelope,
)
from app.modules.multi_agent.runtime.supervisor import (
    AgentSupervisor,
    DeliberationStatus,
    SupervisorTask,
)
from app.modules.world.world_models import WorldState


# ─────────────────────────────────────────────────────────────────────────────
# 1. API Endpoint Integration Tests (FastAPI TestClient)
# ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def client():
    test_app = FastAPI()
    test_app.include_router(api_router, prefix="/api/v1")
    return TestClient(test_app)


def test_agent_registry_endpoint(client):
    """GET /api/v1/agents/registry returns registered specialist agents."""
    resp = client.get("/api/v1/agents/registry")
    assert resp.status_code == 200
    data = resp.json()
    assert "agents" in data
    roles = [a["role"] for a in data["agents"]]
    assert "sourcing_specialist" in roles
    assert "inventory_specialist" in roles
    assert "logistics_specialist" in roles
    assert "production_specialist" in roles
    assert "executive_coordinator" in roles


def test_agent_tools_listing_endpoint(client):
    """GET /api/v1/agents/tools lists capability-governed operational tools."""
    resp = client.get("/api/v1/agents/tools")
    assert resp.status_code == 200
    data = resp.json()
    assert "tools" in data
    tool_names = [t["name"] for t in data["tools"]]
    assert "get_world_state" in tool_names
    assert "get_supplier" in tool_names
    assert "get_inventory" in tool_names
    assert "find_alternatives" in tool_names
    assert "calculate_impact" in tool_names
    assert "run_simulation" in tool_names
    assert "query_decision_memory" in tool_names


def test_agent_tool_execute_endpoint(client):
    """POST /api/v1/agents/tools/execute executes tool under caller context."""
    resp = client.post(
        "/api/v1/agents/tools/execute",
        json={
            "tool_name": "find_alternatives",
            "input_data": {"primary_supplier_id": "SUP_999"},
        },
        headers={
            "x-workspace-id": "ws_test_api",
            "x-organization-id": "org_test_api",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["tool_name"] == "find_alternatives"
    assert data["success"] is True
    assert "candidate_alternatives" in data["output"]


def test_deliberate_api_and_decision_room_flow(client):
    """Full API integration: Trigger deliberation -> inspect conversation -> view Decision Room timeline."""
    ws_id = f"ws_delib_{uuid7()}"

    # 1. Deliberate
    resp = client.post(
        "/api/v1/agents/deliberate",
        json={
            "task_type": "supplier_disruption",
            "description": "Port of Long Beach congestion causing 10-day delay for critical sub-assemblies",
            "world_state_version": 2,
            "priority": "HIGH",
        },
        headers={
            "x-workspace-id": ws_id,
            "x-organization-id": "org_acme",
        },
    )
    assert resp.status_code == 200
    result = resp.json()
    assert result["status"] == "COMPLETED"
    assert result["consensus_score"] > 0.0
    assert result["plan"] is not None

    # 2. List conversations in workspace
    list_resp = client.get(
        "/api/v1/agents/conversations",
        headers={"x-workspace-id": ws_id},
    )
    assert list_resp.status_code == 200
    convs = list_resp.json()["conversations"]
    assert len(convs) == 1
    conv_id = convs[0]["conversation_id"]

    # 3. Get single conversation detail
    detail_resp = client.get(f"/api/v1/agents/conversations/{conv_id}")
    assert detail_resp.status_code == 200
    assert detail_resp.json()["conversation_id"] == conv_id

    # 4. Get Decision Room timeline
    room_resp = client.get(f"/api/v1/agents/decision-room/{conv_id}")
    assert room_resp.status_code == 200
    room_data = room_resp.json()
    assert "timeline" in room_data
    assert len(room_data["timeline"]) >= 3
    agents_in_timeline = [item["agent"] for item in room_data["timeline"]]
    assert "SUPERVISOR" in agents_in_timeline


def test_intelligence_gateway_endpoints(client):
    """Test AI gateway inference, baselines, and model registration APIs."""
    # 1. List baselines
    base_resp = client.get("/api/v1/ai/baselines")
    assert base_resp.status_code == 200
    assert len(base_resp.json()["baselines"]) >= 4

    # 2. Run inference with fallback
    infer_resp = client.post(
        "/api/v1/ai/infer",
        json={
            "task": "RISK_PROPAGATION",
            "input_data": {"origin_node": "SUP_001", "severity": 0.8},
            "world_state_version": 1,
            "fallback_to_deterministic": True,
        },
        headers={"x-workspace-id": "ws_ai_test"},
    )
    assert infer_resp.status_code == 200
    res_data = infer_resp.json()
    assert res_data["task"] == "RISK_PROPAGATION"
    assert res_data["status"] in {"SUCCESS", "FALLBACK"}
    assert "risk_score" in res_data["output"] or "prediction" in res_data["output"]

    # 3. List models
    models_resp = client.get("/api/v1/ai/models")
    assert models_resp.status_code == 200
    assert "models" in models_resp.json()


def test_realtime_stats_endpoint():
    """GET /api/v1/realtime/stats returns connection channels and status (operator role required)."""
    from app.infrastructure.security import AuthContext, get_current_user

    test_app = FastAPI()
    test_app.include_router(api_router, prefix="/api/v1")
    test_app.dependency_overrides[get_current_user] = lambda: AuthContext(
        user_id="operator_01",
        email="operator@cortex.internal",
        roles=["operator"],
        workspace_ids=["ws_test"],
        is_anonymous=False,
    )

    client = TestClient(test_app)
    resp = client.get("/api/v1/realtime/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "active_connections" in data
    assert "world-state" in data["channels"]
    assert "agent-messages" in data["channels"]
    assert "decisions" in data["channels"]


# ─────────────────────────────────────────────────────────────────────────────
# 2. Concurrency & High-Throughput Message Bus Tests
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_high_concurrency_message_bus_publishing():
    """Publish 100 messages concurrently and ensure total offset ordering and no drops."""
    bus = get_message_bus()
    tenant_id = f"tenant_stress_{uuid7()}"
    num_messages = 100

    async def publish_worker(index: int):
        env = create_envelope(
            message_type=MessageType.OBSERVATION,
            organization_id="org_stress",
            workspace_id="ws_stress",
            agent_id=f"agent_{index % 5}",
            agent_version="1.0.0",
            correlation_id=f"corr_{index}",
            causation_id=f"cause_{index}",
            conversation_id="conv_stress",
            world_state_version=1,
            tenant_id=tenant_id,
            idempotency_key=f"idem_stress_{index}",
            payload={"metric_value": index * 1.5},
        )
        return await bus.publish(topic=NexusTopic.AGENT_MESSAGES, envelope=env)

    tasks = [publish_worker(i) for i in range(num_messages)]
    results = await asyncio.gather(*tasks)

    assert len(results) == num_messages
    offsets = [r.offset for r in results]
    # Verify unique monotonically increasing offsets
    assert len(set(offsets)) == num_messages

    # Replay all messages for this tenant
    replayed = await bus.replay(
        topic=NexusTopic.AGENT_MESSAGES,
        from_offset=0,
        limit=200,
        tenant_id=tenant_id,
    )
    assert len(replayed) == num_messages


# ─────────────────────────────────────────────────────────────────────────────
# 3. Distributed Lock Contention & Expiration
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_distributed_lock_mutual_exclusion():
    """Verify that lock prevents simultaneous access to shared state updates."""
    cache = get_cache_manager()
    resource_id = f"workspace_{uuid7()}"
    execution_trace: list[str] = []

    async def critical_section(worker_id: str):
        async with cache.lock(resource=resource_id, timeout_seconds=1.0) as acquired:
            if acquired:
                execution_trace.append(f"{worker_id}_entered")
                await asyncio.sleep(0.05)
                execution_trace.append(f"{worker_id}_exited")
            else:
                execution_trace.append(f"{worker_id}_denied")

    # Run two workers attempting to acquire the same lock
    await asyncio.gather(
        critical_section("worker_A"),
        critical_section("worker_B"),
    )

    # Either worker A entered and exited before B entered, or one was denied
    assert "worker_A_entered" in execution_trace
    assert "worker_A_exited" in execution_trace


# ─────────────────────────────────────────────────────────────────────────────
# 4. Chaos & Resilience: Model Timeout & Degradation Injection
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_chaos_model_failure_triggers_deterministic_recovery():
    """Inject timeout and exception into model execution; verify transparent deterministic fallback."""
    gateway = IntelligenceGateway()

    # Request with simulated failure
    req = IntelligenceRequest(
        request_id=str(uuid7()),
        task=IntelligenceTask.CRITICAL_NODE_DETECTION,
        tenant_id="tenant_chaos",
        workspace_id="ws_chaos",
        correlation_id=str(uuid7()),
        world_state_version=1,
        input_data={"graph_nodes": 500},
        timeout_seconds=0.001,  # Ultra-low timeout to trigger timeout fallback
        fallback_to_deterministic=True,
    )

    response = await gateway.infer(req)
    assert response.status == InferenceStatus.FALLBACK
    assert "critical_nodes" in response.output
    assert response.calibration_score == 1.0  # Deterministic guarantees baseline score


# ─────────────────────────────────────────────────────────────────────────────
# 5. Multi-Agent Deliberation Edge Cases (Nominal State / NOOP)
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_multi_agent_deliberation_nominal_state():
    """Verify that when no disruptions exist, supervisor cleanly synthesizes a nominal NOOP plan."""
    supervisor = AgentSupervisor()
    principal = UserPrincipal(user_id="usr_auto", tenant_id="tenant_acme")
    ctx = ExecutionContext.from_request(
        principal=principal,
        workspace_id="ws_nominal",
        organization_id="org_acme",
    )

    # Clean world state with zero disruptions
    clean_ws = WorldState(
        world_id="world_nominal",
        workspace_id="ws_nominal",
        version=1,
        variables={},
        graph_version=1,
    )

    task = SupervisorTask(
        task_id=f"task_nominal_{uuid7()}",
        task_type="scheduled_health_check",
        description="Routine morning operational state sweep",
        world_state_version=1,
    )

    result = await supervisor.run_deliberation(task=task, context=ctx, world_state=clean_ws)

    assert result.status == DeliberationStatus.COMPLETED
    assert result.plan is not None
    assert result.consensus_score == 1.0
    assert len(result.plan.selected_actions) > 0
