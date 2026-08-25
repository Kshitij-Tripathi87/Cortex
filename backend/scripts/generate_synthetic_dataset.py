"""Synthetic dataset generator — produces CSVs for the MVP wedge tables.

Usage:

    python scripts/generate_synthetic_dataset.py \\
        --workspace acme-corp \\
        --seed 42 \\
        --size medium \\
        --out ./datasets

Output: ten CSV files (one per dataset_type) under --out, ready to upload
via `POST /api/v1/mvp/ingest`. The data references itself by external
identifier (SKU/code/name) so the ingestion ref-resolver can wire edges,
inventory, BOM, and orders against the entity tables in a single pass.

Sizes (MVP execution plan §11):
    small:   10 suppliers,   50 components,   5 warehouses,   3 factories,
             25 products,    10 customers,   100 edges,       50 inventory,
             30 BOM,        100 orders
    medium:  50 suppliers,  200 components,  30 warehouses,  10 factories,
            100 products,   50 customers,   500 edges,      200 inventory,
            100 BOM,        500 orders
    large:  200 suppliers,  800 components, 100 warehouses,  30 factories,
            400 products,  200 customers, 2000 edges,      800 inventory,
            400 BOM,       2000 orders

Determinism: given the same --seed, identical CSVs are produced.
"""

from __future__ import annotations

import argparse
import csv
import random
import string
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# Size presets
# ─────────────────────────────────────────────────────────────────────────────

SIZES: dict[str, dict[str, int]] = {
    "small": {
        "suppliers": 10,
        "components": 50,
        "warehouses": 5,
        "factories": 3,
        "products": 25,
        "customers": 10,
        "edges": 100,
        "inventory": 50,
        "bom": 30,
        "orders": 100,
    },
    "medium": {
        "suppliers": 50,
        "components": 200,
        "warehouses": 30,
        "factories": 10,
        "products": 100,
        "customers": 50,
        "edges": 500,
        "inventory": 200,
        "bom": 100,
        "orders": 500,
    },
    "large": {
        "suppliers": 200,
        "components": 800,
        "warehouses": 100,
        "factories": 30,
        "products": 400,
        "customers": 200,
        "edges": 2000,
        "inventory": 800,
        "bom": 400,
        "orders": 2000,
    },
}

COUNTRIES = ["US", "CN", "DE", "JP", "KR", "TW", "MX", "BR", "GB", "FR"]
SUPPLIER_NAMES = [
    "Apex",
    "Beacon",
    "Cascade",
    "Delta",
    "Echo",
    "Forge",
    "Glen",
    "Helix",
    "Ironclad",
    "Junction",
    "Keystone",
    "Lattice",
    "Meridian",
    "Northbridge",
    "Orion",
    "Pinnacle",
    "Quanta",
    "Ridge",
    "Summit",
    "Tangent",
    "Umbra",
    "Vector",
    "Westgate",
    "Xenon",
    "York",
    "Zenith",
    "Atlas",
    "Beacon",
    "Cobalt",
    "Drift",
    "Eden",
]
COMPONENT_CATEGORIES = [
    "Sensor",
    "Actuator",
    "PCB",
    "Semiconductor",
    "Resistor",
    "Capacitor",
    "Coil",
    "Fastener",
    "Housing",
    "Wire",
]
COMPANY_SUFFIXES = ["Inc", "Corp", "LLC", "Group", "Industries", "Systems", "Manufacturing"]
PRODUCT_WORDS = ["Aurora", "Comet", "Eclipse", "Falcon", "Galaxy", "Halo", "Iris", "Jet"]
WAREHOUSE_CODES = ["WH", "DC", "ST", "RT"]
FACTORY_CODES = ["PL", "FA", "PL", "MF"]


def _rand_str(rng: random.Random, length: int = 6) -> str:
    return "".join(rng.choices(string.ascii_uppercase + string.digits, k=length))


# ─────────────────────────────────────────────────────────────────────────────
# Per-dataset writers
# ─────────────────────────────────────────────────────────────────────────────


def write_suppliers(rng: random.Random, out: Path, count: int) -> list[dict]:
    rows = []
    with out.open("w", newline="") as f:
        w = csv.DictWriter(
            f, fieldnames=["name", "country", "tier", "lead_time_days", "status", "risk_score"]
        )
        w.writeheader()
        for _ in range(count):
            name = f"{rng.choice(SUPPLIER_NAMES)} {_rand_str(rng)}"
            tier = rng.choice(["tier_1", "tier_2", "tier_3"])
            lead = rng.randint(2, 60)
            status = rng.choices(["active", "disrupted", "disabled"], weights=[80, 10, 10])[0]
            risk = round(rng.uniform(0, 1), 4)
            w.writerow(
                {
                    "name": name,
                    "country": rng.choice(COUNTRIES),
                    "tier": tier,
                    "lead_time_days": lead,
                    "status": status,
                    "risk_score": risk,
                }
            )
            rows.append({"name": name, "tier": tier})
    return rows


