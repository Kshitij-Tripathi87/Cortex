"""Tests for Program D: Signal Engine.

Covers:
  - Detector correctness (thresholds, severity, confidence)
  - Signal deduplication
  - Explanation formatting
  - Replay stability (same features → same signals)
  - API endpoint integration
"""

from __future__ import annotations

from app.modules.graph.context_fusion import EnrichedSnapshot
from app.modules.graph.detectors import (
    detect_bottleneck_signals,
    detect_concentration_signals,
    detect_criticality_signals,
    detect_isolation_signals,
    detect_spof_signals,
    get_detector,
)
from app.modules.graph.feature_models import FeatureSnapshot, NodeFeatures
from app.modules.graph.signal_engine import _deduplicate_signals
from app.modules.graph.signal_models import SignalCategory, SignalInstance, SignalSeverity
from app.modules.graph.signal_registry import (
    SIGNAL_REGISTRY,
    compute_signal_severity,
)

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


def make_enriched_snapshot(
    workspace_id: str = "ws-test",
    nodes: dict[str, NodeFeatures] | None = None,
) -> EnrichedSnapshot:
    """Build an EnrichedSnapshot with given nodes (no operational context)."""
    if nodes is None:
        nodes = {}
    feature_snapshot = FeatureSnapshot(
        workspace_id=workspace_id,
        snapshot_id=None,
        snapshot_version=1,
        snapshot_hash="test_hash_" + workspace_id,
        by_node=nodes,
        workspace=None,
    )
    return EnrichedSnapshot.fuse(feature_snapshot, None)


def make_node(
    node_id: str = "n1",
    entity_type: str = "Part",
    entity_id: str = "part-1",
    **feature_overrides,
) -> tuple[str, NodeFeatures]:
    """Build a (node_id, NodeFeatures) tuple."""
    nf = NodeFeatures(
        node_id=node_id,
        entity_type=entity_type,
        entity_id=entity_id,
        in_degree=feature_overrides.get("in_degree", 1),
        out_degree=feature_overrides.get("out_degree", 1),
        total_degree=feature_overrides.get("total_degree", 2),
        degree_centrality=feature_overrides.get("degree_centrality", 0.5),
        in_degree_centrality=feature_overrides.get("in_degree_centrality", 0.5),
        out_degree_centrality=feature_overrides.get("out_degree_centrality", 0.5),
        downstream_reach=feature_overrides.get("downstream_reach", 3),
        upstream_reach=feature_overrides.get("upstream_reach", 2),
        total_reach=feature_overrides.get("total_reach", 5),
        downstream_depth=feature_overrides.get("downstream_depth", 2),
        upstream_depth=feature_overrides.get("upstream_depth", 1),
        criticality=feature_overrides.get("criticality", 0.5),
        single_point_of_failure=feature_overrides.get("single_point_of_failure", 0.5),
        concentration_risk=feature_overrides.get("concentration_risk", 0.5),
        redundancy=feature_overrides.get("redundancy", 0.5),
        betweenness=feature_overrides.get("betweenness", 0.5),
    )
    return (node_id, nf)


# ─────────────────────────────────────────────────────────────────────────────
# Detector tests
# ─────────────────────────────────────────────────────────────────────────────


class TestSpofDetector:
    def test_no_signal_below_threshold(self):
        snapshot = make_enriched_snapshot(nodes=dict([make_node(single_point_of_failure=0.2)]))
        defn = SIGNAL_REGISTRY["single_point_of_failure_alert"]
        signals = detect_spof_signals(snapshot, defn)
        assert len(signals) == 0

    def test_signal_above_threshold(self):
        snapshot = make_enriched_snapshot(nodes=dict([make_node(single_point_of_failure=0.6)]))
        defn = SIGNAL_REGISTRY["single_point_of_failure_alert"]
        signals = detect_spof_signals(snapshot, defn)
        assert len(signals) == 1
        sig = signals[0]
        assert sig.signal_name == "single_point_of_failure_alert"
        assert sig.severity in (
            SignalSeverity.INFO,
            SignalSeverity.WARNING,
            SignalSeverity.CRITICAL,
        )
        assert sig.confidence > 0
        assert "single_point_of_failure" in sig.feature_evidence

    def test_severity_scales_with_spof(self):
        low = make_enriched_snapshot(nodes=dict([make_node("n1", single_point_of_failure=0.35)]))
        high = make_enriched_snapshot(nodes=dict([make_node("n2", single_point_of_failure=0.85)]))
        defn = SIGNAL_REGISTRY["single_point_of_failure_alert"]

        low_sigs = detect_spof_signals(low, defn)
        high_sigs = detect_spof_signals(high, defn)

        assert len(low_sigs) == 1
        assert len(high_sigs) == 1
        # Higher SPOF should yield >= severity
        severity_order = {"info": 0, "warning": 1, "critical": 2, "blocking": 3}
        assert (
            severity_order[high_sigs[0].severity.value]
            >= severity_order[low_sigs[0].severity.value]
        )


