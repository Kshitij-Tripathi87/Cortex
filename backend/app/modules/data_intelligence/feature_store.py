"""Program Q9 — Graph Feature Store with Temporal Leakage Protection.

Persists versioned tabular, temporal, and graph topological features.
Enforces the Temporal Leakage Gate: feature_timestamp <= T_prediction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class VersionedFeatureVector:
    entity_id: str
    feature_group: str  # "TABULAR" | "TEMPORAL" | "GRAPH"
    features: dict[str, float | str | bool]
    world_state_version: int
    feature_timestamp: datetime
    feature_version: str = "v1.0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "feature_group": self.feature_group,
            "features": self.features,
            "world_state_version": self.world_state_version,
            "feature_timestamp": self.feature_timestamp.isoformat(),
            "feature_version": self.feature_version,
        }


class GraphFeatureStore:
    """Versioned feature repository with temporal leakage prevention."""

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], list[VersionedFeatureVector]] = {}

    def put_features(self, vector: VersionedFeatureVector) -> None:
        key = (vector.entity_id, vector.feature_group)
        if key not in self._store:
            self._store[key] = []
        self._store[key].append(vector)

    def get_features_as_of(
        self,
        entity_id: str,
        feature_group: str,
        as_of_timestamp: datetime,
    ) -> VersionedFeatureVector | None:
        """Retrieve latest feature vector strictly before or at the prediction timestamp T."""
        key = (entity_id, feature_group)
        vectors = self._store.get(key, [])
        valid_vectors = [v for v in vectors if v.feature_timestamp <= as_of_timestamp]
        if not valid_vectors:
            return None
        # Return most recent valid vector
        return max(valid_vectors, key=lambda v: v.feature_timestamp)

    def validate_no_temporal_leakage(
        self,
        features: dict[str, Any],
        t_prediction: datetime,
        feature_timestamps: dict[str, datetime],
    ) -> bool:
        """Enforces hard Temporal Leakage Gate: All feature timestamps must be <= T_prediction."""
        for feat_name, ts in feature_timestamps.items():
            if ts > t_prediction:
                raise ValueError(
                    f"Temporal Leakage Violation: Feature '{feat_name}' has timestamp {ts.isoformat()} which is AFTER prediction timestamp {t_prediction.isoformat()}"
                )
        return True