def write_components(rng: random.Random, out: Path, count: int) -> list[str]:
    skus = []
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["sku", "name", "category", "unit_of_measure"])
        w.writeheader()
        for i in range(count):
            sku = f"COMP-{i:05d}"
            skus.append(sku)
            cat = rng.choice(COMPONENT_CATEGORIES)
            w.writerow(
                {
                    "sku": sku,
                    "name": f"{cat} {_rand_str(rng)}",
                    "category": cat,
                    "unit_of_measure": rng.choice(["EA", "KG", "M"]),
                }
            )
    return skus


def write_warehouses(rng: random.Random, out: Path, count: int) -> list[str]:
    codes = []
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["code", "name", "location", "capacity_units"])
        w.writeheader()
        for i in range(count):
            code = f"{rng.choice(WAREHOUSE_CODES)}-{i:03d}"
            codes.append(code)
            w.writerow(
                {
                    "code": code,
                    "name": f"Warehouse {i}",
                    "location": f"{rng.choice(COUNTRIES)}/{_rand_str(rng)}",
                    "capacity_units": rng.randint(1000, 100000),
                }
            )
    return codes


def write_factories(rng: random.Random, out: Path, count: int) -> list[str]:
    codes = []
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["code", "name", "location", "throughput_per_day"])
        w.writeheader()
        for i in range(count):
            code = f"{rng.choice(FACTORY_CODES)}-{i:02d}"
            codes.append(code)
            w.writerow(
                {
                    "code": code,
                    "name": f"Plant {_rand_str(rng)}",
                    "location": f"{rng.choice(COUNTRIES)}/{_rand_str(rng)}",
                    "throughput_per_day": rng.randint(100, 10000),
                }
            )
    return codes


def write_products(
    rng: random.Random, out: Path, count: int, factory_codes: list[str]
) -> list[str]:
    skus = []
    with out.open("w", newline="") as f:
        w = csv.DictWriter(
            f, fieldnames=["sku", "name", "factory_code", "unit_price", "lead_time_days"]
        )
        w.writeheader()
        for i in range(count):
            sku = f"PROD-{i:05d}"
            skus.append(sku)
            fc = rng.choice(factory_codes) if factory_codes else ""
            w.writerow(
                {
                    "sku": sku,
                    "name": f"{rng.choice(PRODUCT_WORDS)} {_rand_str(rng)}",
                    "factory_code": fc,
                    "unit_price": round(rng.uniform(10, 5000), 4),
                    "lead_time_days": rng.randint(1, 30),
                }
            )
    return skus


def write_customers(rng: random.Random, out: Path, count: int) -> list[str]:
    names = []
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["name", "country", "tier", "contract_value_annual"])
        w.writeheader()
        for _ in range(count):
            name = f"{rng.choice(SUPPLIER_NAMES)} {rng.choice(COMPANY_SUFFIXES)}"
            names.append(name)
            w.writerow(
                {
                    "name": name,
                    "country": rng.choice(COUNTRIES),
                    "tier": rng.choice(["gold", "silver", "bronze"]),
                    "contract_value_annual": round(rng.uniform(50000, 5000000), 4),
                }
            )
    return names


def write_edges(
    rng: random.Random,
    out: Path,
    count: int,
    supplier_names: list[str],
    component_skus: list[str],
    warehouse_codes: list[str],
    factory_codes: list[str],
    product_skus: list[str],
    customer_names: list[str],
) -> None:
    # Build the set of valid edges here — supplier→component (supplies),
    # component→warehouse (stored_in), factory→component (consumes),
    # factory→product (makes), customer→product (orders).
    edge_specs = [
        ("supplier", "supplier", "component", "supplies"),
        ("component", "component", "warehouse", "stored_in"),
        ("factory", "factory", "component", "consumes"),
        ("factory", "factory", "product", "makes"),
        ("customer", "customer", "product", "orders"),
    ]
    with out.open("w", newline="") as f:
        w = csv.DictWriter(
            f, fieldnames=["from_type", "from_ref", "to_type", "to_ref", "edge_type", "weight"]
        )
        w.writeheader()
        for _ in range(count):
            from_type, from_pool, to_type, edge_type = rng.choice(edge_specs)
            if from_type == "supplier" and not supplier_names:
                continue
            if from_type == "component" and not component_skus:
                continue
            if from_type == "factory" and not factory_codes:
                continue
            if from_type == "customer" and not customer_names:
                continue
            if to_type == "component":
                to_ref = rng.choice(component_skus)
            elif to_type == "warehouse":
                to_ref = rng.choice(warehouse_codes)
            elif to_type == "product":
                to_ref = rng.choice(product_skus)
            else:
                to_ref = ""
            if from_pool == "supplier":
                from_ref = rng.choice(supplier_names)
            elif from_pool == "component":
                from_ref = rng.choice(component_skus)
            elif from_pool == "factory":
                from_ref = rng.choice(factory_codes)
            else:
                from_ref = rng.choice(customer_names)
            if not from_ref or not to_ref:
                continue
            w.writerow(
                {
                    "from_type": from_type,
                    "from_ref": from_ref,
                    "to_type": to_type,
                    "to_ref": to_ref,
                    "edge_type": edge_type,
                    "weight": round(rng.uniform(0.5, 2), 4),
                }
            )


