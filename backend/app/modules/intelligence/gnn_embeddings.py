"""Intelligence Plane — GNN Research Module.

Graph Neural Network research for:
- Supplier similarity embeddings
- Hidden dependency pattern detection
- Weak-signal risk identification
- Critical node prediction
- Structural anomaly detection

This is a RESEARCH TRACK ONLY. GNN outputs are never used in production
until they pass the Intelligence Validation gate.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np


@dataclass(frozen=True)
class GNNGraphData:
    """Graph data structure for GNN training/inference."""

    # Node features: [n_nodes, n_features]
    node_features: np.ndarray

    # Edge index: [2, n_edges] - source, target
    edge_index: np.ndarray

    # Edge attributes: [n_edges, n_edge_features]
    edge_attr: np.ndarray | None

    # Node labels (for supervised tasks): [n_nodes]
    node_labels: np.ndarray | None

    # Graph-level labels (for graph classification): [1]
    graph_label: np.ndarray | None

    # Node type mapping: node_id -> type
    node_types: list[str]

    # Edge type mapping: edge_id -> type
    edge_types: list[str]

    # Metadata
    workspace_id: str
    snapshot_version: int
    created_at: datetime = datetime.now(UTC)


@dataclass(frozen=True)
class GNNEmbeddings:
    """Node embeddings produced by a GNN."""

    # Embeddings: [n_nodes, embedding_dim]
    embeddings: np.ndarray

    # Node IDs corresponding to embeddings
    node_ids: list[str]

    # Node types
    node_types: list[str]

    # Model info
    model_id: str
    model_version: str
    dataset_version: int

    # Quality metrics
    reconstruction_error: float | None = None
    clustering_score: float | None = None

    created_at: datetime = datetime.now(UTC)

    def get_supplier_embeddings(self) -> dict[str, np.ndarray]:
        """Extract embeddings for supplier nodes only."""
        return {
            node_id: self.embeddings[i]
            for i, (node_id, node_type) in enumerate(
                zip(self.node_ids, self.node_types, strict=True)
            )
            if node_type == "supplier"
        }

    def get_similarity_matrix(self, node_type: str = "supplier") -> np.ndarray:
        """Compute cosine similarity matrix for nodes of a given type."""
        indices = [i for i, t in enumerate(self.node_types) if t == node_type]
        if not indices:
            return np.array([])

        emb = self.embeddings[indices]
        # Normalize
        norms = np.linalg.norm(emb, axis=1, keepdims=True)
        norms[norms == 0] = 1
        emb_norm = emb / norms

        # Cosine similarity
        return emb_norm @ emb_norm.T


class GNNModel(ABC):
    """Abstract base class for GNN models."""

    def __init__(self, model_id: str, model_version: str, embedding_dim: int = 64):
        self.model_id = model_id
        self.model_version = model_version
        self.embedding_dim = embedding_dim
        self._model = None
        self._is_trained = False

    @abstractmethod
    def train(
        self,
        graph_data: GNNGraphData,
        epochs: int = 100,
        lr: float = 0.01,
        **kwargs: Any,
    ) -> dict[str, float]:
        """Train the GNN model."""
        pass

    @abstractmethod
    def encode(self, graph_data: GNNGraphData) -> GNNEmbeddings:
        """Encode graph into node embeddings."""
        pass

    @abstractmethod
    def save(self, path: Path) -> None:
        """Save model to disk."""
        pass

    @classmethod
    @abstractmethod
    def load(cls, path: Path) -> GNNModel:
        """Load model from disk."""
        pass


class Node2VecBaseline(GNNModel):
    """Node2Vec baseline for supplier similarity.

    This is a simple random-walk based embedding (not a true GNN)
    but serves as a strong baseline for graph representation learning.
    """

    def __init__(
        self,
        model_id: str = "node2vec_baseline",
        model_version: str = "1.0.0",
        embedding_dim: int = 64,
    ):
        super().__init__(model_id, model_version, embedding_dim)
        self._embeddings: np.ndarray | None = None
        self._node_ids: list[str] = []
        self._node_types: list[str] = []

    def train(
        self,
        graph_data: GNNGraphData,
        epochs: int = 100,
        lr: float = 0.01,
        walk_length: int = 80,
        num_walks: int = 10,
        p: float = 1.0,
        q: float = 1.0,
        **kwargs: Any,
    ) -> dict[str, float]:
        """Train Node2Vec embeddings using random walks.

        This is a simplified implementation. Production would use
        node2vec or DeepWalk libraries.
        """
        # Build adjacency list
        n_nodes = graph_data.node_features.shape[0]
        adj: list[list[int]] = [[] for _ in range(n_nodes)]
        for src, tgt in graph_data.edge_index.T:
            adj[src].append(tgt)
            adj[tgt].append(src)  # Undirected for Node2Vec

        # Generate random walks
        walks = []
        for _ in range(num_walks):
            for start_node in range(n_nodes):
                walk = [start_node]
                for _ in range(walk_length - 1):
                    current = walk[-1]
                    neighbors = adj[current]
                    if not neighbors:
                        break
                    # Simple random walk (Node2Vec biased walk would go here)
                    next_node = np.random.choice(neighbors)
                    walk.append(next_node)
                walks.append(walk)

        # Simplified: Use SVD on co-occurrence matrix as proxy for Node2Vec
        # Real implementation would use Word2Vec on walks
        cooc = np.zeros((n_nodes, n_nodes))
        for walk in walks:
            for i, u in enumerate(walk):
                for j in range(max(0, i - 5), min(len(walk), i + 6)):
                    if i != j:
                        v = walk[j]
                        cooc[u, v] += 1

        # SVD for embeddings
        try:
            U, S, Vt = np.linalg.svd(cooc, full_matrices=False)
            k = min(self.embedding_dim, len(S))
            self._embeddings = U[:, :k] * np.sqrt(S[:k])
        except np.linalg.LinAlgError:
            # Fallback: random embeddings
            self._embeddings = np.random.randn(n_nodes, self.embedding_dim) * 0.01

        self._node_ids = [f"node_{i}" for i in range(n_nodes)]
        self._node_types = graph_data.node_types
        self._is_trained = True

        # Compute reconstruction error
        recon = self._embeddings @ self._embeddings.T
        recon_error = float(np.mean((cooc - recon) ** 2))

        return {
            "reconstruction_error": recon_error,
            "num_walks": len(walks),
            "embedding_dim": self.embedding_dim,
        }

    def encode(self, graph_data: GNNGraphData) -> GNNEmbeddings:
        if not self._is_trained:
            raise RuntimeError("Model not trained")
        return GNNEmbeddings(
            embeddings=self._embeddings,
            node_ids=self._node_ids,
            node_types=self._node_types,
            model_id=self.model_id,
            model_version=self.model_version,
            dataset_version=graph_data.snapshot_version,
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "model_id": self.model_id,
            "model_version": self.model_version,
            "embedding_dim": self.embedding_dim,
            "embeddings": self._embeddings,
            "node_ids": self._node_ids,
            "node_types": self._node_types,
            "is_trained": self._is_trained,
        }
        np.savez_compressed(path, **data)

    @classmethod
    def load(cls, path: Path) -> Node2VecBaseline:
        data = np.load(path, allow_pickle=True)
        instance = cls(
            model_id=str(data["model_id"]),
            model_version=str(data["model_version"]),
            embedding_dim=int(data["embedding_dim"]),
        )
        instance._embeddings = data["embeddings"]
        instance._node_ids = list(data["node_ids"])
        instance._node_types = list(data["node_types"])
        instance._is_trained = bool(data["is_trained"])
        return instance


class GraphSAGEBaseline(GNNModel):
    """GraphSAGE baseline for inductive node embedding.

    Samples and aggregates neighbor features to generate embeddings.
    Can generalize to unseen nodes (inductive).
    """

    def __init__(
        self,
        model_id: str = "graphsage_baseline",
        model_version: str = "1.0.0",
        embedding_dim: int = 64,
        hidden_dim: int = 128,
        num_layers: int = 2,
    ):
        super().__init__(model_id, model_version, embedding_dim)
        self.hidden_dim = hidden_dim
        self.num_layers = num_layers
        self._weights: list[np.ndarray] = []

    def _aggregate(
        self, node_features: np.ndarray, edge_index: np.ndarray, weights: np.ndarray
    ) -> np.ndarray:
        """Simple mean aggregation (GraphSAGE)."""
        n_nodes = node_features.shape[0]
        aggregated = np.zeros((n_nodes, self.hidden_dim))

        # Build neighbor lists
        neighbors: list[list[int]] = [[] for _ in range(n_nodes)]
        for src, tgt in edge_index.T:
            neighbors[src].append(tgt)

        for i in range(n_nodes):
            if neighbors[i]:
                neighbor_feats = node_features[neighbors[i]]
                aggregated[i] = neighbor_feats.mean(axis=0) @ weights
            else:
                aggregated[i] = np.zeros(self.hidden_dim)

        return aggregated

    def train(
        self,
        graph_data: GNNGraphData,
        epochs: int = 100,
        lr: float = 0.01,
        **kwargs: Any,
    ) -> dict[str, float]:
        """Train GraphSAGE with unsupervised loss (GraphSAGE-style)."""
        n_nodes = graph_data.node_features.shape[0]
        n_features = graph_data.node_features.shape[1]

        # Initialize weights
        self._weights = []
        # Input projection
        self._weights.append(np.random.randn(n_features, self.hidden_dim) * 0.01)
        # Hidden layers
        for _ in range(self.num_layers - 1):
            self._weights.append(np.random.randn(self.hidden_dim, self.hidden_dim) * 0.01)
        # Output projection
        self._weights.append(np.random.randn(self.hidden_dim, self.embedding_dim) * 0.01)

        # Simple unsupervised training: reconstruct adjacency
        adj = np.zeros((n_nodes, n_nodes))
        for src, tgt in graph_data.edge_index.T:
            adj[src, tgt] = 1
            adj[tgt, src] = 1

        losses = []
        for epoch in range(epochs):
            # Forward pass
            h = graph_data.node_features
            for i, w in enumerate(self._weights):
                if i < self.num_layers:
                    h = self._aggregate(h, graph_data.edge_index, w)
                    h = np.maximum(h, 0)  # ReLU
                else:
                    h = h @ w  # Final projection

            # Reconstruction loss (dot product similarity)
            recon = h @ h.T
            loss = float(np.mean((adj - recon) ** 2))
            losses.append(loss)

            # Simplified gradient update (would use autograd in practice)
            # This is a placeholder - real implementation needs PyTorch/TensorFlow
            if epoch % 20 == 0:
                pass  # Log progress

        self._is_trained = True
        self._final_embeddings = h

        return {
            "final_loss": losses[-1] if losses else 0.0,
            "embedding_dim": self.embedding_dim,
            "num_layers": self.num_layers,
        }

    def encode(self, graph_data: GNNGraphData) -> GNNEmbeddings:
        if not self._is_trained:
            raise RuntimeError("Model not trained")
        return GNNEmbeddings(
            embeddings=self._final_embeddings,
            node_ids=[f"node_{i}" for i in range(graph_data.node_features.shape[0])],
            node_types=graph_data.node_types,
            model_id=self.model_id,
            model_version=self.model_version,
            dataset_version=graph_data.snapshot_version,
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            path,
            model_id=self.model_id,
            model_version=self.model_version,
            embedding_dim=self.embedding_dim,
            hidden_dim=self.hidden_dim,
            num_layers=self.num_layers,
            weights=self._weights,
            is_trained=self._is_trained,
        )

    @classmethod
    def load(cls, path: Path) -> GraphSAGEBaseline:
        data = np.load(path, allow_pickle=True)
        instance = cls(
            model_id=str(data["model_id"]),
            model_version=str(data["model_version"]),
            embedding_dim=int(data["embedding_dim"]),
            hidden_dim=int(data["hidden_dim"]),
            num_layers=int(data["num_layers"]),
        )
        instance._weights = list(data["weights"])
        instance._is_trained = bool(data["is_trained"])
        return instance


async def build_gnn_graph_data(
    db_session: Any,
    workspace_id: str,
    snapshot_version: int,
) -> GNNGraphData:
    """Build GNN graph data from the operational graph.

    Fetches nodes and edges from the graph_snapshots and converts
    to GNNGraphData format.
    """
    # This would query the graph_nodes and graph_edges tables
    # filtered by workspace_id and snapshot_version
    # For now, return a placeholder structure

    # Node types in our graph: supplier, component, product, warehouse, factory, customer
    # Edge types: supplies, depends_on, located_in, produces, ships_to, orders

    # Placeholder: return minimal structure
    return GNNGraphData(
        node_features=np.array([]).reshape(0, 10),
        edge_index=np.array([]).reshape(2, 0).astype(int),
        edge_attr=None,
        node_labels=None,
        graph_label=None,
        node_types=[],
        edge_types=[],
        workspace_id=workspace_id,
        snapshot_version=snapshot_version,
    )


@dataclass(frozen=True)
class GNNResearchResult:
    """Result of a GNN research experiment."""

    experiment_id: str
    model_id: str
    model_version: str
    dataset_id: str
    dataset_version: int

    # Embeddings
    embeddings: GNNEmbeddings

    # Supplier similarity benchmarks
    supplier_similarity_auc: float | None = None
    supplier_clustering_nmi: float | None = None

    # Risk prediction benchmarks
    risk_prediction_auc: float | None = None
    risk_prediction_f1: float | None = None

    # Hidden dependency detection
    hidden_dependency_precision: float | None = None
    hidden_dependency_recall: float | None = None

    # Critical node prediction
    critical_node_precision: float | None = None
    critical_node_recall: float | None = None

    # Anomaly detection
    anomaly_auc: float | None = None

    # Beats deterministic baseline?
    beats_deterministic: bool = False
    improvement_notes: str = ""

    created_at: datetime = datetime.now(UTC)

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "dataset_id": self.dataset_id,
            "dataset_version": self.dataset_version,
            "supplier_similarity_auc": self.supplier_similarity_auc,
            "supplier_clustering_nmi": self.supplier_clustering_nmi,
            "risk_prediction_auc": self.risk_prediction_auc,
            "risk_prediction_f1": self.risk_prediction_f1,
            "hidden_dependency_precision": self.hidden_dependency_precision,
            "hidden_dependency_recall": self.hidden_dependency_recall,
            "critical_node_precision": self.critical_node_precision,
            "critical_node_recall": self.critical_node_recall,
            "anomaly_auc": self.anomaly_auc,
            "beats_deterministic": self.beats_deterministic,
            "improvement_notes": self.improvement_notes,
            "created_at": self.created_at.isoformat(),
        }
