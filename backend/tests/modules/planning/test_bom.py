from datetime import date
from decimal import Decimal

from app.modules.planning.bom import explode_production_order
from app.modules.planning.models import (
    BOMLine,
    BOMRevision,
    ExplicitMaterialRequirement,
    ItemType,
    ProductionOrder,
    ProjectionStatus,
    UOMConverter,
)


def _order(quantity="10", *, revision=None):
    return ProductionOrder(
        order_id="MO-001",
        facility_id="PLANT-1",
        item_id="P-100",
        item_type=ItemType.PRODUCT,
        quantity=Decimal(quantity),
        order_uom="EA",
        item_base_uom="EA",
        material_need_at=date(2026, 11, 10),
        status="released",
        bom_revision_id=revision,
    )


def test_multilevel_bom_explosion_multiplies_each_level():
    revisions = (
        BOMRevision(
            "r-product", "P-100", ItemType.PRODUCT, "A",
            (BOMLine("L1", "A-10", ItemType.COMPONENT, Decimal("2"), "EA", "EA", True),),
        ),
        BOMRevision(
            "r-assembly", "A-10", ItemType.COMPONENT, "A",
            (BOMLine("L2", "C-01", ItemType.COMPONENT, Decimal("3"), "EA", "EA"),),
        ),
    )
    result = explode_production_order(_order(), revisions)
    assert result.status == ProjectionStatus.COMPLETED
    assert len(result.contributions) == 1
    assert result.contributions[0].material_id == "C-01"
    assert result.contributions[0].gross_quantity == Decimal("60")
    assert result.contributions[0].bom_line_path == ("L1", "L2")


def test_shared_material_on_distinct_branches_is_additive_and_keeps_lineage():
    revisions = (
        BOMRevision(
            "rp", "P-100", ItemType.PRODUCT, "A",
            (
                BOMLine("L-A", "A", ItemType.COMPONENT, Decimal("1"), "EA", "EA", True),
                BOMLine("L-B", "B", ItemType.COMPONENT, Decimal("1"), "EA", "EA", True),
            ),
        ),
        BOMRevision(
            "ra", "A", ItemType.COMPONENT, "A",
            (BOMLine("L-A-C", "C-01", ItemType.COMPONENT, Decimal("2"), "EA", "EA"),),
        ),
        BOMRevision(
            "rb", "B", ItemType.COMPONENT, "A",
            (BOMLine("L-B-C", "C-01", ItemType.COMPONENT, Decimal("3"), "EA", "EA"),),
        ),
    )
    result = explode_production_order(_order(revision="rp"), revisions)
    assert result.status == ProjectionStatus.COMPLETED
    # The order quantity is 10, so each branch's unit usage is multiplied by 10.
    assert [c.gross_quantity for c in result.contributions] == [
        Decimal("20"),
        Decimal("30"),
    ]
    assert sum((c.gross_quantity for c in result.contributions), Decimal("0")) == Decimal("50")
    assert len({c.bom_line_path for c in result.contributions}) == 2


def test_cycle_fails_closed():
    revisions = (
        BOMRevision(
            "rp", "P-100", ItemType.PRODUCT, "A",
            (BOMLine("L1", "A-10", ItemType.COMPONENT, Decimal("1"), "EA", "EA", True),),
        ),
        BOMRevision(
            "ra", "A-10", ItemType.COMPONENT, "A",
            (BOMLine("L2", "P-100", ItemType.PRODUCT, Decimal("1"), "EA", "EA", True),),
        ),
    )
    result = explode_production_order(_order(), revisions)
    assert result.status == ProjectionStatus.NOT_CALCULABLE
    assert result.error_code == "BOM_CYCLE"


def test_overlapping_revision_is_ambiguous():
    revisions = (
        BOMRevision("r1", "P-100", ItemType.PRODUCT, "A", (BOMLine("1", "C", ItemType.COMPONENT, Decimal("1"), "EA", "EA"),)),
        BOMRevision("r2", "P-100", ItemType.PRODUCT, "B", (BOMLine("2", "D", ItemType.COMPONENT, Decimal("1"), "EA", "EA"),)),
    )
    result = explode_production_order(_order(revision=None), revisions)
    assert result.status == ProjectionStatus.NOT_CALCULABLE
    assert result.error_code.startswith("AMBIGUOUS_BOM_REVISION")


def test_uom_conversion_is_explicit():
    revisions = (
        BOMRevision(
            "rp", "P-100", ItemType.PRODUCT, "A",
            (BOMLine("L1", "C-01", ItemType.COMPONENT, Decimal("2"), "KG", "G"),),
        ),
    )
    result = explode_production_order(
        _order(), revisions, UOMConverter({("KG", "G"): Decimal("1000")})
    )
    assert result.status == ProjectionStatus.COMPLETED
    assert result.contributions[0].gross_quantity == Decimal("20000")


def test_missing_uom_conversion_fails_closed():
    revisions = (
        BOMRevision(
            "rp", "P-100", ItemType.PRODUCT, "A",
            (BOMLine("L1", "C-01", ItemType.COMPONENT, Decimal("2"), "KG", "G"),),
        ),
    )
    result = explode_production_order(_order(), revisions)
    assert result.status == ProjectionStatus.NOT_CALCULABLE
    assert "UOM_CONVERSION_MISSING" in result.error_code


def test_authoritative_explicit_requirements_do_not_explode_bom():
    order = ProductionOrder(
        order_id="MO-EX", facility_id="PLANT-1", item_id="P-100",
        item_type=ItemType.PRODUCT, quantity=Decimal("10"), order_uom="EA",
        item_base_uom="EA", material_need_at=date(2026, 11, 10), status="released",
        explicit_requirements=(
            ExplicitMaterialRequirement(
                "REQ-1", "C-99", Decimal("25"), "EA", date(2026, 11, 8),
                Decimal("5"), True,
            ),
        ),
        explicit_requirements_authoritative=True,
    )
    result = explode_production_order(order, ())
    assert result.status == ProjectionStatus.COMPLETED
    assert len(result.contributions) == 1
    assert result.contributions[0].uncovered_quantity == Decimal("20")


def test_partial_explicit_requirements_are_not_mixed_with_bom():
    order = ProductionOrder(
        order_id="MO-P", facility_id="PLANT-1", item_id="P-100",
        item_type=ItemType.PRODUCT, quantity=Decimal("10"), order_uom="EA",
        item_base_uom="EA", material_need_at=date(2026, 11, 10), status="released",
        explicit_requirements=(
            ExplicitMaterialRequirement("R", "C", Decimal("1"), "EA", date(2026, 11, 9)),
        ),
        explicit_requirements_authoritative=False,
    )
    result = explode_production_order(order, ())
    assert result.status == ProjectionStatus.NOT_CALCULABLE
    assert result.error_code == "AMBIGUOUS_REQUIREMENTS"
