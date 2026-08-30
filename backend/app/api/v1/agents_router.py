"""Agent Fleet & Lifecycle API — Endpoints for Centralized Training & Decentralized Execution.

Exposes REST APIs for:
- Fleet overview and live replica status
- Training run initiation & Central Critic evaluation
- 10-phase promotion gate qualification
- Progressive Canary deployment & traffic routing
- Autonomous health supervision & hot replacement
- Version rollback & self-healing audit log
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.modules.agents.autonomous_replacement import AgentHealthSupervisor
from app.modules.agents.deployment_controller import AgentDeploymentController
from app.modules.agents.evaluation_gate import AgentPromotionGate
from app.modules.agents.lifecycle_models import (
    AgentDomain,
)
from app.modules.agents.training_plane import CentralTrainingSupervisor, TrainingRunConfig

router = APIRouter(prefix="/agents", tags=["Agent Operations Center"])

# Singletons for runtime coordination
_deployment_controller = AgentDeploymentController()
_training_supervisor = CentralTrainingSupervisor()
_promotion_gate = AgentPromotionGate()
_health_supervisor = AgentHealthSupervisor(_deployment_controller)


# ─────────────────────────────────────────────────────────────────────────────
# Request / Response Schemas
# ─────────────────────────────────────────────────────────────────────────────
class TrainAgentRequest(BaseModel):
    agent_id: str
    target_domain: AgentDomain = AgentDomain.SHIPMENT_TRACKING
    target_version: str = "v8"
    dataset_version: str = "ds_logistics_2026_08"
    epochs: int = 10
    max_compute_budget_usd: float = 25.0


class EvaluateAgentRequest(BaseModel):
    agent_id: str
    version: str


class DeployReplicasRequest(BaseModel):
    agent_id: str
    version: str
    workspace_id: str = "ws_default"
    replica_count: int = 2


class ConfigureCanaryRequest(BaseModel):
    agent_id: str
    candidate_version: str
    baseline_version: str
    canary_pct: float = Field(ge=0.0, le=100.0, default=10.0)


class InjectDegradationRequest(BaseModel):
    replica_id: str
    agent_id: str
    prediction_drift_score: float = 0.65
    error_rate_pct: float = 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/fleet")
async def get_agent_fleet(workspace_id: str | None = None):
    """Retrieve full agent fleet topology, artifacts, and running replicas."""
    artifacts = _deployment_controller.list_artifacts()
    replicas = _deployment_controller.list_replicas(workspace_id=workspace_id)
    incidents = _health_supervisor.list_incidents()

    return {
        "total_artifacts": len(artifacts),
        "total_active_replicas": len(replicas),
        "total_incidents_resolved": len(incidents),
        "artifacts": [a.to_dict() for a in artifacts],
        "replicas": [r.to_dict() for r in replicas],
        "recent_incidents": [
            {
                "incident_id": i.incident_id,
                "agent_id": i.agent_id,
                "replica_id": i.replica_id,
                "version": i.version,
                "trigger_type": i.trigger_type,
                "action_taken": i.action_taken,
                "occurred_at": i.occurred_at.isoformat(),
            }
            for i in incidents[-10:]
        ],
    }


@router.post("/train")
async def train_agent(req: TrainAgentRequest):
    """Launch centralized CTDE training run with Central Critic evaluation."""
    cfg = TrainingRunConfig(
        agent_id=req.agent_id,
        target_domain=req.target_domain,
        target_version=req.target_version,
        dataset_version=req.dataset_version,
        epochs=req.epochs,
        max_compute_budget_usd=req.max_compute_budget_usd,
    )
    artifact, metrics = await _training_supervisor.execute_training_run(cfg)
    _deployment_controller.register_artifact(artifact)

    return {
        "status": "TRAINING_COMPLETED",
        "artifact": artifact.to_dict(),
        "metrics": {
            "loss": metrics.loss,
            "mean_reward": metrics.mean_reward,
            "compute_cost_usd": metrics.compute_cost_usd,
            "checkpoint_uri": metrics.checkpoint_uri,
        },
    }


@router.post("/evaluate")
async def evaluate_agent(req: EvaluateAgentRequest):
    """Run 10-phase behavioral and safety promotion gate on trained artifact."""
    artifact = _deployment_controller.get_artifact(req.agent_id, req.version)
    if not artifact:
        raise HTTPException(status_code=404, detail=f"Artifact {req.agent_id}:{req.version} not found.")

    report = await _promotion_gate.evaluate_and_qualify(artifact)
    return {
        "status": "EVALUATION_COMPLETED",
        "eligible_for_canary": report.is_eligible_for_canary,
        "lifecycle_state": artifact.lifecycle_state.value,
        "scorecard": report.to_dict(),
    }


@router.post("/deploy")
async def deploy_agent_replicas(req: DeployReplicasRequest):
    """Deploy and scale decentralized agent replicas across worker nodes."""
    try:
        replicas = _deployment_controller.deploy_replicas(
            agent_id=req.agent_id,
            version=req.version,
            workspace_id=req.workspace_id,
            replica_count=req.replica_count,
        )
        return {
            "status": "REPLICAS_DEPLOYED",
            "agent_id": req.agent_id,
            "version": req.version,
            "deployed_count": len(replicas),
            "replicas": [r.to_dict() for r in replicas],
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/canary")
async def configure_canary(req: ConfigureCanaryRequest):
    """Configure progressive canary traffic split between baseline and candidate version."""
    try:
        res = _deployment_controller.configure_canary(
            agent_id=req.agent_id,
            candidate_version=req.candidate_version,
            baseline_version=req.baseline_version,
            canary_pct=req.canary_pct,
        )
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/supervise")
async def run_supervision_cycle(agent_id: str, workspace_id: str = "ws_default"):
    """Trigger autonomous supervisory cycle to detect and hot-replace degraded replicas."""
    incidents = await _health_supervisor.run_supervisory_cycle(agent_id, workspace_id)
    return {
        "status": "SUPERVISION_CYCLE_COMPLETED",
        "agent_id": agent_id,
        "incidents_detected": len(incidents),
        "actions": [
            {
                "incident_id": i.incident_id,
                "replica_id": i.replica_id,
                "action_taken": i.action_taken,
                "diagnostics": i.diagnostics,
            }
            for i in incidents
        ],
    }


@router.post("/inject-degradation")
async def inject_simulated_degradation(req: InjectDegradationRequest):
    """Inject simulated behavioral drift or infra faults into a replica for chaos testing."""
    reps = _deployment_controller.list_replicas(req.agent_id)
    target = next((r for r in reps if r.replica_id == req.replica_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Replica not found.")

    target.behavioral_metrics.prediction_drift_score = req.prediction_drift_score
    target.infra_metrics.error_rate_pct = req.error_rate_pct

    return {
        "status": "DEGRADATION_INJECTED",
        "replica_id": target.replica_id,
        "behavioral": target.behavioral_metrics.to_dict(),
        "infra": target.infra_metrics.to_dict(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Operational Multi-Agent Task Graph & Manifest Endpoints
# ─────────────────────────────────────────────────────────────────────────────
class CreateTaskRequest(BaseModel):
    incident_entity_id: str = Field(default="seller_01a00b8e99", description="Entity causing disruption")
    world_state_version: int = Field(default=101, description="Authoritative world state version")
    origin: str = Field(default="SP", description="Origin hub / city")
    destination: str = Field(default="RJ", description="Destination hub / city")


from app.modules.multi_agent.runtime.nexus_supervisor import NexusSwarmSupervisor  # noqa: E402
from app.modules.multi_agent.tools.manifests import CAPABILITY_MANIFESTS  # noqa: E402

_swarm_supervisor = NexusSwarmSupervisor()


@router.post("/tasks")
async def create_and_execute_task(req: CreateTaskRequest) -> dict[str, Any]:
    """Executes a complete 4-family multi-agent task graph on the Nexus Multi-Agent OS."""
    summary = _swarm_supervisor.execute_swarm_task(
        incident_entity_id=req.incident_entity_id,
        world_state_version=req.world_state_version,
        origin=req.origin,
        destination=req.destination,
    )
    task = _swarm_supervisor.active_tasks.get(summary.task_id)
    return {
        "status": "SUCCESS",
        "task_summary": summary.to_dict(),
        "task_graph": task.to_dict() if task else None,
    }


@router.get("/tasks/{task_id}")
async def get_task_graph(task_id: str) -> dict[str, Any]:
    """Returns details and step execution trace of a specific task graph."""
    task = _swarm_supervisor.active_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task graph {task_id} not found.")
    return {"status": "SUCCESS", "task_graph": task.to_dict()}


@router.get("/manifests")
async def get_agent_capability_manifests() -> dict[str, Any]:
    """Returns capability manifests and permission scopes for all 17 specialist agents."""
    return {
        "status": "SUCCESS",
        "total_manifests": len(CAPABILITY_MANIFESTS),
        "manifests": {k: m.to_dict() for k, m in CAPABILITY_MANIFESTS.items()},
    }
