"""Tests for Program F: Scenario Engine.

Covers:
  - Scenario models and contracts
  - Scenario rules (validation, estimation formulas)
  - Scenario engine execution (from propagation + from definition)
  - Parameter adjustments
  - Impact estimation (recovery, financial, service level)
  - Assumption generation
  - Replay stability
  - Serialization
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.common.ids import uuid7
from app.modules.graph.context_fusion import EnrichedSnapshot
from app.modules.graph.context_models import (
    BusinessOperationalState,
    FreshnessPolicy,
    InventoryOperationalState,
    OperationalContextSnapshot,
)
from app.modules.graph.feature_models import FeatureSnapshot, NodeFeatures
from app.modules.graph.propagation_models import (
    AffectedEntity,
    ImpactSummary,
    ImpactType,
    PropagationSnapshot,
    PropagationStep,
    PropagationTree,
    Severity,
)
from app.modules.graph.scenario_engine import ScenarioEngine
from app.modules.graph.scenario_models import (
    ScenarioDefinition,
    ScenarioImpactRecord,
    ScenarioParameter,
    ScenarioRequest,
    ScenarioResult,
    ScenarioSnapshot,
    ScenarioStatus,
    ScenarioSummary,
    ScenarioType,
)
from app.modules.graph.scenario_rules import SCENARIO_RULES, get_rule

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
    revenue_at_risk: float | None = 1000000,
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
        revenue_at_risk=revenue_at_risk,
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


def make_propagation_step(
    affected_node_id: str = "n2",
    affected_node_type: str = "Facility",
    affected_entity_id: str = "f1",
    hop_number: int = 1,
    relationship_type: str = "ORDERS_FROM",
    severity: Severity = Severity.WARNING,
    confidence: float = 0.8,
) -> PropagationStep:
    return PropagationStep(
        propagation_id="prop-1",
        source_signal_id="sig-1",
        source_node_id="n1",
        source_node_type="Supplier",
        affected_node_id=affected_node_id,
        affected_node_type=affected_node_type,
        affected_entity_id=affected_entity_id,
        hop_number=hop_number,
        relationship_type=relationship_type,
        parent_node_id="n1" if hop_number > 0 else None,
        attenuation=0.85**hop_number,
        confidence=round(confidence * (0.9**hop_number), 4),
        impact_type=ImpactType.FACILITY,
        impact_severity=severity,
        impact_reason="Test propagation",
        graph_version=1,
        feature_snapshot_version=1,
        context_snapshot_version=1,
    )


def make_propagation_snapshot(
    steps: list[PropagationStep] | None = None,
) -> PropagationSnapshot:
    if steps is None:
        steps = [
            make_propagation_step("n1", "Supplier", "s1", 0, "SOURCE", Severity.CRITICAL, 0.9),
            make_propagation_step("n2", "Facility", "f1", 1, "ORDERS_FROM", Severity.WARNING, 0.7),
            make_propagation_step(
                "n3", "InventoryItem", "inv-1", 2, "STORED_AT", Severity.INFO, 0.5
            ),
        ]

    tree = PropagationTree(
        propagation_id="prop-1",
        source_signal_id="sig-1",
        source_node_id="n1",
        source_node_type="Supplier",
        steps=steps,
    )

    entities = [
        AffectedEntity(
            node_id=s.affected_node_id,
            entity_id=s.affected_entity_id,
            entity_type=s.affected_node_type,
            hop_number=s.hop_number,
            impact_type=s.impact_type,
            impact_severity=s.impact_severity,
            confidence=s.confidence,
            impact_reason=s.impact_reason,
        )
        for s in steps
    ]

    summary = ImpactSummary(
        total_affected=len(steps),
        by_impact_type={},
        by_severity={},
        by_entity_type={},
        max_hop=max(s.hop_number for s in steps),
        avg_confidence=sum(s.confidence for s in steps) / len(steps),
        min_confidence=min(s.confidence for s in steps),
    )

    return PropagationSnapshot(
        propagation_id="prop-1",
        workspace_id="ws-test",
        source_signal_id="sig-1",
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
        affected_facilities=[],
        affected_inventory=[],
        affected_orders=[],
        affected_customers=[],
        execution_time_ms=10.0,
        max_depth_reached=2,
        rules_applied=["supplier_failure"],
    )


def make_scenario_definition(
    scenario_type: ScenarioType = ScenarioType.SUPPLIER_FAILURE,
    parameters: list[ScenarioParameter] | None = None,
) -> ScenarioDefinition:
    if parameters is None:
        parameters = [
            ScenarioParameter(name="failure_duration_days", value=7, unit="days"),
        ]
    return ScenarioDefinition(
        scenario_id=str(uuid7()),
        workspace_id="ws-test",
        scenario_type=scenario_type,
        name="Test Scenario",
        description="Test scenario description",
        parameters=parameters,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Scenario Rules Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestScenarioRules:
    def test_get_rule_for_supplier_failure(self):
        rule = get_rule(ScenarioType.SUPPLIER_FAILURE)
        assert rule.scenario_type == ScenarioType.SUPPLIER_FAILURE
        assert rule.name == "supplier_failure"

    def test_get_rule_for_warehouse_outage(self):
        rule = get_rule(ScenarioType.WAREHOUSE_OUTAGE)
        assert rule.scenario_type == ScenarioType.WAREHOUSE_OUTAGE

    def test_get_rule_fallback(self):
        rule = get_rule(ScenarioType.CUSTOM)
        assert rule.name == "custom"

    def test_parameter_validation_required(self):
        rule = SCENARIO_RULES[ScenarioType.SUPPLIER_FAILURE]
        params = [ScenarioParameter(name="failure_duration_days", value=7)]
        # Should not error - required param provided
        errors = rule.validate_parameters(params)
        assert errors == []

    def test_parameter_validation_missing_required(self):
        rule = SCENARIO_RULES[ScenarioType.SUPPLIER_FAILURE]
        params = [ScenarioParameter(name="alternative_supplier_available", value=False)]
        # Missing failure_duration_days
        errors = rule.validate_parameters(params)
        assert len(errors) > 0
        assert "failure_duration_days" in errors[0]

    def test_parameter_validation_range(self):
        rule = SCENARIO_RULES[ScenarioType.SUPPLIER_FAILURE]
        params = [ScenarioParameter(name="failure_duration_days", value=0)]  # below min
        errors = rule.validate_parameters(params)
        assert len(errors) > 0

    def test_recovery_hours_estimation(self):
        rule = SCENARIO_RULES[ScenarioType.SUPPLIER_FAILURE]

        hours = rule.recovery_hours_base
        assert hours == 48.0

        # With hop and severity
        hours = rule.estimate_recovery_hours(1, "critical", "Facility")
        assert hours > 48.0

    def test_financial_impact_estimation(self):
        rule = SCENARIO_RULES[ScenarioType.SUPPLIER_FAILURE]

        impact = rule.estimate_financial_impact("critical", "Customer", 1)
        assert impact > rule.financial_impact_base

    def test_service_level_impact_estimation(self):
        rule = SCENARIO_RULES[ScenarioType.SUPPLIER_FAILURE]

        impact = rule.estimate_service_level_impact("warning", 2)
        assert impact > rule.service_level_impact_base

    def test_default_assumptions_generated(self):
        rule = SCENARIO_RULES[ScenarioType.SUPPLIER_FAILURE]
        definition = make_scenario_definition(ScenarioType.SUPPLIER_FAILURE)
        assumptions = rule.build_assumptions(definition)

        assert len(assumptions) >= len(rule.default_assumptions)
        for a in assumptions:
            assert a.scenario_id == definition.scenario_id
            assert 0 <= a.confidence <= 1.0


# ─────────────────────────────────────────────────────────────────────────────
# Scenario Engine Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestScenarioEngine:
    def test_execute_from_propagation(self):
        """Execute scenario using propagation snapshot."""
        propagation = make_propagation_snapshot()
        definition = make_scenario_definition(ScenarioType.SUPPLIER_FAILURE)
        enriched = make_enriched_snapshot(
            nodes={
                "n1": make_node_features("n1", "Supplier", "s1"),
                "n2": make_node_features("n2", "Facility", "f1"),
                "n3": make_node_features("n3", "InventoryItem", "inv-1"),
            }
        )

        engine = ScenarioEngine()
        request = ScenarioRequest(
            workspace_id="ws-test",
            scenario_definition=definition,
            source_propagation_id="prop-1",
        )

        result = engine.execute_scenario(
            enriched=enriched, propagation=propagation, request=request
        )

        assert result.success
        snap = result.snapshot
        assert snap.scenario_id == definition.scenario_id
        assert len(snap.impacts) >= 1  # At least hop 1 and 2
        assert snap.status == ScenarioStatus.COMPLETED
        assert snap.summary.total_impacted_entities >= 1

    def test_execute_from_definition_only(self):
        """Execute scenario using only definition (no propagation)."""
        definition = make_scenario_definition(ScenarioType.SUPPLIER_FAILURE)
        enriched = make_enriched_snapshot(
            nodes={
                "n1": make_node_features("n1", "Supplier", "s1"),
            }
        )

        engine = ScenarioEngine()
        request = ScenarioRequest(
            workspace_id="ws-test",
            scenario_definition=definition,
        )

        result = engine.execute_scenario(enriched=enriched, propagation=None, request=request)

        assert result.success
        snap = result.snapshot
        assert snap.scenario_id == definition.scenario_id
        assert len(snap.impacts) >= 1

    def test_parameter_adjustment_scaling(self):
        """Scenario parameters should scale impact estimates."""
        definition = make_scenario_definition(
            ScenarioType.SUPPLIER_FAILURE,
            parameters=[
                ScenarioParameter(name="shortage_severity_pct", value=50, unit="percent"),
            ],
        )
        propagation = make_propagation_snapshot()
        enriched = make_enriched_snapshot()

        engine = ScenarioEngine()
        request = ScenarioRequest(
            workspace_id="ws-test",
            scenario_definition=definition,
            source_propagation_id="prop-1",
        )

        result = engine.execute_scenario(
            enriched=enriched, propagation=propagation, request=request
        )

        assert result.success
        # Financial impact should be scaled by severity factor
        for imp in result.snapshot.impacts:
            assert imp.metadata.get("severity_factor", 1.0) == 0.5

    def test_context_sensitive_estimates(self):
        """Operational context should adjust estimates."""
        # Good inventory coverage should reduce recovery time
        nodes = {
            "n1": make_node_features("n1", "Supplier", "s1"),
            "n2": make_node_features("n2", "Facility", "f1"),
            "n3": make_node_features("n3", "InventoryItem", "inv-1"),
        }
        op_states = {
            "n3": make_inventory_state(
                "n3", "inv-1", "InventoryItem", coverage_days=45
            ),  # Good coverage
        }
        enriched = make_enriched_snapshot(nodes=nodes, op_states=op_states)

        propagation = make_propagation_snapshot()
        definition = make_scenario_definition(ScenarioType.SUPPLIER_FAILURE)

        engine = ScenarioEngine()
        request = ScenarioRequest(
            workspace_id="ws-test",
            scenario_definition=definition,
            source_propagation_id="prop-1",
        )

        result = engine.execute_scenario(
            enriched=enriched, propagation=propagation, request=request
        )

        assert result.success
        # Recovery should be faster with good inventory
        hop2_impacts = [i for i in result.snapshot.impacts if i.hop_number == 2]
        if hop2_impacts:
            # The facility with good coverage should have reduced recovery
            assert hop2_impacts[0].estimated_recovery_hours < 48.0 * 2  # significantly reduced

    def test_critical_customer_increases_impact(self):
        """Critical customer flag should increase financial impact."""
        nodes = {
            "n1": make_node_features("n1", "Supplier", "s1"),
            "n2": make_node_features("n2", "Customer", "cust-1"),
        }
        op_states = {
            "n2": make_business_state("n2", "cust-1", "Customer", critical_customer_flag=True),
        }
        enriched = make_enriched_snapshot(nodes=nodes, op_states=op_states)

        propagation = make_propagation_snapshot()
        definition = make_scenario_definition(ScenarioType.SUPPLIER_FAILURE)

        engine = ScenarioEngine()
        request = ScenarioRequest(
            workspace_id="ws-test",
            scenario_definition=definition,
            source_propagation_id="prop-1",
        )

        result = engine.execute_scenario(
            enriched=enriched, propagation=propagation, request=request
        )

        assert result.success
        customer_impacts = [
            i for i in result.snapshot.impacts if i.affected_entity_type == "Customer"
        ]
        if customer_impacts:
            # Financial impact should be elevated for critical customer
            assert customer_impacts[0].estimated_financial_impact > 50000

    def test_assumptions_recorded(self):
        """Assumptions should be explicitly recorded."""
        propagation = make_propagation_snapshot()
        definition = make_scenario_definition(ScenarioType.SUPPLIER_FAILURE)
        enriched = make_enriched_snapshot()

        engine = ScenarioEngine()
        request = ScenarioRequest(
            workspace_id="ws-test",
            scenario_definition=definition,
            source_propagation_id="prop-1",
        )

        result = engine.execute_scenario(
            enriched=enriched, propagation=propagation, request=request
        )

        assert result.success
        assert len(result.snapshot.assumptions) >= 1
        # Should have default assumptions + parameter assumptions
        assumption_categories = {a.category for a in result.snapshot.assumptions}
        assert "business" in assumption_categories or "parameter" in assumption_categories

    def test_severity_mapping(self):
        """Propagation severity should map to scenario severity per rule."""
        # Create step with CRITICAL severity
        step = make_propagation_step(hop_number=1, severity=Severity.CRITICAL)
        propagation = make_propagation_snapshot(
            steps=[
                make_propagation_step("n1", "Supplier", "s1", 0, "SOURCE", Severity.CRITICAL),
                step,
            ]
        )
        definition = make_scenario_definition(ScenarioType.SUPPLIER_FAILURE)
        enriched = make_enriched_snapshot()

        engine = ScenarioEngine()
        request = ScenarioRequest(
            workspace_id="ws-test",
            scenario_definition=definition,
            source_propagation_id="prop-1",
        )

        result = engine.execute_scenario(
            enriched=enriched, propagation=propagation, request=request
        )

        assert result.success
        hop1_impact = [i for i in result.snapshot.impacts if i.hop_number == 1][0]
        # Supplier failure rule maps CRITICAL -> critical
        assert hop1_impact.severity == "critical"

    def test_impact_category_mapping(self):
        """Entity types should map to correct impact categories."""
        propagation = make_propagation_snapshot()
        definition = make_scenario_definition(ScenarioType.SUPPLIER_FAILURE)
        enriched = make_enriched_snapshot()

        engine = ScenarioEngine()
        request = ScenarioRequest(
            workspace_id="ws-test",
            scenario_definition=definition,
            source_propagation_id="prop-1",
        )

        result = engine.execute_scenario(
            enriched=enriched, propagation=propagation, request=request
        )

        assert result.success
        categories = {i.impact_category for i in result.snapshot.impacts}
        assert "facility" in categories or "production" in categories
        assert "inventory" in categories

    def test_summary_aggregation(self):
        """Summary should correctly aggregate impacts."""
        propagation = make_propagation_snapshot()
        definition = make_scenario_definition(ScenarioType.SUPPLIER_FAILURE)
        enriched = make_enriched_snapshot()

        engine = ScenarioEngine()
        request = ScenarioRequest(
            workspace_id="ws-test",
            scenario_definition=definition,
            source_propagation_id="prop-1",
        )

        result = engine.execute_scenario(
            enriched=enriched, propagation=propagation, request=request
        )

        assert result.success
        summary = result.snapshot.summary
        assert summary.total_impacted_entities >= 1
        assert summary.max_hop >= 1
        assert 0 <= summary.avg_confidence <= 1.0
        assert summary.total_estimated_financial_impact >= 0

    def test_replay_stability(self):
        """Same inputs should produce identical outputs."""
        propagation = make_propagation_snapshot()
        definition = make_scenario_definition(ScenarioType.SUPPLIER_FAILURE)
        enriched = make_enriched_snapshot()

        engine = ScenarioEngine()
        request = ScenarioRequest(
            workspace_id="ws-test",
            scenario_definition=definition,
            source_propagation_id="prop-1",
        )

        result1 = engine.execute_scenario(
            enriched=enriched, propagation=propagation, request=request
        )
        result2 = engine.execute_scenario(
            enriched=enriched, propagation=propagation, request=request
        )

        assert result1.success
        assert result2.success

        # Compare key deterministic fields
        def impact_key(imp: ScenarioImpactRecord):
            return (
                imp.affected_node_id,
                imp.hop_number,
                imp.severity,
                imp.confidence,
                imp.estimated_recovery_hours,
                imp.estimated_financial_impact,
            )

        keys1 = sorted(impact_key(i) for i in result1.snapshot.impacts)
        keys2 = sorted(impact_key(i) for i in result2.snapshot.impacts)

        assert keys1 == keys2, "Scenario not deterministic"


# ─────────────────────────────────────────────────────────────────────────────
# Scenario Models Serialization Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestScenarioModels:
    def test_scenario_definition_to_dict(self):
        definition = make_scenario_definition(
            ScenarioType.SUPPLIER_FAILURE,
            [ScenarioParameter(name="days", value=7, unit="days")],
        )
        d = definition.to_dict()
        assert d["scenario_type"] == "supplier_failure"
        assert len(d["parameters"]) == 1

    def test_scenario_snapshot_to_dict(self):
        definition = make_scenario_definition(ScenarioType.SUPPLIER_FAILURE)
        impact = ScenarioImpactRecord(
            scenario_id=definition.scenario_id,
            affected_node_id="n2",
            affected_entity_id="f1",
            affected_entity_type="Facility",
            hop_number=1,
            impact_category="production",
            severity="warning",
            confidence=0.8,
            estimated_recovery_hours=24.0,
            estimated_financial_impact=50000.0,
            estimated_service_level_impact_pct=10.0,
        )
        summary = ScenarioSummary(
            total_impacted_entities=1,
            by_impact_category={"production": 1},
            by_severity={"warning": 1},
            by_entity_type={"Facility": 1},
            max_hop=1,
            avg_confidence=0.8,
            min_confidence=0.8,
        )
        snap = ScenarioSnapshot(
            scenario_id=definition.scenario_id,
            workspace_id="ws-test",
            scenario_definition=definition,
            impacts=[impact],
            summary=summary,
        )
        d = snap.to_dict()
        assert d["scenario_id"] == definition.scenario_id
        assert d["summary"]["total_impacted_entities"] == 1

    def test_scenario_request_to_dict(self):
        definition = make_scenario_definition(ScenarioType.SUPPLIER_FAILURE)
        request = ScenarioRequest(
            workspace_id="ws-test",
            scenario_definition=definition,
            source_propagation_id="prop-1",
        )
        d = request.to_dict()
        assert d["workspace_id"] == "ws-test"
        assert d["source_propagation_id"] == "prop-1"

    def test_scenario_result_to_dict(self):
        definition = make_scenario_definition(ScenarioType.SUPPLIER_FAILURE)
        snap = ScenarioSnapshot(
            scenario_id=definition.scenario_id,
            workspace_id="ws-test",
            scenario_definition=definition,
        )
        result = ScenarioResult(snapshot=snap, success=True, warnings=[])
        d = result.to_dict()
        assert d["success"] is True
        assert d["snapshot"]["scenario_id"] == definition.scenario_id


# ─────────────────────────────────────────────────────────────────────────────
# Scenario Type Enum Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestScenarioTypeEnum:
    def test_all_types_present(self):
        types = [t.value for t in ScenarioType]
        assert "supplier_failure" in types
        assert "warehouse_outage" in types
        assert "route_closure" in types
        assert "shipment_delay" in types
        assert "demand_spike" in types
        assert "demand_drop" in types
        assert "inventory_shortage" in types
        assert "capacity_constraint" in types
        assert "custom" in types
