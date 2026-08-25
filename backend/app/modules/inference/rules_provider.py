"""Inference module — deterministic rules-based schema mapping.

Maps source column names to canonical fields using the frozen alias registry
from docs/02-ontology.md §10. No ML, no LLM. Rules-first, explainable.
"""

from __future__ import annotations

from dataclasses import dataclass

# Frozen alias registry (subset from docs/02-ontology.md §10)
# Maps lowercased/normalized source column names to canonical entity types + fields.
ALIAS_REGISTRY: dict[str, tuple[str, str]] = {
    # Supplier
    "supplier": ("Supplier", ""),
    "supplier_name": ("Supplier", "legal_name"),
    "supplier_id": ("Supplier", "external_ids"),
    "vendor": ("Supplier", ""),
    "vendor_name": ("Supplier", "legal_name"),
    "vendor_id": ("Supplier", "external_ids"),
    "vendor_master": ("Supplier", ""),
    "tax_id": ("Supplier", "tax_id"),
    "duns": ("Supplier", "duns_number"),
    "duns_number": ("Supplier", "duns_number"),
    "country": ("Supplier", "country"),
    # Warehouse
    "warehouse": ("Warehouse", "name"),
    "warehouse_name": ("Warehouse", "name"),
    "warehouse_id": ("Warehouse", "external_ids"),
    "dc": ("Warehouse", "name"),
    "distribution_center": ("Warehouse", "name"),
    "facility": ("Facility", "name"),
    "facility_id": ("Facility", "external_ids"),
    "facility_name": ("Facility", "name"),
    "site": ("Facility", "name"),
    "site_id": ("Facility", "external_ids"),
    # Plant
    "plant": ("Plant", "name"),
    "plant_name": ("Plant", "name"),
    "plant_id": ("Plant", "external_ids"),
    "factory": ("Plant", "name"),
    # Product
    "product": ("Product", "name"),
    "product_name": ("Product", "name"),
    "sku": ("Product", "sku"),
    "item": ("Product", "name"),
    "item_number": ("Product", "sku"),
    "material": ("Product", "name"),
    "material_number": ("Product", "sku"),
    "part_number": ("Product", "sku"),
    "partno": ("Product", "sku"),
    "item_master": ("Product", "name"),
    "uom": ("Product", "uom"),
    "unit_of_measure": ("Product", "uom"),
    "hs_code": ("Product", "hs_code"),
    # Inventory
    "stock": ("InventoryItem", "quantity"),
    "on_hand": ("InventoryItem", "quantity"),
    "inventory": ("InventoryItem", "quantity"),
    "inventory_balance": ("InventoryItem", "quantity"),
    "quantity": ("InventoryItem", "quantity"),
    "qty": ("InventoryItem", "quantity"),
    "condition": ("InventoryItem", "condition"),
    "lot": ("InventoryItem", "lot_number"),
    "lot_number": ("InventoryItem", "lot_number"),
    "serial_number": ("InventoryItem", "serial_number"),
    # PurchaseOrder
    "po_number": ("PurchaseOrder", "po_number"),
    "purchase_order": ("PurchaseOrder", "po_number"),
    "po": ("PurchaseOrder", "po_number"),
    "supplier_ref": ("PurchaseOrder", "supplier_ref"),
    "buyer": ("PurchaseOrder", "buyer_ref"),
    "placed_at": ("PurchaseOrder", "placed_at"),
    "promised_delivery_at": ("PurchaseOrder", "promised_delivery_at"),
    "ship_to": ("PurchaseOrder", "ship_to_ref"),
    "currency": ("PurchaseOrder", "currency"),
    "total_value": ("PurchaseOrder", "total_value"),
    # Shipment
    "shipment_id": ("Shipment", "shipment_id"),
    "shipment": ("Shipment", "shipment_id"),
    "load": ("Shipment", "shipment_id"),
    "tracking_number": ("Shipment", "shipment_id"),
    "carrier": ("Shipment", "carrier"),
    "mode": ("Shipment", "mode"),
    "etd": ("Shipment", "etd"),
    "atd": ("Shipment", "atd"),
    "eta": ("Shipment", "eta"),
    "ata": ("Shipment", "ata"),
    "origin": ("Shipment", "origin_ref"),
    "destination": ("Shipment", "destination_ref"),
    "cost": ("Shipment", "cost"),
    # Route
    "route_id": ("Route", "route_id"),
    "route": ("Route", "route_id"),
    "lane": ("Route", "route_id"),
    "distance": ("Route", "distance_value"),
    "transit_time": ("Route", "transit_time_value"),
    # Customer
    "customer": ("Customer", "legal_name"),
    "customer_name": ("Customer", "legal_name"),
    "customer_id": ("Customer", "external_ids"),
    "account": ("Customer", "legal_name"),
    "ship_to_customer": ("Customer", "legal_name"),
    # SalesOrder
    "so_number": ("SalesOrder", "so_number"),
    "sales_order": ("SalesOrder", "so_number"),
    "order_number": ("SalesOrder", "so_number"),
    "customer_ref": ("SalesOrder", "customer_ref"),
    "requested_delivery_at": ("SalesOrder", "promised_delivery_at"),
}


@dataclass(frozen=True)
class MappingSuggestion:
    """Schema mapping suggestion for a source column."""

    source_column: str
    canonical_entity: str | None
    canonical_field: str | None
    confidence: float
    requires_review: bool
    matched_alias: str | None = None


def normalize_column_name(name: str) -> str:
    """Normalize a source column name: lowercase, trim, collapse whitespace, strip punctuation."""
    import re

    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9_]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s


def suggest_mapping(source_column: str) -> MappingSuggestion:
    """Produce a deterministic mapping suggestion for a source column name.

    Rules:
    1. Exact match in alias registry → confidence 1.0, no review needed.
    2. Normalized match → confidence 0.9, no review needed.
    3. Partial/prefix match → confidence 0.7, review required.
    4. Unknown → confidence 0.0, review required.
    """
    raw = source_column.strip()
    normalized = normalize_column_name(raw)

    # 1. Exact normalized match
    if normalized in ALIAS_REGISTRY:
        entity, field_name = ALIAS_REGISTRY[normalized]
        return MappingSuggestion(
            source_column=raw,
            canonical_entity=entity,
            canonical_field=field_name or None,
            confidence=1.0,
            requires_review=False,
            matched_alias=normalized,
        )

    # 2. Try some common prefix/suffix transformations
    for alias in ALIAS_REGISTRY:
        if normalized in alias or alias in normalized:
            entity, field_name = ALIAS_REGISTRY[alias]
            return MappingSuggestion(
                source_column=raw,
                canonical_entity=entity,
                canonical_field=field_name or None,
                confidence=0.7,
                requires_review=True,
                matched_alias=alias,
            )

    # 3. Unknown column
    return MappingSuggestion(
        source_column=raw,
        canonical_entity=None,
        canonical_field=None,
        confidence=0.0,
        requires_review=True,
        matched_alias=None,
    )
