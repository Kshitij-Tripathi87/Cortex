"""GNN Module — Graph Intelligence & Graph Neural Networks for Supply Chains.

Program K (Graph Intelligence):
- K.1: Graph Representation & Heterogeneous Topology
- K.2: Multi-layer Graph Attention Network (HeteroGAT)
- K.3: Supplier Similarity & Alternative Sourcing
- K.4: Critical Node & Bottleneck Prediction
- K.5: Hidden Dependency & Link Prediction
- K.6: Risk Propagation & Disruption Cascade Forecasting
- K.7: GNN vs Deterministic Baseline Evaluation
"""

from app.modules.gnn.gnn_evaluation import GNNEvaluationHarness
from app.modules.gnn.gnn_models import (
    CriticalNodePrediction,
    CriticalNodeReport,
    EdgeType,
    EmbeddingBundle,
    GNNBenchmarkComparison,
    GNNTaskType,
    GraphEdge,
    GraphNode,
    HeteroGraphData,
    HiddenDependencyReport,
    NodeEmbedding,
    NodePropagationImpact,
    NodeType,
    PredictedHiddenDependency,
    RiskPropagationForecast,
    SourcingFactorScores,
    SupplierSimilarityCandidate,
    SupplierSimilarityReport,
)
from app.modules.gnn.gnn_service import GNNService
from app.modules.gnn.graph_representation import GraphExtractor
from app.modules.gnn.layers import GraphAttentionLayer
from app.modules.gnn.models import GNN_MODEL_VERSION, SupplyChainGNN
from app.modules.gnn.tasks.critical_node import CriticalNodePredictor
from app.modules.gnn.tasks.link_prediction import HiddenDependencyDetector
from app.modules.gnn.tasks.risk_propagation import RiskPropagationForecaster
from app.modules.gnn.tasks.supplier_similarity import SupplierSimilarityEngine

__all__ = [
    # Models
    "CriticalNodePrediction",
    "CriticalNodeReport",
    "EdgeType",
    "EmbeddingBundle",
    "GNNBenchmarkComparison",
    "GNNTaskType",
    "GraphEdge",
    "GraphNode",
    "HeteroGraphData",
    "HiddenDependencyReport",
    "NodeEmbedding",
    "NodePropagationImpact",
    "NodeType",
    "PredictedHiddenDependency",
    "RiskPropagationForecast",
    "SourcingFactorScores",
    "SupplierSimilarityCandidate",
    "SupplierSimilarityReport",
    # Architecture
    "GNN_MODEL_VERSION",
    "GraphAttentionLayer",
    "GraphExtractor",
    "SupplyChainGNN",
    # Tasks
    "CriticalNodePredictor",
    "HiddenDependencyDetector",
    "RiskPropagationForecaster",
    "SupplierSimilarityEngine",
    # Evaluation & Service
    "GNNEvaluationHarness",
    "GNNService",
]
