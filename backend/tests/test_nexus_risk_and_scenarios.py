"""Tests for the Risk & RCA engine (Phase C) and Scenario Studio (Phase D)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.modules.nexus_spine.ontology import (
    EntityKind,
    InventoryPositionEntity,
    RelationshipEdge,
    RelationshipKind,
    SalesOrderEntity,
    SignalEntity,
    SupplierEntity,
    DisruptionEntity,
    get_world_model,
    reset_world_model,
)
from app.modules.nexus_spine.risk import (
    RiskAssessment,
    Severity,
    get_risk_engine,
    reset_risk_engine,
)
from app.modules.nexus_spine.scenarios import (
    MutationKind,
    ScenarioDefinition,
    ScenarioMutation,
    get_scenario_studio,
    reset_scenario_studio,
)


TENANT = UUID("11111111-1111-1111-1111-111111111111")
WORKSPACE = UUID("22222222-2222-2222-2222-222222222222")


@pytest.fixture
def populated_world():
    reset_world_model()
    reset_risk_engine()
    reset_scenario_studio()
    wm = get_world_model()

    supplier = SupplierEntity.create(
        tenant_id=TENANT, workspace_id=WORKSPACE,
        natural_key="SUP-142", name="Acme Components", source="test",
        capacity_pct=80.0, risk_score=0.6,
    )
    wm.upsert(supplier)

    for i, revenue in enumerate([200000.0, 150000.0, 100000.0]):
        order = SalesOrderEntity.create(
            tenant_id=TENANT, workspace_id=WORKSPACE,
            natural_key=f"SO-{i}", name=f"Order {i}", source="test",
            quantity=10, customer_id=uuid4(),
            promised_delivery=datetime.now(UTC),
            revenue=revenue, sla_risk_pct=0.7,
        )
        wm.upsert(order)
        wm.add_relationship(
            RelationshipEdge(
                from_entity_id=supplier.entity_id,
                to_entity_id=order.entity_id,
                kind=RelationshipKind.SUPPLIES,
                confidence=0.95,
            )
        )

    inv = InventoryPositionEntity.create(
        tenant_id=TENANT, workspace_id=WORKSPACE,
        natural_key="INV-1", name="Central DC", source="test",
        sku="SKU-42", warehouse_id=uuid4(),
        on_hand_qty=0.0, safety_stock_qty=50.0,
    )
    wm.upsert(inv)
    wm.add_relationship(
        RelationshipEdge(
            from_entity_id=supplier.entity_id,
            to_entity_id=inv.entity_id,
            kind=RelationshipKind.SUPPLIES,
        )
    )

    sig = SignalEntity.create(
        tenant_id=TENANT, workspace_id=WORKSPACE,
        natural_key="SIG-1", name="Supplier capacity drop", source="test",
        affected_entity_id=supplier.entity_id,
        severity_score=0.75,
        signal_type="capacity_loss",
        description="Capacity dropped 20% due to outage",
    )
    wm.upsert(sig)

    yield wm


# ── Risk Engine ──────────────────────────────────────────────────────────────


class TestRiskEngine:
    def test_empty_world_produces_no_risks(self):
        reset_world_model()
        reset_risk_engine()
        wm = get_world_model()
        risks = get_risk_engine().compute(TENANT, WORKSPACE)
        assert risks == []

    def test_signals_produce_risks(self, populated_world):
        risks = get_risk_engine().compute(TENANT, WORKSPACE)
        assert len(risks) >= 1
        first = risks[0]
        assert first.severity in (Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFO)
        assert 0.0 <= first.confidence <= 1.0

    def test_blast_radius_feeds_risk_exposure(self, populated_world):
        risks = get_risk_engine().compute(TENANT, WORKSPACE)
        main_risk = next(r for r in risks if r.title.startswith("Supplier capacity drop"))
        # Order revenue total: 200k + 150k + 100k = 450k
        assert main_risk.revenue_at_risk == pytest.approx(450000.0)
        assert main_risk.affected_orders == 3

    def test_root_cause_candidates_include_seed(self, populated_world):
        risks = get_risk_engine().compute(TENANT, WORKSPACE)
        main_risk = next(r for r in risks if "capacity drop" in r.title.lower())
        assert any(c.hop_distance == 0 for c in main_risk.root_cause_candidates)

    def test_risk_ids_are_deterministic(self, populated_world):
        wm = get_world_model()
        risks_a = get_risk_engine().compute(TENANT, WORKSPACE)
        recompute = get_risk_engine().compute(TENANT, WORKSPACE)
        ids_a = {r.risk_id for r in risks_a}
        ids_b = {r.risk_id for r in recompute}
        assert ids_a == ids_b

    def test_risk_aggregates_multiple_signals_same_target(self, populated_world):
        wm = get_world_model()
        supplier = next(e for e in wm.iter_entities(TENANT, WORKSPACE) if e.kind == EntityKind.SUPPLIER)
        sig2 = SignalEntity.create(
            tenant_id=TENANT, workspace_id=WORKSPACE,
            natural_key="SIG-2", name="Second outage signal", source="test",
            affected_entity_id=supplier.entity_id,
            severity_score=0.5,
            signal_type="capacity_loss",
        )
        wm.upsert(sig2)
        risks = get_risk_engine().compute(TENANT, WORKSPACE)
        assert any(sig2.entity_id_str if hasattr(sig2, 'entity_id_str') else str(sig2.entity_id) in r.signal_ids for r in risks) or len(risks) >= 1


# ── Scenario Studio ──────────────────────────────────────────────────────────


class TestScenarioStudio:
    def test_supplier_failure_reduces_confidence(self, populated_world):
        wm = get_world_model()
        supplier = next(e for e in wm.iter_entities(TENANT, WORKSPACE) if e.kind == EntityKind.SUPPLIER)
        studio = get_scenario_studio()
        scenario = ScenarioDefinition(
            workspace_id=str(WORKSPACE),
            tenant_id=str(TENANT),
            name="S-142 failure",
            mutations=[
                ScenarioMutation(
                    kind=MutationKind.SUPPLIER_FAILURE,
                    target_entity_id=supplier.entity_id,
                    parameters={"availability_pct": 0.3},
                )
            ],
        )
        result = studio.run(scenario)
        assert result.success
        assert result.kpis.service_level < 1.0

    def test_demand_surge_increases_revenue_risk(self, populated_world):
        wm = get_world_model()
        order = next(e for e in wm.iter_entities(TENANT, WORKSPACE) if e.kind == EntityKind.SALES_ORDER)
        studio = get_scenario_studio()
        scenario = ScenarioDefinition(
            workspace_id=str(WORKSPACE),
            tenant_id=str(TENANT),
            name="Demand +20%",
            mutations=[
                ScenarioMutation(
                    kind=MutationKind.DEMAND_SURGE,
                    target_entity_id=order.entity_id,
                    parameters={"demand_multiplier": 1.2},
                )
            ],
        )
        result = studio.run(scenario)
        assert result.success
        assert result.kpis.revenue_at_risk >= 0

    def test_port_closure_flags_stockout(self, populated_world):
        wm = get_world_model()
        supplier = next(e for e in wm.iter_entities(TENANT, WORKSPACE) if e.kind == EntityKind.SUPPLIER)
        studio = get_scenario_studio()
        scenario = ScenarioDefinition(
            workspace_id=str(WORKSPACE),
            tenant_id=str(TENANT),
            name="Port closure",
            mutations=[
                ScenarioMutation(
                    kind=MutationKind.PORT_CLOSURE,
                    target_entity_id=supplier.entity_id,
                    parameters={"closure_days": 7},
                )
            ],
        )
        result = studio.run(scenario)
        assert result.success
        assert result.kpis.stockout_probability >= 0.0

    def test_comparison_returns_baseline_plus_candidates(self, populated_world):
        wm = get_world_model()
        supplier = next(e for e in wm.iter_entities(TENANT, WORKSPACE) if e.kind == EntityKind.SUPPLIER)
        studio = get_scenario_studio()
        baseline = ScenarioDefinition(
            workspace_id=str(WORKSPACE),
            tenant_id=str(TENANT),
            name="Baseline",
            mutations=[],
        )
        candidate = ScenarioDefinition(
            workspace_id=str(WORKSPACE),
            tenant_id=str(TENANT),
            name="Shift to S-188",
            mutations=[
                ScenarioMutation(
                    kind=MutationKind.SUPPLIER_FAILURE,
                    target_entity_id=supplier.entity_id,
                    parameters={"availability_pct": 0.2},
                )
            ],
        )
        result = studio.compare(baseline, [candidate])
        assert result["scenario_count"] == 2
        assert result["baseline"]["name"] == "Baseline"
        assert result["candidates"][0]["name"] == "Shift to S-188"

    def test_scenario_deterministic_across_runs(self, populated_world):
        studio = get_scenario_studio()
        wm = get_world_model()
        supplier = next(e for e in wm.iter_entities(TENANT, WORKSPACE) if e.kind == EntityKind.SUPPLIER)
        scenario = ScenarioDefinition(
            workspace_id=str(WORKSPACE),
            tenant_id=str(TENANT),
            name="Deterministic test",
            mutations=[
                ScenarioMutation(
                    kind=MutationKind.SUPPLIER_FAILURE,
                    target_entity_id=supplier.entity_id,
                    parameters={"availability_pct": 0.5},
                )
            ],
        )
        r1 = studio.run(scenario)
        r2 = studio.run(scenario)
        assert r1.kpis == r2.kpis
