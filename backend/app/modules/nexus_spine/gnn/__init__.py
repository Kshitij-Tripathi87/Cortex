"""Nexus v0.7 — Production GNN integration.

Wires the Graph Neural Network into actual Nexus decisions:
  - World Graph → GNN embeddings → Critical-node prediction
  - Hidden dependency detection
  - Risk propagation
  - Supplier similarity

Outputs are exposed as decision features, not disconnected AI widgets.
"""

from app.modules.nexus_spine.gnn.engine import (
    GNNEngine,
    GNNRiskAugmentation,
    HiddenDependency,
    RiskPropagationPath,
    SupplierSimilarity,
    get_gnn_engine,
    reset_gnn_engine,
)

__all__ = [
    "GNNEngine",
    "GNNRiskAugmentation",
    "HiddenDependency",
    "RiskPropagationPath",
    "SupplierSimilarity",
    "get_gnn_engine",
    "reset_gnn_engine",
]