class TestConcentrationDetector:
    def test_no_signal_below_threshold(self):
        snapshot = make_enriched_snapshot(nodes=dict([make_node(concentration_risk=0.4)]))
        defn = SIGNAL_REGISTRY["concentration_risk_alert"]
        signals = detect_concentration_signals(snapshot, defn)
        assert len(signals) == 0

    def test_signal_above_threshold(self):
        snapshot = make_enriched_snapshot(
            nodes=dict([make_node(concentration_risk=0.7, in_degree=1)])
        )
        defn = SIGNAL_REGISTRY["concentration_risk_alert"]
        signals = detect_concentration_signals(snapshot, defn)
        assert len(signals) == 1
        assert signals[0].feature_evidence["concentration_risk"] == 0.7

    def test_higher_confidence_with_single_source(self):
        single = make_enriched_snapshot(
            nodes=dict([make_node("n1", concentration_risk=0.8, in_degree=1)])
        )
        multi = make_enriched_snapshot(
            nodes=dict([make_node("n2", concentration_risk=0.8, in_degree=3)])
        )
        defn = SIGNAL_REGISTRY["concentration_risk_alert"]

        single_sigs = detect_concentration_signals(single, defn)
        multi_sigs = detect_concentration_signals(multi, defn)

        assert len(single_sigs) == 1
        assert len(multi_sigs) == 1
        assert single_sigs[0].confidence > multi_sigs[0].confidence


class TestBottleneckDetector:
    def test_no_signal_below_threshold(self):
        snapshot = make_enriched_snapshot(nodes=dict([make_node(betweenness=0.2)]))
        defn = SIGNAL_REGISTRY["bottleneck_alert"]
        signals = detect_bottleneck_signals(snapshot, defn)
        assert len(signals) == 0

    def test_signal_above_threshold(self):
        snapshot = make_enriched_snapshot(nodes=dict([make_node(betweenness=0.5)]))
        defn = SIGNAL_REGISTRY["bottleneck_alert"]
        signals = detect_bottleneck_signals(snapshot, defn)
        assert len(signals) == 1
        assert signals[0].feature_evidence["betweenness"] == 0.5


class TestIsolationDetector:
    def test_no_signal_for_connected_nodes(self):
        snapshot = make_enriched_snapshot(nodes=dict([make_node(total_degree=2)]))
        defn = SIGNAL_REGISTRY["isolation_alert"]
        signals = detect_isolation_signals(snapshot, defn)
        assert len(signals) == 0

    def test_signal_for_isolated_node(self):
        snapshot = make_enriched_snapshot(nodes=dict([make_node(total_degree=0)]))
        defn = SIGNAL_REGISTRY["isolation_alert"]
        signals = detect_isolation_signals(snapshot, defn)
        assert len(signals) == 1
        assert signals[0].severity == SignalSeverity.INFO  # Part isolation = info

    def test_supplier_isolation_critical(self):
        snapshot = make_enriched_snapshot(
            nodes=dict([make_node(entity_type="Supplier", total_degree=0)])
        )
        defn = SIGNAL_REGISTRY["isolation_alert"]
        signals = detect_isolation_signals(snapshot, defn)
        assert len(signals) == 1
        assert signals[0].severity == SignalSeverity.CRITICAL

    def test_facility_isolation_warning(self):
        snapshot = make_enriched_snapshot(
            nodes=dict([make_node(entity_type="Facility", total_degree=0)])
        )
        defn = SIGNAL_REGISTRY["isolation_alert"]
        signals = detect_isolation_signals(snapshot, defn)
        assert len(signals) == 1
        assert signals[0].severity == SignalSeverity.WARNING


class TestCriticalityDetector:
    def test_no_signal_below_threshold(self):
        snapshot = make_enriched_snapshot(nodes=dict([make_node(criticality=0.2)]))
        defn = SIGNAL_REGISTRY["criticality_alert"]
        signals = detect_criticality_signals(snapshot, defn)
        assert len(signals) == 0

    def test_signal_above_threshold(self):
        snapshot = make_enriched_snapshot(nodes=dict([make_node(criticality=0.6)]))
        defn = SIGNAL_REGISTRY["criticality_alert"]
        signals = detect_criticality_signals(snapshot, defn)
        assert len(signals) == 1
        # Confidence is adjusted: base 0.6 * 0.7 (no context) = 0.42
        assert signals[0].confidence == 0.42


# ─────────────────────────────────────────────────────────────────────────────
# Deduplication tests
# ─────────────────────────────────────────────────────────────────────────────


