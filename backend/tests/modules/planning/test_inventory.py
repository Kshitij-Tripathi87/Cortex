from datetime import date
from decimal import Decimal

from app.modules.planning.inventory import project_inventory
from app.modules.planning.models import (
    DemandContribution,
    InventoryBalanceInput,
    MaterialReceipt,
    ProjectionStatus,
    QuantityBasis,
)


def _balance(**overrides):
    values = dict(
        workspace_id="ws-1",
        snapshot_id="snap-1",
        facility_id="plant-1",
        material_id="C-01",
        as_of=date(2026, 11, 4),
        quantity=Decimal("100"),
        quantity_basis=QuantityBasis.PHYSICAL_ON_HAND,
        safety_stock_quantity=Decimal("25"),
        reserved_quantity=Decimal("20"),
        blocked_quantity=Decimal("5"),
        uom="EA",
        source_refs=("source:inventory:row:2",),
    )
    values.update(overrides)
    return InventoryBalanceInput(**values)


def _demand(qty, day, *, reserved="0", linked=False, ref="REQ-1"):
    gross = Decimal(qty)
    return DemandContribution(
        contribution_id=ref,
        production_order_id="MO-001",
        facility_id="plant-1",
        material_id="C-01",
        gross_quantity=gross,
        reserved_quantity=Decimal(reserved),
        reservation_linked=linked,
        uncovered_quantity=gross - Decimal(reserved),
        uom="EA",
        need_at=date(2026, 11, day),
    )


def test_hand_calculated_projection_reservations_are_netted_once():
    # Opening usable = 100 - 20 reserved - 5 blocked = 75.
    # Gross demand 60 includes 20 reserved; uncovered demand = 40.
    result = project_inventory(
        _balance(),
        (),
        (_demand("60", 10, reserved="20", linked=True),),
        start_date=date(2026, 11, 4),
        end_date=date(2026, 11, 12),
    )
    assert result.status == ProjectionStatus.COMPLETED
    assert result.opening_usable_quantity == Decimal("75")
    assert result.uncovered_requirement_quantity == Decimal("40")
    assert result.daily_buckets[-1].closing_quantity == Decimal("35")
    assert result.first_safety_stock_breach is None
    assert result.first_negative_balance is None


def test_confirmed_receipt_uses_open_quantity_not_ordered_quantity():
    receipt = MaterialReceipt(
        receipt_id="PO-1-1", facility_id="plant-1", material_id="C-01",
        ordered_quantity=Decimal("100"), received_quantity=Decimal("70"),
        open_quantity=Decimal("30"), expected_date=date(2026, 11, 7),
        status="partially_received", confirmed=True, uom="EA",
    )
    result = project_inventory(
        _balance(),
        (receipt,),
        (_demand("80", 8, ref="REQ-2"),),
        start_date=date(2026, 11, 4),
        end_date=date(2026, 11, 10),
    )
    assert result.daily_buckets[3].confirmed_receipts == Decimal("30")
    assert result.daily_buckets[4].closing_quantity == Decimal("25")


def test_unconfirmed_receipt_is_excluded_from_base_projection():
    receipt = MaterialReceipt(
        "PO-1-2", "plant-1", "C-01", Decimal("50"), Decimal("0"),
        date(2026, 11, 6), "open", False, "EA",
    )
    result = project_inventory(
        _balance(), (receipt,), (),
        start_date=date(2026, 11, 4), end_date=date(2026, 11, 8),
    )
    assert result.uncertain_receipts_excluded == Decimal("50")
    assert result.daily_buckets[2].closing_quantity == Decimal("75")
    assert result.status == ProjectionStatus.DEGRADED


def test_safety_stock_breach_and_negative_balance_are_distinct():
    result = project_inventory(
        _balance(safety_stock_quantity=Decimal("50")),
        (),
        (_demand("80", 5),),
        start_date=date(2026, 11, 4), end_date=date(2026, 11, 6),
    )
    assert result.first_safety_stock_breach == date(2026, 11, 5)
    assert result.first_negative_balance == date(2026, 11, 5)
    assert result.daily_buckets[1].closing_quantity == Decimal("-5")


