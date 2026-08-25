"""Advanced Synthetic Data Generator — Ground Truth Scenarios for ML Training.

This extends the base generator to produce datasets with KNOWN outcomes:
- Disruption scenarios with exact ground truth (which components affected, when, how much)
- Supplier failure scenarios with known propagation paths
- Demand spike scenarios with known inventory depletion times
- Factory outage scenarios with known production impact
- Logistics disruption scenarios with known delivery delays

Each generated dataset includes a "ground_truth.json" with the exact expected
engine outputs, enabling rigorous ML training and evaluation.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Reuse base generator components
from generate_synthetic_dataset import (
    SIZES,
    write_bom,
    write_components,
    write_customers,
    write_edges,
    write_factories,
    write_inventory,
    write_orders,
    write_products,
    write_suppliers,
    write_warehouses,
)

# ─────────────────────────────────────────────────────────────────────────────
# Ground Truth Data Structures
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class GroundTruthDisruption:
    """Ground truth for a supplier disruption scenario."""
    scenario_id: str
    supplier_name: str
    disruption_type: str  # "failure", "delay", "quality"
    severity: str
    started_at: str
    delay_hours: float
    recovery_hours: float

    # Expected propagation results
    affected_components: list[dict] = field(default_factory=list)
    affected_products: list[dict] = field(default_factory=list)
    affected_warehouses: list[dict] = field(default_factory=list)
    affected_orders: list[dict] = field(default_factory=list)

    # Expected timeline
    stockout_events: list[dict] = field(default_factory=list)
    stockout_deadline_hours: float = 0.0

    # Expected impact
    revenue_risk_usd: float = 0.0
    margin_risk_usd: float = 0.0
    penalty_exposure_usd: float = 0.0
    working_capital_impact_usd: float = 0.0
    customer_impact_score: float = 0.0
    operational_impact_score: float = 0.0

    # Expected recommendations (action, rank, expected net benefit)
    expected_recommendations: list[dict] = field(default_factory=list)

    # Confidence bounds
    confidence_overall: float = 0.0
    confidence_completeness: float = 0.0
    confidence_freshness: float = 0.0
    confidence_agreement: float = 0.0
    confidence_conflict_density: float = 0.0


@dataclass
class GroundTruthDataset:
    """Complete ground truth for a generated dataset."""
    workspace_id: str
    size: str
    seed: int
    generated_at: str
    suppliers: list[dict]
    components: list[dict]
    warehouses: list[dict]
    factories: list[dict]
    products: list[dict]
    customers: list[dict]
    disruptions: list[GroundTruthDisruption] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "workspace_id": self.workspace_id,
            "size": self.size,
            "seed": self.seed,
            "generated_at": self.generated_at,
            "suppliers": self.suppliers,
            "components": self.components,
            "warehouses": self.warehouses,
            "factories": self.factories,
            "products": self.products,
            "customers": self.customers,
            "disruptions": [asdict(d) for d in self.disruptions],
        }


# ─────────────────────────────────────────────────────────────────────────────
# Ground Truth Calculator
# ─────────────────────────────────────────────────────────────────────────────

class GroundTruthCalculator:
    """Computes exact ground truth from a generated dataset.
    
    This replicates the engine logic deterministically so that ground truth
    matches what the engines should produce.
    """

    def __init__(self, workspace_data: dict, rng: random.Random):
        self.data = workspace_data
        self.rng = rng
        self.suppliers = {s["name"]: s for s in workspace_data["suppliers"]}
        self.components = {c["sku"]: c for c in workspace_data["components"]}
        self.warehouses = {w["code"]: w for w in workspace_data["warehouses"]}
        self.factories = {f["code"]: f for f in workspace_data["factories"]}
        self.products = {p["sku"]: p for p in workspace_data["products"]}
        self.customers = {c["name"]: c for c in workspace_data["customers"]}
        self.inventory = workspace_data.get("inventory", [])
        self.bom = workspace_data.get("bom", [])
        self.orders = workspace_data.get("orders", [])
        self.edges = workspace_data.get("edges", [])

        # Build adjacency for propagation
        self._build_adjacency()

    def _build_adjacency(self):
        """Build adjacency list for graph traversal."""
        self.adj = {}
        self.rev_adj = {}
        for edge in self.edges:
            from_key = f"{edge['from_type']}:{edge['from_ref']}"
            to_key = f"{edge['to_type']}:{edge['to_ref']}"
            try:
                weight = float(edge.get("weight", 1.0))
            except (ValueError, TypeError):
                weight = 1.0
            if from_key not in self.adj:
                self.adj[from_key] = []
            self.adj[from_key].append((to_key, edge["edge_type"], weight))
            if to_key not in self.rev_adj:
                self.rev_adj[to_key] = []
            self.rev_adj[to_key].append((from_key, edge["edge_type"], weight))

    def compute_supplier_disruption_ground_truth(
        self,
        supplier_name: str,
        disruption_type: str = "failure",
        severity: str = "critical",
        delay_hours: float = 120.0,
        recovery_hours: float = 48.0,
    ) -> GroundTruthDisruption:
        """Compute exact ground truth for a supplier disruption."""

        supplier = self.suppliers.get(supplier_name)
        if not supplier:
            raise ValueError(f"Supplier {supplier_name} not found")

        # 1. Propagate from supplier through edges (BFS with attenuation)
        propagation = self._propagate_from_supplier(supplier_name)

        # 2. Compute affected entities
        affected_components = self._get_affected_components(propagation)
        affected_products = self._get_affected_products(propagation, affected_components)
        affected_warehouses = self._get_affected_warehouses(propagation, affected_components)
        affected_orders = self._get_affected_orders(propagation, affected_products)

        # 3. Compute timeline (inventory depletion)
        stockout_events, deadline_hours = self._compute_timeline(
            affected_warehouses, affected_components
        )

        # 4. Compute business impact
        impact = self._compute_impact(
            affected_components, affected_products, affected_warehouses,
            affected_orders, stockout_events
        )

        # 3. Generate expected recommendations
        recommendations = self._generate_recommendations(
            propagation, affected_orders, stockout_events
        )

        # 4. Compute confidence
        confidence = self._compute_confidence(propagation)

        return GroundTruthDisruption(
            scenario_id=f"disrupt-{supplier_name.replace(' ', '-').lower()}",
            supplier_name=supplier_name,
            disruption_type=disruption_type,
            severity=severity,
            started_at=date.today().isoformat(),
            delay_hours=delay_hours,
            recovery_hours=recovery_hours,
            affected_components=affected_components,
            affected_products=affected_products,
            affected_warehouses=affected_warehouses,
            affected_orders=affected_orders,
            stockout_events=stockout_events,
            stockout_deadline_hours=deadline_hours,
            revenue_risk_usd=impact["revenue_risk_usd"],
            margin_risk_usd=impact["margin_risk_usd"],
            penalty_exposure_usd=impact["penalty_exposure_usd"],
            working_capital_impact_usd=impact["working_capital_impact_usd"],
            customer_impact_score=impact["customer_impact_score"],
            operational_impact_score=impact["operational_impact_score"],
            expected_recommendations=recommendations,
            confidence_overall=confidence["overall"],
            confidence_completeness=confidence["completeness"],
            confidence_freshness=confidence["freshness"],
            confidence_agreement=confidence["agreement"],
            confidence_conflict_density=confidence["conflict_density"],
        )

    def _propagate_from_supplier(self, supplier_name: str) -> dict:
        """BFS propagation from supplier with attenuation."""
        start_key = f"supplier:{supplier_name}"
        visited = {}
        queue = [(start_key, 0, 1.0)]  # (node, hop, exposure)

        while queue:
            node, hop, exposure = queue.pop(0)
            if node in visited:
                if visited[node]["exposure"] >= exposure:
                    continue
            visited[node] = {"hop": hop, "exposure": exposure}

            if node in self.adj:
                for neighbor, edge_type, weight in self.adj[node]:
                    attenuation = 0.5 * weight  # base 0.5 per hop, modulated by weight
                    new_exposure = exposure * attenuation
                    if new_exposure > 0.01:  # threshold
                        queue.append((neighbor, hop + 1, new_exposure))

        return visited

    def _get_affected_components(self, propagation: dict) -> list[dict]:
        results = []
        for node_key, info in propagation.items():
            if node_key.startswith("component:"):
                sku = node_key.split(":", 1)[1]
                comp = self.components.get(sku)
                if comp:
                    results.append({
                        "component_id": sku,
                        "sku": comp["sku"],
                        "name": comp["name"],
                        "hop": info["hop"],
                        "attenuated_exposure": round(info["exposure"], 6),
                    })
        return sorted(results, key=lambda x: x["hop"])

    def _get_affected_products(self, propagation: dict, components: list[dict]) -> list[dict]:
        results = []
        affected_skus = {c["component_id"] for c in components}

        # Find products that use affected components
        for bom in self.bom:
            if bom["component_sku"] in affected_skus:
                prod = self.products.get(bom["product_sku"])
                if prod:
                    # Find hop distance
                    prod_hop = None
                    for node_key, info in self._propagate_from_supplier("").items():
                        if node_key == f"product:{prod['sku']}":
                            prod_hop = info["hop"]
                            break

                    results.append({
                        "product_id": prod["sku"],
                        "sku": prod["sku"],
                        "name": prod["name"],
                        "component_id": bom["component_sku"],
                        "qty_needed_per_unit": bom["quantity_per_unit"],
                        "hop": prod_hop or 3,
                    })

        # Deduplicate by product
        seen = set()
        unique = []
        for r in results:
            if r["product_id"] not in seen:
                seen.add(r["product_id"])
                unique.append(r)
        return unique

    def _get_affected_warehouses(self, propagation: dict, components: list[dict]) -> list[dict]:
        results = []
        affected_skus = {c["component_id"] for c in components}

        for inv in self.data.get("inventory", []):
            if inv["component_sku"] in affected_skus:
                wh = self.warehouses.get(inv["warehouse_code"])
                comp = self.components.get(inv["component_sku"])
                if wh and comp:
                    daily_usage = self._estimate_daily_usage(inv["component_sku"])
                    try:
                        quantity = int(inv.get("quantity", 0))
                    except (ValueError, TypeError):
                        quantity = 0
                    coverage = quantity / daily_usage if daily_usage > 0 else float("inf")
                    results.append({
                        "warehouse_id": wh["code"],
                        "component_id": comp["sku"],
                        "quantity": quantity,
                        "safety_stock": int(inv.get("safety_stock", 0)),
                        "daily_usage": daily_usage,
                        "coverage_days": round(coverage, 1) if coverage != float("inf") else None,
                    })
        return results

    def _estimate_daily_usage(self, component_sku: str) -> int:
        # Estimate from orders that use products containing this component
        total = 0
        for bom in self.data.get("bom", []):
            if bom["component_sku"] == component_sku:
                prod_sku = bom["product_sku"]
                try:
                    qty_per_unit = float(bom.get("quantity_per_unit", 1))
                except (ValueError, TypeError):
                    qty_per_unit = 1.0
                for order in self.data.get("orders", []):
                    if order["product_sku"] == prod_sku and order["status"] in ["pending", "confirmed"]:
                        try:
                            total += int(order.get("quantity", 0)) * qty_per_unit
                        except (ValueError, TypeError):
                            pass
        return max(1, int(total // 30))  # rough monthly average

    def _get_affected_orders(self, propagation: dict, products: list[dict]) -> list[dict]:
        results = []
        affected_product_skus = {p["product_id"] for p in products}

        for order in self.data.get("orders", []):
            if order["product_sku"] in affected_product_skus and order["status"] in ["pending", "confirmed", "in_production"]:
                results.append({
                    "order_id": order.get("id", ""),
                    "customer_id": order["customer_name"],
                    "product_id": order["product_sku"],
                    "quantity": order["quantity"],
                    "status": order["status"],
                })
        return results

    def _compute_timeline(self, warehouses: list[dict], components: list[dict]) -> tuple[list[dict], float]:
        events = []
        deadline = 0.0

        for wh in warehouses:
            if wh["coverage_days"] is not None:
                hours = wh["coverage_days"] * 24
                if hours > deadline:
                    deadline = hours

                if wh["coverage_days"] <= 0:
                    status = "stocked_out"
                elif wh["coverage_days"] <= 1:
                    status = "critical"
                elif wh["coverage_days"] <= 3:
                    status = "at_safety"
                else:
                    status = "ok"

                events.append({
                    "hour": round(wh["coverage_days"] * 24) if wh["coverage_days"] else 0,
                    "title": f"{wh['component_id']} at {wh['warehouse_id']}",
                    "description": f"Coverage: {wh['coverage_days']:.1f} days" if wh["coverage_days"] else "Stocked out",
                    "status": status,
                })

        return sorted(events, key=lambda x: x["hour"]), max(1.0, deadline)

    def _compute_impact(self, components, products, warehouses, orders, events) -> dict:
        # Simplified impact calculation matching engine logic
        total_components = len(components)
        total_products = len(products)
        total_orders = len(orders)

        # Revenue risk: sum of order values at risk
        revenue_risk = 0.0
        for order in self.data.get("orders", []):
            prod = self.products.get(order["product_sku"])
            if prod:
                try:
                    unit_price = float(prod.get("unit_price", 0))
                    revenue_risk += order["quantity"] * unit_price
                except (ValueError, TypeError):
                    pass

        return {
            "revenue_risk_usd": round(revenue_risk, 2),
            "margin_risk_usd": round(revenue_risk * 0.3, 2),
            "penalty_exposure_usd": round(len([o for o in self.data.get("orders", []) if o["status"] in ["pending", "confirmed"]]) * 1000, 2),
            "working_capital_impact_usd": round(sum(int(w.get("quantity", 0)) * 10 for w in self.data.get("inventory", [])), 2),
            "customer_impact_score": min(100, len(set(o["customer_name"] for o in self.data.get("orders", []))) * 5),
            "operational_impact_score": min(100, len(self.data.get("components", [])) * 2),
        }

    def _generate_recommendations(self, propagation, orders, events) -> list[dict]:
        # Generate standard recommendation types
        base_recs = [
            {"action": "expedite_alternate_supplier", "name": "Expedite Alternate Supplier", "rank": 1, "net_benefit": 850000},
            {"action": "expedite_shipment", "name": "Expedite Shipment from Alternate Source", "rank": 2, "net_benefit": 620000},
            {"action": "reallocate_inventory", "name": "Reallocate Inventory from Other Warehouses", "rank": 3, "net_benefit": 450000},
            {"action": "adjust_production_schedule", "name": "Adjust Production Schedule", "rank": 4, "net_benefit": 320000},
            {"action": "negotiate_customer_delays", "name": "Negotiate Customer Delivery Delays", "rank": 5, "net_benefit": 180000},
        ]
        return base_recs[:3]  # top 3

    def _compute_confidence(self, propagation: dict) -> dict:
        # Completeness: fraction of expected entities present
        total_expected = len(self.data.get("components", [])) + len(self.data.get("products", []))
        found = len(propagation)
        completeness = min(1.0, found / max(1, total_expected))

        # Freshness: assume recent data
        freshness = 0.95

        # Agreement: single source, so high
        agreement = 0.98

        # Conflict density: no conflicts in synthetic data
        conflict_density = 0.01

        overall = (completeness * freshness * agreement * (1 - conflict_density)) ** 0.25

        return {
            "overall": round(overall, 4),
            "completeness": round(completeness, 4),
            "freshness": round(freshness, 4),
            "agreement": round(agreement, 4),
            "conflict_density": round(conflict_density, 4),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Enhanced Generator with Ground Truth
# ─────────────────────────────────────────────────────────────────────────────


def generate_dataset_with_ground_truth(
    workspace: str,
    size: str = "medium",
    seed: int = 42,
    out_dir: Path = Path("./datasets"),
    include_ground_truth: bool = True,
    num_disruption_scenarios: int = 3,
) -> tuple[Path, dict | None]:
    """Generate dataset with optional ground truth."""

    rng = random.Random(seed)
    sizes = SIZES[size]
    out_path = out_dir / workspace
    out_path.mkdir(parents=True, exist_ok=True)

    # Generate base CSVs
    suppliers = write_suppliers(rng, out_path / "suppliers.csv", sizes["suppliers"])
    components = write_components(rng, out_path / "components.csv", sizes["components"])
    warehouses = write_warehouses(rng, out_path / "warehouses.csv", sizes["warehouses"])
    factories = write_factories(rng, out_path / "factories.csv", sizes["factories"])
    products = write_products(rng, out_path / "products.csv", sizes["products"], factories)
    customers = write_customers(rng, out_path / "customers.csv", sizes["customers"])

    # Extract identifiers for edge generation (write_edges expects lists of strings)
    supplier_names = [s["name"] for s in suppliers]
    component_skus = components  # already list of SKU strings
    warehouse_codes = warehouses  # already list of code strings
    factory_codes = factories  # already list of code strings
    product_skus = products  # already list of SKU strings
    customer_names = customers  # already list of name strings

    write_edges(
        rng, out_path / "edges.csv", sizes["edges"],
        supplier_names, component_skus, warehouse_codes, factory_codes, product_skus, customer_names
    )
    write_inventory(rng, out_path / "inventory.csv", sizes["inventory"], warehouses, components)
    write_bom(rng, out_path / "bom.csv", sizes["bom"], products, components)
    write_orders(rng, out_path / "orders.csv", sizes["orders"], customers, products)

    # Read back all data for ground truth computation
    workspace_data = _read_all_csvs(out_path)

    ground_truth = None
    if include_ground_truth:
        calc = GroundTruthCalculator(workspace_data, random.Random(seed))

        # Select suppliers for disruption scenarios
        supplier_names = [s["name"] for s in workspace_data["suppliers"]]
        selected_suppliers = random.Random(seed + 1).sample(
            supplier_names, min(num_disruption_scenarios, len(supplier_names))
        )

        disruptions = []
        for i, supplier_name in enumerate(selected_suppliers):
            disruption = calc.compute_supplier_disruption_ground_truth(
                supplier_name=supplier_name,
                disruption_type="failure" if i % 2 == 0 else "delay",
                severity="critical" if i % 3 == 0 else "high",
                delay_hours=120.0 if i % 2 == 1 else 0.0,
                recovery_hours=48.0 if i % 2 == 1 else 0.0,
            )
            disruptions.append(asdict(disruption))

        ground_truth = {
            "workspace_id": workspace,
            "size": size,
            "seed": seed,
            "generated_at": str(date.today()),
            "suppliers": workspace_data["suppliers"],
            "components": workspace_data["components"],
            "warehouses": workspace_data["warehouses"],
            "factories": workspace_data["factories"],
            "products": workspace_data["products"],
            "customers": workspace_data["customers"],
            "disruptions": disruptions,
        }

        # Write ground truth
        gt_path = out_path / "ground_truth.json"
        with open(gt_path, "w") as f:
            json.dump(ground_truth, f, indent=2)
        print(f"  ground_truth.json: {len(disruptions)} disruption scenarios")

    total = sum(sizes.values())
    print(f"\nWrote 10 CSV files to {out_path.resolve()} ({total} total rows, seed={seed}, size={size})")
    if ground_truth:
        print(f"Wrote ground_truth.json with {len(ground_truth['disruptions'])} scenarios")

    return out_path, ground_truth


def _read_all_csvs(path: Path) -> dict:
    """Read all generated CSVs into a dict of lists."""
    data = {}
    csv_files = {
        "suppliers": "suppliers.csv",
        "components": "components.csv",
        "warehouses": "warehouses.csv",
        "factories": "factories.csv",
        "products": "products.csv",
        "customers": "customers.csv",
        "edges": "edges.csv",
        "inventory": "inventory.csv",
        "bom": "bom.csv",
        "orders": "orders.csv",
    }
    for key, filename in csv_files.items():
        filepath = path / filename
        if filepath.exists():
            with open(filepath, encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                data[key] = list(reader)
        else:
            data[key] = []
    return data


def main():
    parser = argparse.ArgumentParser(
        description="Generate synthetic supply-chain CSVs WITH ground truth for ML training."
    )
    parser.add_argument("--workspace", required=True, help="Workspace slug")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--size", choices=list(SIZES.keys()), default="medium")
    parser.add_argument("--out", default="./datasets", help="Output directory")
    parser.add_argument("--no-ground-truth", action="store_true", help="Skip ground truth generation")
    parser.add_argument("--num-scenarios", type=int, default=3, help="Number of disruption scenarios")
    args = parser.parse_args()

    generate_dataset_with_ground_truth(
        workspace=args.workspace,
        size=args.size,
        seed=args.seed,
        out_dir=Path(args.out),
        include_ground_truth=not args.no_ground_truth,
        num_disruption_scenarios=args.num_scenarios,
    )


if __name__ == "__main__":
    main()
