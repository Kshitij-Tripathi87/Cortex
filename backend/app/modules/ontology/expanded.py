"""Expanded Supply-Chain Ontology — tiered entities, BOM, lots, transport, carriers, regions.

Extends docs/02-ontology.md with production-grade supply-chain entities.
"""

from __future__ import annotations

from app.common.enums import SourceSystemHint

# ─────────────────────────────────────────────────────────────────────────────
# Entity Catalog (extends 02-ontology.md E1-E15)
# ─────────────────────────────────────────────────────────────────────────────

EXPANDED_ENTITIES = {
    # ─── Party ───────────────────────────────────────────────────────────────
    "Supplier": {
        "category": "Party",
        "source_systems": [
            SourceSystemHint.ERP.value,
            SourceSystemHint.SCM_PLANNING.value,
            SourceSystemHint.SPREADSHEET.value,
            SourceSystemHint.MANUAL.value,
        ],
        "fields": {
            "supplier_id": {"type": "string", "required": True},
            "name": {"type": "string", "required": True},
            "tier": {
                "type": "integer",
                "required": False,
                "enum": [1, 2, 3, 4],
            },  # Tier 1 = direct, Tier 2 = sub-supplier
            "parent_supplier_id": {"type": "string", "required": False},
            "tax_id": {"type": "string"},
            "duns_number": {"type": "string"},
            "country": {"type": "string", "pattern": "^[A-Z]{2}$"},
            "region": {"type": "string"},
            "city": {"type": "string"},
            "address_line": {"type": "string"},
            "risk_tier": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
            "certifications": {"type": "array", "items": {"type": "string"}},
            "financial_health_score": {"type": "float", "min": 0, "max": 1},
        },
    },
    "Customer": {
        "category": "Party",
        "source_systems": [
            SourceSystemHint.ERP.value,
            SourceSystemHint.OMS.value,
            SourceSystemHint.SPREADSHEET.value,
            SourceSystemHint.MANUAL.value,
        ],
        "fields": {
            "customer_id": {"type": "string", "required": True},
            "name": {"type": "string", "required": True},
            "segment": {
                "type": "string",
                "enum": ["retail", "wholesale", "ecommerce", "b2b", "government"],
            },
            "tax_id": {"type": "string"},
            "country": {"type": "string", "pattern": "^[A-Z]{2}$"},
            "region": {"type": "string"},
            "city": {"type": "string"},
            "address_line": {"type": "string"},
            "credit_status": {
                "type": "string",
                "enum": ["approved", "conditional", "on_hold", "blocked"],
            },
        },
    },
    "Carrier": {
        "category": "Party",
        "source_systems": [
            SourceSystemHint.TMS.value,
            SourceSystemHint.SPREADSHEET.value,
            SourceSystemHint.MANUAL.value,
        ],
        "fields": {
            "carrier_id": {"type": "string", "required": True},
            "name": {"type": "string", "required": True},
            "scac_code": {
                "type": "string",
                "pattern": "^[A-Z]{2,4}$",
            },  # Standard Carrier Alpha Code
            "modes": {
                "type": "array",
                "items": {"type": "string", "enum": ["road", "rail", "sea", "air", "multimodal"]},
            },
            "regions_served": {"type": "array", "items": {"type": "string"}},
            "capacity_tier": {"type": "string", "enum": ["small", "medium", "large", "enterprise"]},
            "reliability_score": {"type": "float", "min": 0, "max": 1},
        },
    },
    # ─── Facility ────────────────────────────────────────────────────────────
    "Warehouse": {
        "category": "Facility",
        "source_systems": [
            SourceSystemHint.WMS.value,
            SourceSystemHint.ERP.value,
            SourceSystemHint.SCM_PLANNING.value,
            SourceSystemHint.MANUAL.value,
        ],
        "fields": {
            "warehouse_id": {"type": "string", "required": True},
            "name": {"type": "string", "required": True},
            "warehouse_type": {
                "type": "string",
                "enum": [
                    "distribution_center",
                    "fulfillment_center",
                    "cross_dock",
                    "cold_storage",
                    "hazmat",
                    "bulk",
                    "value_added_services",
                ],
            },
            "country": {"type": "string", "pattern": "^[A-Z]{2}$"},
            "region": {"type": "string"},
            "city": {"type": "string"},
            "address_line": {"type": "string"},
            "timezone": {"type": "string"},
            "capacity_cubic_meters": {"type": "float", "min": 0},
            "capacity_pallet_positions": {"type": "integer", "min": 0},
            "operator_supplier_id": {"type": "string"},
            "operating_hours": {"type": "string"},  # e.g., "24/7", "Mon-Fri 8-18"
            "certifications": {"type": "array", "items": {"type": "string"}},
        },
    },
    "Plant": {
        "category": "Facility",
        "source_systems": [
            SourceSystemHint.ERP.value,
            SourceSystemHint.MES.value,
            SourceSystemHint.SCM_PLANNING.value,
            SourceSystemHint.MANUAL.value,
        ],
        "fields": {
            "plant_id": {"type": "string", "required": True},
            "name": {"type": "string", "required": True},
            "plant_type": {
                "type": "string",
                "enum": ["manufacturing", "assembly", "packaging", "processing", "fabrication"],
            },
            "country": {"type": "string", "pattern": "^[A-Z]{2}$"},
            "region": {"type": "string"},
            "city": {"type": "string"},
            "address_line": {"type": "string"},
            "timezone": {"type": "string"},
            "daily_capacity_units": {"type": "float", "min": 0},
            "capacity_unit": {"type": "string"},
            "operator_supplier_id": {"type": "string"},
            "shifts_per_day": {"type": "integer", "min": 1, "max": 3},
            "certifications": {"type": "array", "items": {"type": "string"}},
        },
    },
    "DistributionCenter": {
        "category": "Facility",
        "source_systems": [
            SourceSystemHint.WMS.value,
            SourceSystemHint.ERP.value,
            SourceSystemHint.SCM_PLANNING.value,
            SourceSystemHint.MANUAL.value,
        ],
        "fields": {
            "dc_id": {"type": "string", "required": True},
            "name": {"type": "string", "required": True},
            "dc_type": {
                "type": "string",
                "enum": ["regional", "national", "cross_dock", "transload", "last_mile"],
            },
            "country": {"type": "string", "pattern": "^[A-Z]{2}$"},
            "region": {"type": "string"},
            "city": {"type": "string"},
            "address_line": {"type": "string"},
            "timezone": {"type": "string"},
            "capacity_cubic_meters": {"type": "float", "min": 0},
            "served_regions": {"type": "array", "items": {"type": "string"}},
        },
    },
    "Port": {
        "category": "Facility",
        "source_systems": [
            SourceSystemHint.TMS.value,
            SourceSystemHint.SPREADSHEET.value,
            SourceSystemHint.MANUAL.value,
        ],
        "fields": {
            "port_id": {"type": "string", "required": True},
            "name": {"type": "string", "required": True},
            "unlocode": {"type": "string", "pattern": "^[A-Z]{5}$"},  # UN/LOCODE
            "country": {"type": "string", "pattern": "^[A-Z]{2}$"},
            "port_type": {"type": "string", "enum": ["sea", "inland", "air", "rail"]},
            "terminal_operator": {"type": "string"},
            "berths_available": {"type": "integer"},
            "max_draft_meters": {"type": "float"},
        },
    },
    "CrossDock": {
        "category": "Facility",
        "source_systems": [
            SourceSystemHint.WMS.value,
            SourceSystemHint.TMS.value,
            SourceSystemHint.MANUAL.value,
        ],
        "fields": {
            "crossdock_id": {"type": "string", "required": True},
            "name": {"type": "string", "required": True},
            "country": {"type": "string", "pattern": "^[A-Z]{2}$"},
            "region": {"type": "string"},
            "city": {"type": "string"},
            "inbound_doors": {"type": "integer"},
            "outbound_doors": {"type": "integer"},
            "max_throughput_pallets_per_hour": {"type": "float"},
        },
    },
    # ─── Product & BOM ───────────────────────────────────────────────────────
    "Product": {
        "category": "Catalog",
        "source_systems": [
            SourceSystemHint.ERP.value,
            SourceSystemHint.MES.value,
            SourceSystemHint.SPREADSHEET.value,
            SourceSystemHint.MANUAL.value,
        ],
        "fields": {
            "sku": {"type": "string", "required": True, "pattern": "^[A-Z0-9\\-]{1,64}$"},
            "name": {"type": "string", "required": True},
            "description": {"type": "string"},
            "category": {"type": "string"},
            "subcategory": {"type": "string"},
            "uom": {"type": "string", "required": True},  # base UOM
            "uom_conversions": {"type": "object"},  # e.g., {"case": 12, "pallet": 48}
            "hs_code": {"type": "string", "pattern": "^\\d{6,10}$"},
            "weight_kg": {"type": "float", "min": 0},
            "volume_m3": {"type": "float", "min": 0},
            "dimensions_mm": {"type": "object"},  # {"L": 100, "W": 50, "H": 30}
            "hazmat_class": {"type": "string"},
            "shelf_life_days": {"type": "integer", "min": 0},
            "requires_cold_chain": {"type": "boolean", "default": False},
            "is_finished_good": {"type": "boolean", "default": False},
            "is_raw_material": {"type": "boolean", "default": False},
            "is_subassembly": {"type": "boolean", "default": False},
            "standard_cost": {"type": "float", "min": 0},
            "currency": {"type": "string", "pattern": "^[A-Z]{3}$"},
        },
    },
    "BOM": {
        "category": "Catalog",
        "source_systems": [
            SourceSystemHint.ERP.value,
            SourceSystemHint.MES.value,
            SourceSystemHint.SPREADSHEET.value,
            SourceSystemHint.MANUAL.value,
        ],
        "fields": {
            "bom_id": {"type": "string", "required": True},
            "parent_sku": {"type": "string", "required": True},
            "child_sku": {"type": "string", "required": True},
            "quantity_per": {"type": "float", "min": 0, "required": True},
            "uom": {"type": "string", "required": True},
            "scrap_rate": {"type": "float", "min": 0, "max": 1, "default": 0},
            "substitute_allowed": {"type": "boolean", "default": False},
            "substitute_skus": {"type": "array", "items": {"type": "string"}},
            "operation_sequence": {"type": "integer", "min": 1},
            "effective_from": {"type": "string", "format": "date"},
            "effective_to": {"type": "string", "format": "date"},
            "revision": {"type": "string"},
        },
    },
    # ─── Inventory & Lots ────────────────────────────────────────────────────
    "InventoryItem": {
        "category": "Operational",
        "source_systems": [
            SourceSystemHint.WMS.value,
            SourceSystemHint.ERP.value,
            SourceSystemHint.MES.value,
        ],
        "fields": {
            "inventory_id": {"type": "string", "required": True},
            "facility_id": {"type": "string", "required": True},
            "sku": {"type": "string", "required": True},
            "lot_number": {"type": "string"},
            "serial_number": {"type": "string"},
            "quantity": {"type": "float", "min": 0, "required": True},
            "uom": {"type": "string", "required": True},
            "condition": {
                "type": "string",
                "enum": [
                    "new",
                    "in_transit",
                    "damaged",
                    "quarantined",
                    "reserved",
                    "available",
                    "expired",
                    "recalled",
                ],
            },
            "location_zone": {"type": "string"},
            "location_aisle": {"type": "string"},
            "location_rack": {"type": "string"},
            "location_bin": {"type": "string"},
            "received_date": {"type": "string", "format": "date-time"},
            "expiry_date": {"type": "string", "format": "date-time"},
            "supplier_lot_id": {"type": "string"},
            "cost_per_unit": {"type": "float", "min": 0},
            "currency": {"type": "string", "pattern": "^[A-Z]{3}$"},
        },
    },
    "InventoryLot": {
        "category": "Operational",
        "source_systems": [
            SourceSystemHint.WMS.value,
            SourceSystemHint.ERP.value,
            SourceSystemHint.MES.value,
        ],
        "fields": {
            "lot_id": {"type": "string", "required": True},
            "sku": {"type": "string", "required": True},
            "supplier_id": {"type": "string"},
            "manufacture_date": {"type": "string", "format": "date"},
            "expiry_date": {"type": "string", "format": "date"},
            "quality_status": {
                "type": "string",
                "enum": ["approved", "quarantined", "rejected", "under_review"],
            },
            "quantity_total": {"type": "float", "min": 0},
            "quantity_available": {"type": "float", "min": 0},
            "receiving_po_id": {"type": "string"},
            "country_of_origin": {"type": "string", "pattern": "^[A-Z]{2}$"},
        },
    },
    # ─── Orders & Shipments ──────────────────────────────────────────────────
    "PurchaseOrder": {
        "category": "Operational",
        "source_systems": [SourceSystemHint.ERP.value, SourceSystemHint.MANUAL.value],
        "fields": {
            "po_number": {"type": "string", "required": True},
            "supplier_id": {"type": "string", "required": True},
            "buyer_org_id": {"type": "string", "required": True},
            "status": {
                "type": "string",
                "enum": [
                    "draft",
                    "open",
                    "confirmed",
                    "partially_received",
                    "received",
                    "closed",
                    "cancelled",
                ],
            },
            "currency": {"type": "string", "pattern": "^[A-Z]{3}$", "required": True},
            "placed_at": {"type": "string", "format": "date-time", "required": True},
            "promised_delivery_at": {"type": "string", "format": "date-time"},
            "ship_to_facility_id": {"type": "string"},
            "incoterm": {"type": "string"},
            "total_value": {"type": "float", "min": 0},
            "lines": {"type": "array", "items": {"type": "object"}},
        },
    },
    "PurchaseOrderLine": {
        "category": "Operational",
        "source_systems": [SourceSystemHint.ERP.value, SourceSystemHint.MANUAL.value],
        "fields": {
            "line_number": {"type": "integer", "min": 1, "required": True},
            "sku": {"type": "string", "required": True},
            "quantity": {"type": "float", "min": 0, "required": True},
            "uom": {"type": "string", "required": True},
            "unit_price": {"type": "float", "min": 0},
            "currency": {"type": "string", "pattern": "^[A-Z]{3}$"},
            "promised_delivery_at": {"type": "string", "format": "date-time"},
            "received_quantity": {"type": "float", "min": 0, "default": 0},
        },
    },
    "SalesOrder": {
        "category": "Operational",
        "source_systems": [
            SourceSystemHint.ERP.value,
            SourceSystemHint.OMS.value,
            SourceSystemHint.MANUAL.value,
        ],
        "fields": {
            "so_number": {"type": "string", "required": True},
            "customer_id": {"type": "string", "required": True},
            "status": {
                "type": "string",
                "enum": [
                    "draft",
                    "open",
                    "confirmed",
                    "partially_fulfilled",
                    "fulfilled",
                    "closed",
                    "cancelled",
                ],
            },
            "currency": {"type": "string", "pattern": "^[A-Z]{3}$", "required": True},
            "placed_at": {"type": "string", "format": "date-time", "required": True},
            "promised_delivery_at": {"type": "string", "format": "date-time"},
            "ship_from_facility_id": {"type": "string"},
            "incoterm": {"type": "string"},
            "total_value": {"type": "float", "min": 0},
            "lines": {"type": "array", "items": {"type": "object"}},
        },
    },
    "Shipment": {
        "category": "Operational",
        "source_systems": [
            SourceSystemHint.TMS.value,
            SourceSystemHint.ERP.value,
            SourceSystemHint.WMS.value,
            SourceSystemHint.EXTERNAL_FEED.value,
        ],
        "fields": {
            "shipment_id": {"type": "string", "required": True},
            "origin_facility_id": {"type": "string"},
            "origin_supplier_id": {"type": "string"},
            "destination_facility_id": {"type": "string"},
            "destination_customer_id": {"type": "string"},
            "carrier_id": {"type": "string"},
            "mode": {"type": "string", "enum": ["road", "rail", "sea", "air", "multimodal"]},
            "etd": {"type": "string", "format": "date-time"},
            "atd": {"type": "string", "format": "date-time"},
            "eta": {"type": "string", "format": "date-time"},
            "ata": {"type": "string", "format": "date-time"},
            "status": {
                "type": "string",
                "enum": [
                    "planned",
                    "dispatched",
                    "in_transit",
                    "arrived",
                    "delayed",
                    "exception",
                    "delivered",
                    "cancelled",
                ],
            },
            "route_id": {"type": "string"},
            "equipment_type": {"type": "string"},
            "hazardous": {"type": "boolean", "default": False},
            "cost": {"type": "float", "min": 0},
            "currency": {"type": "string", "pattern": "^[A-Z]{3}$"},
            "stops": {"type": "array", "items": {"type": "object"}},
            "cargo_lines": {"type": "array", "items": {"type": "object"}},
        },
    },
    "Route": {
        "category": "Operational",
        "source_systems": [
            SourceSystemHint.TMS.value,
            SourceSystemHint.SCM_PLANNING.value,
            SourceSystemHint.MANUAL.value,
        ],
        "fields": {
            "route_id": {"type": "string", "required": True},
            "origin_facility_id": {"type": "string", "required": True},
            "destination_facility_id": {"type": "string", "required": True},
            "mode": {"type": "string", "enum": ["road", "rail", "sea", "air", "multimodal"]},
            "distance_km": {"type": "float", "min": 0},
            "transit_time_hours": {"type": "float", "min": 0},
            "cost": {"type": "float", "min": 0},
            "currency": {"type": "string", "pattern": "^[A-Z]{3}$"},
            "risk_index": {"type": "float", "min": 0, "max": 1},
            "waypoints": {"type": "array", "items": {"type": "object"}},
            "carrier_preferences": {"type": "array", "items": {"type": "string"}},
        },
    },
    # ─── Regions & Geography ─────────────────────────────────────────────────
    "Region": {
        "category": "Reference",
        "source_systems": [
            SourceSystemHint.ERP.value,
            SourceSystemHint.SCM_PLANNING.value,
            SourceSystemHint.MANUAL.value,
        ],
        "fields": {
            "region_id": {"type": "string", "required": True},
            "name": {"type": "string", "required": True},
            "country": {"type": "string", "pattern": "^[A-Z]{2}$", "required": True},
            "parent_region_id": {"type": "string"},
            "region_type": {
                "type": "string",
                "enum": ["country", "state", "province", "county", "city", "metro", "custom"],
            },
            "timezone": {"type": "string"},
        },
    },
    "DemandRegion": {
        "category": "Reference",
        "source_systems": [
            SourceSystemHint.SCM_PLANNING.value,
            SourceSystemHint.OMS.value,
            SourceSystemHint.MANUAL.value,
        ],
        "fields": {
            "demand_region_id": {"type": "string", "required": True},
            "name": {"type": "string", "required": True},
            "served_by_facilities": {"type": "array", "items": {"type": "string"}},
            "forecast_horizon_days": {"type": "integer", "min": 1},
        },
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Relationship Catalog (extends 02-ontology.md R1-R14)
# ─────────────────────────────────────────────────────────────────────────────

EXPANDED_RELATIONSHIPS = {
    # Party → Party
    "SUPPLIES": {
        "source": "Supplier",
        "target": "Product",
        "required": True,
        "evidence_required": True,
    },
    "PARENT_OF": {
        "source": "Supplier",
        "target": "Supplier",
        "required": False,
        "description": "Tier hierarchy",
    },
    "CARRIES_FOR": {"source": "Carrier", "target": "Route", "required": True},
    # Facility → Facility
    "FEEDS": {"source": "Facility", "target": "Facility", "description": "Supply flow"},
    "SERVES": {"source": "Facility", "target": "DemandRegion", "required": True},
    "LOCATED_IN": {"source": "Facility", "target": "Region", "required": True},
    # Product → Product (BOM)
    "HAS_COMPONENT": {
        "source": "Product",
        "target": "Product",
        "required": True,
        "evidence_required": True,
    },
    "SUBSTITUTES_FOR": {"source": "Product", "target": "Product", "required": False},
    # Inventory
    "STORES": {"source": "Facility", "target": "InventoryItem", "required": True},
    "BELONGS_TO_LOT": {"source": "InventoryItem", "target": "InventoryLot", "required": False},
    "HAS_LOT": {"source": "Facility", "target": "InventoryLot", "required": False},
    # Orders
    "ORDERS": {"source": "PurchaseOrder", "target": "Product", "required": True},
    "FULFILLS": {"source": "Shipment", "target": "PurchaseOrder", "required": True},
    "FULFILLS_SO": {"source": "Shipment", "target": "SalesOrder", "required": True},
    "SHIPS_FROM": {"source": "Shipment", "target": "Facility", "required": True},
    "SHIPS_TO": {"source": "Shipment", "target": "Facility", "required": True},
    "CARRIED_BY": {"source": "Shipment", "target": "Carrier", "required": True},
    "USES_ROUTE": {"source": "Shipment", "target": "Route", "required": True},
    # Routing
    "CONNECTS": {"source": "Route", "target": "Facility", "required": True},
    "TRAVERSES_REGION": {"source": "Route", "target": "Region", "required": False},
    # Demand
    "DEMANDS": {"source": "DemandRegion", "target": "Product", "required": False},
    "SERVES_DEMAND": {"source": "Facility", "target": "DemandRegion", "required": False},
}

# ─────────────────────────────────────────────────────────────────────────────
# Enums (Frozen)
# ─────────────────────────────────────────────────────────────────────────────

FROZEN_ENUMS = {
    "supplier_tier": [1, 2, 3, 4],
    "supplier_risk_tier": ["low", "medium", "high", "critical"],
    "warehouse_type": [
        "distribution_center",
        "fulfillment_center",
        "cross_dock",
        "cold_storage",
        "hazmat",
        "bulk",
        "value_added_services",
    ],
    "plant_type": ["manufacturing", "assembly", "packaging", "processing", "fabrication"],
    "dc_type": ["regional", "national", "cross_dock", "transload", "last_mile"],
    "port_type": ["sea", "inland", "air", "rail"],
    "product_uom": ["each", "case", "pallet", "kg", "lb", "m3", "liter", "meter", "roll"],
    "hazmat_class": [
        "1.1",
        "1.2",
        "1.3",
        "1.4",
        "1.5",
        "1.6",
        "2.1",
        "2.2",
        "2.3",
        "3",
        "4.1",
        "4.2",
        "4.3",
        "5.1",
        "5.2",
        "6.1",
        "6.2",
        "7",
        "8",
        "9",
    ],
    "inventory_condition": [
        "new",
        "in_transit",
        "damaged",
        "quarantined",
        "reserved",
        "available",
        "expired",
        "recalled",
    ],
    "po_status": [
        "draft",
        "open",
        "confirmed",
        "partially_received",
        "received",
        "closed",
        "cancelled",
    ],
    "so_status": [
        "draft",
        "open",
        "confirmed",
        "partially_fulfilled",
        "fulfilled",
        "closed",
        "cancelled",
    ],
    "shipment_mode": ["road", "rail", "sea", "air", "multimodal"],
    "shipment_status": [
        "planned",
        "dispatched",
        "in_transit",
        "arrived",
        "delayed",
        "exception",
        "delivered",
        "cancelled",
    ],
    "route_mode": ["road", "rail", "sea", "air", "multimodal"],
    "region_type": ["country", "state", "province", "county", "city", "metro", "custom"],
    "customer_segment": ["retail", "wholesale", "ecommerce", "b2b", "government"],
    "carrier_mode": ["road", "rail", "sea", "air", "multimodal"],
    "credit_status": ["approved", "conditional", "on_hold", "blocked"],
    "lot_quality_status": ["approved", "quarantined", "rejected", "under_review"],
}
