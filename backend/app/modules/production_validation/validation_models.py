"""Program P — Enterprise Production Validation & Controlled Deployment Models.

Data Contracts for:
- P.1 / P.2: Minimal Enterprise Integration Contract & Ingestion Lineage
- P.3: Temporal Historical Backtesting (No-leakage ground truth comparison)
- P.4: Intelligence Progression Comparison (L1 Deterministic vs L2 +GNN vs L3 +RL+Agents)
- P.5: Agent Evidence Grounding & Hallucination Audit
- P.6: Tiered Autonomy Levels (L0 to L5)
- P.9: Observability ("Is Cortex Becoming More Correct?")
- P.10: The Ultimate Cortex Decision Lifecycle Object
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from app.modules.execution.execution_models import ExecutionResult, OperatorDecision
from app.modules.rl.rl_models import MitigationAction


class AutonomyLevel(StrEnum):
    """The six progressive autonomy tiers for Cortex operations."""

    L0_OBSERVE = "L0_OBSERVE"
    L1_RECOMMEND = "L1_RECOMMEND"
    L2_SIMULATE = "L2_SIMULATE"
    L3_HUMAN_APPROVE = "L3_HUMAN_APPROVE"
    L4_POLICY_AUTO = "L4_POLICY_AUTO"
    L5_FULL_AUTONOMOUS = "L5_FULL_AUTONOMOUS"


class ValidationEnvironment(StrEnum):
    """Rigorous classification of the validation environment."""

    CONTROLLED_SYNTHETIC = "CONTROLLED_SYNTHETIC"
    HISTORICAL_REPLAY = "HISTORICAL_REPLAY"
    LIVE_CUSTOMER = "LIVE_CUSTOMER"


class PilotExclusionReason(StrEnum):
    """Categorization for why an operational disruption was excluded from evaluation."""

    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    MISSING_HISTORICAL_STATE = "MISSING_HISTORICAL_STATE"
    OUTSIDE_WEDGE_SCOPE = "OUTSIDE_WEDGE_SCOPE"
    OPERATOR_BYPASS = "OPERATOR_BYPASS"


@dataclass(frozen=True)
class DataReadinessWarning:
    """Actionable warning produced during enterprise data onboarding audit."""

    category: str  # "SUPPLIERS", "INVENTORY", "BOM", "ORDERS", "LEAD_TIMES"
    warning_text: str
    affected_entity_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "warning_text": self.warning_text,
            "affected_entity_count": self.affected_entity_count,
        }


@dataclass(frozen=True)
class DataReadinessReport:
    """Pre-flight audit report assessing customer data completeness before pilot activation."""

    customer_name: str
    overall_readiness_pct: float
    domain_completeness_pct: dict[str, float]  # e.g. {"suppliers": 98.0, "inventory": 94.0}
    is_pilot_ready: bool
    warnings: list[DataReadinessWarning] = field(default_factory=list)
    audited_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "customer_name": self.customer_name,
            "overall_readiness_pct": round(self.overall_readiness_pct, 2),
            "domain_completeness_pct": {
                k: round(v, 2) for k, v in self.domain_completeness_pct.items()
            },
            "is_pilot_ready": self.is_pilot_ready,
            "warnings": [w.to_dict() for w in self.warnings],
            "audited_at": self.audited_at.isoformat(),
        }


@dataclass(frozen=True)
class PilotCoverageMetrics:
    """Comprehensive decision coverage and eligibility statistics for a customer pilot."""

    total_eligible_disruptions: int
    incidents_evaluated: int
    incidents_excluded: int
    exclusion_breakdown: dict[str, int]
    decision_coverage_pct: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_eligible_disruptions": self.total_eligible_disruptions,
            "incidents_evaluated": self.incidents_evaluated,
            "incidents_excluded": self.incidents_excluded,
            "exclusion_breakdown": self.exclusion_breakdown,
            "decision_coverage_pct": round(self.decision_coverage_pct, 2),
        }


class DisruptionType(StrEnum):
    """Historical and real-time operational disruption categories."""

    SUPPLIER_DELAY = "supplier_delay"
    SUPPLIER_BANKRUPTCY = "supplier_bankruptcy"
    FACTORY_FIRE_OR_OUTAGE = "factory_outage"
    PORT_OR_TRANSIT_CLOSURE = "transit_closure"
    INVENTORY_SPOILAGE = "inventory_shortage"
    DEMAND_SPIKE = "demand_spike"


@dataclass(frozen=True)
class MinimalEnterpriseContract:
    """Minimal customer data schema for frictionless pilot integration."""

    suppliers: list[dict[str, Any]]
    components: list[dict[str, Any]]
    bill_of_materials: list[dict[str, Any]]
    warehouses: list[dict[str, Any]]
    inventory_levels: list[dict[str, Any]]
    factories: list[dict[str, Any]]
    purchase_orders: list[dict[str, Any]]
    source_checksum_sha256: str
    ingestion_timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "num_suppliers": len(self.suppliers),
            "num_components": len(self.components),
            "num_bom_records": len(self.bill_of_materials),
            "num_warehouses": len(self.warehouses),
            "num_inventory_records": len(self.inventory_levels),
            "num_factories": len(self.factories),
            "num_orders": len(self.purchase_orders),
            "source_checksum_sha256": self.source_checksum_sha256,
            "ingestion_timestamp": self.ingestion_timestamp.isoformat(),
        }


@dataclass(frozen=True)
class TemporalBacktestScenario:
    """Historical incident definition frozen at pre-event timestamp T_0."""

    scenario_id: str
    incident_name: str
    disruption_type: DisruptionType
    pre_event_world_id: str
    disrupted_entity_id: str
    ground_truth_actual_revenue_loss_usd: float
    ground_truth_affected_products: list[str]
    ground_truth_stockout_hours: float
    ground_truth_recovery_days: float


@dataclass(frozen=True)
class TemporalBacktestResult:
    """Rigorous evaluation of Cortex predictions vs empirical historical truth without leakage."""

    scenario_id: str
    incident_name: str
    predicted_revenue_exposure_usd: float
    actual_revenue_loss_usd: float
    revenue_error_pct: float
    predicted_stockout_hours: float
    actual_stockout_hours: float
    stockout_timing_error_hours: float
    product_impact_precision: float
    product_impact_recall: float
    recommended_mitigation_net_value_usd: float
    backtest_passed: bool
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "incident_name": self.incident_name,
            "predicted_revenue_exposure_usd": round(self.predicted_revenue_exposure_usd, 2),
            "actual_revenue_loss_usd": round(self.actual_revenue_loss_usd, 2),
            "revenue_error_pct": round(self.revenue_error_pct, 2),
            "predicted_stockout_hours": round(self.predicted_stockout_hours, 1),
            "actual_stockout_hours": round(self.actual_stockout_hours, 1),
            "stockout_timing_error_hours": round(self.stockout_timing_error_hours, 1),
            "product_impact_precision": round(self.product_impact_precision, 4),
            "product_impact_recall": round(self.product_impact_recall, 4),
            "recommended_mitigation_net_value_usd": round(
                self.recommended_mitigation_net_value_usd, 2
            ),
            "backtest_passed": self.backtest_passed,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass(frozen=True)
class IntelligenceLevelMetrics:
    """Performance metrics for an intelligence tier."""

    level_name: str  # "L1_Deterministic", "L2_GNN", "L3_MultiAgent_RL"
    mean_revenue_error_pct: float
    stockout_timing_mae_hours: float
    net_economic_value_created_usd: float
    recommendation_f1: float
    is_production_ready: bool


@dataclass(frozen=True)
class IntelligenceProgressionReport:
    """Evaluates whether sophisticated ML/Agents demonstrably outperform simpler baselines."""

    scenario_count: int
    level1_deterministic: IntelligenceLevelMetrics
    level2_gnn_augmented: IntelligenceLevelMetrics
    level3_full_multiagent_rl: IntelligenceLevelMetrics
    gnn_lift_pct: float
    multiagent_rl_lift_pct: float
    recommended_active_intelligence_tier: str
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_count": self.scenario_count,
            "level1_deterministic": self.level1_deterministic.__dict__,
            "level2_gnn_augmented": self.level2_gnn_augmented.__dict__,
            "level3_full_multiagent_rl": self.level3_full_multiagent_rl.__dict__,
            "gnn_lift_pct": round(self.gnn_lift_pct, 2),
            "multiagent_rl_lift_pct": round(self.multiagent_rl_lift_pct, 2),
            "recommended_active_intelligence_tier": self.recommended_active_intelligence_tier,
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class AgentGroundingAuditResult:
    """Verifies that all agent claims are strictly grounded in verifiable evidence."""

    proposal_id: str
    agent_role: str
    total_claims: int
    verified_grounded_claims: int
    unverified_or_hallucinated_claims: int
    grounding_rate_pct: float
    evidence_citations: list[str]
    audit_passed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "agent_role": self.agent_role,
            "total_claims": self.total_claims,
            "verified_grounded_claims": self.verified_grounded_claims,
            "unverified_or_hallucinated_claims": self.unverified_or_hallucinated_claims,
            "grounding_rate_pct": round(self.grounding_rate_pct, 2),
            "evidence_citations": list(self.evidence_citations),
            "audit_passed": self.audit_passed,
        }


@dataclass(frozen=True)
class CortexDecisionLifecycle:
    """The unified end-to-end Cortex operational decision record."""

    decision_id: str
    workspace_id: str
    # 1. Event & World State
    incident_description: str
    affected_entities: list[str]
    # 2. Predicted Impact
    revenue_at_risk_usd: float
    margin_at_risk_usd: float
    customers_exposed: int
    hours_to_first_stockout: float
    # 3. Options Matrix
    recommended_action: MitigationAction
    alternative_actions: list[dict[str, Any]]
    # 4. Intelligence & Consensus
    twin_simulation_id: str
    gnn_model_version: str
    rl_policy_version: str
    agent_consensus_score: float
    # 5. Policy & Governance
    policy_status: str  # "PASS", "FAIL"
    autonomy_level: AutonomyLevel
    # 6. Human Authorization
    operator_decision: OperatorDecision
    operator_id: str
    # 7. Enterprise Execution
    execution_result: ExecutionResult | None
    # 8. Observed Outcome & Economic Value Created
    actual_revenue_protected_usd: float
    intervention_cost_usd: float
    net_economic_value_created_usd: float  # (Loss_without - Loss_with - Cost)
    prediction_error_pct: float
    # 9. Closed-Loop Learning
    decision_memory_record_id: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "workspace_id": self.workspace_id,
            "incident_description": self.incident_description,
            "affected_entities": list(self.affected_entities),
            "revenue_at_risk_usd": round(self.revenue_at_risk_usd, 2),
            "margin_at_risk_usd": round(self.margin_at_risk_usd, 2),
            "customers_exposed": self.customers_exposed,
            "hours_to_first_stockout": round(self.hours_to_first_stockout, 1),
            "recommended_action": self.recommended_action.to_dict(),
            "alternative_actions": self.alternative_actions,
            "twin_simulation_id": self.twin_simulation_id,
            "gnn_model_version": self.gnn_model_version,
            "rl_policy_version": self.rl_policy_version,
            "agent_consensus_score": round(self.agent_consensus_score, 4),
            "policy_status": self.policy_status,
            "autonomy_level": self.autonomy_level.name,
            "operator_decision": self.operator_decision.value,
            "operator_id": self.operator_id,
            "execution_result": self.execution_result.to_dict() if self.execution_result else None,
            "actual_revenue_protected_usd": round(self.actual_revenue_protected_usd, 2),
            "intervention_cost_usd": round(self.intervention_cost_usd, 2),
            "net_economic_value_created_usd": round(self.net_economic_value_created_usd, 2),
            "prediction_error_pct": round(self.prediction_error_pct, 2),
            "decision_memory_record_id": self.decision_memory_record_id,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass(frozen=True)
class MetricComparisonRow:
    """Predicted vs Actual vs Error row for CFO/COO pilot validation reports."""

    metric_name: str
    cortex_predicted: float
    actual_ground_truth: float
    error_pct: float
    unit: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_name": self.metric_name,
            "cortex_predicted": round(self.cortex_predicted, 2),
            "actual_ground_truth": round(self.actual_ground_truth, 2),
            "error_pct": round(self.error_pct, 2),
            "unit": self.unit,
        }


@dataclass(frozen=True)
class HumanDecisionBenchmark:
    """Comparative analysis of Cortex recommendation vs historical human operator choice."""

    benchmark_id: str
    scenario_title: str
    cortex_action: str
    cortex_net_value_usd: float
    human_action: str
    human_net_value_usd: float
    actual_unmitigated_loss_usd: float
    economic_delta_usd: float  # cortex_net_value - human_net_value
    would_cortex_have_improved_decision: bool
    winner: str  # "CORTEX", "HUMAN", "TIE"
    verdict_rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "benchmark_id": self.benchmark_id,
            "scenario_title": self.scenario_title,
            "cortex_action": self.cortex_action,
            "cortex_net_value_usd": round(self.cortex_net_value_usd, 2),
            "human_action": self.human_action,
            "human_net_value_usd": round(self.human_net_value_usd, 2),
            "actual_unmitigated_loss_usd": round(self.actual_unmitigated_loss_usd, 2),
            "economic_delta_usd": round(self.economic_delta_usd, 2),
            "would_cortex_have_improved_decision": self.would_cortex_have_improved_decision,
            "winner": self.winner,
            "verdict_rationale": self.verdict_rationale,
        }


@dataclass(frozen=True)
class CortexPilotValidationReport:
    """The canonical CFO/COO validation artifact evaluating real or controlled customer operations."""

    report_id: str
    customer_name: str
    incident_title: str
    environment_type: ValidationEnvironment
    data_source_summary: str
    metric_comparisons: list[MetricComparisonRow]
    layer_progression: IntelligenceProgressionReport
    human_benchmark: HumanDecisionBenchmark
    intervention_cost_usd: float
    loss_avoided_usd: float
    net_economic_value_usd: float
    would_cortex_have_improved_decision: bool
    executive_verdict: str
    customer_workspace_id: str | None = None
    provenance_audit_hash: str | None = None
    evidence_citations: list[str] = field(default_factory=list)
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "customer_name": self.customer_name,
            "incident_title": self.incident_title,
            "environment_type": self.environment_type.value,
            "data_source_summary": self.data_source_summary,
            "metric_comparisons": [m.to_dict() for m in self.metric_comparisons],
            "layer_progression": self.layer_progression.to_dict(),
            "human_benchmark": self.human_benchmark.to_dict(),
            "intervention_cost_usd": round(self.intervention_cost_usd, 2),
            "loss_avoided_usd": round(self.loss_avoided_usd, 2),
            "net_economic_value_usd": round(self.net_economic_value_usd, 2),
            "would_cortex_have_improved_decision": self.would_cortex_have_improved_decision,
            "executive_verdict": self.executive_verdict,
            "customer_workspace_id": self.customer_workspace_id,
            "provenance_audit_hash": self.provenance_audit_hash,
            "evidence_citations": list(self.evidence_citations),
            "generated_at": self.generated_at.isoformat(),
        }
