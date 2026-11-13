"""Tests for deterministic BOM explosion and time-phased inventory planning."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.modules.supply_chain.planning import (
    BomLine,
    BomRevision,
    CalculationStatus,
    DemandContribution,
    ExplicitMaterialRequirement,
    InventoryBalance,
    PlanningInputError,
    ProductionOrder,
    QuantityBasis,
    ReservationAllocation,
    SupplyReceipt,
    UnitConversion,
    UnitConverter,
    explode_production_order,
    project_inventory,
    resolve_bom_revision,
)


def D(value: str) -> Decimal:
    return Decimal(value)


def revision(
    revision_id: str,
    parent: str,
    lines: tuple[BomLine, ...],
    *,
    facility: str | None = None,
    valid_from: date = date(2026, 1, 1),
    valid_to: date | None = None,
    parent_uom: str = "EA",
) -> BomRevision:
    return BomRevision(
        revision_id=revision_id,
        parent_item_id=parent,
        revision_code=revision_id,
        parent_base_uom=parent_uom,
        valid_from=valid_from,
        valid_to=valid_to,
        lines=lines,
        facility_id=facility,
    )


def production_order(
    *,
    quantity: str = "10",
    explicit: tuple[ExplicitMaterialRequirement, ...] | None = None,
    complete: bool = False,
    authoritative: bool = False,
) -> ProductionOrder:
    return ProductionOrder(
        production_order_id="PO-100",
        item_id="P-100",
        facility_id="PLANT-1",
        quantity=D(quantity),
        quantity_uom="EA",
        scheduled_date=date(2026, 11, 10),
        explicit_requirements=explicit,
        explicit_requirements_complete=complete,
        explicit_requirements_authoritative=authoritative,
    )


def test_multilevel_bom_explosion_multiplies_quantities_without_path_deduplication() -> None:
    revisions = (
        revision(
            "P-100-R1",
            "P-100",
            (
                BomLine("L-1", "A-10", D("2"), "EA", "EA"),
                BomLine("L-2", "B-20", D("1"), "EA", "EA"),
            ),
        ),
        revision("A-10-R1", "A-10", (BomLine("L-3", "C-01", D("3"), "EA", "EA"),)),
        revision("B-20-R1", "B-20", (BomLine("L-4", "C-01", D("4"), "EA", "EA"),)),
    )

    result = explode_production_order(
        production_order(),
        revisions,
        snapshot_id="SNAP-001",
        manufactured_item_ids={"P-100", "A-10", "B-20"},
        converter=UnitConverter(),
    )

    assert len(result.contributions) == 2
    assert [item.quantity for item in result.contributions] == [D("60"), D("40")]
    assert {item.material_id for item in result.contributions} == {"C-01"}
    assert len({item.bom_path for item in result.contributions}) == 2
    assert result.revision_ids == ("A-10-R1", "B-20-R1", "P-100-R1")


def test_bom_cycle_is_detected_using_current_ancestry() -> None:
    revisions = (
        revision("P-R1", "P-100", (BomLine("L1", "A-10", D("1"), "EA", "EA"),)),
        revision("A-R1", "A-10", (BomLine("L2", "P-100", D("1"), "EA", "EA"),)),
    )

    with pytest.raises(PlanningInputError, match="Cycle detected") as exc_info:
        explode_production_order(
            production_order(),
            revisions,
            snapshot_id="SNAP-001",
            manufactured_item_ids={"P-100", "A-10"},
            converter=UnitConverter(),
        )

    assert exc_info.value.code == "BOM_CYCLE"


def test_bom_revision_effectivity_uses_exclusive_valid_to() -> None:
    revisions = (
        revision(
            "OLD",
            "P-100",
            (BomLine("L1", "C-01", D("1"), "EA", "EA"),),
            valid_to=date(2026, 11, 10),
        ),
        revision(
            "NEW",
            "P-100",
            (BomLine("L2", "C-02", D("1"), "EA", "EA"),),
            valid_from=date(2026, 11, 10),
        ),
    )

    selected = resolve_bom_revision(
        revisions,
        parent_item_id="P-100",
        facility_id="PLANT-1",
        effective_date=date(2026, 11, 10),
    )

    assert selected.revision_id == "NEW"


def test_facility_specific_bom_takes_precedence_over_global_fallback() -> None:
    revisions = (
        revision("GLOBAL", "P-100", (BomLine("L1", "C-01", D("1"), "EA", "EA"),)),
        revision(
            "PLANT",
            "P-100",
            (BomLine("L2", "C-02", D("1"), "EA", "EA"),),
            facility="PLANT-1",
        ),
    )

    selected = resolve_bom_revision(
        revisions,
        parent_item_id="P-100",
        facility_id="PLANT-1",
        effective_date=date(2026, 11, 10),
    )

    assert selected.revision_id == "PLANT"


def test_overlapping_effective_revisions_fail_closed() -> None:
    revisions = (
        revision("R1", "P-100", (BomLine("L1", "C-01", D("1"), "EA", "EA"),)),
        revision("R2", "P-100", (BomLine("L2", "C-02", D("1"), "EA", "EA"),)),
    )

    with pytest.raises(PlanningInputError) as exc_info:
        resolve_bom_revision(
            revisions,
            parent_item_id="P-100",
            facility_id="PLANT-1",
            effective_date=date(2026, 11, 10),
        )

    assert exc_info.value.code == "BOM_REVISION_AMBIGUOUS"


def test_scrap_multiplier_and_explicit_uom_conversion_are_applied() -> None:
    converter = UnitConverter((UnitConversion("KG", "G", D("1000"), "mass"),))
    revisions = (
        revision(
            "P-R1",
            "P-100",
            (BomLine("L1", "RESIN", D("0.5"), "KG", "G", D("1.1")),),
        ),
    )

    result = explode_production_order(
        production_order(quantity="2"),
        revisions,
        snapshot_id="SNAP-001",
        manufactured_item_ids={"P-100"},
        converter=converter,
    )

    assert result.contributions[0].quantity == D("1100")
    assert result.contributions[0].base_uom == "G"


def test_missing_uom_conversion_fails_closed() -> None:
    revisions = (
        revision(
            "P-R1",
            "P-100",
            (BomLine("L1", "RESIN", D("1"), "KG", "G"),),
        ),
    )

    with pytest.raises(PlanningInputError) as exc_info:
        explode_production_order(
            production_order(),
            revisions,
            snapshot_id="SNAP-001",
            manufactured_item_ids={"P-100"},
            converter=UnitConverter(),
        )

    assert exc_info.value.code == "UOM_CONVERSION_MISSING"


def test_complete_authoritative_explicit_requirements_override_bom() -> None:
    explicit = (ExplicitMaterialRequirement("REQ-1", "C-99", D("12"), "EA", "EA"),)
    revisions = (revision("P-R1", "P-100", (BomLine("L1", "C-01", D("99"), "EA", "EA"),)),)

    result = explode_production_order(
        production_order(explicit=explicit, complete=True, authoritative=True),
        revisions,
        snapshot_id="SNAP-001",
        manufactured_item_ids={"P-100"},
        converter=UnitConverter(),
    )

    assert len(result.contributions) == 1
    assert result.contributions[0].material_id == "C-99"
    assert result.contributions[0].quantity == D("12")
    assert result.contributions[0].source_kind == "explicit_requirement"
    assert result.revision_ids == ()


def test_partial_explicit_requirements_do_not_mix_with_bom() -> None:
    explicit = (ExplicitMaterialRequirement("REQ-1", "C-01", D("2"), "EA", "EA"),)
    with pytest.raises(PlanningInputError) as exc_info:
        explode_production_order(
            production_order(explicit=explicit, complete=False, authoritative=True),
            (revision("P-R1", "P-100", (BomLine("L1", "C-02", D("1"), "EA", "EA"),)),),
            snapshot_id="SNAP-001",
            manufactured_item_ids={"P-100"},
            converter=UnitConverter(),
        )

    assert exc_info.value.code == "EXPLICIT_REQUIREMENTS_INCOMPLETE"


def test_inventory_physical_on_hand_reservations_are_not_double_counted() -> None:
    inventory = InventoryBalance(
        facility_id="PLANT-1",
        material_id="C-01",
        as_of=date(2026, 11, 4),
        quantity_basis=QuantityBasis.PHYSICAL_ON_HAND,
        quantity=D("100"),
        reserved_quantity=D("20"),
        blocked_quantity=D("5"),
        safety_stock=D("10"),
        uom="EA",
    )
    demand = DemandContribution(
        "REQ-1",
        "PO-100",
        "C-01",
        "PLANT-1",
        D("60"),
        "EA",
        date(2026, 11, 5),
        "bom_explosion",
    )
    reservation = ReservationAllocation(
        "RES-1", "PO-100", "PLANT-1", "C-01", D("20"), "EA", date(2026, 11, 5)
    )

    projection = project_inventory(
        inventory,
        (demand,),
        reservations=(reservation,),
        snapshot_id="SNAP-001",
        start_date=date(2026, 11, 4),
        end_date=date(2026, 11, 5),
        converter=UnitConverter(),
    )

    assert projection.snapshot_id == "SNAP-001"
    assert "REQ-1" in projection.input_source_refs
    assert "RES-1" in projection.input_source_refs
    assert projection.opening_usable_quantity == D("75")
    assert projection.daily_buckets[1].gross_demand == D("60")
    assert projection.daily_buckets[1].reserved_demand == D("20")
    assert projection.daily_buckets[1].net_demand == D("40")
    assert projection.daily_buckets[1].closing_quantity == D("35")
    assert projection.total_unmet_demand == D("0")
    assert projection.status == CalculationStatus.COMPLETED


def test_available_to_use_basis_does_not_subtract_reserved_or_blocked_again() -> None:
    inventory = InventoryBalance(
        facility_id="PLANT-1",
        material_id="C-01",
        as_of=date(2026, 11, 4),
        quantity_basis=QuantityBasis.AVAILABLE_TO_USE,
        quantity=D("75"),
        reserved_quantity=D("20"),
        blocked_quantity=D("5"),
        safety_stock=D("10"),
        uom="EA",
    )
    demand = DemandContribution(
        "REQ-1",
        "PO-100",
        "C-01",
        "PLANT-1",
        D("60"),
        "EA",
        date(2026, 11, 5),
        "bom_explosion",
    )
    reservation = ReservationAllocation(
        "RES-1", "PO-100", "PLANT-1", "C-01", D("20"), "EA", date(2026, 11, 5)
    )

    projection = project_inventory(
        inventory,
        (demand,),
        reservations=(reservation,),
        snapshot_id="SNAP-001",
        start_date=date(2026, 11, 4),
        end_date=date(2026, 11, 5),
        converter=UnitConverter(),
    )

    assert projection.opening_usable_quantity == D("75")
    assert projection.daily_buckets[1].closing_quantity == D("35")


def test_unconfirmed_receipt_is_excluded_and_marks_projection_degraded() -> None:
    inventory = InventoryBalance(
        facility_id="PLANT-1",
        material_id="C-01",
        as_of=date(2026, 11, 4),
        quantity_basis=QuantityBasis.PHYSICAL_ON_HAND,
        quantity=D("10"),
        uom="EA",
    )
    receipt = SupplyReceipt(
        "PO-LINE-1",
        "PLANT-1",
        "C-01",
        D("100"),
        "EA",
        date(2026, 11, 5),
        "pending_supplier_confirmation",
    )

    projection = project_inventory(
        inventory,
        (),
        receipts=(receipt,),
        snapshot_id="SNAP-001",
        start_date=date(2026, 11, 4),
        end_date=date(2026, 11, 6),
        converter=UnitConverter(),
    )

    assert projection.daily_buckets[1].firm_receipts == D("0")
    assert projection.excluded_receipt_quantity == D("100")
    assert projection.status == CalculationStatus.DEGRADED
    assert "UNCONFIRMED_RECEIPT_EXCLUDED" in projection.warnings


def test_firm_receipt_is_available_before_same_day_demand() -> None:
    inventory = InventoryBalance(
        facility_id="PLANT-1",
        material_id="C-01",
        as_of=date(2026, 11, 4),
        quantity_basis=QuantityBasis.PHYSICAL_ON_HAND,
        quantity=D("10"),
        uom="EA",
    )
    demand = DemandContribution(
        "REQ-1",
        "PO-100",
        "C-01",
        "PLANT-1",
        D("25"),
        "EA",
        date(2026, 11, 6),
        "bom_explosion",
    )
    receipt = SupplyReceipt(
        "PO-LINE-1",
        "PLANT-1",
        "C-01",
        D("20"),
        "EA",
        date(2026, 11, 6),
        "confirmed",
    )

    projection = project_inventory(
        inventory,
        (demand,),
        receipts=(receipt,),
        snapshot_id="SNAP-001",
        start_date=date(2026, 11, 4),
        end_date=date(2026, 11, 6),
        converter=UnitConverter(),
    )

    bucket = projection.daily_buckets[2]
    assert bucket.opening_quantity == D("10")
    assert bucket.firm_receipts == D("20")
    assert bucket.net_demand == D("25")
    assert bucket.closing_quantity == D("5")
    assert projection.first_stockout is None


def test_shortage_dates_and_unmet_demand_are_time_phased() -> None:
    inventory = InventoryBalance(
        facility_id="PLANT-1",
        material_id="C-01",
        as_of=date(2026, 11, 4),
        quantity_basis=QuantityBasis.PHYSICAL_ON_HAND,
        quantity=D("30"),
        safety_stock=D("15"),
        uom="EA",
    )
    demands = (
        DemandContribution(
            "REQ-1",
            "PO-1",
            "C-01",
            "PLANT-1",
            D("20"),
            "EA",
            date(2026, 11, 5),
            "explicit_requirement",
        ),
        DemandContribution(
            "REQ-2",
            "PO-2",
            "C-01",
            "PLANT-1",
            D("20"),
            "EA",
            date(2026, 11, 6),
            "explicit_requirement",
        ),
    )

    projection = project_inventory(
        inventory,
        demands,
        snapshot_id="SNAP-001",
        start_date=date(2026, 11, 4),
        end_date=date(2026, 11, 6),
        converter=UnitConverter(),
    )

    assert projection.first_safety_stock_breach == date(2026, 11, 5)
    assert projection.first_stockout == date(2026, 11, 6)
    assert projection.total_unmet_demand == D("10")
    assert projection.daily_buckets[2].closing_quantity == D("-10")
    assert projection.daily_buckets[2].unmet_demand == D("10")


def test_reservation_allocations_cannot_exceed_inventory_reserved_quantity() -> None:
    inventory = InventoryBalance(
        facility_id="PLANT-1",
        material_id="C-01",
        as_of=date(2026, 11, 4),
        quantity_basis=QuantityBasis.PHYSICAL_ON_HAND,
        quantity=D("100"),
        reserved_quantity=D("10"),
        uom="EA",
    )
    demand = DemandContribution(
        "REQ-1",
        "PO-100",
        "C-01",
        "PLANT-1",
        D("40"),
        "EA",
        date(2026, 11, 5),
        "explicit_requirement",
    )
    reservation = ReservationAllocation(
        "RES-1", "PO-100", "PLANT-1", "C-01", D("20"), "EA", date(2026, 11, 5)
    )

    with pytest.raises(PlanningInputError) as exc_info:
        project_inventory(
            inventory,
            (demand,),
            reservations=(reservation,),
            snapshot_id="SNAP-001",
            start_date=date(2026, 11, 4),
            end_date=date(2026, 11, 5),
            converter=UnitConverter(),
        )

    assert exc_info.value.code == "ALLOCATIONS_EXCEED_RESERVED_STOCK"


def test_unlinked_reservations_are_conservative_and_mark_result_degraded() -> None:
    inventory = InventoryBalance(
        facility_id="PLANT-1",
        material_id="C-01",
        as_of=date(2026, 11, 4),
        quantity_basis=QuantityBasis.PHYSICAL_ON_HAND,
        quantity=D("100"),
        reserved_quantity=D("15"),
        uom="EA",
    )

    projection = project_inventory(
        inventory,
        (),
        snapshot_id="SNAP-001",
        start_date=date(2026, 11, 4),
        end_date=date(2026, 11, 4),
        converter=UnitConverter(),
    )

    assert projection.opening_usable_quantity == D("85")
    assert projection.unlinked_reserved_quantity == D("15")
    assert projection.status == CalculationStatus.DEGRADED
    assert "UNLINKED_RESERVED_STOCK" in projection.warnings


def test_projection_horizon_is_bounded() -> None:
    inventory = InventoryBalance(
        facility_id="PLANT-1",
        material_id="C-01",
        as_of=date(2026, 11, 4),
        quantity_basis=QuantityBasis.PHYSICAL_ON_HAND,
        quantity=D("100"),
        uom="EA",
    )

    with pytest.raises(PlanningInputError) as exc_info:
        project_inventory(
            inventory,
            (),
            snapshot_id="SNAP-001",
            start_date=date(2026, 11, 4),
            end_date=date(2028, 1, 1),
            converter=UnitConverter(),
        )

    assert exc_info.value.code == "PROJECTION_HORIZON_EXCEEDED"


def test_inventory_snapshot_must_match_projection_opening_date() -> None:
    inventory = InventoryBalance(
        facility_id="PLANT-1",
        material_id="C-01",
        as_of=date(2026, 11, 3),
        quantity_basis=QuantityBasis.PHYSICAL_ON_HAND,
        quantity=D("100"),
        uom="EA",
    )

    with pytest.raises(PlanningInputError) as exc_info:
        project_inventory(
            inventory,
            (),
            snapshot_id="SNAP-001",
            start_date=date(2026, 11, 4),
            end_date=date(2026, 11, 4),
            converter=UnitConverter(),
        )

    assert exc_info.value.code == "INVENTORY_SNAPSHOT_DATE_MISMATCH"
