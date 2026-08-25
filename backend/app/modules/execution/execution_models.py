"""Execution Models — Data Contracts for Supervised Execution & Decision Memory.

Program N (Supervised Execution & Closed-Loop Operations):
- N.1: Action Plan & Lifecycle Statuses
- N.2: Policy & Safety Rules
- N.3: Simulation Gate Assertions
- N.4: Human Decision Records & Options
- N.5: Adapter Invocations & Rollback Traces
- N.6: Decision Memory Records
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from app.modules.rl.rl_models import MitigationAction


class PlanStatus(StrEnum):
    """Lifecycle states of an Action Plan."""

    DRAFT = "draft"
    POLICY_REJECTED = "policy_rejected"
    SIMULATION_PENDING = "simulation_pending"
    SIMULATION_FAILED = "simulation_failed"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    MODIFIED = "modified"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class ExecutionSystem(StrEnum):
    """Target enterprise systems for execution."""

    ERP = "erp"  # SAP, NetSuite, Oracle
    WMS = "wms"  # Manhattan, Blue Yonder
    TMS = "tms"  # Freight carriers, route dispatch
    PROCUREMENT = "procurement"
    INTERNAL_API = "internal_api"


class OperatorDecision(StrEnum):
    """Human-in-the-loop operator actions."""

    APPROVE = "approve"
    REJECT = "reject"
    MODIFY = "modify"
    SIMULATE_ALTERNATIVE = "simulate_alternative"


@dataclass(frozen=True)
class PolicyViolation:
    """Details of a policy constraint breach."""

    rule_name: str
    severity: str  # "critical", "warning"
    violation_message: str
    remediation_suggestion: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_name": self.rule_name,
            "severity": self.severity,
            "violation_message": self.violation_message,
            "remediation_suggestion": self.remediation_suggestion,
        }


@dataclass(frozen=True)
class ActionPlan:
    """Formal, immutable executable mitigation plan."""

    plan_id: str
    workspace_id: str
    world_id: str
    objective: str
    action: MitigationAction
    target_system: ExecutionSystem
    expected_cost_usd: float
    expected_benefit_usd: float
    expected_risk_score: float  # 0.0 - 1.0
    affected_entities: list[str]
    prerequisites: list[str]
    policy_version: str
    simulation_id: str | None
    status: PlanStatus
    violations: list[PolicyViolation] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "workspace_id": self.workspace_id,
            "world_id": self.world_id,
            "objective": self.objective,
            "action": self.action.to_dict(),
            "target_system": self.target_system.value
            if hasattr(self.target_system, "value")
            else str(self.target_system),
            "expected_cost_usd": round(self.expected_cost_usd, 2),
            "expected_benefit_usd": round(self.expected_benefit_usd, 2),
            "expected_risk_score": round(self.expected_risk_score, 4),
            "affected_entities": list(self.affected_entities),
            "prerequisites": list(self.prerequisites),
            "policy_version": self.policy_version,
            "simulation_id": self.simulation_id,
            "status": self.status.value if hasattr(self.status, "value") else str(self.status),
            "violations": [v.to_dict() for v in self.violations],
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True)
class SimulationGateResult:
    """Result of digital twin sandbox pre-execution dry-run."""

    plan_id: str
    simulation_passed: bool
    simulated_net_benefit_usd: float
    simulated_downstream_stockouts: int
    validation_log: str
    twin_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "simulation_passed": self.simulation_passed,
            "simulated_net_benefit_usd": round(self.simulated_net_benefit_usd, 2),
            "simulated_downstream_stockouts": self.simulated_downstream_stockouts,
            "validation_log": self.validation_log,
            "twin_id": self.twin_id,
        }


@dataclass(frozen=True)
class DecisionCardOption:
    """Alternative option displayed on the operator decision card."""

    option_id: str
    name: str
    action_type: str
    cost_usd: float
    revenue_protected_usd: float
    risk_level: str  # "Low", "Medium", "High"
    estimated_duration_hours: int
    is_recommended: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "option_id": self.option_id,
            "name": self.name,
            "action_type": self.action_type,
            "cost_usd": self.cost_usd,
            "revenue_protected_usd": self.revenue_protected_usd,
            "risk_level": self.risk_level,
            "estimated_duration_hours": self.estimated_duration_hours,
            "is_recommended": self.is_recommended,
        }


@dataclass(frozen=True)
class DecisionCard:
    """Decision-grade interactive briefing presented for human review."""

    card_id: str
    plan_id: str
    incident_summary: str
    cortex_prediction: str
    financial_exposure_usd: float
    options: list[DecisionCardOption]
    recommendation_rationale: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "card_id": self.card_id,
            "plan_id": self.plan_id,
            "incident_summary": self.incident_summary,
            "cortex_prediction": self.cortex_prediction,
            "financial_exposure_usd": round(self.financial_exposure_usd, 2),
            "options": [o.to_dict() for o in self.options],
            "recommendation_rationale": self.recommendation_rationale,
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True)
class ExecutionResult:
    """Result of external enterprise system connector invocation."""

    execution_id: str
    plan_id: str
    target_system: ExecutionSystem
    idempotency_key: str
    success: bool
    external_transaction_id: str | None
    latency_ms: float
    error_message: str | None = None
    audit_trace: dict[str, Any] = field(default_factory=dict)
    executed_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "plan_id": self.plan_id,
            "target_system": self.target_system.value,
            "idempotency_key": self.idempotency_key,
            "success": self.success,
            "external_transaction_id": self.external_transaction_id,
            "latency_ms": round(self.latency_ms, 2),
            "error_message": self.error_message,
            "audit_trace": dict(self.audit_trace),
            "executed_at": self.executed_at.isoformat(),
        }


@dataclass(frozen=True)
class DecisionMemoryRecord:
    """Complete immutable decision record closing the operational intelligence loop."""

    record_id: str
    workspace_id: str
    world_id: str
    plan: ActionPlan
    operator_decision: OperatorDecision
    operator_id: str
    execution_result: ExecutionResult | None
    actual_outcome_revenue_saved_usd: float
    predicted_vs_actual_error_pct: float
    flywheel_feedback_applied: bool
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "workspace_id": self.workspace_id,
            "world_id": self.world_id,
            "plan": self.plan.to_dict(),
            "operator_decision": self.operator_decision.value,
            "operator_id": self.operator_id,
            "execution_result": self.execution_result.to_dict() if self.execution_result else None,
            "actual_outcome_revenue_saved_usd": round(self.actual_outcome_revenue_saved_usd, 2),
            "predicted_vs_actual_error_pct": round(self.predicted_vs_actual_error_pct, 2),
            "flywheel_feedback_applied": self.flywheel_feedback_applied,
            "timestamp": self.timestamp.isoformat(),
        }
