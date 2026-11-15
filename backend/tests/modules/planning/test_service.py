from datetime import date
from decimal import Decimal

import pytest

from app.modules.planning.models import (
    BOMLine,
    BOMRevision,
    InventoryBalanceInput,
    ItemType,
    ProductionOrder,
    ProjectionStatus,
    QuantityBasis,
)
from app.modules.planning.service import PlanningSnapshot, run_material_plan


def _snapshot():
    as_of = date(2026, 11, 4)
    order = ProductionOrder(
        order_id="MO-001",
        facility_id="PLANT-1",
        item_id="P-100",
        item_type=ItemType.PRODUCT,
        quantity=Decimal("10"),
        order_uom="EA",
        item_base_uom="EA",
        material_need_at=date(2026, 11, 6),
        status="released",
        bom_revision_id="REV-1",
    )
    revision = BOMRevision(
        revision_id="REV-1",
        parent_item_id="P-100",
        parent_item_type=ItemType.PRODUCT,
        revision_code="A",
        lines=(
            BOMLine(
                line_id="LINE-1",
                child_item_id="C-01",
                child_item_type=ItemType.COMPONENT,
                usage_quantity=Decimal("6"),
                usage_uom="EA",
                child_base_uom="EA",
            ),
        ),
    )
    balance = InventoryBalanceInput(
        workspace_id="WS-1",
        snapshot_id="SNAP-1",
        facility_id="PLANT-1",
        material_id="C-01",
        as_of=as_of,
        quantity=Decimal("100"),
        quantity_basis=QuantityBasis.PHYSICAL_ON_HAND,
        safety_stock_quantity=Decimal("20"),
        reserved_quantity=Decimal("0"),
        blocked_quantity=Decimal("0"),
        uom="EA",
    )
    return PlanningSnapshot(
        workspace_id="WS-1",
        snapshot_id="SNAP-1",
        as_of=as_of,
        bom_revisions=(revision,),
        production_orders=(order,),
        inventory_balances=(balance,),
    )


def test_snapshot_run_produces_expected_quantity_and_stable_hash():
    snapshot = _snapshot()
    kwargs = dict(start_date=date(2026, 11, 4), end_date=date(2026, 11, 8))
    first = run_material_plan(snapshot, **kwargs)
    second = run_material_plan(snapshot, **kwargs)

    assert first.status == ProjectionStatus.COMPLETED
    assert first.order_results[0].contributions[0].gross_quantity == Decimal("60")
    assert first.inventory_projections[0].daily_buckets[2].closing_quantity == Decimal("40")
    assert first.result_sha256 == second.result_sha256


def test_snapshot_mismatch_is_rejected_before_calculation():
    snapshot = _snapshot()
    bad_balance = InventoryBalanceInput(
        workspace_id="WS-1",
        snapshot_id="SNAP-OLD",
        facility_id="PLANT-1",
        material_id="C-01",
        as_of=date(2026, 11, 4),
        quantity=Decimal("100"),
        quantity_basis=QuantityBasis.PHYSICAL_ON_HAND,
        safety_stock_quantity=Decimal("10"),
        reserved_quantity=Decimal("0"),
        blocked_quantity=Decimal("0"),
    )
    bad_snapshot = PlanningSnapshot(
        workspace_id=snapshot.workspace_id,
        snapshot_id=snapshot.snapshot_id,
        as_of=snapshot.as_of,
        bom_revisions=snapshot.bom_revisions,
        production_orders=snapshot.production_orders,
        inventory_balances=(bad_balance,),
    )
    with pytest.raises(ValueError, match="SNAPSHOT_BOUNDARY_MISMATCH"):
        run_material_plan(
            bad_snapshot, start_date=date(2026, 11, 4), end_date=date(2026, 11, 5)
        )


def test_missing_inventory_balance_is_not_fabricated():
    snapshot = _snapshot()
    missing = PlanningSnapshot(
        workspace_id=snapshot.workspace_id,
        snapshot_id=snapshot.snapshot_id,
        as_of=snapshot.as_of,
        bom_revisions=snapshot.bom_revisions,
        production_orders=snapshot.production_orders,
        inventory_balances=(),
    )
    result = run_material_plan(
        missing, start_date=date(2026, 11, 4), end_date=date(2026, 11, 8)
    )
    assert result.status == ProjectionStatus.NOT_CALCULABLE
    assert "INVENTORY_SNAPSHOT_MISSING" in result.warnings
