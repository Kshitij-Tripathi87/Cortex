"""Generate a deterministic, referentially complete, Olist-shaped fixture dataset.

Produces the five CSVs consumed by ``OlistAdapter`` under
``backend/tests/fixtures/olist/`` so the Nexus vertical-slice pipeline runs
hermetically (no external downloads) with stable assertions:

- 220 orders / ~330 order items / 60 products / 40 suppliers / 180 customers
- One supplier (sup000) is deliberately degraded: its purchase -> carrier
  handoff latency is far above the cross-supplier baseline, so the anomaly
  signal path fires from REAL data.
- Every foreign key resolves by construction, so relationship coverage is
  genuinely ~100% instead of an artifact of disjoint row caps.

Seed is fixed; regenerating produces byte-identical output.
"""

from __future__ import annotations

import csv
import os
import random
from datetime import datetime, timedelta

SEED = 20260825
OUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tests",
    "fixtures",
    "olist",
)

N_ORDERS = 220
N_CUSTOMERS = 180
N_PRODUCTS = 60
N_SUPPLIERS = 40
DEGRADED_SUPPLIER = "sup000"
DEGRADED_ORDERS = 45  # orders routed to the degraded supplier

STATES = {
    "SP": ["sao paulo", "campinas", "santos"],
    "RJ": ["rio de janeiro", "niteroi"],
    "MG": ["belo horizonte", "uberlandia"],
    "RS": ["porto alegre"],
    "PR": ["curitiba"],
    "BA": ["salvador"],
}

ORDER_STATUSES = ["delivered"] * 21 + ["shipped"] * 2 + ["approved"]


def _dt(s: str) -> str:
    return s  # datetime.strftime already yields ISO-ish "YYYY-MM-DD HH:MM:SS"


