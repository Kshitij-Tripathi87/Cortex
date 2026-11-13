"""Entity primary keys and foreign-key → edge-type registry.

Drives deterministic entity resolution in the Evidence → Graph Compiler.
Every mapping here is frozen and explainable — no heuristics, no AI.
The compiler uses these registries to decide, for each column in a source
file, whether it identifies an entity (→ node) or references another
entity (→ edge).
"""

from __future__ import annotations

import re

# Maps canonical entity type → the field that uniquely identifies it.
# The compiler looks for a column whose recommended_mapping matches this
# field to derive the entity_id for each row.
ENTITY_PRIMARY_KEYS: dict[str, str] = {
    "Supplier": "supplier_id",
    "Customer": "customer_id",
    "Carrier": "carrier_id",
    "Warehouse": "warehouse_id",
    "Plant": "plant_id",
    "DistributionCenter": "dc_id",
    "CrossDock": "crossdock_id",
    "Port": "port_id",
    "Product": "sku",
    "BOM": "bom_id",
    "InventoryItem": "inventory_id",
    "InventoryLot": "lot_id",
    "PurchaseOrder": "po_number",
    "SalesOrder": "so_number",
    "Shipment": "shipment_id",
    "Route": "route_id",
    "Region": "region_id",
    "DemandRegion": "demand_region_id",
}

# Maps (source_entity_type, column_field) → (target_entity_type, relationship_type).
# The compiler uses this to build edges: when a column in a Supplier row
# contains a value that matches a foreign key pattern, an edge is created.
#
# Facility is used as a generic target — Warehouse/Plant/DC/CrossDock/Port
# all contribute nodes with entity_type="Facility" and a facility_type
# attribute derived from the source entity.
ENTITY_FOREIGN_KEYS: dict[tuple[str, str], tuple[str, str]] = {
    # PurchaseOrder relationships
    ("PurchaseOrder", "supplier_id"): ("Supplier", "ORDERS_FROM"),
    ("PurchaseOrder", "ship_to_facility_id"): ("Facility", "SHIPS_TO"),
    ("PurchaseOrder", "buyer_id"): ("Organization", "ORDERED_BY"),
    # SalesOrder relationships
    ("SalesOrder", "customer_id"): ("Customer", "ORDERED_BY"),
    ("SalesOrder", "ship_from_facility_id"): ("Facility", "SHIPS_FROM"),
    # Shipment relationships
    ("Shipment", "origin_facility_id"): ("Facility", "ORIGINATES_FROM"),
    ("Shipment", "origin_supplier_id"): ("Supplier", "ORIGINATES_FROM"),
    ("Shipment", "destination_facility_id"): ("Facility", "DESTINED_TO"),
    ("Shipment", "destination_customer_id"): ("Customer", "DESTINED_TO"),
    ("Shipment", "carrier_id"): ("Carrier", "CARRIED_BY"),
    ("Shipment", "route_id"): ("Route", "USES_ROUTE"),
    # Inventory relationships
    ("InventoryItem", "facility_id"): ("Facility", "STORED_AT"),
    ("InventoryItem", "sku"): ("Product", "IS_PRODUCT"),
    ("InventoryItem", "supplier_lot_id"): ("Supplier", "SUPPLIED_BY"),
    # BOM relationships
    ("BOM", "parent_sku"): ("Product", "COMPONENT_OF"),
    ("BOM", "child_sku"): ("Product", "HAS_COMPONENT"),
    # Supplier hierarchy
    ("Supplier", "parent_supplier_id"): ("Supplier", "PARENT_OF"),
    # Route relationships
    ("Route", "origin_facility_id"): ("Facility", "CONNECTS_FROM"),
    ("Route", "destination_facility_id"): ("Facility", "CONNECTS_TO"),
    # Facility → Region
    ("Warehouse", "region"): ("Region", "LOCATED_IN"),
    ("Plant", "region"): ("Region", "LOCATED_IN"),
    ("DistributionCenter", "region"): ("Region", "LOCATED_IN"),
}

# Maps source entity types to their facility_type attribute, used when a
# warehouse/plant/DC node is promoted to a generic Facility node.
FACILITY_ENTITY_TYPES: dict[str, str] = {
    "Warehouse": "warehouse",
    "Plant": "plant",
    "DistributionCenter": "distribution_center",
    "CrossDock": "cross_dock",
    "Port": "port",
}


