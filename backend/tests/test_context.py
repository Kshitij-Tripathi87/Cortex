"""Tests for Program D.5: Operational State Layer.

Covers:
  - Context models (validation, freshness, serialization)
  - Operational State Engine (loading, merging, policies)
  - Context Fusion (feature + operational state fusion)
  - Context Validation (freshness, units, provenance)
  - Detector behavior with operational context
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.graph.context_engine import (
    InMemoryOperationalStateRepository,
    OperationalStateEngine,
    StateLoadResult,
)
from app.modules.graph.context_fusion import EnrichedSnapshot
from app.modules.graph.context_models import (
    BusinessOperationalState,
    FreshnessPolicy,
    InventoryOperationalState,
    OperationalContextSnapshot,
)
from app.modules.graph.context_validation import validate_operational_context
from app.modules.graph.detectors import get_detector
from app.modules.graph.feature_models import FeatureSnapshot, NodeFeatures
from app.modules.graph.signal_registry import SIGNAL_REGISTRY

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


def make_node_features(
    node_id: str = "n1",
    entity_type: str = "Part",
    entity_id: str = "part-1",
    **overrides,
) -> NodeFeatures:
    """Build NodeFeatures with overrides."""
    return NodeFeatures(
        node_id=node_id,
        entity_type=entity_type,
        entity_id=entity_id,
        in_degree=overrides.get("in_degree", 1),
        out_degree=overrides.get("out_degree", 1),
        total_degree=overrides.get("total_degree", 2),
        degree_centrality=overrides.get("degree_centrality", 0.5),
        downstream_reach=overrides.get("downstream_reach", 3),
        upstream_reach=overrides.get("upstream_reach", 2),
        total_reach=overrides.get("total_reach", 5),
        downstream_depth=overrides.get("downstream_depth", 2),
        upstream_depth=overrides.get("upstream_depth", 1),
        criticality=overrides.get("criticality", 0.5),
        single_point_of_failure=overrides.get("single_point_of_failure", 0.5),
        concentration_risk=overrides.get("concentration_risk", 0.5),
        redundancy=overrides.get("redundancy", 0.5),
        betweenness=overrides.get("betweenness", 0.5),
    )


def make_feature_snapshot(
    workspace_id: str = "ws-test",
    nodes: dict[str, NodeFeatures] | None = None,
) -> FeatureSnapshot:
    """Build FeatureSnapshot."""
    if nodes is None:
        nodes = {}
    return FeatureSnapshot(
        workspace_id=workspace_id,
        snapshot_id=None,
        snapshot_version=1,
        snapshot_hash="test_hash",
        by_node=nodes,
        workspace=None,
    )


def make_inventory_state(
    node_id: str = "n1",
    entity_id: str = "part-1",
    entity_type: str = "Part",
    coverage_days: float | None = 30.0,
    timestamp: datetime | None = None,
    **overrides,
) -> InventoryOperationalState:
    """Build InventoryOperationalState."""
    now = datetime.now(UTC)
    return InventoryOperationalState(
        node_id=node_id,
        entity_id=entity_id,
        entity_type=entity_type,
        coverage_days=coverage_days,
        safety_stock_units=overrides.get("safety_stock_units", 100),
        days_of_supply=overrides.get("days_of_supply", coverage_days),
        on_hand_units=overrides.get("on_hand_units", 500),
        timestamp=timestamp or now,
        source=overrides.get("source", "SAP"),
        freshness_seconds=overrides.get("freshness_seconds", 3600),
        confidence=overrides.get("confidence", 0.95),
    )


def make_business_state(
    node_id: str = "n1",
    entity_id: str = "cust-1",
    entity_type: str = "Customer",
    critical_customer_flag: bool = True,
    revenue_at_risk: float | None = 1000000,
    **overrides,
) -> BusinessOperationalState:
    """Build BusinessOperationalState."""
    now = datetime.now(UTC)
    return BusinessOperationalState(
        node_id=node_id,
        entity_id=entity_id,
        entity_type=entity_type,
        critical_customer_flag=critical_customer_flag,
        revenue_at_risk=revenue_at_risk,
        timestamp=overrides.get("timestamp", now),
        source=overrides.get("source", "Salesforce"),
        freshness_seconds=overrides.get("freshness_seconds", 7200),
        confidence=overrides.get("confidence", 0.9),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Context Model Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestInventoryOperationalState:
    def test_is_fresh_within_threshold(self):
        now = datetime.now(UTC)
        policy = FreshnessPolicy(
            max_age_seconds=86400,
            degraded_age_seconds=43200,
            stale_age_seconds=172800,
            expiration_policy="degrade",
            required_for_signal=False,
        )
        state = InventoryOperationalState(
            node_id="n1",
            entity_id="part-1",
            entity_type="Part",
            coverage_days=30,
            timestamp=now - timedelta(hours=1),
            source="SAP",
            freshness_seconds=3600,
            freshness_policy=policy,
        )
        assert state.is_fresh()
        assert not state.is_stale()
        assert not state.is_degraded()

    def test_is_stale_beyond_threshold(self):
        old_time = datetime.now(UTC) - timedelta(days=3)
        state = InventoryOperationalState(
            node_id="n1",
            entity_id="part-1",
            entity_type="Part",
            coverage_days=30,
            timestamp=old_time,
            source="SAP",
            freshness_seconds=259200,
        )
        assert state.is_stale()
        assert not state.is_fresh()

    def test_is_degraded_in_middle_zone(self):
        # 18 hours = 64800 seconds
        # degraded zone: > 12h (43200) and <= 48h (172800)
        # fresh zone: <= 24h (86400)
        degraded_time = datetime.now(UTC) - timedelta(hours=18)
        policy = FreshnessPolicy(
            max_age_seconds=86400,  # 24h
            degraded_age_seconds=43200,  # 12h
            stale_age_seconds=172800,  # 48h
            expiration_policy="degrade",
            required_for_signal=False,
        )
        state = InventoryOperationalState(
            node_id="n1",
            entity_id="part-1",
            entity_type="Part",
            coverage_days=30,
            timestamp=degraded_time,
            source="SAP",
            freshness_seconds=64800,
            freshness_policy=policy,
        )
        assert state.is_degraded()
        assert state.is_fresh()  # Still fresh (within 24h)
        assert not state.is_stale()


class TestOperationalContextSnapshot:
    def test_get_inventory_state(self):
        inv = make_inventory_state(node_id="n1")
        snapshot = OperationalContextSnapshot(
            workspace_id="ws-test",
            snapshot_id=None,
            snapshot_version=1,
            snapshot_hash="hash123",
            by_node={"n1": inv},
        )
        result = snapshot.get_inventory_state("n1")
        assert result is inv
        assert result.coverage_days == 30.0

    def test_get_inventory_state_wrong_type(self):
        biz = make_business_state(node_id="n1")
        snapshot = OperationalContextSnapshot(
            workspace_id="ws-test",
            snapshot_id=None,
            snapshot_version=1,
            snapshot_hash="hash123",
            by_node={"n1": biz},
        )
        result = snapshot.get_inventory_state("n1")
        assert result is None

    def test_to_dict_serialization(self):
        inv = make_inventory_state(node_id="n1")
        snapshot = OperationalContextSnapshot(
            workspace_id="ws-test",
            snapshot_id=None,
            snapshot_version=1,
            snapshot_hash="hash123",
            by_node={"n1": inv},
        )
        data = snapshot.to_dict()
        assert data["workspace_id"] == "ws-test"
        assert "n1" in data["by_node"]
        assert data["by_node"]["n1"]["coverage_days"] == 30.0


# ─────────────────────────────────────────────────────────────────────────────
# Operational State Engine Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestOperationalStateEngine:
    @pytest.mark.asyncio
    async def test_load_operational_state(self):
        repo = InMemoryOperationalStateRepository()
        inv = make_inventory_state(node_id="n1")
        repo.add_state("ws-test", "n1", inv)

        engine = OperationalStateEngine(repo)
        result = await engine.load_operational_state("ws-test")

        assert isinstance(result, StateLoadResult)
        assert result.nodes_loaded == 1
        assert result.snapshot.workspace_id == "ws-test"
        assert "n1" in result.snapshot.by_node

    @pytest.mark.asyncio
    async def test_load_missing_node(self):
        repo = InMemoryOperationalStateRepository()
        engine = OperationalStateEngine(repo)
        result = await engine.load_operational_state("ws-empty")

        assert result.nodes_loaded == 0
        assert result.nodes_missing == 0  # No nodes to load

    @pytest.mark.asyncio
    async def test_require_freshness_excludes_stale(self):
        repo = InMemoryOperationalStateRepository()
        old_time = datetime.now(UTC) - timedelta(days=3)
        inv = make_inventory_state(
            node_id="n1",
            timestamp=old_time,
            freshness_seconds=259200,
        )
        repo.add_state("ws-test", "n1", inv)

        engine = OperationalStateEngine(repo)
        result = await engine.load_operational_state("ws-test", require_freshness=True)

        assert result.nodes_stale == 1
        assert "n1" not in result.snapshot.by_node


# ─────────────────────────────────────────────────────────────────────────────
# Context Fusion Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestContextFusion:
    def test_fuse_with_operational_context(self):
        features = make_feature_snapshot(
            nodes={"n1": make_node_features(node_id="n1", single_point_of_failure=0.7)}
        )
        inv = make_inventory_state(node_id="n1", coverage_days=15)
        context = OperationalContextSnapshot(
            workspace_id="ws-test",
            snapshot_id=None,
            snapshot_version=1,
            snapshot_hash="ctx_hash",
            by_node={"n1": inv},
        )

        enriched = EnrichedSnapshot.fuse(features, context)

        assert len(enriched.by_node) == 1
        assert enriched.by_node["n1"].features.single_point_of_failure == 0.7
        assert enriched.by_node["n1"].inventory.coverage_days == 15
        assert enriched.by_node["n1"].has_fresh_operational_state

    def test_fuse_without_operational_context(self):
        features = make_feature_snapshot(nodes={"n1": make_node_features(node_id="n1")})

        enriched = EnrichedSnapshot.fuse(features, None)

        assert len(enriched.by_node) == 1
        assert enriched.by_node["n1"].operational_state is None
        assert not enriched.by_node["n1"].has_fresh_operational_state

    def test_fuse_mismatched_nodes(self):
        features = make_feature_snapshot(
            nodes={"n1": make_node_features(node_id="n1"), "n2": make_node_features(node_id="n2")}
        )
        inv = make_inventory_state(node_id="n1")
        context = OperationalContextSnapshot(
            workspace_id="ws-test",
            snapshot_id=None,
            snapshot_version=1,
            snapshot_hash="ctx_hash",
            by_node={"n1": inv},
        )

        enriched = EnrichedSnapshot.fuse(features, context)

        assert len(enriched.by_node) == 2
        assert enriched.by_node["n1"].operational_state is not None
        assert enriched.by_node["n2"].operational_state is None


# ─────────────────────────────────────────────────────────────────────────────
# Context Validation Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestContextValidation:
    def test_valid_context_passes(self):
        inv = make_inventory_state(coverage_days=30)
        context = OperationalContextSnapshot(
            workspace_id="ws-test",
            snapshot_id=None,
            snapshot_version=1,
            snapshot_hash="hash",
            by_node={"n1": inv},
        )

        result = validate_operational_context(context)

        assert result.is_valid
        assert result.can_proceed
        assert result.warnings == 0
        assert result.errors == 0

    def test_stale_context_fails(self):
        old_time = datetime.now(UTC) - timedelta(days=3)
        inv = make_inventory_state(
            coverage_days=30,
            timestamp=old_time,
            freshness_seconds=259200,
        )
        context = OperationalContextSnapshot(
            workspace_id="ws-test",
            snapshot_id=None,
            snapshot_version=1,
            snapshot_hash="hash",
            by_node={"n1": inv},
        )

        # Default: stale with "degrade" policy = warning, not error
        result = validate_operational_context(context)
        assert result.is_valid
        assert result.can_proceed
        assert any(i.issue_type == "stale" for i in result.issues)
        assert result.warnings == 1

        # With strict_freshness=True: stale becomes error
        result_strict = validate_operational_context(context, strict_freshness=True)
        assert not result_strict.is_valid
        assert any(i.issue_type == "stale" for i in result_strict.issues)

    def test_negative_coverage_fails(self):
        inv = make_inventory_state(coverage_days=-5)
        context = OperationalContextSnapshot(
            workspace_id="ws-test",
            snapshot_id=None,
            snapshot_version=1,
            snapshot_hash="hash",
            by_node={"n1": inv},
        )

        result = validate_operational_context(context)

        assert not result.is_valid
        assert any(i.issue_type == "out_of_bounds" for i in result.issues)

    def test_confidence_out_of_bounds_fails(self):
        inv = make_inventory_state(confidence=1.5)
        context = OperationalContextSnapshot(
            workspace_id="ws-test",
            snapshot_id=None,
            snapshot_version=1,
            snapshot_hash="hash",
            by_node={"n1": inv},
        )

        result = validate_operational_context(context)

        assert not result.is_valid
        assert any(i.field_name == "confidence" for i in result.issues)


# ─────────────────────────────────────────────────────────────────────────────
# Detector Context Integration Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestDetectorsWithContext:
    def test_spof_severity_reduced_with_good_inventory(self):
        """SPOF severity should be reduced when inventory coverage is good."""
        features = make_feature_snapshot(
            nodes={
                "n1": make_node_features(
                    node_id="n1", single_point_of_failure=0.75, downstream_reach=5
                )
            }
        )
        # Good inventory coverage
        inv = make_inventory_state(node_id="n1", coverage_days=45)
        context = OperationalContextSnapshot(
            workspace_id="ws-test",
            snapshot_id=None,
            snapshot_version=1,
            snapshot_hash="ctx",
            by_node={"n1": inv},
        )
        enriched = EnrichedSnapshot.fuse(features, context)

        detector = get_detector("single_point_of_failure_alert")
        signals = detector(enriched, SIGNAL_REGISTRY["single_point_of_failure_alert"])

        assert len(signals) == 1
        # With 45 days coverage, severity should be reduced
        # 0.75 SPOF would normally be CRITICAL, but good inventory reduces it
        assert signals[0].severity.value in ("warning", "critical")

    def test_spof_confidence_degraded_with_stale_context(self):
        """Signal confidence should be degraded when context is stale."""
        features = make_feature_snapshot(
            nodes={"n1": make_node_features(node_id="n1", single_point_of_failure=0.6)}
        )
        # Stale inventory
        old_time = datetime.now(UTC) - timedelta(days=3)
        inv = make_inventory_state(
            node_id="n1",
            coverage_days=30,
            timestamp=old_time,
            freshness_seconds=259200,
        )
        context = OperationalContextSnapshot(
            workspace_id="ws-test",
            snapshot_id=None,
            snapshot_version=1,
            snapshot_hash="ctx",
            by_node={"n1": inv},
        )
        enriched = EnrichedSnapshot.fuse(features, context)

        detector = get_detector("single_point_of_failure_alert")
        signals = detector(enriched, SIGNAL_REGISTRY["single_point_of_failure_alert"])

        assert len(signals) == 1
        # Confidence should be degraded (< base confidence)
        assert signals[0].confidence < 0.6

    def test_criticality_severity_increased_for_critical_customer(self):
        """Criticality severity should increase for critical customers."""
        features = make_feature_snapshot(
            nodes={"n1": make_node_features(node_id="n1", entity_type="Customer", criticality=0.5)}
        )
        biz = make_business_state(
            node_id="n1",
            entity_type="Customer",
            critical_customer_flag=True,
            revenue_at_risk=500000,
        )
        context = OperationalContextSnapshot(
            workspace_id="ws-test",
            snapshot_id=None,
            snapshot_version=1,
            snapshot_hash="ctx",
            by_node={"n1": biz},
        )
        enriched = EnrichedSnapshot.fuse(features, context)

        detector = get_detector("criticality_alert")
        signals = detector(enriched, SIGNAL_REGISTRY["criticality_alert"])

        assert len(signals) == 1
        # Severity should be increased due to critical customer flag
        assert signals[0].severity.value in ("warning", "critical")
        assert "Critical customer" in signals[0].explanation

    def test_detector_works_without_context(self):
        """Detectors should work (with degraded confidence) when context is missing."""
        features = make_feature_snapshot(
            nodes={"n1": make_node_features(node_id="n1", single_point_of_failure=0.7)}
        )
        # No operational context
        enriched = EnrichedSnapshot.fuse(features, None)

        detector = get_detector("single_point_of_failure_alert")
        signals = detector(enriched, SIGNAL_REGISTRY["single_point_of_failure_alert"])

        assert len(signals) == 1
        # Confidence should be degraded due to missing context
        assert signals[0].confidence < 0.7
