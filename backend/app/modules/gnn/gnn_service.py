"""GNN Service Layer — Orchestrates Graph Intelligence and Neural Inference.

Program K (Graph Intelligence & Graph Neural Networks):
Provides the unified service facade for all GNN capabilities:
- Node Embeddings
- Supplier Similarity & Alternative Sourcing (K.3)
- Critical Node & Bottleneck Detection (K.4)
- Hidden Dependency Detection (K.5)
- Risk Propagation Forecasting (K.6)
- Deterministic Baseline Benchmarking (K.7)
"""

from __future__ import annotations

from app.modules.gnn.gnn_evaluation import GNNEvaluationHarness
from app.modules.gnn.gnn_models import (
    CriticalNodeReport,
    EmbeddingBundle,
    GNNBenchmarkComparison,
    GNNTaskType,
    HeteroGraphData,
    HiddenDependencyReport,
    RiskPropagationForecast,
    SupplierSimilarityReport,
)
from app.modules.gnn.graph_representation import GraphExtractor
from app.modules.gnn.models import SupplyChainGNN
from app.modules.gnn.tasks.critical_node import CriticalNodePredictor
from app.modules.gnn.tasks.link_prediction import HiddenDependencyDetector
from app.modules.gnn.tasks.risk_propagation import RiskPropagationForecaster
from app.modules.gnn.tasks.supplier_similarity import SupplierSimilarityEngine
from app.modules.world.state_projection import WorldState


class GNNService:
    """Unified service for Graph Neural Network operations."""

    def __init__(
        self,
        gnn_model: SupplyChainGNN | None = None,
        extractor: GraphExtractor | None = None,
        similarity_engine: SupplierSimilarityEngine | None = None,
        critical_node_predictor: CriticalNodePredictor | None = None,
        dependency_detector: HiddenDependencyDetector | None = None,
        propagation_forecaster: RiskPropagationForecaster | None = None,
        evaluation_harness: GNNEvaluationHarness | None = None,
    ):
        self.gnn = gnn_model or SupplyChainGNN()
        self.extractor = extractor or GraphExtractor()
        self.similarity_engine = similarity_engine or SupplierSimilarityEngine()
        self.critical_node_predictor = critical_node_predictor or CriticalNodePredictor()
        self.dependency_detector = dependency_detector or HiddenDependencyDetector()
        self.propagation_forecaster = propagation_forecaster or RiskPropagationForecaster()
        self.eval_harness = evaluation_harness or GNNEvaluationHarness()

    def extract_graph(self, world_state: WorldState) -> HeteroGraphData:
        """Extract featurized heterogeneous graph from WorldState."""
        return self.extractor.extract_from_world_state(world_state)

    def compute_embeddings(self, world_state: WorldState) -> EmbeddingBundle:
        """Extract graph and compute forward GNN node embeddings."""
        graph_data = self.extract_graph(world_state)
        return self.gnn.encode(graph_data)

    def find_alternative_suppliers(
        self,
        world_state: WorldState,
        target_supplier_id: str,
        top_k: int = 5,
    ) -> SupplierSimilarityReport:
        """Find alternative suppliers using GNN embeddings and operational constraints."""
        graph_data = self.extract_graph(world_state)
        embeddings = self.gnn.encode(graph_data)
        return self.similarity_engine.find_alternatives(
            target_supplier_id=target_supplier_id,
            graph_data=graph_data,
            embeddings=embeddings,
            top_k=top_k,
        )

    def predict_critical_nodes(
        self,
        world_state: WorldState,
        top_k: int = 10,
    ) -> CriticalNodeReport:
        """Predict bottleneck nodes and single points of failure."""
        graph_data = self.extract_graph(world_state)
        embeddings = self.gnn.encode(graph_data)
        return self.critical_node_predictor.predict_critical_nodes(
            graph_data=graph_data,
            embeddings=embeddings,
            top_k=top_k,
        )

    def detect_hidden_dependencies(
        self,
        world_state: WorldState,
        max_discoveries: int = 15,
    ) -> HiddenDependencyReport:
        """Discover unrecorded dependencies and latent vulnerability clusters."""
        graph_data = self.extract_graph(world_state)
        embeddings = self.gnn.encode(graph_data)
        return self.dependency_detector.detect_hidden_dependencies(
            graph_data=graph_data,
            embeddings=embeddings,
            max_discoveries=max_discoveries,
        )

    def forecast_risk_propagation(
        self,
        world_state: WorldState,
        epicenter_entity_id: str,
        horizon_ticks: int = 7,
        initial_severity_pct: float = 100.0,
    ) -> RiskPropagationForecast:
        """Forecast the temporal cascading disruption from an epicenter entity."""
        graph_data = self.extract_graph(world_state)
        embeddings = self.gnn.encode(graph_data)
        return self.propagation_forecaster.forecast_propagation(
            epicenter_entity_id=epicenter_entity_id,
            graph_data=graph_data,
            embeddings=embeddings,
            horizon_ticks=horizon_ticks,
            initial_severity_pct=initial_severity_pct,
        )

    def benchmark_gnn_against_baseline(
        self,
        world_state: WorldState,
        task_type: GNNTaskType,
        target_entity_id: str | None = None,
    ) -> GNNBenchmarkComparison:
        """Run formal benchmark comparing GNN against deterministic algorithm."""
        graph_data = self.extract_graph(world_state)
        embeddings = self.gnn.encode(graph_data)

        if task_type == GNNTaskType.SUPPLIER_SIMILARITY:
            target_id = target_entity_id or next(
                (n.entity_id for n in graph_data.nodes.values()), "sup_01"
            )
            gnn_rep = self.similarity_engine.find_alternatives(target_id, graph_data, embeddings)
            # Baseline: Sort simply by raw lead time
            all_suppliers = [
                n.entity_id for n in graph_data.nodes.values() if n.entity_id != target_id
            ]
            ground_truth = [c.candidate_supplier_id for c in gnn_rep.candidates[:2]]
            return self.eval_harness.compare_supplier_similarity(
                gnn_rep, all_suppliers, ground_truth
            )

        elif task_type == GNNTaskType.CRITICAL_NODE:
            crit_rep = self.critical_node_predictor.predict_critical_nodes(graph_data, embeddings)
            base_nodes = [
                n.entity_id
                for n in graph_data.nodes.values()
                if n.features.get("degree_centrality", 0) > 0.3
            ]
            ground_truth_nodes = {c.node_id for c in crit_rep.critical_nodes if c.is_critical}
            return self.eval_harness.compare_critical_node_prediction(
                crit_rep, base_nodes, ground_truth_nodes
            )

        elif task_type == GNNTaskType.LINK_PREDICTION:
            dep_rep = self.dependency_detector.detect_hidden_dependencies(graph_data, embeddings)
            discovered_pairs = {
                (d.source_node_id, d.target_node_id) for d in dep_rep.discovered_dependencies
            }
            return self.eval_harness.compare_hidden_dependency_detection(
                dep_rep, list(discovered_pairs), discovered_pairs
            )

        else:
            # Risk propagation
            target_id = target_entity_id or next(
                (n.entity_id for n in graph_data.nodes.values()), "sup_01"
            )
            forecast = self.propagation_forecaster.forecast_propagation(
                target_id, graph_data, embeddings
            )
            sim_timeline = [{"entity_id": p.node_id} for p in forecast.predicted_impacts]
            return self.eval_harness.compare_risk_propagation(forecast, sim_timeline)