# Explicit, deterministic aliases for common ERP/WMS/TMS exports. These are
# schema aliases, not fuzzy matches: an alias is only accepted when its meaning
# is stable enough to map to one canonical field.
COLUMN_ALIASES: dict[str, str] = {
    # Supplier / vendor master and supplier foreign keys.
    "vendor_id": "supplier_id",
    "vendor_code": "supplier_id",
    "vendor_number": "supplier_id",
    "vendor_no": "supplier_id",
    "supplier_code": "supplier_id",
    "supplier_number": "supplier_id",
    "supplier_no": "supplier_id",
    # Customer master / order references.
    "customer_code": "customer_id",
    "customer_number": "customer_id",
    "customer_no": "customer_id",
    # Carrier / logistics references.
    "carrier_code": "carrier_id",
    "scac": "carrier_id",
    "scac_code": "carrier_id",
    # Facility master identifiers.
    "wh_id": "warehouse_id",
    "warehouse_code": "warehouse_id",
    "warehouse_number": "warehouse_id",
    "warehouse_no": "warehouse_id",
    "plant_code": "plant_id",
    "factory_id": "plant_id",
    "dc_code": "dc_id",
    "distribution_center_id": "dc_id",
    "distribution_center_code": "dc_id",
    "cross_dock_id": "crossdock_id",
    "crossdock_code": "crossdock_id",
    "port_code": "port_id",
    "unlocode": "port_id",
    # Product / material master.
    "product_id": "sku",
    "product_code": "sku",
    "item_id": "sku",
    "item_number": "sku",
    "material_id": "sku",
    "material_number": "sku",
    "part_number": "sku",
    "part_id": "sku",
    # Bills of material and inventory.
    "bom_number": "bom_id",
    "bill_of_materials_id": "bom_id",
    "bill_of_materials_number": "bom_id",
    "inventory_item_id": "inventory_id",
    "stock_id": "inventory_id",
    "lot_number": "lot_id",
    "lot_code": "lot_id",
    "batch_number": "lot_id",
    # Order / shipment / network master.
    "purchase_order_id": "po_number",
    "purchase_order_number": "po_number",
    "po_id": "po_number",
    "po_num": "po_number",
    "sales_order_id": "so_number",
    "sales_order_number": "so_number",
    "so_id": "so_number",
    "so_num": "so_number",
    "shipment_number": "shipment_id",
    "shipment_no": "shipment_id",
    "consignment_id": "shipment_id",
    "consignment_number": "shipment_id",
    "route_number": "route_id",
    "route_code": "route_id",
    "lane_id": "route_id",
    "region_code": "region_id",
    "territory_id": "region_id",
    "demand_region_code": "demand_region_id",
}

