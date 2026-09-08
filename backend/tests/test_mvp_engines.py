"""Tests for disruption engines + Morning Brief orchestrator.

Covers: propagation, business impact, confidence, recommendations, timeline,
         orchestrator, determinism, and deferred-import guard.
All tests are pure-Python — no DB, no async, no network.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from app.modules.disruption.engines.brief import run_morning_brief
from app.modules.disruption.engines.confidence import compute_confidence
from app.modules.disruption.engines.impact import compute_business_impact
from app.modules.disruption.engines.propagation import propagate
from app.modules.disruption.engines.recommendations import recommend
from app.modules.disruption.engines.timeline import build_timeline
from app.modules.disruption.engines.types import (
    BomData,
    ComponentData,
    DisruptionKind,
    DisruptionScenario,
    EdgeData,
    InventoryData,
    ProductData,
    PropagationResult,
    SupplierData,
    SupplyChainSnapshot,
    WarehouseData,
)

WS = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
SID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
C1 = UUID("c0000000-0000-0000-0000-000000000001")
W1 = UUID("d0000000-0000-0000-0000-000000000001")
P1 = UUID("f0000000-0000-0000-0000-000000000001")
CU1 = UUID("00000000-1111-0000-0000-000000000001")
O1 = UUID("00000000-2222-0000-0000-000000000001")

NOW = datetime(2026, 8, 1, 8, 0, 0, tzinfo=UTC)


def _supp() -> SupplierData:
    return SupplierData(id=SID, name="Acme", country="US", tier="tier_1", lead_time_days=14)


def _comp(cid=C1) -> ComponentData:
    return ComponentData(id=cid, sku="SKU", name="Widget", category=None, unit_of_measure="EA")


def _prod() -> ProductData:
    return ProductData(
        id=P1,
        sku="SKU-P",
        name="Product A",
        factory_id=None,
        unit_price=80.0,
        margin_pct=0.30,
        lead_time_days=7,
    )


def _snap(**kw) -> SupplyChainSnapshot:
    d = {
        "workspace_id": WS,
        "as_of": NOW,
        "suppliers": (),
        "components": (),
        "products": (),
        "edges": (),
        "warehouses": (),
        "factories": (),
        "inventory": (),
        "bom": (),
        "orders": (),
        "customers": (),
    }
    d.update(kw)
    return SupplyChainSnapshot(**d)


def _scenario() -> DisruptionScenario:
    return DisruptionScenario(
        workspace_id=WS,
        supplier_id=SID,
        kind=DisruptionKind.FAILURE,
        severity="critical",
        started_at=NOW,
        delay_hours=0,
    )


def _pr(**ov) -> PropagationResult:
    a = {
        "source_supplier_id": SID,
        "affected_components": (),
        "affected_products": (),
        "affected_warehouses": (),
        "open_orders_at_risk": (),
        "max_hop": 0,
        "traversed_edge_types": (),
    }
    a.update(ov)
    return PropagationResult(**a)


class TestPropagation:
    def test_empty(self):
        r = propagate(_snap(suppliers=[_supp()]), SID)
        assert len(r.affected_components) == 0

    def test_component_found(self):
        e = EdgeData("supplier", SID, "component", C1, "supplies")
        r = propagate(_snap(suppliers=[_supp()], components=[_comp()], edges=[e]), SID)
        assert len(r.affected_components) == 1

    def test_warehouse(self):
        wh = WarehouseData(id=W1, code="WH", name="W")
        inv = InventoryData(
            warehouse_id=W1,
            component_id=C1,
            quantity=100,
            safety_stock=20,
            daily_usage=5,
            last_updated_at=NOW,
        )
        ed_s = EdgeData("supplier", SID, "component", C1, "supplies")
        ed_w = EdgeData("component", C1, "warehouse", W1, "stored_in")
        r = propagate(
            _snap(
                suppliers=[_supp()],
                components=[_comp()],
                warehouses=[wh],
                inventory=[inv],
                edges=[ed_s, ed_w],
            ),
            SID,
        )
        assert len(r.affected_warehouses) == 1

    def test_bom_product(self):
        e = EdgeData("supplier", SID, "component", C1, "supplies")
        b = BomData(P1, C1, 1.0)
        result = propagate(
            _snap(
                suppliers=[_supp()], components=[_comp()], products=[_prod()], edges=[e], bom=[b]
            ),
            SID,
        )
        assert any(p.product_id == P1 for p in result.affected_products)


class TestImpact:
    def test_zero(self):
        biz = compute_business_impact(_snap(), _pr())
        assert biz.overall_score == 0.0


class TestConfidence:
    def test_bounds(self):
        c = compute_confidence(_snap(), _pr())
        assert 0 <= c.overall <= 1


class TestRecommend:
    def test_five(self):
        biz = compute_business_impact(_snap(), _pr())
        recs = recommend(_pr(), biz)
        assert len(recs.recommendations) == 5


class TestTimeline:
    def test_five(self):
        tl = build_timeline(_pr(), _scenario())
        assert len(tl.events) == 5


class TestOrchestrator:
    def test_e2e(self):
        brief = run_morning_brief(_snap(suppliers=[_supp()]), _scenario())
        assert brief.business_impact.overall_score >= 0


class TestBacktest:
    def test_supplier_delay_scenario_runs(self):
        """Verify the backtest scenario produces valid predictions against ground truth."""
        from datetime import datetime
        from uuid import UUID

        from app.modules.disruption.engines.backtest import BacktestEvent, run_backtest
        from app.modules.disruption.scenarios.supplier_delay import build

        snapshot, scenario, labels = build()
        now = datetime(2026, 3, 15, 8, 1, 0)
        event = BacktestEvent(
            event_id=UUID("eeeeeee1-0000-0000-0000-000000000001"),
            workspace_id=snapshot.workspace_id,
            snapshot=snapshot,
            scenario=scenario,
            actual_labels=labels,
        )
        report = run_backtest(
            workspace_id=snapshot.workspace_id,
            events=[event],
            started_at=now,
            ended_at=now,
        )
        assert report.event_count == 1
        assert report.total_predictions > 0
        assert 0.0 <= report.accuracy <= 1.0
        assert 0.0 <= report.f1 <= 1.0
        assert len(report.events) == 1
        assert report.events[0].true_positives > 0

    def test_supplier_delay_backtest_is_deterministic(self):
        """Two runs with identical data produce the same backtest report."""
        from datetime import datetime
        from uuid import UUID

        from app.modules.disruption.engines.backtest import BacktestEvent, run_backtest
        from app.modules.disruption.scenarios.supplier_delay import build

        s1, sc1, l1 = build()
        s2, sc2, l2 = build()
        now = datetime(2026, 3, 15, 8, 1, 0)
        r1 = run_backtest(
            workspace_id=s1.workspace_id,
            events=[
                BacktestEvent(
                    event_id=UUID("eeeeeee1-0000-0000-0000-000000000001"),
                    workspace_id=s1.workspace_id,
                    snapshot=s1,
                    scenario=sc1,
                    actual_labels=l1,
                )
            ],
            started_at=now,
            ended_at=now,
        )
        r2 = run_backtest(
            workspace_id=s2.workspace_id,
            events=[
                BacktestEvent(
                    event_id=UUID("eeeeeee1-0000-0000-0000-000000000001"),
                    workspace_id=s2.workspace_id,
                    snapshot=s2,
                    scenario=sc2,
                    actual_labels=l2,
                )
            ],
            started_at=now,
            ended_at=now,
        )
        assert r1.accuracy == r2.accuracy
        assert r1.precision == r2.precision
        assert r1.recall == r2.recall
        assert r1.f1 == r2.f1
