"""Evaluation Harness Module — Benchmarking and evaluation infrastructure."""

from app.modules.evaluation.benchmark_runner import BenchmarkRunner, run_benchmark
from app.modules.evaluation.comparison import (
    EngineComparator,
    generate_comparison_report,
    paired_significance,
    statistical_significance,
    wilcoxon_test,
)
from app.modules.evaluation.metrics import (
    average_precision,
    bootstrap_ci,
    brier_score,
    calibration_ece,
    confidence_interval,
    exact_match,
    kendall_tau,
    mae,
    mape,
    mce,
    mean_average_precision,
    mrr,
    ndcg_at_k,
    precision_recall_f1,
    recommendation_rank_agreement,
    reliability_diagram,
    rmse,
    spearman_rho,
    timeline_error,
)
from app.modules.evaluation.models import (
    EngineComparison,
    EngineType,
    EvaluationReport,
    EvaluationRun,
    EvaluationSummary,
    MetricResult,
    MetricType,
    ScenarioResult,
)
from app.modules.evaluation.registry import EvaluationRegistry, EvaluationRunRecord
from app.modules.evaluation.simulation_evaluation import (
    SimulationBenchmarkRecord,
    SimulationEvaluationHarness,
    TrajectoryEvaluationResult,
)

__all__ = [
    # Models
    "EngineType",
    "MetricType",
    "ScenarioResult",
    "MetricResult",
    "EvaluationRun",
    "EvaluationSummary",
    "EngineComparison",
    "EvaluationReport",
    # Simulation Evaluation Bridge
    "SimulationBenchmarkRecord",
    "SimulationEvaluationHarness",
    "TrajectoryEvaluationResult",
    # Benchmark
    "BenchmarkRunner",
    "run_benchmark",
    # Metrics
    "precision_recall_f1",
    "exact_match",
    "mae",
    "mape",
    "rmse",
    "calibration_ece",
    "mce",
    "brier_score",
    "reliability_diagram",
    "ndcg_at_k",
    "mrr",
    "kendall_tau",
    "spearman_rho",
    "average_precision",
    "mean_average_precision",
    "recommendation_rank_agreement",
    "timeline_error",
    "confidence_interval",
    "bootstrap_ci",
    # Registry
    "EvaluationRunRecord",
    "EvaluationRegistry",
    # Comparison
    "EngineComparator",
    "generate_comparison_report",
    "statistical_significance",
    "paired_significance",
    "wilcoxon_test",
]
