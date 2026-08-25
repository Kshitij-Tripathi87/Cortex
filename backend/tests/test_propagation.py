"""Tests for Program E: Propagation Engine.

Covers:
  - Propagation models and contracts
  - Propagation rules (selection, matching, formulas)
  - Propagation engine runtime (BFS, attenuation, confidence decay, cycles)
  - Context-sensitive severity/confidence adjustment
  - Impact classification
  - Replay stability
  - API integration
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.common.ids import uuid7
from app.modules.graph.context_fusion import EnrichedSnapshot
from app.modules.graph.context_models import (
    BusinessOperationalState,
    FreshnessPolicy,
    InventoryOperationalState,
    OperationalContextSnapshot,
)
from app.modules.graph.feature_models import FeatureSnapshot, NodeFeatures
from app.modules.graph.propagation_engine import PropagationEngine
from app.modules.graph.propagation_models import (
    AffectedEntity,
    ImpactSummary,
    ImpactType,
    PropagationDirection,
    PropagationRequest,
    PropagationSnapshot,
    PropagationStep,
    PropagationTree,
    Severity,
)
from app.modules.graph.propagation_rules import PROPAGATION_RULES, get_rule
from app.modules.graph.repository import EdgeDTO, NodeDTO
from app.modules.graph.signal_models import SignalCategory, SignalInstance, SignalSeverity
from app.modules.graph.traversal import InMemoryGraph, build_in_memory_graph

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


def make_node_features(
    node_id: str = "n1",
    entity_type: str = "Part",
    entity_id: str = "part-1",
    **overrides,
) -> NodeFeatures:
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
    **overrides,
) -> InventoryOperationalState:
    now = datetime.now(UTC)
    return InventoryOperationalState(
        node_id=node_id,
        entity_id=entity_id,
        entity_type=entity_type,
        timestamp=now,
        source=overrides.get("source", "SAP"),
        freshness_seconds=overrides.get("freshness_seconds", 3600),
        confidence=overrides.get("confidence", 0.95),
        coverage_days=coverage_days,
        freshness_policy=FreshnessPolicy(
            max_age_seconds=86400,
            degraded_age_seconds=43200,
            stale_age_seconds=172800,
            expiration_policy="degrade",
            required_for_signal=False,
        ),
    )


def make_business_state(
    node_id: str = "n1",
    entity_id: str = "cust-1",
    entity_type: str = "Customer",
    critical_customer_flag: bool = True,
    **overrides,
) -> BusinessOperationalState:
    now = datetime.now(UTC)
    return BusinessOperationalState(
        node_id=node_id,
        entity_id=entity_id,
        entity_type=entity_type,
        timestamp=now,
        source=overrides.get("source", "Salesforce"),
        freshness_seconds=overrides.get("freshness_seconds", 7200),
        confidence=overrides.get("confidence", 0.9),
        critical_customer_flag=critical_customer_flag,
    )


def make_enriched_snapshot(
    workspace_id: str = "ws-test",
    nodes: dict[str, NodeFeatures] | None = None,
    op_states: dict[str, InventoryOperationalState | BusinessOperationalState] | None = None,
) -> EnrichedSnapshot:
    features = make_feature_snapshot(workspace_id, nodes or {})
    context = None
    if op_states:
        context = OperationalContextSnapshot(
            workspace_id=workspace_id,
            snapshot_id=None,
            snapshot_version=1,
            snapshot_hash="ctx_hash",
            by_node=op_states,
        )
    return EnrichedSnapshot.fuse(features, context)


def make_signal(
    node_id: str = "n1",
    signal_name: str = "single_point_of_failure_alert",
    severity: SignalSeverity = SignalSeverity.CRITICAL,
    confidence: float = 0.9,
) -> SignalInstance:
    return SignalInstance(
        signal_id=str(uuid7()),
        signal_name=signal_name,
        signal_version="1.0.0",
        workspace_id="ws-test",
        snapshot_version=1,
        snapshot_hash="sig_hash",
        severity=severity,
        confidence=confidence,
        category=SignalCategory.SUPPLIER_RISK,
        affected_node_ids=[node_id],
        affected_entity_types=["Supplier"],
        affected_entity_ids=["supplier-1"],
        propagation_scope="downstream",
        feature_evidence={"single_point_of_failure": 0.8},
        explanation="Test signal",
    )


def make_graph(nodes: list[NodeDTO], edges: list[EdgeDTO]) -> InMemoryGraph:
    return build_in_memory_graph(nodes, edges)


def make_node_dto(node_id: str, entity_type: str, entity_id: str) -> NodeDTO:
    now = datetime.now(UTC)
    return NodeDTO(
        node_id=node_id,
        workspace_id="ws-test",
        entity_type=entity_type,
        entity_id=entity_id,
        attributes={},
        first_seen_version=1,
        last_modified_version=1,
        valid_from=now,
        valid_to=None,
    )


def make_edge_dto(source: str, target: str, rel_type: str) -> EdgeDTO:
    now = datetime.now(UTC)
    return EdgeDTO(
        edge_id=f"{source}->{target}:{rel_type}",
        workspace_id="ws-test",
        source_node_id=source,
        target_node_id=target,
        relationship_type=rel_type,
        attributes={},
        first_seen_version=1,
        last_modified_version=1,
        valid_from=now,
        valid_to=None,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Propagation Rules Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestPropagationRules:
    def test_get_rule_for_spof_signal(self):
        rule = get_rule("single_point_of_failure_alert")
        assert rule.name == "supplier_failure"
        assert rule.direction == PropagationDirection.UPSTREAM

    def test_get_rule_for_bottleneck_signal(self):
        rule = get_rule("bottleneck_alert")
        assert rule.name in ("route_closure", "warehouse_outage", "shipment_delay")

    def test_get_rule_fallback(self):
        rule = get_rule("nonexistent_signal")
        assert rule.name == "generic_downstream"

    def test_rule_attenuation_formula(self):
        rule = PROPAGATION_RULES["supplier_failure"]
        # attenuation_at_hop(h) = attenuation_per_hop ** h
        assert rule.attenuation_at_hop(0) == 1.0
        assert abs(rule.attenuation_at_hop(1) - 0.85) < 0.001
        assert abs(rule.attenuation_at_hop(2) - 0.85**2) < 0.001

    def test_rule_confidence_decay(self):
        rule = PROPAGATION_RULES["supplier_failure"]
        # confidence_at_hop(h) = source_conf * decay ** h
        assert rule.confidence_at_hop(0, 1.0) == 1.0
        assert abs(rule.confidence_at_hop(1, 1.0) - 0.90) < 0.001
        assert abs(rule.confidence_at_hop(2, 1.0) - 0.90**2) < 0.001

    def test_rule_severity_degradation(self):
        rule = PROPAGATION_RULES["supplier_failure"]
        sev0 = rule.severity_for_hop(0, Severity.CRITICAL)
        sev1 = rule.severity_for_hop(1, Severity.CRITICAL)
        sev2 = rule.severity_for_hop(2, Severity.CRITICAL)
        sev3 = rule.severity_for_hop(3, Severity.CRITICAL)
        # hop 0,1 = CRITICAL, hop 2,3 = WARNING (degraded)
        assert sev0 == Severity.CRITICAL
        assert sev1 == Severity.CRITICAL
        assert sev2 == Severity.WARNING
        assert sev3 == Severity.WARNING

    def test_rule_impact_type_mapping(self):
        rule = PROPAGATION_RULES["supplier_failure"]
        assert rule.impact_type_for("Supplier") == ImpactType.SUPPLIER
        assert rule.impact_type_for("Facility") == ImpactType.FACILITY
        assert rule.impact_type_for("InventoryItem") == ImpactType.INVENTORY
        assert rule.impact_type_for("Customer") == ImpactType.CUSTOMER


# ─────────────────────────────────────────────────────────────────────────────
# Propagation Engine Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestPropagationEngine:
    def test_simple_one_hop_propagation(self):
        # Graph: Supplier(n1) --ORDERS_FROM--> PurchaseOrder(n2)
        nodes = [
            make_node_dto("n1", "Supplier", "supplier-1"),
            make_node_dto("n2", "PurchaseOrder", "po-1"),
        ]
        edges = [make_edge_dto("n2", "n1", "ORDERS_FROM")]  # PO orders from Supplier
        graph = make_graph(nodes, edges)

        enriched = make_enriched_snapshot(
            nodes={
                "n1": make_node_features("n1", "Supplier", "supplier-1"),
                "n2": make_node_features("n2", "PurchaseOrder", "po-1"),
            }
        )
        signal = make_signal("n1")

        engine = PropagationEngine()
        request = PropagationRequest(
            workspace_id="ws-test",
            source_signal_id=signal.signal_id,
            source_node_id="n1",
            max_depth=2,
        )

        result = engine.propagate(signal, enriched, graph, request)

        assert result.success
        snap = result.snapshot
        assert len(snap.tree.steps) >= 1
        # Source step
        assert snap.tree.steps[0].affected_node_id == "n1"
        assert snap.tree.steps[0].hop_number == 0
        # Downstream hop to PO
        hop1 = [s for s in snap.tree.steps if s.hop_number == 1]
        assert len(hop1) == 1
        assert hop1[0].affected_node_id == "n2"
        assert hop1[0].relationship_type == "ORDERS_FROM"
        assert hop1[0].parent_node_id == "n1"

    def test_multi_hop_propagation(self):
        # Supplier -> PO -> Inventory -> SalesOrder -> Customer
        nodes = [
            make_node_dto("n1", "Supplier", "supplier-1"),
            make_node_dto("n2", "PurchaseOrder", "po-1"),
            make_node_dto("n3", "InventoryItem", "inv-1"),
            make_node_dto("n4", "SalesOrder", "so-1"),
            make_node_dto("n5", "Customer", "cust-1"),
        ]
        edges = [
            make_edge_dto("n2", "n1", "ORDERS_FROM"),
            make_edge_dto("n3", "n2", "IS_PRODUCT"),  # inventory linked to PO
            make_edge_dto("n4", "n3", "SHIPS_FROM"),  # SO ships from inventory
            make_edge_dto("n5", "n4", "ORDERED_BY"),  # customer ordered by SO
        ]
        graph = make_graph(nodes, edges)

        enriched = make_enriched_snapshot(
            nodes={
                "n1": make_node_features("n1", "Supplier", "supplier-1"),
                "n2": make_node_features("n2", "PurchaseOrder", "po-1"),
                "n3": make_node_features("n3", "InventoryItem", "inv-1"),
                "n4": make_node_features("n4", "SalesOrder", "so-1"),
                "n5": make_node_features("n5", "Customer", "cust-1"),
            }
        )
        signal = make_signal("n1")

        engine = PropagationEngine()
        request = PropagationRequest(
            workspace_id="ws-test",
            source_signal_id=signal.signal_id,
            source_node_id="n1",
            max_depth=5,
        )

        result = engine.propagate(signal, enriched, graph, request)

        assert result.success
        snap = result.snapshot
        # Should reach all 5 nodes
        affected_ids = {s.affected_node_id for s in snap.tree.steps}
        assert "n1" in affected_ids
        assert "n2" in affected_ids
        assert "n3" in affected_ids
        assert "n4" in affected_ids
        assert "n5" in affected_ids
        assert snap.max_depth_reached == 4

    def test_cycle_protection(self):
        # Graph with cycle: A -> B -> C -> A
        nodes = [
            make_node_dto("n1", "Supplier", "s1"),
            make_node_dto("n2", "Facility", "f1"),
            make_node_dto("n3", "Facility", "f2"),
        ]
        edges = [
            make_edge_dto("n1", "n2", "ORDERS_FROM"),
            make_edge_dto("n2", "n3", "SHIPS_TO"),
            make_edge_dto("n3", "n1", "SUPPLIED_BY"),  # cycle back
        ]
        graph = make_graph(nodes, edges)

        enriched = make_enriched_snapshot(
            nodes={
                "n1": make_node_features("n1", "Supplier", "s1"),
                "n2": make_node_features("n2", "Facility", "f1"),
                "n3": make_node_features("n3", "Facility", "f2"),
            }
        )
        signal = make_signal("n1")

        engine = PropagationEngine()
        request = PropagationRequest(
            workspace_id="ws-test",
            source_signal_id=signal.signal_id,
            source_node_id="n1",
            max_depth=5,
        )

        result = engine.propagate(signal, enriched, graph, request)

        assert result.success
        # Should not infinite loop - each node visited once
        steps_per_node = {}
        for s in result.snapshot.tree.steps:
            steps_per_node[s.affected_node_id] = steps_per_node.get(s.affected_node_id, 0) + 1
        # Each node should appear exactly once (at its first visit)
        assert all(v == 1 for v in steps_per_node.values())

    def test_max_depth_limit(self):
        nodes = [make_node_dto(f"n{i}", "Facility", f"f{i}") for i in range(6)]
        # For UPSTREAM traversal, edges must point TOWARDS the source
        # Edge from n{i+1} -> n{i} means n{i+1} SHIPS_TO n{i}
        # Starting at n0, UPSTREAM follows in-edges to n1, n2, etc.
        edges = [make_edge_dto(f"n{i + 1}", f"n{i}", "SHIPS_TO") for i in range(5)]
        graph = make_graph(nodes, edges)

        enriched = make_enriched_snapshot(
            nodes={f"n{i}": make_node_features(f"n{i}", "Facility", f"f{i}") for i in range(6)}
        )
        signal = make_signal("n0")

        engine = PropagationEngine()
        request = PropagationRequest(
            workspace_id="ws-test",
            source_signal_id=signal.signal_id,
            source_node_id="n0",
            max_depth=3,
        )

        result = engine.propagate(signal, enriched, graph, request)

        assert result.success
        # Should only reach up to n3 (hop 3)
        affected = {s.affected_node_id for s in result.snapshot.tree.steps}
        assert "n0" in affected
        assert "n3" in affected
        assert "n4" not in affected  # beyond max_depth

    def test_confidence_decay_per_hop(self):
        # For UPSTREAM, edge must point TO source: n2 -> n1
        nodes = [make_node_dto("n1", "Supplier", "s1"), make_node_dto("n2", "Facility", "f1")]
        edges = [make_edge_dto("n2", "n1", "ORDERS_FROM")]
        graph = make_graph(nodes, edges)

        enriched = make_enriched_snapshot(
            nodes={
                "n1": make_node_features("n1", "Supplier", "s1"),
                "n2": make_node_features("n2", "Facility", "f1"),
            }
        )
        signal = make_signal("n1", confidence=1.0)

        engine = PropagationEngine()
        request = PropagationRequest(
            workspace_id="ws-test",
            source_signal_id=signal.signal_id,
            source_node_id="n1",
            max_depth=2,
        )

        result = engine.propagate(signal, enriched, graph, request)

        assert result.success
        hop1 = [s for s in result.snapshot.tree.steps if s.hop_number == 1][0]
        # confidence at hop 1 = source * decay * no_context_penalty = 1.0 * 0.90 * 0.70 = 0.63
        assert abs(hop1.confidence - 0.63) < 0.01

    def test_attenuation_per_hop(self):
        nodes = [make_node_dto("n1", "Supplier", "s1"), make_node_dto("n2", "Facility", "f1")]
        edges = [make_edge_dto("n2", "n1", "ORDERS_FROM")]
        graph = make_graph(nodes, edges)

        enriched = make_enriched_snapshot(
            nodes={
                "n1": make_node_features("n1", "Supplier", "s1"),
                "n2": make_node_features("n2", "Facility", "f1"),
            }
        )
        signal = make_signal("n1")

        engine = PropagationEngine()
        request = PropagationRequest(
            workspace_id="ws-test",
            source_signal_id=signal.signal_id,
            source_node_id="n1",
            max_depth=2,
        )

        result = engine.propagate(signal, enriched, graph, request)

        assert result.success
        hop1 = [s for s in result.snapshot.tree.steps if s.hop_number == 1][0]
        assert abs(hop1.attenuation - 0.85) < 0.001

    def test_min_confidence_filter(self):
        nodes = [make_node_dto("n1", "Supplier", "s1"), make_node_dto("n2", "Facility", "f1")]
        edges = [make_edge_dto("n2", "n1", "ORDERS_FROM")]
        graph = make_graph(nodes, edges)

        enriched = make_enriched_snapshot(
            nodes={
                "n1": make_node_features("n1", "Supplier", "s1"),
                "n2": make_node_features("n2", "Facility", "f1"),
            }
        )
        signal = make_signal("n1", confidence=0.5)

        engine = PropagationEngine()
        request = PropagationRequest(
            workspace_id="ws-test",
            source_signal_id=signal.signal_id,
            source_node_id="n1",
            max_depth=2,
            min_confidence=0.5,  # hop 1 will be ~0.45, below threshold
        )

        result = engine.propagate(signal, enriched, graph, request)

        assert result.success
        # n2 should be filtered out due to low confidence
        affected = {s.affected_node_id for s in result.snapshot.tree.steps}
        assert "n2" not in affected


# ─────────────────────────────────────────────────────────────────────────────
# Context-Sensitive Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestContextSensitivePropagation:
    def test_inventory_coverage_reduces_severity(self):
        nodes = [
            make_node_dto("n1", "Supplier", "s1"),
            make_node_dto("n2", "InventoryItem", "inv-1"),
        ]
        edges = [make_edge_dto("n2", "n1", "SUPPLIED_BY")]
        graph = make_graph(nodes, edges)

        # Inventory with good coverage (45 days) - should reduce severity
        enriched = make_enriched_snapshot(
            nodes={
                "n1": make_node_features("n1", "Supplier", "s1"),
                "n2": make_node_features("n2", "InventoryItem", "inv-1"),
            },
            op_states={
                "n2": make_inventory_state("n2", "inv-1", "InventoryItem", coverage_days=45)
            },
        )
        signal = make_signal("n1")

        engine = PropagationEngine()
        request = PropagationRequest(
            workspace_id="ws-test",
            source_signal_id=signal.signal_id,
            source_node_id="n1",
            max_depth=2,
        )

        result = engine.propagate(signal, enriched, graph, request)

        assert result.success
        hop1 = [s for s in result.snapshot.tree.steps if s.hop_number == 1][0]
        # Severity should be reduced by inventory coverage
        assert hop1.impact_severity in (Severity.WARNING, Severity.INFO)

    def test_critical_customer_increases_severity(self):
        nodes = [make_node_dto("n1", "Supplier", "s1"), make_node_dto("n2", "Customer", "cust-1")]
        edges = [make_edge_dto("n2", "n1", "ORDERED_BY")]  # customer orders from supplier (reverse)
        graph = make_graph(nodes, edges)

        enriched = make_enriched_snapshot(
            nodes={
                "n1": make_node_features("n1", "Supplier", "s1"),
                "n2": make_node_features("n2", "Customer", "cust-1"),
            },
            op_states={
                "n2": make_business_state("n2", "cust-1", "Customer", critical_customer_flag=True)
            },
        )
        signal = make_signal("n1", severity=SignalSeverity.WARNING)

        engine = PropagationEngine()
        request = PropagationRequest(
            workspace_id="ws-test",
            source_signal_id=signal.signal_id,
            source_node_id="n1",
            max_depth=2,
        )

        result = engine.propagate(signal, enriched, graph, request)

        assert result.success
        hop1 = [s for s in result.snapshot.tree.steps if s.hop_number == 1][0]
        # Critical customer should increase severity
        assert hop1.impact_severity in (Severity.CRITICAL, Severity.BLOCKING)

    def test_stale_context_degrades_confidence(self):
        nodes = [make_node_dto("n1", "Supplier", "s1"), make_node_dto("n2", "Facility", "f1")]
        edges = [make_edge_dto("n2", "n1", "ORDERS_FROM")]
        graph = make_graph(nodes, edges)

        # Stale inventory state (> 48 hours old)
        old_time = datetime.now(UTC) - timedelta(hours=60)
        stale_inv = InventoryOperationalState(
            node_id="n2",
            entity_id="f1",
            entity_type="Facility",
            coverage_days=10,
            timestamp=old_time,
            source="SAP",
            freshness_seconds=250000,
            confidence=0.9,
        )
        enriched = make_enriched_snapshot(
            nodes={
                "n1": make_node_features("n1", "Supplier", "s1"),
                "n2": make_node_features("n2", "Facility", "f1"),
            },
            op_states={"n2": stale_inv},
        )
        signal = make_signal("n1")

        engine = PropagationEngine()
        request = PropagationRequest(
            workspace_id="ws-test",
            source_signal_id=signal.signal_id,
            source_node_id="n1",
            max_depth=2,
        )

        result = engine.propagate(signal, enriched, graph, request)

        assert result.success
        hop1 = [s for s in result.snapshot.tree.steps if s.hop_number == 1][0]
        # Stale context should reduce confidence more aggressively
        assert hop1.confidence < 0.45  # base 0.9 * 0.9 * 0.5 = 0.405


# ─────────────────────────────────────────────────────────────────────────────
# Impact Classification & Summary Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestImpactClassification:
    def test_affected_entities_deduplicated(self):
        nodes = [make_node_dto("n1", "Supplier", "s1"), make_node_dto("n2", "Facility", "f1")]
        edges = [make_edge_dto("n2", "n1", "ORDERS_FROM")]
        graph = make_graph(nodes, edges)

        enriched = make_enriched_snapshot(
            nodes={
                "n1": make_node_features("n1", "Supplier", "s1"),
                "n2": make_node_features("n2", "Facility", "f1"),
            }
        )
        signal = make_signal("n1")

        engine = PropagationEngine()
        request = PropagationRequest(
            workspace_id="ws-test",
            source_signal_id=signal.signal_id,
            source_node_id="n1",
            max_depth=2,
        )

        result = engine.propagate(signal, enriched, graph, request)

        assert result.success
        # Each node should appear once in affected_entities
        entity_ids = [e.node_id for e in result.snapshot.affected_entities]
        assert len(entity_ids) == len(set(entity_ids))

    def test_affected_entities_sorted_by_hop(self):
        nodes = [make_node_dto(f"n{i}", "Facility", f"f{i}") for i in range(4)]
        edges = [make_edge_dto(f"n{i}", f"n{i + 1}", "SHIPS_TO") for i in range(3)]
        graph = make_graph(nodes, edges)

        enriched = make_enriched_snapshot(
            nodes={f"n{i}": make_node_features(f"n{i}", "Facility", f"f{i}") for i in range(4)}
        )
        signal = make_signal("n0")

        engine = PropagationEngine()
        request = PropagationRequest(
            workspace_id="ws-test",
            source_signal_id=signal.signal_id,
            source_node_id="n0",
            max_depth=3,
        )

        result = engine.propagate(signal, enriched, graph, request)

        assert result.success
        hops = [e.hop_number for e in result.snapshot.affected_entities]
        assert hops == sorted(hops)

    def test_summary_aggregates_correctly(self):
        nodes = [make_node_dto("n1", "Supplier", "s1"), make_node_dto("n2", "Facility", "f1")]
        edges = [make_edge_dto("n2", "n1", "ORDERS_FROM")]
        graph = make_graph(nodes, edges)

        enriched = make_enriched_snapshot(
            nodes={
                "n1": make_node_features("n1", "Supplier", "s1"),
                "n2": make_node_features("n2", "Facility", "f1"),
            }
        )
        signal = make_signal("n1")

        engine = PropagationEngine()
        request = PropagationRequest(
            workspace_id="ws-test",
            source_signal_id=signal.signal_id,
            source_node_id="n1",
            max_depth=2,
        )

        result = engine.propagate(signal, enriched, graph, request)

        assert result.success
        summary = result.snapshot.summary
        assert summary.total_affected == 2
        assert summary.max_hop == 1
        assert "FACILITY" in summary.by_entity_type or "Facility" in summary.by_entity_type


# ─────────────────────────────────────────────────────────────────────────────
# Replay Stability
# ─────────────────────────────────────────────────────────────────────────────


class TestReplayStability:
    def test_same_inputs_same_outputs(self):
        nodes = [make_node_dto("n1", "Supplier", "s1"), make_node_dto("n2", "Facility", "f1")]
        edges = [make_edge_dto("n2", "n1", "ORDERS_FROM")]
        graph = make_graph(nodes, edges)

        enriched = make_enriched_snapshot(
            nodes={
                "n1": make_node_features("n1", "Supplier", "s1"),
                "n2": make_node_features("n2", "Facility", "f1"),
            }
        )
        signal = make_signal("n1")

        engine = PropagationEngine()
        request = PropagationRequest(
            workspace_id="ws-test",
            source_signal_id=signal.signal_id,
            source_node_id="n1",
            max_depth=2,
        )

        # Run twice
        result1 = engine.propagate(signal, enriched, graph, request)
        result2 = engine.propagate(signal, enriched, graph, request)

        # Both should succeed
        assert result1.success
        assert result2.success

        # Compare key deterministic fields
        def step_key(s: PropagationStep):
            return (
                s.affected_node_id,
                s.hop_number,
                s.attenuation,
                s.confidence,
                s.impact_type.value,
                s.impact_severity.value,
            )

        keys1 = sorted(step_key(s) for s in result1.snapshot.tree.steps)
        keys2 = sorted(step_key(s) for s in result2.snapshot.tree.steps)

        assert keys1 == keys2, "Propagation not deterministic"


# ─────────────────────────────────────────────────────────────────────────────
# Propagation Models Serialization
# ─────────────────────────────────────────────────────────────────────────────


class TestPropagationModels:
    def test_step_to_dict(self):
        step = PropagationStep(
            propagation_id="p1",
            source_signal_id="s1",
            source_node_id="n1",
            source_node_type="Supplier",
            affected_node_id="n2",
            affected_node_type="Facility",
            affected_entity_id="f1",
            hop_number=1,
            relationship_type="ORDERS_FROM",
            parent_node_id="n1",
            attenuation=0.85,
            confidence=0.81,
            impact_type=ImpactType.FACILITY,
            impact_severity=Severity.WARNING,
            impact_reason="Test",
            graph_version=1,
            feature_snapshot_version=1,
            context_snapshot_version=1,
        )
        d = step.to_dict()
        assert d["affected_node_id"] == "n2"
        assert d["attenuation"] == 0.85
        assert d["confidence"] == 0.81

    def test_snapshot_to_dict(self):
        step = PropagationStep(
            propagation_id="p1",
            source_signal_id="s1",
            source_node_id="n1",
            source_node_type="Supplier",
            affected_node_id="n2",
            affected_node_type="Facility",
            affected_entity_id="f1",
            hop_number=1,
            relationship_type="ORDERS_FROM",
            parent_node_id="n1",
            attenuation=0.85,
            confidence=0.81,
            impact_type=ImpactType.FACILITY,
            impact_severity=Severity.WARNING,
            impact_reason="Test",
            graph_version=1,
            feature_snapshot_version=1,
            context_snapshot_version=1,
        )
        tree = PropagationTree(
            propagation_id="p1",
            source_signal_id="s1",
            source_node_id="n1",
            source_node_type="Supplier",
            steps=[step],
        )
        entities = [
            AffectedEntity(
                node_id="n2",
                entity_id="f1",
                entity_type="Facility",
                hop_number=1,
                impact_type=ImpactType.FACILITY,
                impact_severity=Severity.WARNING,
                confidence=0.81,
                impact_reason="Test",
            )
        ]
        summary = ImpactSummary(
            total_affected=1, max_hop=1, avg_confidence=0.81, min_confidence=0.81
        )
        snap = PropagationSnapshot(
            propagation_id="p1",
            workspace_id="ws-test",
            source_signal_id="s1",
            source_signal_name="single_point_of_failure_alert",
            source_node_id="n1",
            source_node_type="Supplier",
            source_severity=Severity.CRITICAL,
            source_confidence=0.9,
            graph_version=1,
            feature_snapshot_version=1,
            context_snapshot_version=1,
            signal_snapshot_version=1,
            tree=tree,
            affected_entities=entities,
            summary=summary,
        )
        d = snap.to_dict()
        assert d["propagation_id"] == "p1"
        assert d["summary"]["total_affected"] == 1
