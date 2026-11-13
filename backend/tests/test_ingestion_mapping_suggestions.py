from __future__ import annotations

from app.modules.inference.rules_provider import suggest_mapping


def test_vendor_id_is_interpreted_in_purchase_order_row_context() -> None:
    mapping = suggest_mapping("Vendor ID", row_entity_type="PurchaseOrder")

    assert mapping.canonical_entity == "PurchaseOrder"
    assert mapping.canonical_field == "supplier_id"
    assert mapping.confidence == 1.0
    assert mapping.requires_review is False


def test_vendor_id_is_interpreted_as_supplier_primary_key_in_supplier_master() -> None:
    mapping = suggest_mapping("Vendor ID", row_entity_type="Supplier")

    assert mapping.canonical_entity == "Supplier"
    assert mapping.canonical_field == "supplier_id"
    assert mapping.requires_review is False


def test_warehouse_code_is_interpreted_as_destination_relationship_in_purchase_order() -> None:
    mapping = suggest_mapping("Ship To Warehouse Code", row_entity_type="PurchaseOrder")

    assert mapping.canonical_entity == "PurchaseOrder"
    assert mapping.canonical_field == "ship_to_facility_id"
    assert mapping.requires_review is False


def test_warehouse_id_is_interpreted_as_inventory_facility_relationship() -> None:
    mapping = suggest_mapping("Warehouse ID", row_entity_type="InventoryItem")

    assert mapping.canonical_entity == "InventoryItem"
    assert mapping.canonical_field == "facility_id"
    assert mapping.requires_review is False


def test_unknown_header_remains_unmapped_and_requires_review() -> None:
    mapping = suggest_mapping("Mystery Column", row_entity_type="PurchaseOrder")

    assert mapping.canonical_entity is None
    assert mapping.canonical_field is None
    assert mapping.requires_review is True
