"""Golden Supply Chain Dataset v1 — regression test corpus.

This dataset contains realistic supply-chain exports with intentional
anomalies to exercise the evidence pipeline:

- ERP exports (purchase orders, inventory)
- WMS exports (warehouse stock, movements)
- TMS exports (shipments, routes)
- Master data (suppliers, products, customers)

Each file has intentional issues:
- duplicates (exact and fuzzy)
- conflicts (same entity, different values)
- missing required fields
- stale data
- route failures
- supplier failures
- warehouse outages

These files are used by the regression test suite to verify
end-to-end pipeline behavior.
"""

GOLDEN_DATASET_VERSION = "v1.0.0"
GOLDEN_DATASET_DESCRIPTION = """
Golden Supply Chain Dataset v1.0.0

Contains 7 synthetic files covering core supply-chain entities with
controlled anomalies for regression testing.
"""

# 1. ERP Purchase Orders (CSV)
ERP_PURCHASE_ORDERS_CSV = """po_number,supplier_id,buyer_id,placed_at,promised_delivery_at,ship_to_facility_id,incoterm,currency,total_value,line_count
PO-20260115-001,SUP-001,BUYER-001,2026-01-15T10:00:00Z,2026-02-01T10:00:00Z,WH-001,FOB,USD,125000.00,5
PO-20260115-002,SUP-002,BUYER-001,2026-01-15T11:00:00Z,2026-02-05T10:00:00Z,WH-002,CIF,EUR,98000.00,3
PO-20260115-003,SUP-001,BUYER-001,2026-01-15T12:00:00Z,2026-02-01T10:00:00Z,WH-001,FOB,USD,125000.00,5
PO-20260115-004,SUP-003,BUYER-002,2026-01-15T14:00:00Z,2026-02-10T10:00:00Z,PLANT-001,DDP,CNY,560000.00,8
PO-20260116-001,SUP-004,BUYER-001,2026-01-16T09:00:00Z,2026-02-15T10:00:00Z,WH-003,FOB,USD,210000.00,12
"""

# 2. ERP Purchase Order Lines (CSV) - includes duplicate lines
ERP_PO_LINES_CSV = """po_number,line_number,product_sku,quantity,unit,unit_price,promised_delivery_at
PO-20260115-001,1,SKU-001,1000,each,25.00,2026-02-01T10:00:00Z
PO-20260115-001,2,SKU-002,500,each,50.00,2026-02-01T10:00:00Z
PO-20260115-001,3,SKU-003,200,case,150.00,2026-02-01T10:00:00Z
PO-20260115-001,4,SKU-004,100,pallet,500.00,2026-02-01T10:00:00Z
PO-20260115-001,5,SKU-005,50,each,200.00,2026-02-01T10:00:00Z
PO-20260115-002,1,SKU-006,1000,each,35.00,2026-02-05T10:00:00Z
PO-20260115-002,2,SKU-007,500,case,80.00,2026-02-05T10:00:00Z
PO-20260115-002,3,SKU-008,200,each,120.00,2026-02-05T10:00:00Z
PO-20260115-003,1,SKU-001,1000,each,25.00,2026-02-01T10:00:00Z
PO-20260115-003,2,SKU-002,500,each,50.00,2026-02-01T10:00:00Z
PO-20260115-003,3,SKU-003,200,case,150.00,2026-02-01T10:00:00Z
PO-20260115-003,4,SKU-004,100,pallet,500.00,2026-02-01T10:00:00Z
PO-20260115-003,5,SKU-005,50,each,200.00,2026-02-01T10:00:00Z
"""

# 3. WMS Inventory Snapshot (CSV) - with stale data and conflicts
WMS_INVENTORY_CSV = """facility_id,product_sku,lot_number,condition,quantity,unit,as_of
WH-001,SKU-001,LOT-001,new,1500,each,2026-01-15T06:00:00Z
WH-001,SKU-001,LOT-002,new,500,each,2026-01-15T06:00:00Z
WH-001,SKU-002,LOT-003,new,800,each,2026-01-15T06:00:00Z
WH-001,SKU-003,LOT-004,damaged,50,each,2026-01-15T06:00:00Z
WH-001,SKU-003,LOT-005,new,150,each,2026-01-15T06:00:00Z
WH-002,SKU-004,LOT-006,new,200,pallet,2026-01-15T06:00:00Z
WH-002,SKU-005,LOT-007,quarantined,50,each,2026-01-15T06:00:00Z
WH-002,SKU-006,LOT-008,new,2000,each,2026-01-14T06:00:00Z
WH-003,SKU-007,LOT-009,new,1000,each,2026-01-15T06:00:00Z
WH-003,SKU-008,LOT-010,new,500,each,2026-01-15T06:00:00Z
WH-003,SKU-001,LOT-011,new,2000,each,2026-01-15T06:00:00Z
"""

