"""Supplier Delay backtest scenario — a Tier-1 supplier 5-day delay.

This is the MVP wedge validation scenario. It constructs a realistic supply chain
snapshot with 2 suppliers, 4 components, 2 products, 1 warehouse, 2 customers,
5 open orders, and a single disruption event (Acme Supplier delayed by 5 days).
Ground-truth labels are embedded: we know which components, products, orders,
and warehouses are affected.

Call ``build()`` to get the canonical snapshot + disruption scenario +
ground-truth labels. Deterministic: no RNG, no IO, same output every call.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from app.modules.disruption.engines.backtest import BacktestLabels
from app.modules.disruption.engines.types import (
    BomData,
    ComponentData,
    CustomerData,
    DisruptionKind,
    DisruptionScenario,
    EdgeData,
    InventoryData,
    OrderData,
    ProductData,
    SupplierData,
    SupplyChainSnapshot,
    WarehouseData,
)

WS = UUID("55555555-5555-5555-5555-555555555555")
T0 = datetime(2026, 3, 15, 8, 0, 0, tzinfo=UTC)

# ── Entities ──
S_ACME = UUID("aaaaaaa1-0000-0000-0000-000000000001")
S_BEACON = UUID("aaaaaaa2-0000-0000-0000-000000000002")

C_PCB = UUID("ccccccc1-0000-0000-0000-000000000001")
C_SENSOR = UUID("ccccccc2-0000-0000-0000-000000000002")

W_MAIN = UUID("ddddddd1-0000-0000-0000-000000000001")

P_CONTROLLER = UUID("fffffff1-0000-0000-0000-000000000001")
P_BOARD = UUID("fffffff2-0000-0000-0000-000000000002")

CU_AUTOMOTIVE = UUID("a0000001-0000-0000-0000-000000000001")
CU_INDUSTRIAL = UUID("a0000002-0000-0000-0000-000000000002")

O1 = UUID("b0000001-0000-0000-0000-000000000001")
O2 = UUID("b0000002-0000-0000-0000-000000000002")
O3 = UUID("b0000003-0000-0000-0000-000000000003")
O4 = UUID("b0000004-0000-0000-0000-000000000004")
O5 = UUID("b0000005-0000-0000-0000-000000000005")

ORDER_DATE_OFFSET = date(2026, 2, 1)


def build() -> tuple[SupplyChainSnapshot, DisruptionScenario, BacktestLabels]:
    """Return the supplier_delay scenario with known outcomes.

    The snapshot is point-in-time (March 15, 2026, 08:00 UTC). Acme
    (S_ACME) delays by 5 days (120hrs) with partial recovery.

    Ground truth: when Acme delays:
        * C_PCB and C_SENSOR are affected (Acme supplies both)
        * P_CONTROLLER and P_BOARD are affected (both consume PCB/Sensor)
        * W_MAIN is affected (holds PCB inventory)
        * Orders O1..O4 are at risk (pending/confirmed orders on affected
          products)
        * O5 (on P_BOARD with customer CU_INDUSTRIAL) is not in open_status
          statuses (delivered), so it doesn't appear in open_orders_at_risk
    """

    suppliers = (
        SupplierData(
            id=S_ACME, name="Acme Electronics", country="TW", tier="tier_1", lead_time_days=14
        ),
        SupplierData(
            id=S_BEACON, name="Beacon Supply", country="US", tier="tier_2", lead_time_days=7
        ),
    )

    components = (
        ComponentData(
            id=C_PCB, sku="PCB-001", name="Control Board PCB", category="PCB", unit_of_measure="EA"
        ),
        ComponentData(
            id=C_SENSOR,
            sku="SNS-002",
            name="Temperature Sensor",
            category="Sensor",
            unit_of_measure="EA",
        ),
    )

    products = (
        ProductData(
            id=P_CONTROLLER,
            sku="CONTR-1",
            name="Motor Controller V2",
            factory_id=None,
            unit_price=2500.0,
            margin_pct=0.35,
            lead_time_days=7,
        ),
        ProductData(
            id=P_BOARD,
            sku="BOARD-3",
            name="I/O Interface Board",
            factory_id=None,
            unit_price=800.0,
            margin_pct=0.25,
            lead_time_days=5,
        ),
    )

    warehouse = WarehouseData(id=W_MAIN, code="WH-01", name="Main Warehouse")

    customers = (
        CustomerData(
            id=CU_AUTOMOTIVE,
            name="Automotive Systems Inc",
            country="DE",
            tier="gold",
            contract_value_annual=5000000.0,
            late_delivery_penalty_pct=0.03,
        ),
        CustomerData(
            id=CU_INDUSTRIAL,
            name="Industrial Motors LLC",
            country="US",
            tier="silver",
            contract_value_annual=2000000.0,
            late_delivery_penalty_pct=0.02,
        ),
    )

    edges = (
        EdgeData("supplier", S_ACME, "component", C_PCB, "supplies"),
        EdgeData("supplier", S_ACME, "component", C_SENSOR, "supplies"),
        EdgeData("supplier", S_BEACON, "component", C_PCB, "supplies"),
        EdgeData("component", C_PCB, "warehouse", W_MAIN, "stored_in"),
        EdgeData("component", C_SENSOR, "warehouse", W_MAIN, "stored_in"),
    )

    bom = (
        BomData(product_id=P_CONTROLLER, component_id=C_PCB, quantity_per_unit=1.0),
        BomData(product_id=P_CONTROLLER, component_id=C_SENSOR, quantity_per_unit=2.0),
        BomData(product_id=P_BOARD, component_id=C_PCB, quantity_per_unit=1.0),
        BomData(product_id=P_BOARD, component_id=C_SENSOR, quantity_per_unit=1.0),
    )

    inventory = (
        InventoryData(
            warehouse_id=W_MAIN,
            component_id=C_PCB,
            quantity=500,
            safety_stock=100,
            daily_usage=80,
            last_updated_at=T0,
        ),
        InventoryData(
            warehouse_id=W_MAIN,
            component_id=C_SENSOR,
            quantity=200,
            safety_stock=50,
            daily_usage=30,
            last_updated_at=T0,
        ),
    )

    orders = (
        OrderData(
            id=O1,
            customer_id=CU_AUTOMOTIVE,
            product_id=P_CONTROLLER,
            quantity=20,
            status="pending",
            order_date=ORDER_DATE_OFFSET,
            requested_delivery_date=date(2026, 3, 25),
            actual_delivery_date=None,
            unit_price=2500.0,
        ),
        OrderData(
            id=O2,
            customer_id=CU_AUTOMOTIVE,
            product_id=P_CONTROLLER,
            quantity=10,
            status="confirmed",
            order_date=ORDER_DATE_OFFSET,
            requested_delivery_date=date(2026, 3, 22),
            actual_delivery_date=None,
            unit_price=2500.0,
        ),
        OrderData(
            id=O3,
            customer_id=CU_INDUSTRIAL,
            product_id=P_CONTROLLER,
            quantity=15,
            status="pending",
            order_date=ORDER_DATE_OFFSET,
            requested_delivery_date=date(2026, 3, 30),
            actual_delivery_date=None,
            unit_price=2500.0,
        ),
        OrderData(
            id=O4,
            customer_id=CU_INDUSTRIAL,
            product_id=P_BOARD,
            quantity=30,
            status="in_production",
            order_date=ORDER_DATE_OFFSET,
            requested_delivery_date=date(2026, 3, 20),
            actual_delivery_date=None,
            unit_price=800.0,
        ),
        OrderData(
            id=O5,
            customer_id=CU_INDUSTRIAL,
            product_id=P_BOARD,
            quantity=5,
            status="delivered",
            order_date=(ORDER_DATE_OFFSET - timedelta(days=30)),
            requested_delivery_date=date(2026, 3, 1),
            actual_delivery_date=date(2026, 2, 28),
            unit_price=800.0,
        ),
    )

    snapshot = SupplyChainSnapshot(
        workspace_id=S_ACME,
        as_of=T0,
        suppliers=suppliers,
        components=components,
        warehouses=(warehouse,),
        factories=(),
        products=products,
        customers=customers,
        edges=edges,
        inventory=inventory,
        bom=bom,
        orders=orders,
    )

    scenario = DisruptionScenario(
        workspace_id=S_ACME,
        supplier_id=S_ACME,
        kind=DisruptionKind.DELAY,
        severity="high",
        started_at=T0,
        delay_hours=120.0,
        recovery_hours=48.0,
        description="Acme Electronics (tier_1) delayed by 5 days — PCB & Sensor supply disruption",
    )

    # Known outcomes: when Acme delays, PCB and Sensor are impacted.
    # Products: Controller and Board both consume PCB. Board also consumes Sensor.
    # Orders: O1, O2, O3 for controller are at risk; O4 for board is at risk.
    # Warehouse: WH-DMA holds PCB/Sensor and is affected.
    labels = BacktestLabels(
        affected_component_ids=(C_PCB, C_SENSOR),
        affected_product_ids=(P_CONTROLLER, P_BOARD),
        affected_order_ids=(O1, O2, O3, O4),
        affected_warehouse_ids=(W_MAIN,),
    )

    return snapshot, scenario, labels


__all__ = ["build"]
