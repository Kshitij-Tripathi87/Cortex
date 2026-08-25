"""Cortex Nexus — Real-World Olist Logistics Dataset Training & Qualification Test.

Validates:
1. Parsing real CSV telemetry from C:\\Users\\21330\\Downloads\\archive
2. Building an immutable VersionedAgentDataset with SHA-256 provenance
3. Training ShipmentTrackingAgent under Central Training Supervisor & Central Critic
4. Qualifying through the 10-Phase Promotion Gate with HMAC-SHA256 signature
5. Executing Historical Replay comparison of Candidate v9_olist against Baseline v7
6. Deploying decentralized replicas with progressive Canary traffic routing
"""

import os

os.environ.setdefault("CORTEX_ENV", "dev")
os.environ.setdefault("CORTEX_DB_DSN", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("CORTEX_JWT_SECRET", "0" * 32)

import pytest

from app.common.context import ExecutionContext
from app.modules.agents.deployment_controller import AgentDeploymentController
from app.modules.agents.lifecycle_models import AgentLifecycleState
from app.modules.agents.olist_pipeline import OlistLogisticsPipeline
from app.modules.agents.replay_engine import AgentReplayEngine


@pytest.mark.asyncio
async def test_olist_real_dataset_ingestion_and_training():
    """Verify that real-world Olist e-commerce logistics data is ingested, trained, evaluated, and deployed."""
    pipeline = OlistLogisticsPipeline(data_dir=r"C:\Users\21330\Downloads\archive")

    # 1. Run complete training and qualification pipeline on real Olist data
    dataset, artifact, report = await pipeline.run_end_to_end_training_and_qualification(
        max_samples=500,
        target_version="v9_olist",
    )

    assert dataset.sample_count > 100
    assert dataset.provenance_metadata["source_system"] == "nexus_event_log"
    assert len(dataset.checksum_sha256) == 64

    # 2. Verify artifact qualification scorecard
    assert artifact.version == "v9_olist"
    assert artifact.lifecycle_state == AgentLifecycleState.VALIDATED
    assert report.is_eligible_for_canary is True
    assert artifact.capability_manifest.verify() is True

    # 3. Benchmark via Historical Replay against Baseline v7
    ctx = ExecutionContext.create_system_context()
    replay_engine = AgentReplayEngine()

    real_telemetry = pipeline.load_and_preprocess_telemetry(max_rows=100)
    replay_report = await replay_engine.run_replay_comparison(
        candidate_version="v9_olist",
        baseline_version="v7",
        historical_telemetry=real_telemetry,
        context=ctx,
    )

    assert replay_report.events_replayed_count >= 50
    assert replay_report.candidate_accuracy >= 0.70
    assert replay_report.candidate_avg_latency_ms < 10.0

    # 4. Deploy Candidate Replicas & Configure Canary
    controller = AgentDeploymentController()
    controller.register_artifact(artifact)

    replicas = controller.deploy_replicas(
        agent_id=artifact.agent_id,
        version="v9_olist",
        workspace_id="ws_brazil_logistics",
        replica_count=3,
    )

    assert len(replicas) == 3
    assert all(r.status.value == "HEALTHY" for r in replicas)

    # 5. Progressive Canary 10% split
    canary_result = controller.configure_canary(
        agent_id=artifact.agent_id,
        candidate_version="v9_olist",
        baseline_version="v7",
        canary_pct=10.0,
    )
    assert canary_result["status"] == "CANARY_ACTIVE"
    assert canary_result["candidate_aggregate_traffic_pct"] == 10.0
    assert canary_result["total_traffic_sum_pct"] == 100.0
