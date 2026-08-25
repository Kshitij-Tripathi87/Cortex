"""Agent Lifecycle Plane — Models & Contracts for Centralized Training, Decentralized Execution.

Defines:
- Agent versions (immutable trained artifacts) vs Agent replicas (running instances)
- Explicit 12-state lifecycle (DRAFT -> ACTIVE -> RETIRED)
- Dual-track health: Infrastructure health + Behavioral health
- Signed capability manifests and deployment artifacts
- Central critic evaluation contracts
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class AgentLifecycleState(StrEnum):
    DRAFT = "DRAFT"
    TRAINING = "TRAINING"
    TRAINED = "TRAINED"
    EVALUATING = "EVALUATING"
    VALIDATED = "VALIDATED"
    REGISTERED = "REGISTERED"
    SHADOW = "SHADOW"
    CANARY = "CANARY"
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    QUARANTINED = "QUARANTINED"
    ROLLED_BACK = "ROLLED_BACK"
    RETIRED = "RETIRED"


class AgentDomain(StrEnum):
    SHIPMENT_TRACKING = "shipment_tracking"
    LOGISTICS_ROUTING = "logistics_routing"
    INVENTORY_ALLOCATION = "inventory_allocation"
    PROCUREMENT_SOURCING = "procurement_sourcing"
    PRODUCTION_SCHEDULING = "production_scheduling"
    EXECUTIVE_COORDINATOR = "executive_coordinator"


class ReplicaStatus(StrEnum):
    PROVISIONING = "PROVISIONING"
    WARMING = "WARMING"
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    DRAINING = "DRAINING"
    TERMINATED = "TERMINATED"


@dataclass
class SignedCapabilityManifest:
    """Cryptographically verifiable agent capability manifest."""

    agent_id: str
    version: str
    allowed_capabilities: list[str]  # e.g., ["read", "propose", "simulate"]
    allowed_tools: list[str]
    max_tokens_per_turn: int = 100_000
    max_cost_per_turn_usd: float = 5.0
    policy_id: str = "nexus-policy-v1"
    signature: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def compute_signature(self, secret: str = "cortex_capability_master_2026") -> str:
        payload = f"{self.agent_id}:{self.version}:{sorted(self.allowed_capabilities)}:{sorted(self.allowed_tools)}:{self.policy_id}:{secret}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def verify(self, secret: str = "cortex_capability_master_2026") -> bool:
        return self.signature == self.compute_signature(secret)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "version": self.version,
            "allowed_capabilities": self.allowed_capabilities,
            "allowed_tools": self.allowed_tools,
            "max_tokens_per_turn": self.max_tokens_per_turn,
            "max_cost_per_turn_usd": self.max_cost_per_turn_usd,
            "policy_id": self.policy_id,
            "signature": self.signature,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class BehavioralMetrics:
    """Behavioral health signals to detect drift, hallucination, or bad action proposals."""

    prediction_drift_score: float = 0.0  # 0.0 (nominal) to 1.0 (severe drift)
    calibration_error: float = 0.02  # ECE (Expected Calibration Error)
    baseline_disagreement_rate: float = 0.05
    policy_violation_count: int = 0
    consecutive_empty_proposals: int = 0
    outcome_accuracy_brier: float = 0.04

    @property
    def is_behaviorally_healthy(self) -> bool:
        return (
            self.prediction_drift_score < 0.35
            and self.calibration_error < 0.15
            and self.baseline_disagreement_rate < 0.40
            and self.policy_violation_count == 0
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "prediction_drift_score": round(self.prediction_drift_score, 4),
            "calibration_error": round(self.calibration_error, 4),
            "baseline_disagreement_rate": round(self.baseline_disagreement_rate, 4),
            "policy_violation_count": self.policy_violation_count,
            "outcome_accuracy_brier": round(self.outcome_accuracy_brier, 4),
            "is_behaviorally_healthy": self.is_behaviorally_healthy,
        }


@dataclass
class InfrastructureMetrics:
    """Low-level infrastructure health."""

    cpu_utilization_pct: float = 12.5
    memory_mb: float = 240.0
    message_lag_ms: float = 4.2
    error_rate_pct: float = 0.0
    p99_latency_ms: float = 38.0
    uptime_seconds: float = 3600.0

    @property
    def is_infra_healthy(self) -> bool:
        return (
            self.cpu_utilization_pct < 90.0
            and self.error_rate_pct < 5.0
            and self.message_lag_ms < 1000.0
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "cpu_utilization_pct": round(self.cpu_utilization_pct, 1),
            "memory_mb": round(self.memory_mb, 1),
            "message_lag_ms": round(self.message_lag_ms, 2),
            "error_rate_pct": round(self.error_rate_pct, 2),
            "p99_latency_ms": round(self.p99_latency_ms, 1),
            "uptime_seconds": self.uptime_seconds,
            "is_infra_healthy": self.is_infra_healthy,
        }


@dataclass
class AgentReplica:
    """A running decentralized execution instance of an AgentVersion."""

    replica_id: str
    agent_id: str
    version: str
    status: ReplicaStatus
    workspace_id: str
    node_id: str
    infra_metrics: InfrastructureMetrics = field(default_factory=InfrastructureMetrics)
    behavioral_metrics: BehavioralMetrics = field(default_factory=BehavioralMetrics)
    last_heartbeat_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    traffic_weight: float = 1.0  # Used in canary (0.0 to 1.0)

    @property
    def is_healthy(self) -> bool:
        return (
            self.status == ReplicaStatus.HEALTHY
            and self.infra_metrics.is_infra_healthy
            and self.behavioral_metrics.is_behaviorally_healthy
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "replica_id": self.replica_id,
            "agent_id": self.agent_id,
            "version": self.version,
            "status": self.status.value,
            "workspace_id": self.workspace_id,
            "node_id": self.node_id,
            "is_healthy": self.is_healthy,
            "traffic_weight": self.traffic_weight,
            "infra": self.infra_metrics.to_dict(),
            "behavioral": self.behavioral_metrics.to_dict(),
            "last_heartbeat_at": self.last_heartbeat_at.isoformat(),
        }


@dataclass
class AgentEvaluationReport:
    """Formal qualification scorecard across the 10-phase promotion gate."""

    unit_tests_passed: bool
    schema_contract_valid: bool
    behavioral_test_score: float  # 0.0 to 1.0 (normal, late, missing, ood)
    safety_guardrails_passed: bool
    digital_twin_simulation_score: float
    baseline_outperformance_pct: float
    adversarial_robustness_score: float
    ood_drift_resilience: float
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    evaluator_id: str = "nexus_central_evaluator"

    @property
    def is_eligible_for_canary(self) -> bool:
        return (
            self.unit_tests_passed
            and self.schema_contract_valid
            and self.safety_guardrails_passed
            and self.behavioral_test_score >= 0.85
            and self.digital_twin_simulation_score >= 0.80
            and self.baseline_outperformance_pct >= 0.0
            and self.adversarial_robustness_score >= 0.85
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit_tests_passed": self.unit_tests_passed,
            "schema_contract_valid": self.schema_contract_valid,
            "behavioral_test_score": round(self.behavioral_test_score, 4),
            "safety_guardrails_passed": self.safety_guardrails_passed,
            "digital_twin_simulation_score": round(self.digital_twin_simulation_score, 4),
            "baseline_outperformance_pct": round(self.baseline_outperformance_pct, 2),
            "adversarial_robustness_score": round(self.adversarial_robustness_score, 4),
            "ood_drift_resilience": round(self.ood_drift_resilience, 4),
            "is_eligible_for_canary": self.is_eligible_for_canary,
            "evaluated_at": self.evaluated_at.isoformat(),
        }


@dataclass
class AgentArtifact:
    """Immutable, versioned artifact bundle produced by central training & evaluation."""

    artifact_id: str
    agent_id: str
    version: str
    domain: AgentDomain
    model_uri: str
    policy_id: str
    dataset_version: str
    training_run_id: str
    capability_manifest: SignedCapabilityManifest
    evaluation_report: AgentEvaluationReport | None = None
    lifecycle_state: AgentLifecycleState = AgentLifecycleState.REGISTERED
    canary_traffic_pct: float = 0.0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "agent_id": self.agent_id,
            "version": self.version,
            "domain": self.domain.value,
            "model_uri": self.model_uri,
            "policy_id": self.policy_id,
            "dataset_version": self.dataset_version,
            "training_run_id": self.training_run_id,
            "lifecycle_state": self.lifecycle_state.value,
            "canary_traffic_pct": self.canary_traffic_pct,
            "capability_manifest": self.capability_manifest.to_dict(),
            "evaluation_report": self.evaluation_report.to_dict() if self.evaluation_report else None,
            "created_at": self.created_at.isoformat(),
        }
