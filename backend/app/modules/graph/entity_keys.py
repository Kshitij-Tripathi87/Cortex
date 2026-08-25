"""Entity primary keys and foreign-key → edge-type registry.

Drives deterministic entity resolution in the Evidence → Graph Compiler.
Every mapping here is frozen and explainable — no heuristics, no AI.
The compiler uses these registries to decide, for each column in a source
file, whether it identifies an entity (→ node) or references another
entity (→ edge).
"""

from __future__ import annotations

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