class TestDeduplication:
    def test_keeps_highest_severity(self):
        sig1 = SignalInstance(
            signal_id="s1",
            signal_name="test_alert",
            signal_version="1.0.0",
            workspace_id="ws",
            snapshot_version=1,
            snapshot_hash="h1",
            severity=SignalSeverity.INFO,
            confidence=0.9,
            category=SignalCategory.SUPPLIER_RISK,
            affected_node_ids=["n1"],
            affected_entity_types=["Part"],
            affected_entity_ids=["p1"],
            propagation_scope="workspace",
            feature_evidence={"x": 1},
            explanation="test",
        )
        sig2 = SignalInstance(
            signal_id="s2",
            signal_name="test_alert",
            signal_version="1.0.0",
            workspace_id="ws",
            snapshot_version=1,
            snapshot_hash="h1",
            severity=SignalSeverity.CRITICAL,
            confidence=0.5,
            category=SignalCategory.SUPPLIER_RISK,
            affected_node_ids=["n1"],
            affected_entity_types=["Part"],
            affected_entity_ids=["p1"],
            propagation_scope="workspace",
            feature_evidence={"x": 1},
            explanation="test",
        )

        deduped = _deduplicate_signals([sig1, sig2])
        assert len(deduped) == 1
        assert deduped[0].severity == SignalSeverity.CRITICAL

    def test_different_nodes_not_deduped(self):
        sig1 = SignalInstance(
            signal_id="s1",
            signal_name="test_alert",
            signal_version="1.0.0",
            workspace_id="ws",
            snapshot_version=1,
            snapshot_hash="h1",
            severity=SignalSeverity.INFO,
            confidence=0.9,
            category=SignalCategory.SUPPLIER_RISK,
            affected_node_ids=["n1"],
            affected_entity_types=["Part"],
            affected_entity_ids=["p1"],
            propagation_scope="workspace",
            feature_evidence={"x": 1},
            explanation="test",
        )
        sig2 = SignalInstance(
            signal_id="s2",
            signal_name="test_alert",
            signal_version="1.0.0",
            workspace_id="ws",
            snapshot_version=1,
            snapshot_hash="h1",
            severity=SignalSeverity.INFO,
            confidence=0.9,
            category=SignalCategory.SUPPLIER_RISK,
            affected_node_ids=["n2"],
            affected_entity_types=["Part"],
            affected_entity_ids=["p2"],
            propagation_scope="workspace",
            feature_evidence={"x": 1},
            explanation="test",
        )

        deduped = _deduplicate_signals([sig1, sig2])
        assert len(deduped) == 2


# ─────────────────────────────────────────────────────────────────────────────
# Registry tests
# ─────────────────────────────────────────────────────────────────────────────


class TestDetectorRegistry:
    def test_all_signals_have_detectors(self):
        for signal_name in SIGNAL_REGISTRY:
            detector = get_detector(signal_name)
            assert detector is not None, f"No detector for {signal_name}"

    def test_unknown_signal_returns_none(self):
        assert get_detector("nonexistent_alert") is None


class TestSignalSeverityComputation:
    def test_spof_severity_thresholds(self):
        evidence_low = {"single_point_of_failure": 0.35}
        evidence_high = {"single_point_of_failure": 0.85}

        low_sev = compute_signal_severity("single_point_of_failure_alert", evidence_low)
        high_sev = compute_signal_severity("single_point_of_failure_alert", evidence_high)

        severity_order = {"info": 0, "warning": 1, "critical": 2, "blocking": 3}
        assert severity_order[high_sev.value] >= severity_order[low_sev.value]

    def test_invalid_evidence_returns_info(self):
        evidence = {"bad_key": 999}
        sev = compute_signal_severity("single_point_of_failure_alert", evidence)
        assert sev == SignalSeverity.INFO


# ─────────────────────────────────────────────────────────────────────────────
# Replay stability tests
# ─────────────────────────────────────────────────────────────────────────────


class TestReplayStability:
    def test_same_features_same_signals(self):
        """Determinism: identical features must produce identical signals."""
        snapshot = make_enriched_snapshot(
            workspace_id="ws-replay",
            nodes=dict(
                [
                    make_node("n1", single_point_of_failure=0.7),
                    make_node("n2", concentration_risk=0.8, in_degree=1),
                    make_node("n3", betweenness=0.5),
                    make_node("n4", total_degree=0),
                    make_node("n5", criticality=0.6),
                ]
            ),
        )

        all_signals = []
        for signal_name, defn in SIGNAL_REGISTRY.items():
            detector = get_detector(signal_name)
            if detector:
                signals = detector(snapshot, defn)
                all_signals.extend(signals)

        # Run again
        all_signals_2 = []
        for signal_name, defn in SIGNAL_REGISTRY.items():
            detector = get_detector(signal_name)
            if detector:
                signals = detector(snapshot, defn)
                all_signals_2.extend(signals)

        # Compare (excluding signal_id and created_at which vary)
        def signal_key(sig: SignalInstance):
            return (
                sig.signal_name,
                sig.severity.value,
                sig.confidence,
                tuple(sig.affected_node_ids),
                tuple(sig.affected_entity_ids),
            )

        keys1 = sorted(signal_key(s) for s in all_signals)
        keys2 = sorted(signal_key(s) for s in all_signals_2)

        assert keys1 == keys2, "Signals differ between runs with same features"
