"""Contract tests for the manufacturing ingestion dataset schemas."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.common.enums import MvpDatasetType
from app.modules.ingestion.service import _DATASET_TO_SCHEMA
from app.modules.supply_chain.schemas import (
    BOMLineRow,
    InventoryRow,
    PurchaseOrderLineRow,
    ROW_SCHEMA_BY_DATASET,
)


def test_new_planning_dataset_types_have_ingestion_schemas():
    expected = {
        MvpDatasetType.BOM_REVISIONS,
        MvpDatasetType.BOM_LINES,
        MvpDatasetType.PRODUCTION_ORDERS,
        MvpDatasetType.PURCHASE_ORDER_LINES,
        MvpDatasetType.UOM_CONVERSIONS,
    }
    assert expected.issubset(_DATASET_TO_SCHEMA)
    assert {
        "bom_revisions",
        "bom_lines",
        "production_orders",
        "purchase_order_lines",
        "uom_conversions",
    }.issubset(ROW_SCHEMA_BY_DATASET)


def test_inventory_requires_explicit_semantics_for_available_stock():
    with pytest.raises(ValidationError):
        InventoryRow(
            warehouse_code="WH-1",
            component_sku="C-1",
            quantity=Decimal("100"),
            quantity_basis="available_to_use",
        )


def test_physical_inventory_defaults_reservation_buckets_to_zero():
    row = InventoryRow(
        warehouse_code="WH-1",
        component_sku="C-1",
        quantity=Decimal("100"),
    )
    assert row.quantity_basis == "physical_on_hand"
    assert row.reserved_quantity == Decimal("0")
    assert row.blocked_quantity == Decimal("0")


def test_purchase_order_line_rejects_received_quantity_above_ordered():
    with pytest.raises(ValidationError):
        PurchaseOrderLineRow(
            po_number="PO-1",
            line_number="1",
            supplier_name="Supplier A",
            warehouse_code="WH-1",
            component_sku="C-1",
            ordered_quantity=Decimal("10"),
            received_quantity=Decimal("11"),
            uom="EA",
        )


def test_purchase_order_line_rejects_open_quantity_above_remaining():
    with pytest.raises(ValidationError):
        PurchaseOrderLineRow(
            po_number="PO-1",
            line_number="1",
            supplier_name="Supplier A",
            warehouse_code="WH-1",
            component_sku="C-1",
            ordered_quantity=Decimal("10"),
            received_quantity=Decimal("5"),
            open_quantity=Decimal("6"),
            uom="EA",
        )


def test_bom_line_requires_positive_usage_quantity():
    with pytest.raises(ValidationError):
        BOMLineRow(
            parent_item_type="product",
            parent_item_ref="P-1",
            revision_code="A",
            line_code="1",
            child_item_type="component",
            child_item_ref="C-1",
            usage_quantity=Decimal("0"),
            usage_uom="EA",
            child_base_uom="EA",
        )
