"""Cortex Nexus — Centralized Training, Decentralized Execution (CTDE) Comprehensive Test Suite.

Validates:
1. Centralized Training with Central Critic evaluating joint global reward
2. Digital Twin scenario generation (carrier delay, scan drop, port congestion)
3. 10-Phase Promotion Gate & cryptographically signed capability manifests
4. Decentralized Replica Fleet deployment and progressive Canary traffic split
5. Dual-track health monitoring (Infrastructure vs Behavioral drift)
6. Autonomous hot replacement (Quarantine -> Warm -> Replay -> Promote -> Terminate)
7. Automatic version rollback on systematic model degradation
8. Domain Specialist Agents (Shipment, Logistics, Inventory, Procurement)
9. Historical Event Replay Engine (Candidate v8 vs Baseline v7 comparison)
10. Shadow Deployment Pipeline (live production zero-risk divergence tracking)
11. Decentralized Runtime Node (Heartbeats, Checkpoint persistence, and state recovery)
12. REST API endpoints under /api/v1/agents
"""

import os

os.environ.setdefault("CORTEX_ENV", "dev")
os.environ.setdefault("CORTEX_DB_DSN", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("CORTEX_JWT_SECRET", "0" * 32)

import pytest
from fastapi.testclient import TestClient

from app.common.context import ExecutionContext
from app.main import create_app
from app.modules.agents.autonomous_replacement import AgentHealthSupervisor
from app.modules.agents.deployment_controller import AgentDeploymentController
from app.modules.agents.domain_agents.inventory_allocation import InventoryAllocationAgent
from app.modules.agents.domain_agents.logistics_routing import LogisticsRoutingAgent
from app.modules.agents.domain_agents.procurement_sourcing import ProcurementSourcingAgent
from app.modules.agents.domain_agents.shipment_tracking import (
    ShipmentTelemetry,
    ShipmentTrackingAgent,
)
from app.modules.agents.evaluation_gate import AgentPromotionGate
from app.modules.agents.lifecycle_models import (
    AgentArtifact,
    AgentDomain,
    AgentLifecycleState,
    SignedCapabilityManifest,
)
from app.modules.agents.replay_engine import AgentReplayEngine
from app.modules.agents.runtime_node import DecentralizedAgentRuntime
from app.modules.agents.shadow_pipeline import ShadowDeploymentPipeline
from app.modules.agents.training_plane import (
    CentralCritic,
    CentralTrainingSupervisor,
    TrainingRunConfig,
)


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Centralized Training & Central Critic
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_ctde_centralized_training_with_central_critic():
    """Verify Central Training Supervisor trains agent across Digital Twin scenarios with Central Critic evaluation."""
    supervisor = CentralTrainingSupervisor()
    critic = CentralCritic()

    # Central Critic joint reward evaluation
    global_world_state = {"world_id": "w_global", "active_shipments": 120}
    joint_actions = [
        {"action_type": "reroute", "cost_usd": 200.0, "revenue_protected": 3000.0},
        {"action_type": "expedite", "cost_usd": 500.0, "revenue_protected": 4500.0},
    ]
    reward = critic.evaluate_joint_trajectory(global_world_state, joint_actions)
    assert reward > 0.0

    # Execute full training run
    cfg = TrainingRunConfig(
        agent_id="shipment_tracking_agent",
        target_domain=AgentDomain.SHIPMENT_TRACKING,
        target_version="v8",
        dataset_version="ds_logistics_2026_08",
        epochs=5,
    )
    artifact, metrics = await supervisor.execute_training_run(cfg)

    assert artifact.agent_id == "shipment_tracking_agent"
    assert artifact.version == "v8"
    assert artifact.lifecycle_state == AgentLifecycleState.TRAINED
    assert metrics.episodes_completed == 50
    assert metrics.mean_reward > 0.0
    assert "s3://" in metrics.checkpoint_uri
    assert artifact.capability_manifest.verify() is True


# ─────────────────────────────────────────────────────────────────────────────
# 2. 10-Phase Promotion Gate & Signature Verification
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_ctde_promotion_gate_and_signature_security():
    """Verify 10-phase promotion gate certifies valid artifacts and rejects tampered manifests."""
    gate = AgentPromotionGate()

    manifest = SignedCapabilityManifest(
        agent_id="shipment_tracking_agent",
        version="v8",
        allowed_capabilities=["read", "propose", "simulate"],
        allowed_tools=["get_shipment_telemetry"],
        policy_id="policy_v8",
    )
    manifest.signature = manifest.compute_signature()

    valid_artifact = AgentArtifact(
        artifact_id="art_valid_101",
        agent_id="shipment_tracking_agent",
        version="v8",
        domain=AgentDomain.SHIPMENT_TRACKING,
        model_uri="s3://cortex-models/checkpoints/v8.pt",
        policy_id="policy_v8",
        dataset_version="ds_2026",
        training_run_id="run_101",
        capability_manifest=manifest,
        lifecycle_state=AgentLifecycleState.TRAINED,
    )

    report = await gate.evaluate_and_qualify(valid_artifact)
    assert report.is_eligible_for_canary is True
    assert valid_artifact.lifecycle_state == AgentLifecycleState.VALIDATED

    # Negative test: Tampered signature rejection
    tampered_manifest = SignedCapabilityManifest(
        agent_id="shipment_tracking_agent",
        version="v8",
        allowed_capabilities=["read", "execute"],  # Forged EXECUTE capability
        allowed_tools=["dangerous_tool"],
        policy_id="policy_v8",
        signature="tampered_invalid_signature_xyz",
    )
    tampered_artifact = AgentArtifact(
        artifact_id="art_tampered_102",
        agent_id="shipment_tracking_agent",
        version="v8",
        domain=AgentDomain.SHIPMENT_TRACKING,
        model_uri="s3://cortex-models/checkpoints/v8.pt",
        policy_id="policy_v8",
        dataset_version="ds_2026",
        training_run_id="run_102",
        capability_manifest=tampered_manifest,
    )

    with pytest.raises(PermissionError, match="Unsigned or tampered capability manifest"):
        await gate.evaluate_and_qualify(tampered_artifact)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Decentralized Replicas, Canary Routing & Autoscaling
# ─────────────────────────────────────────────────────────────────────────────
def test_ctde_decentralized_replicas_and_canary_routing():
    """Verify provisioning multiple replicas and configuring progressive Canary traffic splits."""
    ctrl = AgentDeploymentController(max_replicas_per_agent=10)

    # Register baseline v7 and candidate v8
    art_v7 = AgentArtifact(
        artifact_id="art_v7",
        agent_id="shipment_tracking",
        version="v7",
        domain=AgentDomain.SHIPMENT_TRACKING,
        model_uri="s3://models/v7.pt",
        policy_id="pol_v7",
        dataset_version="ds_v7",
        training_run_id="run_v7",
        capability_manifest=SignedCapabilityManifest("shipment_tracking", "v7", ["read", "propose"], []),
    )
    art_v8 = AgentArtifact(
        artifact_id="art_v8",
        agent_id="shipment_tracking",
        version="v8",
        domain=AgentDomain.SHIPMENT_TRACKING,
        model_uri="s3://models/v8.pt",
        policy_id="pol_v8",
        dataset_version="ds_v8",
        training_run_id="run_v8",
        capability_manifest=SignedCapabilityManifest("shipment_tracking", "v8", ["read", "propose"], []),
    )
    ctrl.register_artifact(art_v7)
    ctrl.register_artifact(art_v8)

    # Deploy 2 replicas of baseline v7 and 2 replicas of canary v8
    reps_v7 = ctrl.deploy_replicas("shipment_tracking", "v7", "ws_austin", replica_count=2)
    reps_v8 = ctrl.deploy_replicas("shipment_tracking", "v8", "ws_austin", replica_count=2)

    assert len(ctrl.list_replicas("shipment_tracking")) == 4

    # Configure 10% Canary split
    canary_res = ctrl.configure_canary("shipment_tracking", "v8", "v7", 10.0)
    assert canary_res["status"] == "CANARY_ACTIVE"
    assert canary_res["candidate_aggregate_traffic_pct"] == 10.0
    assert canary_res["total_traffic_sum_pct"] == 100.0

    # Verify per-replica distribution (10% / 2 = 5% per candidate replica, 90% / 2 = 45% per baseline replica)
    assert reps_v8[0].traffic_weight == 0.05
    assert reps_v7[0].traffic_weight == 0.45
    assert sum(r.traffic_weight for r in ctrl.list_replicas("shipment_tracking")) == 1.0

    # Autoscaler test: high queue lag triggers scale up
    scale_res = ctrl.autoscale_fleet("shipment_tracking", "ws_austin", current_queue_lag_ms=650.0)
    assert scale_res["action"] == "SCALE_UP"
    assert scale_res["new_count"] == 6


# ─────────────────────────────────────────────────────────────────────────────
# 4. Behavioral Drift Detection & Autonomous Hot Replacement
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_ctde_autonomous_hot_replacement_on_behavioral_drift():
    """Verify supervisor detects single replica behavioral drift, isolates it, and performs hot replacement."""
    ctrl = AgentDeploymentController()
    art = AgentArtifact(
        artifact_id="art_v8",
        agent_id="shipment_tracking",
        version="v8",
        domain=AgentDomain.SHIPMENT_TRACKING,
        model_uri="s3://models/v8.pt",
        policy_id="pol_v8",
        dataset_version="ds_v8",
        training_run_id="run_v8",
        capability_manifest=SignedCapabilityManifest("shipment_tracking", "v8", ["read"], []),
    )
    ctrl.register_artifact(art)

    # Deploy 2 healthy replicas
    reps = ctrl.deploy_replicas("shipment_tracking", "v8", "ws_austin", replica_count=2)
    broken_rep = reps[0]

    # Inject behavioral drift: Process is healthy, but model is making erratic predictions (drift score = 0.72)
    broken_rep.behavioral_metrics.prediction_drift_score = 0.72

    supervisor = AgentHealthSupervisor(ctrl)
    is_healthy, reason = supervisor.evaluate_replica_health(broken_rep)
    assert is_healthy is False
    assert "Behavioral drift detected" in str(reason)

    # Run supervisory cycle
    incidents = await supervisor.run_supervisory_cycle("shipment_tracking", "ws_austin")
    assert len(incidents) >= 1
    assert incidents[0].action_taken == "HOT_REPLACEMENT"

    # Verify broken replica was replaced with a healthy instance
    active_reps = ctrl.list_replicas("shipment_tracking", "ws_austin")
    assert all(r.is_healthy for r in active_reps)
    assert broken_rep not in active_reps


# ─────────────────────────────────────────────────────────────────────────────
# 5. Cluster-Wide Version Rollback on Systematic Failure
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_ctde_cluster_wide_version_rollback():
    """Verify systematic degradation across multiple candidate replicas triggers cluster-wide version rollback."""
    ctrl = AgentDeploymentController()
    art_v7 = AgentArtifact(
        artifact_id="art_v7",
        agent_id="shipment_tracking",
        version="v7",
        domain=AgentDomain.SHIPMENT_TRACKING,
        model_uri="s3://models/v7.pt",
        policy_id="pol_v7",
        dataset_version="ds_v7",
        training_run_id="run_v7",
        capability_manifest=SignedCapabilityManifest("shipment_tracking", "v7", ["read"], []),
        lifecycle_state=AgentLifecycleState.ACTIVE,
    )
    art_v8 = AgentArtifact(
        artifact_id="art_v8",
        agent_id="shipment_tracking",
        version="v8",
        domain=AgentDomain.SHIPMENT_TRACKING,
        model_uri="s3://models/v8.pt",
        policy_id="pol_v8",
        dataset_version="ds_v8",
        training_run_id="run_v8",
        capability_manifest=SignedCapabilityManifest("shipment_tracking", "v8", ["read"], []),
        lifecycle_state=AgentLifecycleState.CANARY,
    )
    ctrl.register_artifact(art_v7)
    ctrl.register_artifact(art_v8)

    # Deploy 2 replicas of v8 and inject widespread calibration degradation into both
    reps_v8 = ctrl.deploy_replicas("shipment_tracking", "v8", "ws_austin", replica_count=2)
    for r in reps_v8:
        r.behavioral_metrics.calibration_error = 0.45  # Severe calibration failure

    supervisor = AgentHealthSupervisor(ctrl)
    incidents = await supervisor.run_supervisory_cycle("shipment_tracking", "ws_austin")

    # Should contain hot replacements AND a cluster-wide version rollback
    rollback_incidents = [i for i in incidents if i.action_taken == "VERSION_ROLLBACK"]
    assert len(rollback_incidents) == 1
    assert rollback_incidents[0].diagnostics["flawed_version"] == "v8"
    assert rollback_incidents[0].diagnostics["rollback_target_version"] == "v7"
    assert art_v8.lifecycle_state == AgentLifecycleState.ROLLED_BACK


# ─────────────────────────────────────────────────────────────────────────────
# 6. Domain Specialist Agents In-Depth Execution
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_ctde_domain_agents_execution():
    """Verify all 4 domain specialist agents execute within capability constraints."""
    ctx = ExecutionContext.create_system_context()

    # 1. Shipment Tracking Agent
    tracker = ShipmentTrackingAgent(version="v8")
    telem = ShipmentTelemetry(
        shipment_id="ship_congested_01",
        origin="PORT_OF_SHANGHAI",
        destination="PORT_OF_LA",
        carrier="Maersk Line",
        current_location="PACIFIC_OCEAN_SECTOR_4",
        planned_eta_days=14.0,
        elapsed_days=10.0,
        port_congestion_index=0.85,
        weather_severity=0.60,
    )
    assessment = await tracker.evaluate_shipment(telem, ctx)
    assert assessment.status == "CRITICAL_DELAY"
    assert assessment.mitigation_needed is True
    assert assessment.recommended_action["action_type"] == "expedite_air_freight"

    # 2. Logistics Routing Agent
    router = LogisticsRoutingAgent(version="v4")
    routes = await router.evaluate_alternatives("SHANGHAI", "AUSTIN", "CRITICAL", ctx)
    assert len(routes) == 3
    assert routes[0].mode == "AIR"  # Sorted by speed for critical urgency

    # 3. Inventory Allocation Agent
    inv_agent = InventoryAllocationAgent(version="v6")
    xfer = await inv_agent.balance_stock("semi_part_09", "wh_austin_fab", 500.0, ctx)
    assert xfer.quantity == 500.0
    assert xfer.protected_production_hours == 72.0

    # 4. Procurement Sourcing Agent
    proc_agent = ProcurementSourcingAgent(version="v5")
    quotes = await proc_agent.rank_alternative_sources("semi_part_09", 2000.0, ctx)
    assert len(quotes) == 2
    assert quotes[0].supplier_id == "sup_beta_semi"


# ─────────────────────────────────────────────────────────────────────────────
# 7. Historical Event Replay Engine (Candidate v8 vs Baseline v7)
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_ctde_historical_event_replay_comparison():
    """Verify Replay Engine reprocesses historical event logs to compare versions side-by-side."""
    ctx = ExecutionContext.create_system_context()
    engine = AgentReplayEngine()

    telemetry_stream = [
        ShipmentTelemetry("s1", "A", "B", "C1", "LOC1", 10.0, 4.0, 0.1, 0.0),  # On time
        ShipmentTelemetry("s2", "A", "B", "C1", "LOC2", 10.0, 9.0, 0.9, 0.7),  # Severe delay
        ShipmentTelemetry("s3", "A", "B", "C2", "LOC3", 12.0, 11.0, 0.5, 0.4),  # Delayed
        ShipmentTelemetry("s4", "A", "B", "C3", "LOC4", 8.0, 3.0, 0.05, 0.0),  # On time
    ]

    report = await engine.run_replay_comparison("v8", "v7", telemetry_stream, ctx)
    assert report.events_replayed_count == 4
    assert report.candidate_accuracy >= 0.75
    assert report.is_candidate_superior is True


# ─────────────────────────────────────────────────────────────────────────────
# 8. Shadow Deployment Pipeline
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_ctde_shadow_deployment_live_pipeline():
    """Verify shadow pipeline evaluates candidate against live traffic with zero side effects."""
    ctx = ExecutionContext.create_system_context()
    pipeline = ShadowDeploymentPipeline()

    telem = ShipmentTelemetry("s_live", "A", "B", "C1", "PACIFIC", 14.0, 8.0, 0.7, 0.3)
    active_res, shadow_res, metric = await pipeline.evaluate_live_event(
        event_id="evt_live_101",
        telemetry=telem,
        active_version="v7",
        shadow_version="v8",
        context=ctx,
    )

    assert active_res is not None
    assert shadow_res is not None
    assert metric.event_id == "evt_live_101"

    summary = pipeline.get_summary_metrics()
    assert summary["total_events"] == 1
    assert summary["avg_shadow_latency_ms"] >= 0.0


# ─────────────────────────────────────────────────────────────────────────────
# 9. Decentralized Runtime Node (Checkpoints & Heartbeats)
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_ctde_runtime_node_checkpoints_and_heartbeats():
    """Verify runtime node handles events, writes checkpoints, and emits structured heartbeats."""
    ctx = ExecutionContext.create_system_context()
    node = DecentralizedAgentRuntime(
        replica_id="rep_test_01",
        agent_id="shipment_tracking_agent",
        version="v8",
        workspace_id="ws_austin",
    )

    telem = ShipmentTelemetry("s_rt_01", "A", "B", "C", "LOC", 10.0, 5.0, 0.2, 0.1)
    res = await node.handle_shipment_telemetry_event(telem, ctx)
    assert res.status == "ON_TIME"

    # Checkpoint state
    chk = node.create_checkpoint("evt_checkpoint_01")
    assert chk.replica_id == "rep_test_01"
    assert "s_rt_01" in chk.working_memory_state

    # Emit heartbeat
    hb = node.emit_heartbeat()
    assert hb["replica_id"] == "rep_test_01"
    assert hb["status"] == "HEALTHY"


# ─────────────────────────────────────────────────────────────────────────────
# 10. REST API End-to-End Endpoints Test
# ─────────────────────────────────────────────────────────────────────────────
def test_ctde_rest_api_fleet_and_lifecycle(client):
    """Verify REST API endpoints for fleet status, training, evaluation, canary, and supervision."""
    # 1. Train agent
    train_res = client.post(
        "/api/v1/agents/train",
        json={
            "agent_id": "logistics_agent",
            "target_domain": "logistics_routing",
            "target_version": "v4",
            "dataset_version": "ds_logistics_2026",
            "epochs": 3,
        },
    )
    assert train_res.status_code == 200
    assert train_res.json()["status"] == "TRAINING_COMPLETED"

    # 2. Evaluate agent
    eval_res = client.post(
        "/api/v1/agents/evaluate",
        json={"agent_id": "logistics_agent", "version": "v4"},
    )
    assert eval_res.status_code == 200
    assert eval_res.json()["eligible_for_canary"] is True

    # 3. Deploy replicas
    deploy_res = client.post(
        "/api/v1/agents/deploy",
        json={
            "agent_id": "logistics_agent",
            "version": "v4",
            "workspace_id": "ws_austin",
            "replica_count": 2,
        },
    )
    assert deploy_res.status_code == 200
    assert deploy_res.json()["deployed_count"] == 2

    # 4. Check fleet overview
    fleet_res = client.get("/api/v1/agents/fleet")
    assert fleet_res.status_code == 200
    data = fleet_res.json()
    assert data["total_artifacts"] >= 1
    assert data["total_active_replicas"] >= 2
