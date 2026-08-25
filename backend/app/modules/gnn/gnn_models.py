"""GNN Models — Immutable Data Contracts for Graph Intelligence.

Program K (Graph Intelligence & Graph Neural Networks):
- K.1: Graph Representation & Heterogeneous Topology
- K.2: Graph Embeddings & Message Passing
- K.3: Supplier Similarity & Alternative Sourcing
- K.4: Critical Node & Bottleneck Prediction
- K.5: Hidden Dependency & Link Prediction
- K.6: Risk Propagation & Disruption Cascade
- K.7: GNN vs. Deterministic Baseline Evaluation
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class NodeType(StrEnum):
    """Types of entities in the heterogeneous supply chain graph."""

    SUPPLIER = "supplier"
    FACTORY = "factory"
    WAREHOUSE = "warehouse"
    CUSTOMER = "customer"
    ROUTE = "route"
    COMPONENT = "component"


class EdgeType(StrEnum):
    """Types of directed relationships in the supply chain graph."""

    SUPPLIES = "supplies"
    SHIPS_TO = "ships_to"
    MANUFACTURES = "manufactures"
    CONSUMES = "consumes"
    DEPENDS_ON = "depends_on"
    ALTERNATE_FOR = "alternate_for"


class GNNTaskType(StrEnum):
    """GNN operational and intelligence task types."""

    EMBEDDING = "embedding"
    SUPPLIER_SIMILARITY = "supplier_similarity"
    CRITICAL_NODE = "critical_node"
    LINK_PREDICTION = "link_prediction"
    RISK_PROPAGATION = "risk_propagation"


# ─────────────────────────────────────────────────────────────────────────────
# Graph Structure & Feature Models
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GraphNode:
    """A node in the heterogeneous graph."""

    node_id: str
    node_type: NodeType
    entity_id: str
    name: str = ""
    features: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_type": self.node_type.value,
            "entity_id": self.entity_id,
            "name": self.name,
            "features": dict(self.features),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class GraphEdge:
    """A directed edge in the heterogeneous graph."""

    edge_id: str
    source_id: str
    target_id: str
    edge_type: EdgeType
    weight: float = 1.0
    features: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "edge_type": self.edge_type.value,
            "weight": self.weight,
            "features": dict(self.features),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class HeteroGraphData:
    """Complete heterogeneous graph representation ready for GNN processing."""

    workspace_id: str
    world_id: str
    version: int
    nodes: dict[str, GraphNode]  # node_id -> GraphNode
    edges: list[GraphEdge]
    node_to_idx: dict[str, int]
    idx_to_node: dict[int, str]
    feature_dim: int
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def num_nodes(self) -> int:
        return len(self.nodes)

    @property
    def num_edges(self) -> int:
        return len(self.edges)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "world_id": self.world_id,
            "version": self.version,
            "num_nodes": self.num_nodes,
            "num_edges": self.num_edges,
            "feature_dim": self.feature_dim,
            "created_at": self.created_at.isoformat(),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Embedding Models
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class NodeEmbedding:
    """Learned dense vector embedding for a graph node."""

    node_id: str
    node_type: NodeType
    vector: list[float]
    dim: int
    model_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_type": self.node_type.value,
            "vector": list(self.vector),
            "dim": self.dim,
            "model_version": self.model_version,
        }


@dataclass(frozen=True)
class EmbeddingBundle:
    """Bundle of all node embeddings for a graph."""

    workspace_id: str
    world_id: str
    version: int
    embeddings: dict[str, NodeEmbedding]  # node_id -> NodeEmbedding
    dim: int
    model_version: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def num_embeddings(self) -> int:
        return len(self.embeddings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "world_id": self.world_id,
            "version": self.version,
            "num_embeddings": self.num_embeddings,
            "dim": self.dim,
            "model_version": self.model_version,
            "created_at": self.created_at.isoformat(),
            "embeddings": {nid: emb.to_dict() for nid, emb in self.embeddings.items()},
        }


# ─────────────────────────────────────────────────────────────────────────────
# Supplier Similarity & Sourcing Models (K.3)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SourcingFactorScores:
    """Decomposition of similarity factors for transparency and auditability."""

    structural_embedding_similarity: float  # GNN embedding cosine similarity
    lead_time_compatibility: float  # 0.0 - 1.0 score based on lead time parity
    capacity_readiness: float  # 0.0 - 1.0 based on available headroom
    risk_profile_match: float  # 0.0 - 1.0 based on supplier health and risk parity
    product_overlap_score: float  # Fraction of shared supplied components

    def to_dict(self) -> dict[str, float]:
        return {
            "structural_embedding_similarity": round(self.structural_embedding_similarity, 4),
            "lead_time_compatibility": round(self.lead_time_compatibility, 4),
            "capacity_readiness": round(self.capacity_readiness, 4),
            "risk_profile_match": round(self.risk_profile_match, 4),
            "product_overlap_score": round(self.product_overlap_score, 4),
        }


@dataclass(frozen=True)
class SupplierSimilarityCandidate:
    """A recommended alternative supplier ranked by GNN similarity and operational constraints."""

    candidate_supplier_id: str
    candidate_name: str
    overall_match_score: float  # Composite 0.0 - 1.0
    rank: int
    factor_scores: SourcingFactorScores
    estimated_lead_time_days: float
    health_score: float
    capacity_pct: float
    shared_components: list[str] = field(default_factory=list)
    recommendation_rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_supplier_id": self.candidate_supplier_id,
            "candidate_name": self.candidate_name,
            "overall_match_score": round(self.overall_match_score, 4),
            "rank": self.rank,
            "factor_scores": self.factor_scores.to_dict(),
            "estimated_lead_time_days": self.estimated_lead_time_days,
            "health_score": self.health_score,
            "capacity_pct": self.capacity_pct,
            "shared_components": list(self.shared_components),
            "recommendation_rationale": self.recommendation_rationale,
        }


@dataclass(frozen=True)
class SupplierSimilarityReport:
    """Consolidated alternative sourcing report."""

    target_supplier_id: str
    target_supplier_name: str
    candidates: list[SupplierSimilarityCandidate]
    model_version: str
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_supplier_id": self.target_supplier_id,
            "target_supplier_name": self.target_supplier_name,
            "candidates": [c.to_dict() for c in self.candidates],
            "model_version": self.model_version,
            "evaluated_at": self.evaluated_at.isoformat(),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Critical Node Prediction Models (K.4)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CriticalNodePrediction:
    """Criticality prediction for a single node."""

    node_id: str
    node_type: NodeType
    name: str
    criticality_score: float  # 0.0 - 1.0 (GNN predicted failure severity)
    is_critical: bool  # Exceeds criticality threshold
    is_single_point_of_failure: bool
    affected_downstream_nodes: int
    estimated_revenue_at_risk_usd: float
    primary_vulnerability_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_type": self.node_type.value,
            "name": self.name,
            "criticality_score": round(self.criticality_score, 4),
            "is_critical": self.is_critical,
            "is_single_point_of_failure": self.is_single_point_of_failure,
            "affected_downstream_nodes": self.affected_downstream_nodes,
            "estimated_revenue_at_risk_usd": round(self.estimated_revenue_at_risk_usd, 2),
            "primary_vulnerability_reasons": list(self.primary_vulnerability_reasons),
        }


@dataclass(frozen=True)
class CriticalNodeReport:
    """Network-wide critical node analysis report."""

    workspace_id: str
    world_id: str
    total_nodes_analyzed: int
    critical_nodes: list[CriticalNodePrediction]
    spof_count: int
    max_network_risk_score: float
    model_version: str
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "world_id": self.world_id,
            "total_nodes_analyzed": self.total_nodes_analyzed,
            "critical_nodes": [c.to_dict() for c in self.critical_nodes],
            "spof_count": self.spof_count,
            "max_network_risk_score": round(self.max_network_risk_score, 4),
            "model_version": self.model_version,
            "evaluated_at": self.evaluated_at.isoformat(),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Hidden Dependency & Link Prediction Models (K.5)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PredictedHiddenDependency:
    """Predicted latent relationship / shared dependency between two entities."""

    source_node_id: str
    target_node_id: str
    predicted_edge_type: EdgeType
    confidence: float  # 0.0 - 1.0
    dependency_nature: (
        str  # e.g., "shared_tier_2_supplier", "shared_corridor", "geographic_cluster"
    )
    evidence_rationale: str
    risk_impact: str  # low, medium, high, critical

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_node_id": self.source_node_id,
            "target_node_id": self.target_node_id,
            "predicted_edge_type": self.predicted_edge_type.value,
            "confidence": round(self.confidence, 4),
            "dependency_nature": self.dependency_nature,
            "evidence_rationale": self.evidence_rationale,
            "risk_impact": self.risk_impact,
        }


@dataclass(frozen=True)
class HiddenDependencyReport:
    """Report of discovered latent dependencies across the network."""

    workspace_id: str
    world_id: str
    discovered_dependencies: list[PredictedHiddenDependency]
    high_risk_correlation_clusters: list[list[str]] = field(default_factory=list)
    model_version: str = "gnn-link-v1.0"
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "world_id": self.world_id,
            "discovered_dependencies": [d.to_dict() for d in self.discovered_dependencies],
            "high_risk_correlation_clusters": self.high_risk_correlation_clusters,
            "model_version": self.model_version,
            "evaluated_at": self.evaluated_at.isoformat(),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Risk Propagation Forecasting Models (K.6)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class NodePropagationImpact:
    """Predicted impact on a specific node during a disruption cascade."""

    node_id: str
    node_type: NodeType
    time_to_impact_ticks: int  # Expected tick when disruption reaches this node
    impact_probability: float  # 0.0 - 1.0
    expected_capacity_loss_pct: float
    expected_revenue_loss_usd: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_type": self.node_type.value,
            "time_to_impact_ticks": self.time_to_impact_ticks,
            "impact_probability": round(self.impact_probability, 4),
            "expected_capacity_loss_pct": round(self.expected_capacity_loss_pct, 2),
            "expected_revenue_loss_usd": round(self.revenue_loss_usd, 2)
            if hasattr(self, "revenue_loss_usd")
            else round(self.expected_revenue_loss_usd, 2),
        }


@dataclass(frozen=True)
class RiskPropagationForecast:
    """Forecast of disruption spread from an epicenter node."""

    epicenter_node_id: str
    scenario_description: str
    horizon_ticks: int
    predicted_impacts: list[NodePropagationImpact]
    total_expected_revenue_loss: float
    critical_path: list[str] = field(default_factory=list)
    model_version: str = "gnn-prop-v1.0"
    forecast_generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "epicenter_node_id": self.epicenter_node_id,
            "scenario_description": self.scenario_description,
            "horizon_ticks": self.horizon_ticks,
            "predicted_impacts": [p.to_dict() for p in self.predicted_impacts],
            "total_expected_revenue_loss": round(self.total_expected_revenue_loss, 2),
            "critical_path": list(self.critical_path),
            "model_version": self.model_version,
            "forecast_generated_at": self.forecast_generated_at.isoformat(),
        }


# ─────────────────────────────────────────────────────────────────────────────
# GNN vs Baseline Benchmark Models (K.7)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GNNBenchmarkComparison:
    """Rigorous evaluation comparison between GNN and deterministic baseline."""

    task_type: GNNTaskType
    gnn_model_version: str
    baseline_algorithm: str
    gnn_metrics: dict[str, float]
    baseline_metrics: dict[str, float]
    lift_pct: dict[str, float]  # Percentage improvement per metric
    statistically_significant: bool  # p < 0.05
    p_value: float
    passed_production_gate: bool  # Demonstrates statistically significant business lift
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_type": self.task_type.value,
            "gnn_model_version": self.gnn_model_version,
            "baseline_algorithm": self.baseline_algorithm,
            "gnn_metrics": dict(self.gnn_metrics),
            "baseline_metrics": dict(self.baseline_metrics),
            "lift_pct": dict(self.lift_pct),
            "statistically_significant": self.statistically_significant,
            "p_value": self.p_value,
            "passed_production_gate": self.passed_production_gate,
            "summary": self.summary,
        }