# Context-specific aliases for relationship columns whose meaning depends on
# the row type. For example, warehouse_id is a facility foreign key on an
# InventoryItem, but a warehouse primary key on a Warehouse row.
ENTITY_COLUMN_ALIASES: dict[tuple[str, str], str] = {
    # Primary-key aliases are interpreted relative to the row's table.
    ("Supplier", "vendor_id"): "supplier_id",
    ("Supplier", "vendor_code"): "supplier_id",
    ("Supplier", "vendor_number"): "supplier_id",
    ("Supplier", "supplier_code"): "supplier_id",
    ("Customer", "customer_code"): "customer_id",
    ("Customer", "customer_number"): "customer_id",
    ("Carrier", "carrier_code"): "carrier_id",
    ("Carrier", "scac"): "carrier_id",
    ("Warehouse", "warehouse_code"): "warehouse_id",
    ("Warehouse", "warehouse_number"): "warehouse_id",
    ("Plant", "plant_code"): "plant_id",
    ("PurchaseOrder", "vendor_id"): "supplier_id",
    ("PurchaseOrder", "vendor_code"): "supplier_id",
    ("PurchaseOrder", "supplier_ref"): "supplier_id",
    ("SalesOrder", "customer_code"): "customer_id",
    ("SalesOrder", "customer_ref"): "customer_id",
    ("Shipment", "carrier_code"): "carrier_id",
    ("Shipment", "scac"): "carrier_id",
    ("Shipment", "route_code"): "route_id",
    ("InventoryItem", "product_code"): "sku",
    ("InventoryItem", "item_number"): "sku",
    ("InventoryItem", "material_number"): "sku",
    ("PurchaseOrder", "ship_to_warehouse_id"): "ship_to_facility_id",
    ("PurchaseOrder", "ship_to_warehouse_code"): "ship_to_facility_id",
    ("PurchaseOrder", "ship_to_plant_id"): "ship_to_facility_id",
    ("PurchaseOrder", "destination_warehouse_id"): "ship_to_facility_id",
    ("SalesOrder", "ship_from_warehouse_id"): "ship_from_facility_id",
    ("SalesOrder", "ship_from_plant_id"): "ship_from_facility_id",
    ("Shipment", "origin_warehouse_id"): "origin_facility_id",
    ("Shipment", "origin_plant_id"): "origin_facility_id",
    ("Shipment", "origin_port_id"): "origin_facility_id",
    ("Shipment", "destination_warehouse_id"): "destination_facility_id",
    ("Shipment", "destination_plant_id"): "destination_facility_id",
    ("Shipment", "destination_port_id"): "destination_facility_id",
    ("InventoryItem", "warehouse_id"): "facility_id",
    ("InventoryItem", "warehouse_code"): "facility_id",
    ("InventoryItem", "plant_id"): "facility_id",
    ("InventoryItem", "dc_id"): "facility_id",
    ("Route", "origin_warehouse_id"): "origin_facility_id",
    ("Route", "origin_plant_id"): "origin_facility_id",
    ("Route", "destination_warehouse_id"): "destination_facility_id",
    ("Route", "destination_plant_id"): "destination_facility_id",
    ("Supplier", "parent_vendor_id"): "parent_supplier_id",
    ("Supplier", "parent_vendor_code"): "parent_supplier_id",
    ("BOM", "parent_product_code"): "parent_sku",
    ("BOM", "component_sku"): "child_sku",
    ("BOM", "child_product_code"): "child_sku",
}


def normalize_column_name(name: str) -> str:
    """Normalize a source header without guessing its business meaning."""
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


def canonical_column_name(name: str, entity_type: str | None = None) -> str:
    """Resolve a known source-header alias to a canonical field name."""
    normalized = normalize_column_name(name)
    if entity_type is not None:
        contextual = ENTITY_COLUMN_ALIASES.get((entity_type, normalized))
        if contextual is not None:
            return contextual
    return COLUMN_ALIASES.get(normalized, normalized)


# Reverse lookup: column_field → canonical_entity type, for entity detection.
# When a column's name (normalized) matches one of these, the compiler
# infers the entity type for that row even without a successful mapping suggestion.
COLUMN_TO_ENTITY_TYPE: dict[str, str] = {
    "supplier_id": "Supplier",
    "customer_id": "Customer",
    "carrier_id": "Carrier",
    "warehouse_id": "Warehouse",
    "plant_id": "Plant",
    "dc_id": "DistributionCenter",
    "crossdock_id": "CrossDock",
    "port_id": "Port",
    "sku": "Product",
    "bom_id": "BOM",
    "inventory_id": "InventoryItem",
    "lot_id": "InventoryLot",
    "lot_number": "InventoryLot",
    "po_number": "PurchaseOrder",
    "so_number": "SalesOrder",
    "shipment_id": "Shipment",
    "route_id": "Route",
    "region_id": "Region",
    "demand_region_id": "DemandRegion",
}


def infer_entity_type(headers: list[str]) -> str | None:
    """Infer the row entity using PK candidates and known relationship columns.

    A foreign key such as customer_id must not make a SalesOrder export look
    like a Customer master. When a file contains multiple entity identifiers,
    score candidates by the explicit FK fields defined for each row type. Ties
    remain unresolved and fail closed instead of guessing.
    """
    canonical_fields = {
        canonical_column_name(header)
        for header in headers
    }
    candidates = {
        COLUMN_TO_ENTITY_TYPE[field]
        for field in canonical_fields
        if field in COLUMN_TO_ENTITY_TYPE
    }
    if not candidates:
        return None
    if len(candidates) == 1:
        return next(iter(candidates))

    scores = {
        entity_type: sum(
            1 for field in canonical_fields if (entity_type, field) in ENTITY_FOREIGN_KEYS
        )
        for entity_type in candidates
    }
    highest = max(scores.values(), default=0)
    winners = [entity_type for entity_type, score in scores.items() if score == highest]
    if highest > 0 and len(winners) == 1:
        return winners[0]
    return None
