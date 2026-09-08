"""Phase A — Agent Specifications & Training Contracts.

Defines the formal contract for trainable agents:
- Objective declarations
- Input and output JSON schemas
- Capability constraints (READ, PROPOSE, SIMULATE, EXECUTE)
- Minimum qualification acceptance thresholds (Accuracy, ECE, Drift, Latency)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.common.capabilities import Capability
from app.modules.agents.lifecycle_models import AgentDomain


@dataclass
class EvaluationThresholds:
    min_accuracy: float = 0.85
    max_calibration_error_ece: float = 0.10
    max_prediction_drift: float = 0.30
    max_latency_p99_ms: float = 100.0
    min_simulation_score: float = 0.80
    min_baseline_outperformance_pct: float = 5.0
    max_false_positive_rate: float = 0.08


@dataclass
class AgentSpecification:
    """Formal specification and contract for a trainable agent in Cortex Nexus."""

    agent_id: str
    domain: AgentDomain
    version: str
    objectives: list[str]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    allowed_capabilities: list[str]
    allowed_tools: list[str]
    thresholds: EvaluationThresholds = field(default_factory=EvaluationThresholds)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def validate_capability_privileges(self) -> bool:
        """Enforce privilege separation: Specialist domain agents must NOT have EXECUTE."""
        return not (
            Capability.EXECUTE.value in self.allowed_capabilities
            and self.domain != AgentDomain.EXECUTIVE_COORDINATOR
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "domain": self.domain.value,
            "version": self.version,
            "objectives": self.objectives,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "allowed_capabilities": self.allowed_capabilities,
            "allowed_tools": self.allowed_tools,
            "thresholds": {
                "min_accuracy": self.thresholds.min_accuracy,
                "max_calibration_error_ece": self.thresholds.max_calibration_error_ece,
                "max_prediction_drift": self.thresholds.max_prediction_drift,
                "max_latency_p99_ms": self.thresholds.max_latency_p99_ms,
                "min_simulation_score": self.thresholds.min_simulation_score,
                "min_baseline_outperformance_pct": self.thresholds.min_baseline_outperformance_pct,
            },
            "created_at": self.created_at.isoformat(),
        }


# Canonical Built-in Specifications
def get_canonical_shipment_tracking_spec(version: str = "v8") -> AgentSpecification:
    return AgentSpecification(
        agent_id="shipment_tracking_agent",
        domain=AgentDomain.SHIPMENT_TRACKING,
        version=version,
        objectives=[
            "Detect overdue shipments and port bottlenecks",
            "Predict exception severity and latency risk",
            "Propose air-freight expedite actions when delay exceeds SLA",
        ],
        input_schema={
            "type": "object",
            "required": [
                "shipment_id",
                "origin",
                "destination",
                "planned_eta_days",
                "elapsed_days",
            ],
            "properties": {
                "shipment_id": {"type": "string"},
                "origin": {"type": "string"},
                "destination": {"type": "string"},
                "planned_eta_days": {"type": "number"},
                "elapsed_days": {"type": "number"},
                "port_congestion_index": {"type": "number"},
                "weather_severity": {"type": "number"},
            },
        },
        output_schema={
            "type": "object",
            "required": [
                "shipment_id",
                "status",
                "risk_score",
                "predicted_delay_days",
                "mitigation_needed",
            ],
            "properties": {
                "shipment_id": {"type": "string"},
                "status": {"type": "string", "enum": ["ON_TIME", "AT_RISK", "CRITICAL_DELAY"]},
                "risk_score": {"type": "number"},
                "predicted_delay_days": {"type": "number"},
                "mitigation_needed": {"type": "boolean"},
                "recommended_action": {"type": "object"},
            },
        },
        allowed_capabilities=[
            Capability.READ.value,
            Capability.PROPOSE.value,
            Capability.SIMULATE.value,
        ],
        allowed_tools=["get_shipment_telemetry", "get_port_congestion", "simulate_eta"],
    )
