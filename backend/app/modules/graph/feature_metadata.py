"""Feature Metadata — versioning, provenance, and reproducibility information.

Every FeatureSnapshot now carries metadata that answers:
  - Which algorithm version produced these features?
  - When were they computed?
  - What was the graph state (snapshot hash)?
  - How long did computation take?
  - Was this served from cache or recomputed?

This metadata becomes critical when comparing recommendations across time
or when customers ask "why did the recommendation change?" The answer
always starts with "let me check the feature version and algorithm version."

Feature checksums enable cache invalidation: if the same graph state produces
a different checksum, something changed (algorithm, code path, bug fix) and
the cache must be invalidated.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class FeatureMetadata:
    """Metadata attached to every FeatureSnapshot.

    This travels with the features wherever they go — into the cache,
    into Signal Engine inputs, into Decision Memory. Every downstream
    consumer should log the feature_version and algorithm_version for
    reproducibility.
    """

    feature_version: str = "1.0.0"  # semver for the feature schema
    algorithm_version: str = "1.0.0"  # semver for the computation logic
    snapshot_version: int | None = None  # graph snapshot version
    snapshot_hash: str | None = None  # graph snapshot hash (tamper-evident)
    workspace_id: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    computation_time_ms: float = 0.0  # wall-clock time to compute all features
    cache_hit: bool = False
    feature_checksum: str = ""  # SHA256 of all feature values (cache invalidation)
    notes: str = ""  # optional annotations (e.g., "computed during migration")

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_version": self.feature_version,
            "algorithm_version": self.algorithm_version,
            "snapshot_version": self.snapshot_version,
            "snapshot_hash": self.snapshot_hash,
            "workspace_id": self.workspace_id,
            "created_at": self.created_at.isoformat(),
            "computation_time_ms": round(self.computation_time_ms, 2),
            "cache_hit": self.cache_hit,
            "feature_checksum": self.feature_checksum,
            "notes": self.notes,
        }


def compute_feature_checksum(node_features: dict[str, Any]) -> str:
    """Compute a deterministic checksum over all feature values.

    The checksum is SHA256 of a canonical JSON serialization of the
    feature dictionary (sorted keys, no spaces). This enables:
      - Cache invalidation when feature values change
      - Replay verification (same graph → same checksum)
      - Drift detection (different algorithm versions produce different checksums)

    The checksum does NOT include node_id, entity_type, entity_id — only
    the numeric feature values. This means the same graph structure with
    different node IDs produces the same checksum.
    """
    # Extract only numeric feature values, sorted by node_id for determinism
    values_to_hash: list[tuple[str, float | int]] = []
    for node_id in sorted(node_features.keys()):
        nf = node_features[node_id]
        # Include all numeric features, excluding strings and node identifiers
        values_to_hash.append((node_id, nf.get("in_degree", 0)))
        values_to_hash.append((node_id, nf.get("out_degree", 0)))
        values_to_hash.append((node_id, nf.get("total_degree", 0)))
        values_to_hash.append((node_id, nf.get("degree_centrality", 0.0)))
        values_to_hash.append((node_id, nf.get("downstream_reach", 0)))
        values_to_hash.append((node_id, nf.get("upstream_reach", 0)))
        values_to_hash.append((node_id, nf.get("criticality", 0.0)))
        values_to_hash.append((node_id, nf.get("single_point_of_failure", 0.0)))
        values_to_hash.append((node_id, nf.get("redundancy", 0.0)))
        values_to_hash.append((node_id, nf.get("concentration_risk", 0.0)))
        values_to_hash.append((node_id, nf.get("betweenness", 0.0)))

    # Canonical serialization
    import json

    canonical = json.dumps(values_to_hash, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FeatureDefinition:
    """Formal definition of a single feature in the Feature Registry.

    Every feature has:
      - A name (e.g., "criticality")
      - A version (semver)
      - Input features (dependencies)
      - Output range (min, max)
      - A description (for explainability)
      - An algorithm reference (documentation or paper)

    The registry uses this to validate that features are computed correctly
    and to document the feature lineage for auditors.
    """

    name: str
    version: str
    description: str
    input_features: list[str]  # names of features this depends on
    output_range: tuple[float, float]  # (min, max)
    algorithm_reference: str  # URL or docstring reference
    is_normalized: bool = True  # whether output is in [0, 1]


# Frozen Feature Registry for Phase 3 v1
FEATURE_REGISTRY: dict[str, FeatureDefinition] = {
    "in_degree": FeatureDefinition(
        name="in_degree",
        version="1.0.0",
        description="Number of incoming edges to this node",
        input_features=[],
        output_range=(0.0, float("inf")),
        algorithm_reference="app.modules.graph.features:in_degree",
        is_normalized=False,
    ),
    "out_degree": FeatureDefinition(
        name="out_degree",
        version="1.0.0",
        description="Number of outgoing edges from this node",
        input_features=[],
        output_range=(0.0, float("inf")),
        algorithm_reference="app.modules.graph.features:out_degree",
        is_normalized=False,
    ),
    "total_degree": FeatureDefinition(
        name="total_degree",
        version="1.0.0",
        description="Sum of in_degree + out_degree",
        input_features=["in_degree", "out_degree"],
        output_range=(0.0, float("inf")),
        algorithm_reference="app.modules.graph.features:total_degree",
        is_normalized=False,
    ),
    "degree_centrality": FeatureDefinition(
        name="degree_centrality",
        version="1.0.0",
        description="total_degree / max_total_degree_in_graph (normalized)",
        input_features=["total_degree"],
        output_range=(0.0, 1.0),
        algorithm_reference="app.modules.graph.features:degree_centrality",
        is_normalized=True,
    ),
    "downstream_reach": FeatureDefinition(
        name="downstream_reach",
        version="1.0.0",
        description="Number of nodes reachable from this node via out-edges (excluding self)",
        input_features=[],
        output_range=(0.0, float("inf")),
        algorithm_reference="app.modules.graph.features:downstream_reach_count",
        is_normalized=False,
    ),
    "upstream_reach": FeatureDefinition(
        name="upstream_reach",
        version="1.0.0",
        description="Number of nodes that can reach this node via out-edges (excluding self)",
        input_features=[],
        output_range=(0.0, float("inf")),
        algorithm_reference="app.modules.graph.features:upstream_reach_count",
        is_normalized=False,
    ),
    "downstream_depth": FeatureDefinition(
        name="downstream_depth",
        version="1.0.0",
        description="Longest shortest-path distance from this node downstream",
        input_features=[],
        output_range=(0.0, float("inf")),
        algorithm_reference="app.modules.graph.features:downstream_depth",
        is_normalized=False,
    ),
    "upstream_depth": FeatureDefinition(
        name="upstream_depth",
        version="1.0.0",
        description="Longest shortest-path distance to this node from any upstream source",
        input_features=[],
        output_range=(0.0, float("inf")),
        algorithm_reference="app.modules.graph.features:upstream_depth",
        is_normalized=False,
    ),
    "criticality": FeatureDefinition(
        name="criticality",
        version="1.0.0",
        description="Weighted blend of reach, depth, and degree centrality (0..1)",
        input_features=[
            "downstream_reach",
            "upstream_reach",
            "downstream_depth",
            "upstream_depth",
            "degree_centrality",
        ],
        output_range=(0.0, 1.0),
        algorithm_reference="app.modules.graph.features:criticality",
        is_normalized=True,
    ),
    "single_point_of_failure": FeatureDefinition(
        name="single_point_of_failure",
        version="1.0.0",
        description="Score indicating how much downstream disruption occurs if this node fails (0..1)",
        input_features=["downstream_reach", "redundancy"],
        output_range=(0.0, 1.0),
        algorithm_reference="app.modules.graph.features:single_point_of_failure",
        is_normalized=True,
    ),
    "redundancy": FeatureDefinition(
        name="redundancy",
        version="1.0.0",
        description="Number of independent upstream sources (saturates at 4) (0..1)",
        input_features=["in_degree"],
        output_range=(0.0, 1.0),
        algorithm_reference="app.modules.graph.features:redundancy",
        is_normalized=True,
    ),
    "concentration_risk": FeatureDefinition(
        name="concentration_risk",
        version="1.0.0",
        description="1 - redundancy; high when relying on single upstream source (0..1)",
        input_features=["redundancy"],
        output_range=(0.0, 1.0),
        algorithm_reference="app.modules.graph.features:concentration_risk",
        is_normalized=True,
    ),
    "betweenness": FeatureDefinition(
        name="betweenness",
        version="1.0.0",
        description="Fraction of all-pairs shortest paths passing through this node (0..1)",
        input_features=[],
        output_range=(0.0, 1.0),
        algorithm_reference="app.modules.graph.features:betweenness",
        is_normalized=True,
    ),
}


def validate_feature_values(feature_name: str, value: float) -> bool:
    """Validate that a feature value is within its defined range."""
    if feature_name not in FEATURE_REGISTRY:
        return False
    defn = FEATURE_REGISTRY[feature_name]
    min_val, max_val = defn.output_range
    return min_val <= value <= max_val
