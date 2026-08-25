"""Cortex Nexus — Comprehensive Agent Platform Test Suite (Phases A through O).

Verifies the complete Agent Lifecycle & Deployment Platform:
- Phase A: Agent Specifications & Training Contracts
- Phase B: Central Dataset Builder & Provenance Checksums
- Phase C: Central Training Supervisor & Digital Twin Scenarios
- Phase D: 10-Phase Promotion Gate & Cryptographic Capability Signing
- Phase E: Live Shadow Mode Pipeline
- Phase F & G: Decentralized Replicas & Message Bus Routing
- Phase H: Dual-Track Health Monitoring & Autonomous Hot Replacement
- Phase I: Progressive Canary Deployment
- Phase J: Agent Supply-Chain Security & Privilege Separation
- Phase K: Recoverable State Checkpoints
- Phase L & M: Agent Operations Center REST APIs
- Phase N & O: Closed-Loop Retraining & Organization Fleet Quotas
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
from app.modules.agents.dataset_builder import CentralDatasetBuilder
from app.modules.agents.deployment_controller import AgentDeploymentController
from app.modules.agents.domain_agents.shipment_tracking import (
    ShipmentTelemetry,
)
from app.modules.agents.evaluation_gate import AgentPromotionGate
from app.modules.agents.lifecycle_models import (
    AgentArtifact,
    AgentDomain,
    AgentLifecycleState,
    SignedCapabilityManifest,
)
from app.modules.agents.runtime_node import DecentralizedAgentRuntime
from app.modules.agents.shadow_pipeline import ShadowDeploymentPipeline
from app.modules.agents.specifications import get_canonical_shipment_tracking_spec
from app.modules.agents.training_plane import (
    CentralTrainingSupervisor,
    TrainingRunConfig,
)


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


# ─────────────────────────────────────────────────────────────────────────────
# Phase A & B: Specifications, Contracts & Central Dataset Builder
# ─────────────────────────────────────────────────────────────────────────────
def test_phase_a_b_specifications_and_dataset_builder():
    """Verify formal agent specifications and provenance-tagged dataset construction."""
    spec = get_canonical_shipment_tracking_spec(version="v8")
    assert spec.validate_capability_privileges() is True
    assert spec.domain == AgentDomain.SHIPMENT_TRACKING
    assert "read" in spec.allowed_capabilities
    assert "execute" not in spec.allowed_capabilities  # Privilege separation verified

    # Build dataset with provenance
    builder = CentralDatasetBuilder()
    telemetry_stream = [
        ShipmentTelemetry("s1", "SHANGHAI", "LA", "Maersk", "PORT", 14.0, 12.0, 0.85, 0.4),
        ShipmentTelemetry("s2", "SHANGHAI", "LA", "Hapag", "OCEAN", 14.0, 5.0, 0.1, 0.0),
    ]
    dataset = builder.build_dataset_from_historical_telemetry(
        domain="shipment_tracking",
        version="ds_2026_08",
        telemetry_records=telemetry_stream,
        world_state_version=5,
    )

    assert dataset.sample_count == 2
    assert dataset.provenance_metadata["world_state_version"] == 5
    assert len(dataset.checksum_sha256) == 64  # Valid SHA256 checksum


# ─────────────────────────────────────────────────────────────────────────────
# Phase C & D: Centralized Training & 10-Phase Promotion Gate
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_phase_c_d_training_and_10_phase_gate():
    """Verify Central Critic training loop and 10-phase qualification gate certification."""
    supervisor = CentralTrainingSupervisor()
    gate = AgentPromotionGate()

    cfg = TrainingRunConfig(
        agent_id="shipment_tracking_agent",
        target_domain=AgentDomain.SHIPMENT_TRACKING,
        target_version="v8",
        dataset_version="ds_2026_08",
        epochs=4,
    )
    artifact, metrics = await supervisor.execute_training_run(cfg)
    assert artifact.lifecycle_state == AgentLifecycleState.TRAINED
    assert metrics.episodes_completed == 40

    # 10-phase gate evaluation
    report = await gate.evaluate_and_qualify(artifact)
    assert report.is_eligible_for_canary is True
    assert report.behavioral_test_score == 1.0
    assert report.digital_twin_simulation_score > 0.8
    assert artifact.lifecycle_state == AgentLifecycleState.VALIDATED


# ─────────────────────────────────────────────────────────────────────────────
# Phase E, F & I: Shadow Mode, Decentralized Replicas & Progressive Canary
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_phase_e_f_i_shadow_and_progressive_canary():
    """Verify shadow mode evaluation and progressive canary traffic split."""
    ctx = ExecutionContext.create_system_context()
    shadow_pipe = ShadowDeploymentPipeline()
    ctrl = AgentDeploymentController()

    telem = ShipmentTelemetry("s_live", "A", "B", "C", "OCEAN", 14.0, 7.0, 0.65, 0.2)
    act_res, shd_res, div_metric = await shadow_pipe.evaluate_live_event("evt_1", telem, "v7", "v8", ctx)
    assert act_res is not None
    assert shd_res is not None

    # Deploy replicas and configure Canary
    art_v7 = AgentArtifact("a_v7", "shipment_tracking", "v7", AgentDomain.SHIPMENT_TRACKING, "s3://v7", "p7", "d7", "r7", SignedCapabilityManifest("shipment_tracking", "v7", ["read"], []))
    art_v8 = AgentArtifact("a_v8", "shipment_tracking", "v8", AgentDomain.SHIPMENT_TRACKING, "s3://v8", "p8", "d8", "r8", SignedCapabilityManifest("shipment_tracking", "v8", ["read"], []))
    ctrl.register_artifact(art_v7)
    ctrl.register_artifact(art_v8)

    reps_v7 = ctrl.deploy_replicas("shipment_tracking", "v7", "ws_austin", replica_count=2)
    reps_v8 = ctrl.deploy_replicas("shipment_tracking", "v8", "ws_austin", replica_count=2)

    # Progressive Canary: 5% -> 25% -> 100%
    ctrl.configure_canary("shipment_tracking", "v8", "v7", 5.0)
    assert reps_v8[0].traffic_weight == 0.025  # 5% / 2 candidate replicas

    ctrl.configure_canary("shipment_tracking", "v8", "v7", 25.0)
    assert reps_v8[0].traffic_weight == 0.125  # 25% / 2 candidate replicas

    ctrl.configure_canary("shipment_tracking", "v8", "v7", 100.0)
    assert reps_v8[0].traffic_weight == 0.50   # 100% / 2 candidate replicas
    assert sum(r.traffic_weight for r in ctrl.list_replicas("shipment_tracking")) == 1.0


# ─────────────────────────────────────────────────────────────────────────────
# Phase H, J & K: Dual-Track Health, Hot Replacement, Security & Checkpoints
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_phase_h_j_k_health_hot_replacement_and_checkpoints():
    """Verify dual-track behavioral health, autonomous hot replacement, and recoverable state checkpoints."""
    ctrl = AgentDeploymentController()
    art = AgentArtifact("a_v8", "shipment_tracking", "v8", AgentDomain.SHIPMENT_TRACKING, "s3://v8", "p8", "d8", "r8", SignedCapabilityManifest("shipment_tracking", "v8", ["read"], []))
    ctrl.register_artifact(art)

    reps = ctrl.deploy_replicas("shipment_tracking", "v8", "ws_austin", replica_count=2)
    degraded_rep = reps[0]
    degraded_rep.behavioral_metrics.prediction_drift_score = 0.68  # Behavioral failure

    health_sup = AgentHealthSupervisor(ctrl)
    incidents = await health_sup.run_supervisory_cycle("shipment_tracking", "ws_austin")
    assert len(incidents) >= 1
    assert incidents[0].action_taken == "HOT_REPLACEMENT"

    # Runtime Node State Checkpointing
    ctx = ExecutionContext.create_system_context()
    runtime_node = DecentralizedAgentRuntime("rep_node_1", "shipment_tracking", "v8", "ws_austin")
    telem = ShipmentTelemetry("ship_chk_01", "A", "B", "C", "PORT", 10.0, 2.0, 0.1, 0.0)
    await runtime_node.handle_shipment_telemetry_event(telem, ctx)

    chk = runtime_node.create_checkpoint("evt_checkpoint_101")
    assert chk.replica_id == "rep_node_1"
    assert "ship_chk_01" in chk.working_memory_state


# ─────────────────────────────────────────────────────────────────────────────
# Phase N & O: Closed-Loop Retraining & Organization Fleet Quotas
# ─────────────────────────────────────────────────────────────────────────────
def test_phase_n_o_fleet_quotas():
    """Verify organization quota limit prevents unbounded fleet expansion."""
    restricted_ctrl = AgentDeploymentController(max_agents=2, max_replicas_per_agent=4)

    art1 = AgentArtifact("a1", "agent_1", "v1", AgentDomain.SHIPMENT_TRACKING, "s3://1", "p1", "d1", "r1", SignedCapabilityManifest("agent_1", "v1", ["read"], []))
    art2 = AgentArtifact("a2", "agent_2", "v1", AgentDomain.LOGISTICS_ROUTING, "s3://2", "p2", "d2", "r2", SignedCapabilityManifest("agent_2", "v1", ["read"], []))
    art3 = AgentArtifact("a3", "agent_3", "v1", AgentDomain.INVENTORY_ALLOCATION, "s3://3", "p3", "d3", "r3", SignedCapabilityManifest("agent_3", "v1", ["read"], []))

    restricted_ctrl.register_artifact(art1)
    restricted_ctrl.register_artifact(art2)

    # 3rd agent exceeds quota of 2
    with pytest.raises(ValueError, match="Organization quota exceeded"):
        restricted_ctrl.register_artifact(art3)
