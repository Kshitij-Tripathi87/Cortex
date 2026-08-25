"""Context Fusion — merges FeatureSnapshot and OperationalContextSnapshot.

The ContextFusion engine combines:
  - FeatureSnapshot (graph-derived features)
  - OperationalContextSnapshot (enterprise-derived operational state)

Into a single EnrichedSnapshot consumed by SignalEngine and downstream.

This separation ensures:
  - Graph reasoning stays pure (features don't depend on ops state)
  - Operational state is loaded independently (no graph coupling)
  - Signal detectors receive both in a single immutable object
  - Replay and caching work cleanly (both snapshots versioned separately)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.modules.graph.context_models import (
    BusinessOperationalState,
    InventoryOperationalState,
    LogisticsOperationalState,
    NodeOperationalState,
    OperationalContextSnapshot,
    OrderOperationalState,
    ProductionOperationalState,
)
from app.modules.graph.feature_models import FeatureSnapshot, NodeFeatures


@dataclass(frozen=True)
class EnrichedNodeState:
    """Fused feature + operational state for a single node.

    This is the immutable object consumed by signal detectors.
    """

    node_id: str
    entity_id: str
    entity_type: str

    # Graph-derived features
    features: NodeFeatures

    # Operational state (may be None if not available)
    operational_state: NodeOperationalState | None = None

    # Convenience accessors for specific state types
    @property
    def inventory(self) -> InventoryOperationalState | None:
        if isinstance(self.operational_state, InventoryOperationalState):
            return self.operational_state
        return None

    @property
    def orders(self) -> OrderOperationalState | None:
        if isinstance(self.operational_state, OrderOperationalState):
            return self.operational_state
        return None

    @property
    def logistics(self) -> LogisticsOperationalState | None:
        if isinstance(self.operational_state, LogisticsOperationalState):
            return self.operational_state
        return None

    @property
    def production(self) -> ProductionOperationalState | None:
        if isinstance(self.operational_state, ProductionOperationalState):
            return self.operational_state
        return None

    @property
    def business(self) -> BusinessOperationalState | None:
        if isinstance(self.operational_state, BusinessOperationalState):
            return self.operational_state
        return None

    # Freshness helpers
    @property
    def has_fresh_operational_state(self) -> bool:
        if self.operational_state is None:
            return False
        return self.operational_state.is_fresh()

    @property
    def has_stale_operational_state(self) -> bool:
        if self.operational_state is None:
            return False
        return self.operational_state.is_stale()

    @property
    def has_degraded_operational_state(self) -> bool:
        if self.operational_state is None:
            return False
        return self.operational_state.is_degraded()


@dataclass(frozen=True)
class EnrichedSnapshot:
    """Complete enriched snapshot for a workspace.

    Combines FeatureSnapshot and OperationalContextSnapshot into a single
    immutable object consumed by SignalEngine.
    """

    workspace_id: str
    snapshot_version: int | None
    snapshot_hash: str | None

    # Feature snapshot metadata
    feature_snapshot_version: int | None
    feature_snapshot_hash: str | None

    # Operational snapshot metadata
    operational_snapshot_version: int | None
    operational_snapshot_hash: str | None

    # Per-node enriched state
    by_node: dict[str, EnrichedNodeState] = field(default_factory=dict)

    # Metadata
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def fuse(
        cls,
        feature_snapshot: FeatureSnapshot,
        operational_snapshot: OperationalContextSnapshot | None,
    ) -> EnrichedSnapshot:
        """Create an EnrichedSnapshot by fusing feature and operational snapshots.

        If operational_snapshot is None, creates enriched state with features only.
        """
        by_node: dict[str, EnrichedNodeState] = {}

        for node_id, features in feature_snapshot.by_node.items():
            op_state = None
            if operational_snapshot is not None:
                op_state = operational_snapshot.by_node.get(node_id)

            by_node[node_id] = EnrichedNodeState(
                node_id=node_id,
                entity_id=features.entity_id,
                entity_type=features.entity_type,
                features=features,
                operational_state=op_state,
            )

        return cls(
            workspace_id=feature_snapshot.workspace_id,
            snapshot_version=feature_snapshot.snapshot_version,
            snapshot_hash=feature_snapshot.snapshot_hash,
            feature_snapshot_version=feature_snapshot.snapshot_version,
            feature_snapshot_hash=feature_snapshot.snapshot_hash,
            operational_snapshot_version=operational_snapshot.snapshot_version
            if operational_snapshot
            else None,
            operational_snapshot_hash=operational_snapshot.snapshot_hash
            if operational_snapshot
            else None,
            by_node=by_node,
            timestamp=datetime.now(UTC),
            metadata={
                "feature_nodes": len(feature_snapshot.by_node),
                "operational_nodes": len(operational_snapshot.by_node)
                if operational_snapshot
                else 0,
                "enriched_nodes": len(by_node),
            },
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for API response or caching."""
        return {
            "workspace_id": self.workspace_id,
            "snapshot_version": self.snapshot_version,
            "snapshot_hash": self.snapshot_hash,
            "feature_snapshot_version": self.feature_snapshot_version,
            "feature_snapshot_hash": self.feature_snapshot_hash,
            "operational_snapshot_version": self.operational_snapshot_version,
            "operational_snapshot_hash": self.operational_snapshot_hash,
            "timestamp": self.timestamp.isoformat(),
            "by_node": {nid: _enriched_node_to_dict(ens) for nid, ens in self.by_node.items()},
            "metadata": self.metadata,
        }


def _enriched_node_to_dict(ens: EnrichedNodeState) -> dict[str, Any]:
    """Convert EnrichedNodeState to dict."""
    from app.modules.graph.feature_models import _node_to_dict

    result = {
        "node_id": ens.node_id,
        "entity_id": ens.entity_id,
        "entity_type": ens.entity_type,
        "features": _node_to_dict(ens.features),
        "has_operational_state": ens.operational_state is not None,
        "has_fresh_operational_state": ens.has_fresh_operational_state,
        "has_stale_operational_state": ens.has_stale_operational_state,
        "has_degraded_operational_state": ens.has_degraded_operational_state,
    }

    if ens.operational_state is not None:
        from app.modules.graph.context_models import _state_to_dict

        result["operational_state"] = _state_to_dict(ens.operational_state)

    return result
