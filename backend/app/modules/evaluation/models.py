"""Evaluation Harness Models — Contracts for benchmarking and evaluation."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field

from app.common.ids import uuid7


class EngineType(StrEnum):
    """Type of engine being evaluated."""

    DETERMINISTIC = "deterministic"
    GNN = "gnn"
    RL = "rl"
    HEURISTIC = "heuristic"
    HYBRID = "hybrid"


class EvaluationStatus(StrEnum):
    """Status of an evaluation run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class MetricType(StrEnum):
    """Types of evaluation metrics."""

    # Classification metrics
    PRECISION = "precision"
    RECALL = "recall"
    F1 = "f1"
    EXACT_MATCH = "exact_match"
    ACCURACY = "accuracy"

    # Regression metrics
    REVENUE_ERROR = "revenue_error"
    REVENUE_RELATIVE_ERROR = "revenue_relative_error"
    MARGIN_ERROR = "margin_error"
    PENALTY_ERROR = "penalty_error"
    WC_ERROR = "working_capital_error"
    TIMELINE_ERROR = "timeline_error"
    STOCKOUT_DEADLINE_ERROR = "stockout_deadline_error"

    # Ranking metrics
    RECOMMENDATION_RANK_AGREEMENT = "recommendation_rank_agreement"
    NDCG = "ndcg"
    MRR = "mrr"

    # Confidence metrics
    CALIBRATION_ERROR = "calibration_error"
    ECE = "expected_calibration_error"
    MCE = "maximum_calibration_error"
    BRIER_SCORE = "brier_score"

    # Latency
    LATENCY_P50 = "latency_p50"
    LATENCY_P95 = "latency_p95"
    LATENCY_P99 = "latency_p99"


class ScenarioResult(BaseModel):
    """Result for a single scenario evaluation."""

    scenario_id: str
    scenario_type: str
    supplier_name: str

    # Ground truth
    gt_affected_components: list[dict] = []
    gt_affected_products: list[dict] = []
    gt_affected_warehouses: list[dict] = []
    gt_affected_orders: list[dict] = []
    gt_stockout_events: list[dict] = []
    gt_revenue_risk: float = 0.0
    gt_margin_risk: float = 0.0
    gt_penalty_exposure: float = 0.0
    gt_deadline_hours: float = 0.0
    gt_recommendations: list[dict] = []
    gt_confidence: float = 0.0

    # Predictions
    pred_affected_components: list[dict] = []
    pred_affected_products: list[dict] = []
    pred_affected_warehouses: list[dict] = []
    pred_affected_orders: list[dict] = []
    pred_stockout_events: list[dict] = []
    pred_revenue_risk: float = 0.0
    pred_margin_risk: float = 0.0
    pred_penalty_exposure: float = 0.0
    pred_deadline_hours: float = 0.0
    pred_recommendations: list[dict] = []
    pred_confidence: float = 0.0

    # Computed metrics
    component_precision: float | None = None
    component_recall: float | None = None
    component_f1: float | None = None
    component_exact_match: bool | None = None

    product_precision: float | None = None
    product_recall: float | None = None
    product_f1: float | None = None
    product_exact_match: bool | None = None

    warehouse_precision: float | None = None
    warehouse_recall: float | None = None
    warehouse_f1: float | None = None

    order_precision: float | None = None
    order_recall: float | None = None
    order_f1: float | None = None

    revenue_error: float | None = None
    revenue_relative_error: float | None = None
    margin_error: float | None = None
    penalty_error: float | None = None
    deadline_error: float | None = None

    recommendation_rank_agreement: float | None = None
    confidence_calibration_error: float | None = None

    # Errors
    error: str | None = None


class MetricResult(BaseModel):
    """Individual metric result."""

    metric_type: str
    name: str
    value: float
    dataset_id: str | None = None
    scenario_id: str | None = None
    engine_type: str
    engine_version: str | None = None
    computed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict = {}


class EvaluationRun(BaseModel):
    """Complete evaluation run record."""

    run_id: UUID = Field(default_factory=uuid7)
    dataset_id: str
    dataset_version: int
    engine_type: str
    engine_version: str | None = None

    status: str = "pending"
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    duration_seconds: float | None = None

    # Configuration
    dataset_id: str
    dataset_version: int
    engine_type: str
    engine_version: str | None = None
    scenarios_evaluated: list[str] = []
    scenarios_total: int = 0

    # Results
    scenario_results: list[dict] = []
    aggregate_metrics: dict[str, float] = {}
    per_scenario_metrics: dict[str, dict[str, float]] = {}

    # Status
    status: str = "pending"
    error: str | None = None

    # Timing
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    duration_seconds: float | None = None


class EvaluationSummary(BaseModel):
    """Summary of evaluation results across runs."""

    run_id: str
    engine_type: str
    engine_version: str | None
    dataset_id: str
    dataset_version: int
    timestamp: datetime

    # Aggregate metrics
    component_precision: float
    component_recall: float
    component_f1: float
    component_exact_match_rate: float

    product_precision: float
    product_recall: float
    product_f1: float
    product_exact_match_rate: float

    warehouse_precision: float
    warehouse_recall: float
    warehouse_f1: float

    order_precision: float
    order_recall: float
    order_f1: float

    revenue_mae: float
    revenue_mape: float
    margin_mae: float
    penalty_mae: float
    deadline_mae: float

    recommendation_rank_agreement: float
    calibration_ece: float
    calibration_mce: float
    brier_score: float

    # Scenario breakdown
    scenarios_passed: int
    scenarios_total: int
    scenarios_failed: list[str] = []

    # Latency
    latency_p50_ms: float
    latency_p95_ms: float
    latency_p99_ms: float


class EngineComparison(BaseModel):
    """Comparison between two or more engines."""

    comparison_id: UUID = Field(default_factory=uuid7)
    baseline_engine: str
    baseline_version: str
    candidate_engines: list[dict]  # {engine_type, version}

    dataset_id: str
    dataset_version: int

    results: dict[str, dict]  # engine -> metrics
    winner: str | None = None
    significance: dict[str, float] = {}  # p-values

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class EvaluationReport(BaseModel):
    """Complete evaluation report."""

    report_id: UUID = Field(default_factory=uuid7)
    run_id: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    summary: EvaluationSummary
    scenario_details: list[dict]
    per_scenario_metrics: dict[str, dict]
    engine_comparisons: list[EngineComparison] = []

    # Visualization data
    confusion_matrices: dict[str, dict] = {}
    calibration_curves: dict[str, list[dict]] = {}


# Type aliases for clarity
ScenarioID = str
DatasetID = str
EngineID = str

__all__ = [
    "EngineType",
    "MetricType",
    "ScenarioResult",
    "MetricResult",
    "EvaluationRun",
    "EvaluationSummary",
    "EngineComparison",
    "EvaluationReport",
]
