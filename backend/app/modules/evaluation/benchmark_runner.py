"""Benchmark Runner — Runs evaluation benchmarks against ground truth."""

from __future__ import annotations

import csv
import json
import time
from datetime import UTC, datetime
from pathlib import Path

# Import the deterministic engine
from app.modules.disruption.engines.brief import run_morning_brief
from app.modules.disruption.engines.types import (
    DisruptionKind,
    DisruptionScenario,
    SupplyChainSnapshot,
)


class BenchmarkRunner:
    """Runs evaluation benchmarks against ground truth datasets."""

    def __init__(self, dataset_path: str | Path):
        self.dataset_path = Path(dataset_path)
        self.ground_truth = self._load_ground_truth()
        self.snapshot = self._build_snapshot()

    def _load_ground_truth(self) -> dict:
        """Load ground truth from dataset."""
        gt_path = self.dataset_path / "ground_truth.json"
        if not gt_path.exists():
            raise FileNotFoundError(f"No ground_truth.json found in {self.dataset_path}")
        with open(gt_path) as f:
            return json.load(f)

    def _build_snapshot(self) -> SupplyChainSnapshot:
        """Build SupplyChainSnapshot from dataset CSVs."""
        # This mirrors the logic in briefs.py endpoint
        # Load all entities
        suppliers = self._load_suppliers()
        components = self._load_components()
        warehouses = self._load_warehouses()
        factories = self._load_factories()
        products = self._load_products()
        customers = self._load_customers()
        edges = self._load_edges()
        inventory = self._load_inventory()
        boms = self._load_boms()
        orders = self._load_orders()

        return SupplyChainSnapshot(
            workspace_id=self.ground_truth.get("workspace_id", "unknown"),
            as_of=datetime.now(UTC),
            suppliers=tuple(suppliers),
            components=tuple(components),
            warehouses=tuple(warehouses),
            factories=tuple(factories),
            products=tuple(products),
            customers=tuple(customers),
            edges=tuple(edges),
            inventory=tuple(inventory),
            bom=tuple(boms),
            orders=tuple(orders),
        )

    def _load_suppliers(self):
        from app.modules.disruption.engines.types import SupplierData

        suppliers = []
        for row in self._read_csv("suppliers.csv"):
            suppliers.append(
                SupplierData(
                    id=row["id"] if "id" in row else f"sup-{row['name']}",
                    name=row["name"],
                    country=row["country"],
                    tier=row["tier"],
                    lead_time_days=int(row["lead_time_days"]),
                )
            )
        return suppliers

    def _load_components(self):
        from app.modules.disruption.engines.types import ComponentData

        components = []
        for row in self._read_csv("components.csv"):
            components.append(
                ComponentData(
                    id=row["id"] if "id" in row else row["sku"],
                    sku=row["sku"],
                    name=row["name"],
                    category=row.get("category", ""),
                    unit_of_measure=row.get("unit_of_measure", "EA"),
                )
            )
        return components

    def _load_warehouses(self):
        from app.modules.disruption.engines.types import WarehouseData

        warehouses = []
        for row in self._read_csv("warehouses.csv"):
            warehouses.append(
                WarehouseData(
                    id=row["id"] if "id" in row else row["code"],
                    code=row["code"],
                    name=row["name"],
                )
            )
        return warehouses

    def _load_factories(self):
        from app.modules.disruption.engines.types import FactoryData

        factories = []
        for row in self._read_csv("factories.csv"):
            factories.append(
                FactoryData(
                    id=row["id"] if "id" in row else row["code"],
                    code=row["code"],
                    name=row["name"],
                    throughput_per_day=int(row.get("throughput_per_day", 0)),
                )
            )
        return factories

    def _load_products(self):
        from app.modules.disruption.engines.types import ProductData

        products = []
        for row in self._read_csv("products.csv"):
            products.append(
                ProductData(
                    id=row["id"] if "id" in row else row["sku"],
                    sku=row["sku"],
                    name=row["name"],
                    factory_id=row.get("factory_code") or None,
                    unit_price=float(row.get("unit_price", 0)) if row.get("unit_price") else None,
                    lead_time_days=int(row.get("lead_time_days", 7)),
                )
            )
        return products

    def _load_customers(self):
        from app.modules.disruption.engines.types import CustomerData

        customers = []
        for row in self._read_csv("customers.csv"):
            customers.append(
                CustomerData(
                    id=row["id"] if "id" in row else row["name"],
                    name=row["name"],
                    country=row["country"],
                    tier=row.get("tier", ""),
                    contract_value_annual=float(row.get("contract_value_annual", 0))
                    if row.get("contract_value_annual")
                    else None,
                )
            )
        return customers

    def _load_edges(self):
        from app.modules.disruption.engines.types import EdgeData

        edges = []
        for row in self._read_csv("edges.csv"):
            edges.append(
                EdgeData(
                    from_type=row["from_type"],
                    from_id=row["from_ref"],
                    to_type=row["to_type"],
                    to_id=row["to_ref"],
                    edge_type=row["edge_type"],
                    weight=float(row.get("weight", 1.0)),
                )
            )
        return edges

    def _load_inventory(self):
        from app.modules.disruption.engines.types import InventoryData

        inventory = []
        for row in self._read_csv("inventory.csv"):
            last_updated = row.get("last_updated_at")
            if last_updated:
                from datetime import UTC, datetime

                try:
                    last_updated = datetime.fromisoformat(last_updated)
                    if last_updated.tzinfo is None:
                        last_updated = last_updated.replace(tzinfo=UTC)
                except ValueError:
                    last_updated = datetime.now(UTC)
            else:
                from datetime import UTC, datetime

                last_updated = datetime.now(UTC)

            inventory.append(
                InventoryData(
                    warehouse_id=row["warehouse_code"],
                    component_id=row["component_sku"],
                    quantity=int(row.get("quantity", 0)),
                    safety_stock=int(row.get("safety_stock", 0)),
                    daily_usage=int(row.get("daily_usage", 0)),
                    last_updated_at=last_updated,
                )
            )
        return inventory

    def _load_boms(self):
        from app.modules.disruption.engines.types import BomData

        boms = []
        for row in self._read_csv("bom.csv"):
            boms.append(
                BomData(
                    product_id=row["product_sku"],
                    component_id=row["component_sku"],
                    quantity_per_unit=float(row.get("quantity_per_unit", 1)),
                )
            )
        return boms

    def _load_orders(self):
        from app.modules.disruption.engines.types import OrderData

        orders = []
        for row in self._read_csv("orders.csv"):
            # Find product for unit_price
            prod_row = next(
                (p for p in self._read_csv("products.csv") if p["sku"] == row["product_sku"]), None
            )
            unit_price = (
                float(prod_row["unit_price"]) if prod_row and prod_row.get("unit_price") else None
            )

            orders.append(
                OrderData(
                    id=row["id"] if "id" in row else row.get("id", ""),
                    customer_id=row["customer_name"],
                    product_id=row["product_sku"],
                    quantity=int(row.get("quantity", 0)),
                    status=row.get("status", "pending"),
                    order_date=row.get("order_date", ""),
                    requested_delivery_date=row.get("requested_delivery_date", ""),
                    actual_delivery_date=row.get("actual_delivery_date") or None,
                    unit_price=unit_price,
                )
            )
        return orders

    def _read_csv(self, filename: str) -> list[dict]:
        filepath = Path(self.dataset_path) / filename
        if not filepath.exists():
            return []
        with open(filepath, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            return list(reader)

    def run_benchmark(self, engine_type: str = "deterministic") -> dict:
        """Run benchmark on all scenarios in ground truth."""
        gt = self.ground_truth
        gt.get("disruptions", [])

        results = []
        start_time = time.time()

        for disruption in gt.get("disruptions", []):
            scenario_start = time.time()
            disruption.get("scenario_id", "")
            supplier_name = disruption.get("supplier_name", "")

            # Find supplier ID
            supplier_row = next(
                (s for s in self._read_csv("suppliers.csv") if s["name"] == supplier_name), None
            )
            if not supplier_row:
                continue

            supplier_id = supplier_row.get("id", supplier_name)

            # Create scenario
            kind = DisruptionKind.FAILURE
            if disruption.get("disruption_type") == "delay":
                kind = DisruptionKind.DELAY

            scenario = DisruptionScenario(
                workspace_id=gt.get("workspace_id", "test"),
                supplier_id=supplier_id,
                kind=kind,
                severity=disruption.get("severity", "critical"),
                started_at=datetime.now(UTC),
                delay_hours=disruption.get("delay_hours", 0.0),
                recovery_hours=disruption.get("recovery_hours", 0.0),
            )

            # Run engine
            try:
                brief = run_morning_brief(self.snapshot, scenario)
                scenario_time = time.time() - scenario_start

                # Compare with ground truth
                scenario_result = self._compare_with_ground_truth(disruption, brief, scenario_time)
                results.append(scenario_result)

            except Exception as e:
                # Record error
                results.append(
                    {
                        "scenario_id": disruption.get("scenario_id", ""),
                        "supplier_name": supplier_name,
                        "error": str(e),
                        "latency_seconds": time.time() - scenario_start,
                    }
                )

        total_time = time.time() - start_time

        # Aggregate metrics
        aggregate = self._aggregate_results(results)

        return {
            "dataset_id": self.ground_truth.get("workspace_id", "unknown"),
            "engine_type": "deterministic",
            "engine_version": "1.0",
            "total_time_seconds": total_time,
            "scenarios_evaluated": len(results),
            "scenarios_passed": sum(1 for r in results if "error" not in r),
            "scenario_results": results,
            "aggregate_metrics": aggregate,
        }

    def _compare_with_ground_truth(self, gt: dict, brief, latency: float) -> dict:
        """Compare engine output with ground truth."""
        gt_affected_comp = {c["component_id"] for c in gt.get("affected_components", [])}
        gt_affected_prod = {p["product_id"] for p in gt.get("affected_products", [])}
        gt_affected_wh = {w["warehouse_id"] for w in gt.get("affected_warehouses", [])}
        gt_affected_orders = {o["order_id"] for o in gt.get("affected_orders", [])}

        pred_comp = {c.component_id for c in brief.propagation.affected_components}
        pred_prod = {p.product_id for p in brief.propagation.affected_products}
        pred_wh = {w.warehouse_id for w in brief.propagation.affected_warehouses}
        pred_orders = {o.order_id for o in brief.propagation.open_orders_at_risk}

        def pr_recall_f1(gt_set, pred_set):
            if not gt_set and not pred_set:
                return 1.0, 1.0, 1.0, True
            if not gt_set or not pred_set:
                return 0.0, 0.0, 0.0, False
            tp = len(gt_set & pred_set)
            fp = len(pred_set - gt_set)
            fn = len(gt_set - pred_set)
            precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
            exact = gt_set == pred_set
            return precision, recall, f1, exact

        comp_p, comp_r, comp_f1, comp_exact = pr_recall_f1(gt_affected_comp, pred_comp)
        prod_p, prod_r, prod_f1, prod_exact = pr_recall_f1(gt_affected_prod, pred_prod)
        wh_p, wh_r, wh_f1, _ = pr_recall_f1(gt_affected_wh, pred_wh)
        ord_p, ord_r, ord_f1, _ = pr_recall_f1(gt_affected_orders, pred_orders)

        # Revenue error
        gt_rev = gt.get("revenue_risk_usd", 0.0)
        pred_rev = brief.business_impact.revenue_risk_usd
        rev_error = abs(pred_rev - gt_rev)
        rev_rel = rev_error / gt_rev if gt_rev > 0 else 0.0

        # Deadline error
        gt_deadline = gt.get("stockout_deadline_hours", 1.0)
        pred_deadline = 72  # default
        if brief.timeline.stockout_deadline_at:
            delta = brief.timeline.stockout_deadline_at - brief.timeline.bucket_zero
            pred_deadline = max(1, int(delta.total_seconds() / 3600))
        deadline_error = abs(pred_deadline - gt_deadline)

        # Confidence calibration error
        gt_conf = gt.get("confidence_overall", 0.0)
        pred_conf = brief.confidence.overall
        conf_error = abs(pred_conf - gt_conf)

        return {
            "scenario_id": gt.get("scenario_id", ""),
            "supplier_name": gt.get("supplier_name", ""),
            "latency_seconds": 0,  # will be set by caller
            "component_precision": comp_p,
            "component_recall": comp_r,
            "component_f1": comp_f1,
            "component_exact_match": comp_exact,
            "product_precision": prod_p,
            "product_recall": prod_r,
            "product_f1": prod_f1,
            "product_exact_match": prod_exact,
            "warehouse_precision": wh_p,
            "warehouse_recall": wh_r,
            "warehouse_f1": wh_f1,
            "order_precision": ord_p,
            "order_recall": ord_r,
            "order_f1": ord_f1,
            "revenue_error": rev_error,
            "revenue_relative_error": rev_rel,
            "margin_error": abs(
                brief.business_impact.margin_risk_usd - gt.get("margin_risk_usd", 0.0)
            ),
            "penalty_error": abs(
                brief.business_impact.penalty_exposure_usd - gt.get("penalty_exposure_usd", 0.0)
            ),
            "deadline_error": deadline_error,
            "confidence_calibration_error": conf_error,
            "gt_confidence": gt.get("confidence_overall", 0.0),
            "pred_confidence": brief.confidence.overall,
        }

    def _aggregate_results(self, results: list[dict]) -> dict:
        """Compute aggregate metrics across all scenarios."""
        valid = [r for r in results if "error" not in r]
        if not valid:
            return {"error": "No valid scenarios"}

        len(valid)

        def avg(key):
            return sum(r.get(key, 0.0) for r in valid) / len(valid)

        return {
            "component_precision": avg("component_precision"),
            "component_recall": avg("component_recall"),
            "component_f1": avg("component_f1"),
            "component_exact_match_rate": sum(1 for r in valid if r.get("component_exact_match"))
            / len(valid),
            "product_precision": avg("product_precision"),
            "product_recall": avg("product_recall"),
            "product_f1": avg("product_f1"),
            "product_exact_match_rate": sum(1 for r in valid if r.get("product_exact_match"))
            / len(valid),
            "warehouse_precision": avg("warehouse_precision"),
            "warehouse_recall": avg("warehouse_recall"),
            "warehouse_f1": avg("warehouse_f1"),
            "order_precision": avg("order_precision"),
            "order_recall": avg("order_recall"),
            "order_f1": avg("order_f1"),
            "revenue_mae": avg("revenue_error"),
            "revenue_mape": avg("revenue_relative_error"),
            "margin_mae": avg("margin_error"),
            "penalty_mae": avg("penalty_error"),
            "deadline_mae": avg("deadline_error"),
            "calibration_ece": avg("confidence_calibration_error"),
            "scenarios_passed": len(valid),
            "scenarios_total": len(results),
        }


def run_benchmark(
    dataset_path: str | Path,
    engine_type: str = "deterministic",
) -> dict:
    """Convenience function to run benchmark on a dataset."""
    runner = BenchmarkRunner(dataset_path)
    return runner.run_benchmark(engine_type)


__all__ = ["BenchmarkRunner", "run_benchmark"]
