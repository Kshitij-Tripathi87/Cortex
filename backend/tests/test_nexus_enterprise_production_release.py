"""Cortex Nexus — Enterprise Production Release Candidate Test Suite.

Comprehensive validation covering:
1. Frozen Canonical Message Schema (v1.0) serialization & deserialization
2. Message Bus 2.0 DLQ poison message isolation, out-of-order resequencing, & consumer groups
3. Supervisor 2.0 fault tolerance: stale state rejection, timeout resilience, policy gating
4. AI Lifecycle 5-part provenance tracking (model, dataset, feature, eval, policy)
5. Real-Time State Pipeline: Event -> DB -> Bus -> Projection -> Cache -> Memory -> UI Fanout
6. Memory 2.0 Closed-Loop Feedback: Outcome -> Prediction Error -> Vector Lesson Indexing
7. Enterprise Hierarchy: Multi-user organization (Alice/Bob/Charlie), workspace scoping, CLI tokens
8. Nexus CLI operational verification
"""

import asyncio
import os
from datetime import UTC, datetime

os.environ.setdefault("CORTEX_ENV", "dev")
os.environ.setdefault("CORTEX_DB_DSN", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("CORTEX_JWT_SECRET", "0" * 32)

import pytest

from app.cli.nexus_cli import NexusCLI
from app.common.context import ExecutionContext
from app.common.ids import uuid7
from app.infrastructure.message_bus import BusMessage, MessageBus, NexusTopic
from app.infrastructure.state_pipeline import get_state_pipeline
from app.modules.access.hierarchy import (
    EnterpriseIdentityStore,
    OrgRole,
)
from app.modules.events.event_models import InventoryChanged
from app.modules.intelligence.gateway import (
    InferenceStatus,
    IntelligenceGateway,
    IntelligenceRequest,
    IntelligenceTask,
)
from app.modules.memory.coordinator import get_memory_coordinator
from app.modules.memory.decision_memory import DecisionRecord
from app.modules.multi_agent.runtime.contracts_v1 import (
    CanonicalAgentMessage,
    CanonicalMessageType,
    build_canonical_message,
)
from app.modules.multi_agent.runtime.supervisor import (
    AgentSupervisor,
    DeliberationStatus,
    SupervisorConfig,
    SupervisorTask,
    TaskPriority,
)
from app.modules.world.world_models import StateVariable, StateVariableType, WorldState


# ─────────────────────────────────────────────────────────────────────────────
# 1. Canonical Message Schema Freeze
# ─────────────────────────────────────────────────────────────────────────────
def test_canonical_message_schema_round_trip():
    """Verify frozen v1.0 canonical message envelope serialization and invariants."""
    msg = build_canonical_message(
        message_type=CanonicalMessageType.PROPOSAL,
        organization_id="org_apex_mobility",
        workspace_id="ws_detroit_plant",
        tenant_id="tenant_apex",
        project_id="proj_ev_2026",
        sender_id="sourcing_agent",
        sender_role="sourcing_specialist",
        sender_version="2.0.0",
        correlation_id="corr_123",
        causation_id="task_456",
        conversation_id="conv_789",
        world_state_version=42,
        payload={"action": "expedite_semiconductors", "cost_usd": 15000.0},
    )

    data = msg.to_dict()
    assert data["schema_version"] == "1.0"
    assert data["message_type"] == "nexus.agent.proposal"
    assert data["organization_id"] == "org_apex_mobility"
    assert data["world_state_version"] == 42
    assert data["payload"]["cost_usd"] == 15000.0

    hydrated = CanonicalAgentMessage.from_dict(data)
    assert hydrated.message_id == msg.message_id
    assert hydrated.message_type == CanonicalMessageType.PROPOSAL
    assert hydrated.tenant_id == "tenant_apex"
    assert hydrated.world_state_version == 42


# ─────────────────────────────────────────────────────────────────────────────
# 2. Message Bus 2.0 (DLQ, Consumer Groups, Resequencing)
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_message_bus_dlq_poison_isolation():
    """Verify poison messages failing 3 attempts are isolated in Dead Letter Queue."""
    bus = MessageBus(max_retries=3)
    dlq_received: list[BusMessage] = []

    # Faulty handler that always raises
    async def faulty_handler(msg: BusMessage):
        raise RuntimeError("Simulated consumer crash")

    bus.subscribe("test.failing.topic", faulty_handler)

    envelope = build_canonical_message(
        message_type=CanonicalMessageType.OBSERVATION,
        organization_id="org_test",
        workspace_id="ws_test",
        sender_id="sensor_01",
        correlation_id="c1",
        causation_id="c1",
        conversation_id="conv_1",
        world_state_version=1,
        payload={"error_sample": True},
    )

    await bus.publish("test.failing.topic", envelope)
    await asyncio.sleep(0.15)  # Allow async retries to exhaust

    stats = bus.get_topic_stats()
    assert stats["dlq_poison_messages"] >= 1
    dlq_messages = await bus.replay(NexusTopic.DLQ)
    assert len(dlq_messages) >= 1
    assert "Exhausted 3 attempts" in dlq_messages[0].error_reason


@pytest.mark.asyncio
async def test_message_bus_consumer_groups_and_resequencing():
    """Verify consumer group offset commits and causal out-of-order resequencer."""
    bus = MessageBus()
    group_id = "agent_supervisor_group"
    topic = NexusTopic.AGENT_MESSAGES

    for v in [1, 2, 3]:
        env = build_canonical_message(
            message_type=CanonicalMessageType.PROPOSAL,
            organization_id="org_test",
            workspace_id="ws_test",
            sender_id=f"agent_{v}",
            correlation_id="c1",
            causation_id="c1",
            conversation_id="conv_1",
            world_state_version=v,
            payload={"version": v},
            idempotency_key=f"idem_{v}",
        )
        await bus.publish(topic, env)

    batch_1 = await bus.fetch_next_batch(group_id, topic, batch_size=2)
    assert len(batch_1) == 2
    assert batch_1[0].offset == 0
    assert batch_1[1].offset == 1

    await bus.commit_offset(group_id, topic, batch_1[-1].offset)

    batch_2 = await bus.fetch_next_batch(group_id, topic, batch_size=2)
    assert len(batch_2) == 1
    assert batch_2[0].offset == 2

    # Test out-of-order resequencing
    msg_v5 = BusMessage(
        offset=10,
        topic=topic.value,
        key="ws_test",
        envelope=build_canonical_message(
            message_type=CanonicalMessageType.REVISION,
            organization_id="org_test",
            workspace_id="ws_test",
            sender_id="a1",
            correlation_id="c1",
            causation_id="c1",
            conversation_id="conv_seq",
            world_state_version=5,
            payload={},
        ),
    )
    msg_v2 = BusMessage(
        offset=11,
        topic=topic.value,
        key="ws_test",
        envelope=build_canonical_message(
            message_type=CanonicalMessageType.PROPOSAL,
            organization_id="org_test",
            workspace_id="ws_test",
            sender_id="a1",
            correlation_id="c1",
            causation_id="c1",
            conversation_id="conv_seq",
            world_state_version=2,
            payload={},
        ),
    )

    bus.buffer_and_resequence("conv_seq", msg_v5)
    resequenced = bus.buffer_and_resequence("conv_seq", msg_v2)
    assert len(resequenced) == 2
    assert resequenced[0].envelope.world_state_version == 2
    assert resequenced[1].envelope.world_state_version == 5


# ─────────────────────────────────────────────────────────────────────────────
# 3. Supervisor 2.0 Deliberation Protocol & Fault Tolerance
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_supervisor_stale_state_rejection():
    """Verify supervisor rejects tasks requiring newer state than provided."""
    supervisor = AgentSupervisor()
    ctx = ExecutionContext.create_system_context(
        tenant_id="tenant_apex",
        organization_id="org_apex",
        workspace_id="ws_detroit",
    )

    task = SupervisorTask(
        task_id="task_stale",
        task_type="SUPPLIER_DISRUPTION",
        description="Verify stale state rejection",
        world_state_version=10,
    )

    stale_state = WorldState(
        world_id="w1",
        workspace_id="ws_detroit",
        version=5,  # Stale: 5 < 10
        variables={},
        graph_version=1,
    )

    result = await supervisor.run_deliberation(task, ctx, stale_state)
    assert result.status == DeliberationStatus.STALE_STATE_REJECTED
    assert len(result.errors) >= 1
    assert "Stale World State rejected" in result.errors[0]


@pytest.mark.asyncio
async def test_supervisor_10_step_deliberation_and_decision_card():
    """Verify complete 10-step deliberation protocol, trade-off synthesis, and decision card."""
    supervisor = AgentSupervisor(
        config=SupervisorConfig(
            max_rounds=3,
            spending_limit_usd=500000.0,
            enable_parallel_execution=True,
        )
    )
    ctx = ExecutionContext.create_system_context(
        tenant_id="tenant_apex",
        organization_id="org_apex",
        workspace_id="ws_detroit",
    )

    task = SupervisorTask(
        task_id="task_disruption_01",
        task_type="FACILITY_FIRE_RESPONSE",
        description="Tier-1 semiconductor fabrication plant offline due to electrical fire.",
        world_state_version=1,
        priority=TaskPriority.CRITICAL,
    )

    state = WorldState(
        world_id="w_live",
        workspace_id="ws_detroit",
        version=1,
        variables={
            "lead_time_days": StateVariable(
                variable_id="lead_time_days",
                variable_type=StateVariableType.LEAD_TIME,
                entity_id="supplier_alpha",
                entity_type="supplier",
                value=45.0,
            ),
            "inventory_units": StateVariable(
                variable_id="inventory_units",
                variable_type=StateVariableType.INVENTORY,
                entity_id="fab_01",
                entity_type="warehouse",
                value=120.0,
            ),
        },
        graph_version=1,
    )

    result = await supervisor.run_deliberation(task, ctx, state)
    assert result.status == DeliberationStatus.COMPLETED
    assert result.decision_card is not None
    assert result.decision_card["policy_status"] == "COMPLIANT"
    assert result.plan is not None
    assert len(result.messages) >= 3


# ─────────────────────────────────────────────────────────────────────────────
# 4. AI Lifecycle 5-Part Provenance
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_intelligence_gateway_provenance_tracking():
    """Verify inference responses carry 5-part AI governance & provenance record."""
    gateway = IntelligenceGateway()
    req = IntelligenceRequest(
        request_id="req_prov_01",
        task=IntelligenceTask.SUPPLIER_SIMILARITY,
        tenant_id="tenant_apex",
        workspace_id="ws_detroit",
        correlation_id="corr_prov",
        world_state_version=1,
        input_data={"target_supplier": "supplier_tier1", "features": [0.85, 0.92]},
    )

    resp = await gateway.infer(req)
    assert resp.status in {InferenceStatus.SUCCESS, InferenceStatus.FALLBACK}
    assert resp.provenance is not None
    assert resp.provenance.dataset_version == "ds-2026-08-16"
    assert resp.provenance.feature_version == "feat-v1"
    assert resp.provenance.policy_version == "pol-v1"


# ─────────────────────────────────────────────────────────────────────────────
# 5. Real-Time State Pipeline & Latency Instrumentation
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_realtime_state_pipeline_end_to_end():
    """Verify Event -> DB -> Bus -> Projection -> Cache -> Memory -> UI with microsecond latencies."""
    pipeline = get_state_pipeline()
    ctx = ExecutionContext.create_system_context(
        tenant_id="tenant_apex",
        organization_id="org_apex",
        workspace_id="ws_detroit",
    )

    initial_state = WorldState(
        world_id="w_rt",
        workspace_id="ws_detroit",
        version=1,
        variables={
            "inventory_qty": StateVariable(
                variable_id="inventory_qty",
                variable_type=StateVariableType.INVENTORY,
                entity_id="warehouse_a",
                entity_type="warehouse",
                value=1000.0,
            )
        },
        graph_version=1,
    )

    event = InventoryChanged(
        event_id=f"evt_{uuid7()}",
        world_id="w_rt",
        workspace_id="ws_detroit",
        entity_type="warehouse",
        entity_id="warehouse_a",
        warehouse_id="warehouse_a",
        component_id="semiconductor_01",
        quantity_change=-200,
        reason="production_consumption",
        occurred_at=datetime.now(UTC),
    )

    res = await pipeline.ingest_event_and_propagate(event, initial_state, ctx)
    assert res.success is True
    assert res.new_world_state.version == 2
    assert res.latency_metrics.total_pipeline_latency_ms < 50.0  # <50ms end-to-end latency invariant

    stats = pipeline.get_latency_stats()
    assert stats["sample_count"] >= 1
    assert stats["avg_latency_ms"] >= 0.0


# ─────────────────────────────────────────────────────────────────────────────
# 6. Memory 2.0 Closed-Loop Flywheel
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_memory_closed_loop_outcome_and_lesson_vector_indexing():
    """Verify realized outcome triggers prediction error and indexes retrospective lesson in vector memory."""
    coord = get_memory_coordinator()
    tenant_id = "tenant_apex"
    workspace_id = "ws_detroit"
    decision_id = f"dec_{uuid7()}"

    # Setup initial Decision Record
    rec = DecisionRecord(
        decision_id=decision_id,
        workspace_id=workspace_id,
        tenant_id=tenant_id,
        disruption_id="disr_01",
        world_state_version=1,
        recommendations_presented=[],
        chosen_action={"type": "AIR_FREIGHT_EXPEDITE"},
        operator_id="Alice (Operations Director)",
        operator_decision="approved",
        operator_rationale="Bypass port queue by air freighting emergency inventory batch",
        predicted_cost_usd=80000.0,
        predicted_protected_revenue_usd=500000.0,
    )
    coord.decision.record_decision(rec)

    # Record realized real-world outcome
    result = await coord.record_closed_loop_outcome(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        decision_id=decision_id,
        actual_cost_usd=82000.0,
        actual_protected_revenue_usd=490000.0,
        notes="Air cargo arrived in 48 hours; zero production stoppage.",
    )
    assert result.decision_id == decision_id
    assert result.prediction_error_pct == 2.0  # |500k - 490k| / 500k = 2%

    # Query deliberative context to verify lesson indexed in Semantic Vector Memory
    context_data = await coord.query_deliberative_context(tenant_id, workspace_id, "Decision")
    assert len(context_data["relevant_precedents"]) >= 1
    assert "Retrospective Lesson" in context_data["relevant_precedents"][0]["title"]


# ─────────────────────────────────────────────────────────────────────────────
# 7. Enterprise Multi-User Organization Hierarchy
# ─────────────────────────────────────────────────────────────────────────────
def test_enterprise_multi_user_collaboration_and_cli_tokens():
    """Verify multi-user onboarding (Alice/Bob/Charlie under Apex Mobility) and scoped CLI tokens."""
    identity = EnterpriseIdentityStore()

    # 1. Organization creation (Alice)
    org, alice = identity.create_organization(
        name="Apex Mobility Inc",
        slug="apex-mobility",
        owner_email="alice@apexmobility.com",
    )
    assert alice.role == OrgRole.OWNER

    # 2. Invite colleagues (Bob & Charlie) to the SAME organization
    bob = identity.invite_user_to_org(
        org_id=org.org_id,
        email="bob@apexmobility.com",
        full_name="Bob Logistics",
        role=OrgRole.MEMBER,
    )
    charlie = identity.invite_user_to_org(
        org_id=org.org_id,
        email="charlie@apexmobility.com",
        full_name="Charlie Procurement",
        role=OrgRole.MEMBER,
    )

    users = identity.list_org_users(org.org_id)
    assert len(users) == 3
    assert {u.email for u in users} == {
        "alice@apexmobility.com",
        "bob@apexmobility.com",
        "charlie@apexmobility.com",
    }

    # 3. Create Shared Project & Workspace
    project = identity.create_project(
        org_id=org.org_id,
        name="Global EV Battery Supply 2026",
        description="Core battery and semiconductor mitigation project",
        creator_user_id=alice.user_id,
    )
    ws = identity.create_workspace(
        org_id=org.org_id,
        project_id=project.project_id,
        name="GigaPlant Austin",
        slug="gigaplant-austin",
    )

    # 4. Generate CLI Device Token for Bob
    raw_token, token_obj = identity.generate_device_token(
        user_id=bob.user_id,
        org_id=org.org_id,
        workspace_id=ws.workspace_id,
        device_name="bobs-macbook-pro",
    )

    assert raw_token.startswith("nxt_")
    auth_device = identity.authenticate_device_token(raw_token)
    assert auth_device is not None
    assert auth_device.user_id == bob.user_id
    assert auth_device.workspace_id == ws.workspace_id


# ─────────────────────────────────────────────────────────────────────────────
# 8. Nexus CLI Operational Verification
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_nexus_cli_operations():
    """Verify CLI login, whoami, health, and deliberate commands."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp_dir:
        cli = NexusCLI(config_dir=tmp_dir)

        # Health check
        health = cli.health()
        assert health["status"] == "HEALTHY"

        # Login
        login_res = cli.login("http://localhost:8000", "nxt_sample_token_123")
        assert login_res["status"] == "authenticated"

        # Whoami
        who = cli.whoami()
        assert who["server_url"] == "http://localhost:8000"
        assert who["token_configured"] is True

        # Deliberate CLI command
        delib_res = await cli.deliberate(
            task_type="FACILITY_OUTAGE",
            description="Austin assembly line sensor warning",
            priority="HIGH",
        )
        assert delib_res["status"] in {"COMPLETED", "PARTIAL"}
        assert "consensus_score" in delib_res
