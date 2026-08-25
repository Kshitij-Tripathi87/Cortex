"""Test GNN vs Deterministic Baseline Evaluation — Program K.7.

Verifies:
- Rigorous comparative evaluation of GNN against deterministic baselines
- Statistical significance validation (p < 0.05)
- Production gate enforcement
"""

from __future__ import annotations

from app.modules.gnn.gnn_evaluation import GNNEvaluationHarness
from app.modules.gnn.gnn_models import (
    CriticalNodePrediction,
    CriticalNodeReport,
    GNNTaskType,
    NodeType,
    SourcingFactorScores,
    SupplierSimilarityCandidate,
    SupplierSimilarityReport,
)


class TestGNNEvaluation:
    def test_compare_supplier_similarity_against_baseline(self) -> None:
        """GNN alternative sourcing evaluated against rule-based baseline."""
        harness = GNNEvaluationHarness()

        # GNN ranked report
        gnn_report = SupplierSimilarityReport(
            target_supplier_id="sup_target",
            target_supplier_name="Target Supplier",
            candidates=[
                SupplierSimilarityCandidate(
                    candidate_supplier_id="sup_best",
                    candidate_name="Best Supplier",
                    overall_match_score=0.92,
                    rank=1,
                    factor_scores=SourcingFactorScores(0.9, 0.9, 0.9, 0.9, 0.9),
                    estimated_lead_time_days=7.0,
                    health_score=0.98,
                    capacity_pct=100.0,
                ),
                SupplierSimilarityCandidate(
                    candidate_supplier_id="sup_second",
                    candidate_name="Second Supplier",
                    overall_match_score=0.81,
                    rank=2,
                    factor_scores=SourcingFactorScores(0.8, 0.8, 0.8, 0.8, 0.8),
                    estimated_lead_time_days=10.0,
                    health_score=0.90,
                    capacity_pct=90.0,
                ),
            ],
            model_version="gnn-v1.0",
        )

        baseline_candidates = ["sup_mediocre", "sup_best", "sup_second"]
        ground_truth = ["sup_best", "sup_second"]

        comparison = harness.compare_supplier_similarity(
            gnn_report=gnn_report,
            baseline_candidates=baseline_candidates,
            ground_truth_best=ground_truth,
        )

        assert comparison.task_type == GNNTaskType.SUPPLIER_SIMILARITY
        assert comparison.gnn_metrics["mrr"] == 1.0  # Top rank hit
        assert comparison.baseline_metrics["mrr"] == 0.5  # Rank 2 hit
        assert comparison.lift_pct["mrr_lift_pct"] == 100.0
        assert comparison.passed_production_gate is True
        assert comparison.statistically_significant is True

    def test_compare_critical_node_prediction_against_baseline(self) -> None:
        """GNN critical node prediction evaluated against betweenness centrality."""
        harness = GNNEvaluationHarness()

        gnn_report = CriticalNodeReport(
            workspace_id="ws_eval",
            world_id="world_eval",
            total_nodes_analyzed=10,
            critical_nodes=[
                CriticalNodePrediction(
                    node_id="node_a",
                    node_type=NodeType.SUPPLIER,
                    name="Supplier A",
                    criticality_score=0.88,
                    is_critical=True,
                    is_single_point_of_failure=True,
                    affected_downstream_nodes=5,
                    estimated_revenue_at_risk_usd=100000.0,
                ),
                CriticalNodePrediction(
                    node_id="node_b",
                    node_type=NodeType.FACTORY,
                    name="Factory B",
                    criticality_score=0.75,
                    is_critical=True,
                    is_single_point_of_failure=False,
                    affected_downstream_nodes=3,
                    estimated_revenue_at_risk_usd=50000.0,
                ),
            ],
            spof_count=1,
            max_network_risk_score=0.88,
            model_version="gnn-v1.0",
        )

        baseline_nodes = ["node_b", "node_c"]
        ground_truth_nodes = {"node_a", "node_b"}

        comparison = harness.compare_critical_node_prediction(
            gnn_report=gnn_report,
            baseline_critical_node_ids=baseline_nodes,
            ground_truth_critical_ids=ground_truth_nodes,
        )

        assert comparison.task_type == GNNTaskType.CRITICAL_NODE
        assert comparison.gnn_metrics["f1_score"] == 1.0  # Perfect precision & recall
        assert comparison.baseline_metrics["f1_score"] == 0.5
        assert comparison.passed_production_gate is True
        assert comparison.statistically_significant is True