def main() -> None:
    rng = random.Random(SEED)
    os.makedirs(OUT_DIR, exist_ok=True)

    state_codes = sorted(STATES)

    def pick_city(state: str) -> str:
        return rng.choice(STATES[state])

    base_date = datetime(2017, 3, 1, 8, 0, 0)

    # ── Suppliers ────────────────────────────────────────────────────────
    suppliers = []
    for i in range(N_SUPPLIERS):
        state = state_codes[i % len(state_codes)]
        suppliers.append(
            {
                "seller_id": f"sup{i:03d}",
                "seller_zip_code_prefix": f"{10000 + i * 7 % 80000:05d}",
                "seller_city": pick_city(state),
                "seller_state": state,
            }
        )

    # ── Customers ────────────────────────────────────────────────────────
    customers = []
    for i in range(N_CUSTOMERS):
        state = state_codes[(i // 3) % len(state_codes)]
        customers.append(
            {
                "customer_id": f"cust{i:03d}",
                "customer_unique_id": f"cuniq{i:03d}",
                "customer_zip_code_prefix": f"{20000 + i * 13 % 70000:05d}",
                "customer_city": pick_city(state),
                "customer_state": state,
            }
        )

    # ── Products ─────────────────────────────────────────────────────────
    categories = [
        "bed_bath_table", "health_beauty", "sports_leisure",
        "computers_accessories", "housewares", "auto",
    ]
    products = []
    for i in range(N_PRODUCTS):
        w = rng.randint(150, 18000)
        products.append(
            {
                "product_id": f"prod{i:03d}",
                "product_category_name": categories[i % len(categories)],
                "product_name_lenght": rng.randint(25, 60),
                "product_description_lenght": rng.randint(100, 3000),
                "product_photos_qty": rng.randint(1, 5),
                "product_weight_g": w,
                "product_length_cm": max(5, int(w ** 0.5) % 60 + 5),
                "product_height_cm": rng.randint(5, 50),
                "product_width_cm": rng.randint(5, 50),
            }
        )

    # ── Orders + items ───────────────────────────────────────────────────
    # Order → supplier assignment: the first DEGRADED_ORDERS orders go to the
    # degraded supplier; the rest are spread over the remaining suppliers,
    # guaranteeing every supplier has >= 4 dated samples for the latency stats.
    other_suppliers = [s["seller_id"] for s in suppliers[1:]]
    order_supplier: list[str] = []
    for i in range(N_ORDERS):
        if i < DEGRADED_ORDERS:
            order_supplier.append(DEGRADED_SUPPLIER)
        else:
            order_supplier.append(other_suppliers[(i - DEGRADED_ORDERS) % len(other_suppliers)])

    orders_rows = []
    items_rows = []
    item_seq = 0
    for i in range(N_ORDERS):
        # 6-hour spacing keeps the whole dataset inside a realistic ~8-week window.
        purchase = base_date + timedelta(hours=i * 6, minutes=rng.randint(0, 59))
        approved = purchase + timedelta(hours=rng.randint(1, 20))
        if ORDER_STATUSES[i % len(ORDER_STATUSES)] == "delivered":
            handoff_days = rng.uniform(6.5, 9.5) if order_supplier[i] == DEGRADED_SUPPLIER else rng.uniform(1.0, 3.0)
            carrier = purchase + timedelta(days=handoff_days)
            delivered = carrier + timedelta(days=rng.uniform(4.0, 12.0))
        elif ORDER_STATUSES[i % len(ORDER_STATUSES)] == "shipped":
            handoff_days = rng.uniform(6.5, 9.5) if order_supplier[i] == DEGRADED_SUPPLIER else rng.uniform(1.0, 3.0)
            carrier = purchase + timedelta(days=handoff_days)
            delivered = ""
        else:
            carrier = ""
            delivered = ""
        estimated = purchase + timedelta(days=rng.uniform(15.0, 30.0))

        customer = customers[rng.randrange(N_CUSTOMERS)]
        oid = f"ord{i:03d}"
        orders_rows.append(
            {
                "order_id": oid,
                "customer_id": customer["customer_id"],
                "order_status": ORDER_STATUSES[i % len(ORDER_STATUSES)],
                "order_purchase_timestamp": _dt(purchase.strftime("%Y-%m-%d %H:%M:%S")),
                "order_approved_at": _dt(approved.strftime("%Y-%m-%d %H:%M:%S")) if carrier or approved else "",
                "order_delivered_carrier_date": _dt(carrier.strftime("%Y-%m-%d %H:%M:%S")) if carrier else "",
                "order_delivered_customer_date": _dt(delivered.strftime("%Y-%m-%d %H:%M:%S")) if delivered else "",
                "order_estimated_delivery_date": _dt(estimated.strftime("%Y-%m-%d %H:%M:%S")),
            }
        )

        n_items = rng.choice([1, 1, 1, 2])
        for k in range(n_items):
            product = products[rng.randrange(N_PRODUCTS)]
            item_seq += 1
            items_rows.append(
                {
                    "order_id": oid,
                    "order_item_id": str(item_seq),  # globally unique sequence, as in the real dataset
                    "product_id": product["product_id"],
                    "seller_id": order_supplier[i],
                    "shipping_limit_date": _dt((purchase + timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")),
                    "price": f"{rng.uniform(39.9, 299.9):.2f}",
                    "freight_value": f"{rng.uniform(5.0, 35.0):.2f}",
                }
            )

    # ── Write CSVs (column names match _OLIST_MAPPINGS exactly) ─────────
    def write_csv(name: str, rows: list[dict], columns: list[str]) -> None:
        path = os.path.join(OUT_DIR, name)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)

    write_csv(
        "olist_sellers_dataset.csv",
        suppliers,
        ["seller_id", "seller_zip_code_prefix", "seller_city", "seller_state"],
    )
    write_csv(
        "olist_customers_dataset.csv",
        customers,
        [
            "customer_id", "customer_unique_id", "customer_zip_code_prefix",
            "customer_city", "customer_state",
        ],
    )
    write_csv(
        "olist_orders_dataset.csv",
        orders_rows,
        [
            "order_id", "customer_id", "order_status", "order_purchase_timestamp",
            "order_approved_at", "order_delivered_carrier_date",
            "order_delivered_customer_date", "order_estimated_delivery_date",
        ],
    )
    write_csv(
        "olist_order_items_dataset.csv",
        items_rows,
        [
            "order_id", "order_item_id", "product_id", "seller_id",
            "shipping_limit_date", "price", "freight_value",
        ],
    )
    write_csv(
        "olist_products_dataset.csv",
        products,
        [
            "product_id", "product_category_name", "product_name_lenght",
            "product_description_lenght", "product_photos_qty",
            "product_weight_g", "product_length_cm", "product_height_cm",
            "product_width_cm",
        ],
    )

    print(f"fixture written to {OUT_DIR}")
    print(f"orders={len(orders_rows)} items={len(items_rows)} suppliers={N_SUPPLIERS}")


if __name__ == "__main__":
    main()