def test_no_crossing_in_horizon_returns_none():
    result = project_inventory(
        _balance(), (), (),
        start_date=date(2026, 11, 4), end_date=date(2026, 11, 7),
    )
    assert result.first_safety_stock_breach is None
    assert result.first_negative_balance is None


def test_unknown_inventory_basis_semantics_is_not_calculable():
    result = project_inventory(
        _balance(
            quantity_basis=QuantityBasis.AVAILABLE_TO_USE,
            reserved_quantity=None,
            blocked_quantity=None,
            basis_excludes_reserved=None,
            basis_excludes_blocked=None,
        ),
        (),
        (),
        start_date=date(2026, 11, 4), end_date=date(2026, 11, 8),
    )
    assert result.status == ProjectionStatus.NOT_CALCULABLE
    assert any("INVENTORY_BASIS_SEMANTICS_UNKNOWN" in x for x in result.warnings)


def test_unlinked_reservation_blocks_precise_projection():
    demand = _demand("30", 5, reserved="10", linked=False, ref="REQ-UNLINKED")
    result = project_inventory(
        _balance(), (), (demand,),
        start_date=date(2026, 11, 4), end_date=date(2026, 11, 8),
    )
    assert result.status == ProjectionStatus.NOT_CALCULABLE
    assert any("UNLINKED_RESERVATION" in x for x in result.warnings)


def test_facility_balances_are_not_pooled():
    other_facility = MaterialReceipt(
        "PO-OTHER", "plant-2", "C-01", Decimal("100"), Decimal("0"),
        date(2026, 11, 5), "confirmed", True, "EA",
    )
    result = project_inventory(
        _balance(), (other_facility,), (),
        start_date=date(2026, 11, 4), end_date=date(2026, 11, 6),
    )
    assert result.daily_buckets[1].confirmed_receipts == Decimal("0")


def test_negative_reservation_or_blocked_bucket_is_rejected_for_any_quantity_basis():
    result = project_inventory(
        _balance(
            quantity_basis=QuantityBasis.AVAILABLE_TO_USE,
            reserved_quantity=Decimal("-1"),
            blocked_quantity=Decimal("0"),
            basis_excludes_reserved=False,
            basis_excludes_blocked=True,
        ),
        (),
        (),
        start_date=date(2026, 11, 4),
        end_date=date(2026, 11, 5),
    )
    assert result.status == ProjectionStatus.NOT_CALCULABLE
    assert any("RESERVED_QUANTITY_NEGATIVE" in warning for warning in result.warnings)


def test_receipt_open_quantity_cannot_exceed_unreceived_order_quantity():
    receipt = MaterialReceipt(
        "PO-OVER", "plant-1", "C-01", Decimal("100"), Decimal("70"),
        date(2026, 11, 6), "open", True, "EA", open_quantity=Decimal("40"),
    )
    result = project_inventory(
        _balance(),
        (receipt,),
        (),
        start_date=date(2026, 11, 4),
        end_date=date(2026, 11, 8),
    )
    assert result.status == ProjectionStatus.NOT_CALCULABLE
    assert any(
        "RECEIPT_OPEN_QUANTITY_EXCEEDS_REMAINDER" in warning
        for warning in result.warnings
    )


def test_confirmed_receipt_uom_conversion_is_explicit():
    from app.modules.planning.models import UOMConverter

    receipt = MaterialReceipt(
        "PO-KG", "plant-1", "C-01", Decimal("1"), Decimal("0"),
        date(2026, 11, 5), "confirmed", True, "KG",
    )
    result = project_inventory(
        _balance(),
        (receipt,),
        (),
        start_date=date(2026, 11, 4),
        end_date=date(2026, 11, 6),
        uom_converter=UOMConverter({("KG", "EA"): Decimal("10")}),
    )
    assert result.daily_buckets[1].confirmed_receipts == Decimal("10")


def test_projection_must_start_on_inventory_snapshot_date():
    import pytest

    from app.modules.planning.inventory import InventoryProjectionError

    with pytest.raises(
        InventoryProjectionError,
        match="PROJECTION_START_MUST_MATCH_SNAPSHOT_AS_OF",
    ):
        project_inventory(
            _balance(),
            (),
            (),
            start_date=date(2026, 11, 5),
            end_date=date(2026, 11, 8),
        )