# 4. TMS Shipments (CSV) - with route failures and delays
TMS_SHIPMENTS_CSV = """shipment_id,origin_facility_id,destination_facility_id,carrier,mode,etd,atd,eta,ata,status,route_id,cost_usd
SHIP-001,SUP-001,WH-001,CARRIER-A,road,2026-01-15T08:00:00Z,2026-01-15T08:15:00Z,2026-01-16T08:00:00Z,2026-01-16T10:30:00Z,delayed,ROUTE-001,5000
SHIP-002,SUP-002,WH-002,CARRIER-B,rail,2026-01-15T10:00:00Z,2026-01-15T10:00:00Z,2026-01-18T10:00:00Z,2026-01-18T09:45:00Z,delivered,ROUTE-002,12000
SHIP-003,SUP-003,PLANT-001,CARRIER-C,sea,2026-01-10T00:00:00Z,2026-01-10T00:00:00Z,2026-02-01T00:00:00Z,,in_transit,ROUTE-003,45000
SHIP-004,SUP-004,WH-003,CARRIER-A,road,2026-01-16T08:00:00Z,2026-01-16T08:30:00Z,2026-01-17T08:00:00Z,2026-01-17T08:15:00Z,delivered,ROUTE-004,3500
SHIP-005,SUP-001,WH-002,CARRIER-B,road,2026-01-15T12:00:00Z,,2026-01-16T12:00:00Z,,exception,ROUTE-005,4200
SHIP-006,SUP-005,WH-001,CARRIER-A,road,2026-01-15T14:00:00Z,2026-01-15T14:15:00Z,2026-01-16T14:00:00Z,2026-01-16T14:15:00Z,delivered,ROUTE-001,3800
SHIP-007,SUP-002,WH-003,CARRIER-C,rail,2026-01-15T16:00:00Z,2026-01-15T16:00:00Z,2026-01-17T16:00:00Z,2026-01-17T18:30:00Z,delayed,ROUTE-002,11000
"""

# 5. Master Data - Suppliers (CSV) - with duplicate supplier
MASTER_SUPPLIERS_CSV = """supplier_id,legal_name,tax_id,country,city,address_line,risk_tier,currency
SUP-001,Acme Logistics Co.,US12345678,US,Chicago,123 Main St,low,USD
SUP-002,Global Parts Inc.,GB87654321,GB,London,456 High St,medium,EUR
SUP-003,Pacific Manufacturing Ltd.,CN11223344,CN,Shanghai,789 Nanjing Rd,high,CNY
SUP-004,Atlantic Supplies Corp.,US99887766,US,New York,321 Broadway,low,USD
SUP-005,Acme Logistics Co.,US12345678,US,Chicago,123 Main St,low,USD
SUP-006,Northern Components AB,SE55667788,SE,Stockholm,555 Drottninggatan,medium,EUR
"""

# 6. Master Data - Products (CSV)
MASTER_PRODUCTS_CSV = """sku,name,category,subcategory,uom,weight_per_unit,weight_unit,volume_per_unit,volume_unit,hs_code,shelf_life_days
SKU-001,Widget A,Components,Electronic,each,0.1,kg,0.001,m3,8542.31,365
SKU-002,Widget B,Components,Mechanical,each,0.2,kg,0.002,m3,8481.90,365
SKU-003,Gadget Assembly,Assemblies,Electromechanical,case,5.0,kg,0.05,m3,8538.90,180
SKU-004,Container X,Containers,Shipping,pallet,200.0,kg,2.0,m3,8609.00,730
SKU-005,Sensor Module,Components,Electronic,each,0.05,kg,0.0005,m3,8541.40,365
SKU-006,Fastener Kit,Components,Hardware,case,1.5,kg,0.01,m3,7318.15,730
SKU-007,Control Unit,Components,Electronic,each,0.3,kg,0.003,m3,8542.31,365
SKU-008,Power Supply,Components,Electrical,each,0.8,kg,0.008,m3,8504.40,365
"""

# 7. TMS Routes (CSV) - with disrupted route
TMS_ROUTES_CSV = """route_id,origin_facility_id,destination_facility_id,mode,distance_km,transit_time_hours,cost_usd,risk_index
ROUTE-001,SUP-001,WH-001,road,500,10,5000,0.15
ROUTE-002,SUP-002,WH-002,rail,800,48,12000,0.08
ROUTE-003,SUP-003,PLANT-001,sea,12000,336,45000,0.25
ROUTE-004,SUP-004,WH-003,road,300,6,3500,0.12
ROUTE-005,SUP-001,WH-002,road,600,12,4200,0.85
"""

# Expected anomaly counts for regression verification
EXPECTED_ANOMALIES = {
    "erp_purchase_orders": {
        "duplicate_po": 1,  # PO-20260115-001 and PO-20260115-003 are identical
        "duplicate_po_lines": 5,  # PO-001 and PO-003 have identical lines
    },
    "wms_inventory": {
        "stale_snapshot": 1,  # WH-002 SKU-006 is from previous day
        "damaged_inventory": 1,  # SKU-003 LOT-004 damaged
        "quarantined_inventory": 1,  # SKU-005 LOT-007 quarantined
    },
    "tms_shipments": {
        "delayed": 2,  # SHIP-001, SHIP-007
        "exception": 1,  # SHIP-005
        "in_transit": 1,  # SHIP-003
    },
    "master_suppliers": {
        "duplicate_supplier": 1,  # SUP-001 and SUP-005 are same entity
    },
    "tms_routes": {
        "high_risk_route": 1,  # ROUTE-005 risk_index 0.85
    },
}

# Expected pipeline outcomes after processing
EXPECTED_PIPELINE_OUTCOMES = {
    "source_batches": 7,
    "source_files": 7,
    "column_profiles": 7 * 8,  # ~8 columns per file
    "evidence_claims": 7 * 8,  # ~1 claim per column
    "conflicts": {
        "total": 6,
        "blocking": 2,  # duplicate PO, duplicate supplier
        "non_blocking": 4,
    },
    "readiness": {
        "ready": 0,  # conflicts block readiness
        "blocked": 1,  # at least one batch blocked
        "review_required": 6,
    },
}