def write_inventory(
    rng: random.Random, out: Path, count: int, warehouse_codes: list[str], component_skus: list[str]
) -> None:
    with out.open("w", newline="") as f:
        w = csv.DictWriter(
            f, fieldnames=["warehouse_code", "component_sku", "quantity", "safety_stock"]
        )
        w.writeheader()
        for _ in range(count):
            if not warehouse_codes or not component_skus:
                continue
            w.writerow(
                {
                    "warehouse_code": rng.choice(warehouse_codes),
                    "component_sku": rng.choice(component_skus),
                    "quantity": rng.randint(0, 5000),
                    "safety_stock": rng.randint(0, 500),
                }
            )


def write_bom(
    rng: random.Random, out: Path, count: int, product_skus: list[str], component_skus: list[str]
) -> None:
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["product_sku", "component_sku", "quantity_per_unit"])
        w.writeheader()
        for _ in range(count):
            if not product_skus or not component_skus:
                continue
            w.writerow(
                {
                    "product_sku": rng.choice(product_skus),
                    "component_sku": rng.choice(component_skus),
                    "quantity_per_unit": round(rng.uniform(1, 20), 4),
                }
            )


def write_orders(
    rng: random.Random, out: Path, count: int, customer_names: list[str], product_skus: list[str]
) -> None:
    from datetime import date, timedelta

    base = date(2026, 1, 1)
    with out.open("w", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "customer_name",
                "product_sku",
                "quantity",
                "status",
                "order_date",
                "requested_delivery_date",
                "actual_delivery_date",
            ],
        )
        w.writeheader()
        for _ in range(count):
            if not customer_names or not product_skus:
                continue
            order_date = base + timedelta(days=rng.randint(0, 200))
            requested = order_date + timedelta(days=rng.randint(7, 60))
            status = rng.choice(
                ["pending", "confirmed", "in_production", "shipped", "delivered", "delayed"]
            )
            actual = (
                requested + timedelta(days=rng.randint(-5, 20))
                if status in {"shipped", "delivered"}
                else ""
            )
            w.writerow(
                {
                    "customer_name": rng.choice(customer_names),
                    "product_sku": rng.choice(product_skus),
                    "quantity": rng.randint(1, 1000),
                    "status": status,
                    "order_date": order_date.isoformat(),
                    "requested_delivery_date": requested.isoformat(),
                    "actual_delivery_date": actual.isoformat() if actual else "",
                }
            )


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate synthetic supply-chain CSVs for the MVP wedge."
    )
    parser.add_argument("--workspace", required=True, help="Workspace slug (informational)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--size", choices=list(SIZES.keys()), default="medium")
    parser.add_argument("--out", default="./datasets", help="Output directory for CSV files")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    sizes = SIZES[args.size]
    out_dir = Path(args.out) / args.workspace
    out_dir.mkdir(parents=True, exist_ok=True)

    suppliers = write_suppliers(rng, out_dir / "suppliers.csv", sizes["suppliers"])
    print(f"  suppliers.csv: {sizes['suppliers']} rows")
    components = write_components(rng, out_dir / "components.csv", sizes["components"])
    print(f"  components.csv: {sizes['components']} rows")
    warehouses = write_warehouses(rng, out_dir / "warehouses.csv", sizes["warehouses"])
    print(f"  warehouses.csv: {sizes['warehouses']} rows")
    factories = write_factories(rng, out_dir / "factories.csv", sizes["factories"])
    print(f"  factories.csv: {sizes['factories']} rows")
    products = write_products(rng, out_dir / "products.csv", sizes["products"], factories)
    print(f"  products.csv: {sizes['products']} rows")
    customers = write_customers(rng, out_dir / "customers.csv", sizes["customers"])
    print(f"  customers.csv: {sizes['customers']} rows")
    write_edges(
        rng,
        out_dir / "edges.csv",
        sizes["edges"],
        suppliers,
        components,
        warehouses,
        factories,
        products,
        customers,
    )
    print(f"  edges.csv: {sizes['edges']} rows")
    write_inventory(rng, out_dir / "inventory.csv", sizes["inventory"], warehouses, components)
    print(f"  inventory.csv: {sizes['inventory']} rows")
    write_bom(rng, out_dir / "bom.csv", sizes["bom"], products, components)
    print(f"  bom.csv: {sizes['bom']} rows")
    write_orders(rng, out_dir / "orders.csv", sizes["orders"], customers, products)
    print(f"  orders.csv: {sizes['orders']} rows")

    total = sum(sizes.values())
    print(
        f"\nWrote 10 CSV files to {out_dir.resolve()} ({total} total rows, seed={args.seed}, size={args.size})"
    )


if __name__ == "__main__":
    main()
