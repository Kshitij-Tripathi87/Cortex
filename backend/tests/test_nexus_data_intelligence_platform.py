"""Cortex Nexus — Program Q (Data Intelligence Plane) & Program R (Multi-Agent Platform) Comprehensive Test Net.

Validates the full enterprise loop on real Olist data:
- Q1 & Q2: Data Quality Profiler & Readiness Report
- Q3: Canonical Entity Resolution Layer
- Q4 & Q5: Operational Graph Engine & Structural Graph Analytics (PageRank, SPOFs, Centrality)
- Q6 & Q7: Temporal Operational State & Anomaly Signal Engine
- Q8: Root Cause Analysis & Blast Radius Impact Engine
- Q9: Graph Feature Store with Temporal Leakage Protection
- Q11: Authorized AgentContextPackage Builder
- R1 to R6: Graph-Aware Dynamic Agent Routing
- R7 to R10: Multi-Agent Consensus & Standardized Net Economic Value
- P0 Fixes: 100% Total Canary Traffic Accounting & Anti-Affinity Failure-Domain Scheduling
"""

import csv
import os
from datetime import UTC, datetime, timedelta

os.environ.setdefault("CORTEX_ENV", "dev")
os.environ.setdefault("CORTEX_DB_DSN", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("CORTEX_JWT_SECRET", "0" * 32)

import pytest

from app.common.context import ExecutionContext
from app.modules.data_intelligence.entity_resolution import EntityResolutionEngine
from app.modules.data_intelligence.feature_store import (
    GraphFeatureStore,
    VersionedFeatureVector,
)
from app.modules.data_intelligence.operational_graph import OperationalGraphEngine
from app.modules.data_intelligence.orchestrator import NexusDataIntelligenceOrchestrator
from app.modules.data_intelligence.profiler import DataQualityProfiler
from app.modules.data_intelligence.root_cause_engine import RootCauseImpactEngine
from app.modules.data_intelligence.signal_engine import OperationalSignalEngine

# Hermetic dataset: repo-checked-in Olist-shaped fixture, overridable via
# CORTEX_OLIST_DIR for runs against a downloaded full archive.
OLIST_DATA_DIR = os.environ.get(
    "CORTEX_OLIST_DIR",
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "tests",
        "fixtures",
        "olist",
    ),
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Program Q1 & Q2: Data Quality Engine
# ─────────────────────────────────────────────────────────────────────────────
def test_data_quality_profiler_on_real_olist():
    """Verify DataQualityProfiler inspects the Olist-shaped dataset and generates readiness report."""
    profiler = DataQualityProfiler()
    orders_path = os.path.join(OLIST_DATA_DIR, "olist_orders_dataset.csv")
    with open(orders_path, encoding="utf-8") as fh:
        expected_rows = sum(1 for _ in csv.DictReader(fh))

    report = profiler.profile_csv(
        filepath=orders_path,
        dataset_name="olist_orders",
        required_columns=["order_id", "customer_id", "order_status", "order_purchase_timestamp"],
        timestamp_columns=["order_purchase_timestamp", "order_delivered_customer_date"],
        primary_key="order_id",
        max_rows=1000,
    )

    assert report.total_records == expected_rows
    assert report.overall_readiness in {"READY", "READY_WITH_WARNINGS"}
    assert report.dimension_scores["SCHEMA"].passed is True
    assert report.dimension_scores["INTEGRITY"].passed is True
    assert report.dimension_scores["COMPLETENESS"].score_pct > 90.0


# ─────────────────────────────────────────────────────────────────────────────
# 2. Program Q3, Q4 & Q5: Canonical Entities & Operational Graph Analytics
# ─────────────────────────────────────────────────────────────────────────────
def test_operational_graph_and_analytics():
    """Verify Canonical Entity resolution and Graph Engine structural analytics."""
    entities = EntityResolutionEngine()
    graph = OperationalGraphEngine()

    s1 = entities.resolve_seller("s_100", "01310", "Sao Paulo", "SP")
    s2 = entities.resolve_seller("s_200", "20040", "Rio de Janeiro", "RJ")
    c1 = entities.resolve_customer("c_300", "01310", "Sao Paulo", "SP")

    graph.add_node(s1.canonical_id, "SUPPLIER", s1.attributes)
    graph.add_node(s2.canonical_id, "SUPPLIER", s2.attributes)
    graph.add_node(c1.canonical_id, "CUSTOMER", c1.attributes)
    graph.add_node("ord_01", "ORDER", {"price": 200.0})

    graph.add_edge(c1.canonical_id, "ord_01", "PLACED")
    graph.add_edge("ord_01", s1.canonical_id, "FULFILLED_BY")

    analytics = graph.compute_graph_analytics()
    assert analytics.total_nodes == 4
    assert analytics.total_edges == 2
    assert analytics.density > 0.0
    assert s1.canonical_id in graph.nodes


# ─────────────────────────────────────────────────────────────────────────────
# 3. Program Q6, Q7, Q8 & Q9: Signals, Blast Radius & Temporal Feature Store
# ─────────────────────────────────────────────────────────────────────────────
def test_signals_blast_radius_and_feature_store():
    """Verify operational anomaly detection, blast radius projection, and temporal leakage protection."""
    graph = OperationalGraphEngine()
    graph.add_node("seller_99", "SUPPLIER")
    graph.add_node("ord_1", "ORDER")
    graph.add_node("ord_2", "ORDER")
    graph.add_edge("ord_1", "seller_99", "FULFILLED_BY")
    graph.add_edge("ord_2", "seller_99", "FULFILLED_BY")

    # Signal Engine
    sig_engine = OperationalSignalEngine()
    sig = sig_engine.evaluate_seller_performance("seller_99", avg_dispatch_days=4.5, baseline_dispatch_days=2.0)
    assert sig is not None
    assert sig.signal_type == "SUPPLIER_DEGRADATION"
    assert sig.severity == "CRITICAL"

    # Root Cause & Blast Radius
    rc_engine = RootCauseImpactEngine(graph)
    blast = rc_engine.analyze_blast_radius(sig)
    assert blast.root_cause_entity_id == "seller_99"
    assert blast.total_revenue_at_risk_usd > 0.0

    # Feature Store & Temporal Leakage Check
    f_store = GraphFeatureStore()
    t_pred = datetime.now(UTC)
    t_past = t_pred - timedelta(days=1)
    t_future = t_pred + timedelta(days=1)

    f_store.put_features(VersionedFeatureVector("seller_99", "GRAPH", {"pagerank": 0.05}, 1, t_past))
    valid_feat = f_store.get_features_as_of("seller_99", "GRAPH", t_pred)
    assert valid_feat is not None
    assert valid_feat.features["pagerank"] == 0.05

    # Negative test: Hard Temporal Leakage rejection
    with pytest.raises(ValueError, match="Temporal Leakage Violation"):
        f_store.validate_no_temporal_leakage({"f": 1}, t_pred, {"future_feature": t_future})


# ─────────────────────────────────────────────────────────────────────────────
# 4. Program Q & R: Master End-to-End Orchestrator Pipeline
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_nexus_data_to_decision_orchestration():
    """Verify complete canonical Nexus Data -> Graph -> Signals -> Context -> Deliberation -> Evidence loop."""
    ctx = ExecutionContext.create_system_context()
    orchestrator = NexusDataIntelligenceOrchestrator()
    data_dir = OLIST_DATA_DIR

    result = await orchestrator.execute_data_to_decision_pipeline(
        data_dir=data_dir,
        context=ctx,
        max_orders=200,
        world_state_version=101,
    )

    # 1. Ingestion & Quality
    assert result.readiness_report.overall_readiness in {"READY", "READY_WITH_WARNINGS"}

    # 2. Multi-Table Operational Graph Coverage (Hundreds of real nodes & relationships)
    assert result.graph_analytics.coverage.total_nodes_created > 500
    assert result.graph_analytics.coverage.total_edges_created > 500
    assert "SUPPLIER" in result.graph_analytics.coverage.nodes_by_type
    assert "ORDER" in result.graph_analytics.coverage.nodes_by_type
    assert "CUSTOMER" in result.graph_analytics.coverage.nodes_by_type
    assert "ROUTE" in result.graph_analytics.coverage.nodes_by_type
    assert result.graph_analytics.coverage.relationship_coverage_pct > 95.0

    # 3. Signals & Blast Radius
    assert len(result.active_signals) >= 1
    assert result.blast_radius.total_revenue_at_risk_usd > 0.0

    # 4. Graph-Aware Dynamic Agent Selection
    assert len(result.participating_agents) == 3
    assert result.shipment_assessment.status in {"AT_RISK", "CRITICAL_DELAY"}
    assert len(result.routing_proposals) > 0

    # 5. Counterfactual Simulations & Decision Evidence Graph
    assert len(result.decision_evidence_graph["counterfactual_simulations"]) == 4
    optimal_sim = next(c for c in result.decision_evidence_graph["counterfactual_simulations"] if c["is_optimal"])
    assert optimal_sim["candidate"] == "CANDIDATE_C_AIR_EXPEDITE_AND_CROSS_DOCK"
    assert optimal_sim["net_economic_value_usd"] == 2900.0

    # 6. Full Attribution Lineage
    assert result.decision_evidence_graph["total_evidence_nodes"] >= 5
    assert result.decision_evidence_graph["total_attribution_edges"] >= 4
    assert result.synthesized_decision["status"] == "PROPOSED_FOR_POLICY_GATE"
    assert result.net_economic_value_usd == 2900.0  # Formula: Loss_without - Loss_with - Intervention_Cost
