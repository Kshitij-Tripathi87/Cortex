"""Smoke test for the Real Data Spine stages 1-8."""
import asyncio

from app.modules.nexus_spine.canonical_schema import (
    CanonicalDataset,
    CanonicalTable,
    EntityType,
)
from app.modules.nexus_spine.spine_orchestrator import RealDataSpine

# Build a small canonical dataset inline
dataset = CanonicalDataset(workspace_id="ws_test", organization_id="org_test")

sup_table = CanonicalTable(
    entity_type=EntityType.SUPPLIER,
    rows=[
        {"supplier_id": "S1", "state": "SP", "city": "Sao Paulo", "_source_file": "suppliers.csv", "_source_row": 1},
        {"supplier_id": "S2", "state": "RJ", "city": "Rio", "_source_file": "suppliers.csv", "_source_row": 2},
        {"supplier_id": "S3", "state": "MG", "city": "Belo Horizonte", "_source_file": "suppliers.csv", "_source_row": 3},
    ],
    column_types={"supplier_id": "str", "state": "str", "city": "str"},
    source_file="suppliers.csv",
)

cust_table = CanonicalTable(
    entity_type=EntityType.CUSTOMER,
    rows=[
        {"customer_id": "C1", "state": "SP", "city": "Sao Paulo", "_source_file": "customers.csv", "_source_row": 1},
        {"customer_id": "C2", "state": "RJ", "city": "Rio", "_source_file": "customers.csv", "_source_row": 2},
    ],
    column_types={"customer_id": "str", "state": "str", "city": "str"},
    source_file="customers.csv",
)

order_table = CanonicalTable(
    entity_type=EntityType.ORDER,
    rows=[
        {"order_id": "O1", "customer_id": "C1", "status": "delivered", "price": 150.0, "_source_file": "orders.csv", "_source_row": 1},
        {"order_id": "O2", "customer_id": "C2", "status": "shipped", "price": 250.0, "_source_file": "orders.csv", "_source_row": 2},
        {"order_id": "O3", "customer_id": "C1", "status": "processing", "price": 75.0, "_source_file": "orders.csv", "_source_row": 3},
    ],
    column_types={"order_id": "str", "customer_id": "str", "status": "str", "price": "float"},
    source_file="orders.csv",
)

item_table = CanonicalTable(
    entity_type=EntityType.ORDER_ITEM,
    rows=[
        {"item_id": "I1", "order_id": "O1", "supplier_id": "S1", "product_id": "P1", "price": 150.0, "_source_file": "items.csv", "_source_row": 1},
        {"item_id": "I2", "order_id": "O2", "supplier_id": "S2", "product_id": "P2", "price": 250.0, "_source_file": "items.csv", "_source_row": 2},
        {"item_id": "I3", "order_id": "O3", "supplier_id": "S1", "product_id": "P1", "price": 75.0, "_source_file": "items.csv", "_source_row": 3},
    ],
    column_types={"item_id": "str", "order_id": "str", "supplier_id": "str", "product_id": "str", "price": "float"},
    source_file="items.csv",
)

dataset.tables = {
    EntityType.SUPPLIER: sup_table,
    EntityType.CUSTOMER: cust_table,
    EntityType.ORDER: order_table,
    EntityType.ORDER_ITEM: item_table,
}

spine = RealDataSpine()
result = asyncio.run(spine.run(dataset, organization_id="org_test", workspace_id="ws_test"))

print(f"Status: {result.status}")
print(f"Stages: {len(result.stages)}")
for s in result.stages:
    ev = s.evidence_node_id or "none"
    print(f"  {s.stage_name}: {s.status} (evidence={ev})")

gs = result.graph_summary
print(f"Graph: {gs.get('total_nodes', 0)} nodes, {gs.get('total_edges', 0)} edges")
print(f"Gini: {gs.get('supplier_concentration_gini', 'N/A')}")
cov = gs.get("coverage", {})
print(f"Coverage: {cov.get('relationship_coverage_pct', 'N/A')}% (computed)")
print(f"Orphans: {cov.get('orphan_entities_count', 'N/A')} (computed)")
print(f"Graph version: {cov.get('graph_version', 'N/A')} (computed)")
print(f"World state version: {result.world_state_version}")
print(f"Signals: {len(result.signals)}")
for sig in result.signals:
    print(f"  {sig['signal_type']} on {sig['entity_id']} (sev={sig['severity']})")
br = result.blast_radius or {}
print(f"Blast radius: {br.get('affected_orders_count', 0)} orders, ${br.get('total_revenue_at_risk_usd', 0)}")
print(f"Evidence root: {result.evidence_root_id}")
print("SMOKE TEST PASSED")
