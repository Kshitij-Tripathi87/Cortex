"""Dataset Statistics — Statistical summaries of dataset contents."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

from app.modules.datasets.models import DatasetStatistics, SchemaVersion


class StatisticsComputer:
    """Computes statistical summaries of dataset contents."""

    def __init__(self, dataset_path: Path, schema_version: SchemaVersion = SchemaVersion.V2):
        self.dataset_path = Path(dataset_path)
        self.schema_version = schema_version

    def compute(self) -> DatasetStatistics:
        """Compute all statistics for the dataset."""
        stats = DatasetStatistics()

        # Load all CSV data
        data = self._load_all_csvs()

        # Basic counts
        stats.suppliers = len(data.get("suppliers", []))
        stats.components = len(data.get("components", []))
        stats.warehouses = len(data.get("warehouses", []))
        stats.factories = len(data.get("factories", []))
        stats.products = len(data.get("products", []))
        stats.customers = len(data.get("customers", []))
        stats.edges = len(data.get("edges", []))
        stats.inventory_records = len(data.get("inventory", []))
        stats.bom_records = len(data.get("bom", []))
        stats.orders = len(data.get("orders", []))
        stats.disruption_scenarios = len(data.get("disruptions", []))

        stats.total_entities = (
            stats.suppliers
            + stats.components
            + stats.warehouses
            + stats.factories
            + stats.products
            + stats.customers
        )

        # Distributions
        stats.supplier_tier_distribution = self._count_supplier_tiers(data.get("suppliers", []))
        stats.component_category_distribution = self._count_component_categories(data.get("components", []))
        stats.inventory_by_tier = self._inventory_by_tier(
            data.get("inventory", []), data.get("components", [])
        )
        stats.order_status_distribution = self._count_order_statuses(data.get("orders", []))
        stats.scenario_type_distribution = self._count_scenario_types(data.get("disruptions", []))

        # Graph metrics
        stats.avg_supplier_degree = self._avg_supplier_degree(data)
        stats.avg_component_degree = self._avg_component_degree(data)

        return stats

    def _load_all_csvs(self) -> dict[str, list[dict]]:
        """Load all CSV files into memory."""
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
        data = {}
        for key, filename in csv_files.items():
            filepath = self.dataset_path / filename
            if filepath.exists():
                with open(filepath, encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    data[key] = list(reader)
            else:
                data[key] = []

        # Load ground truth if present
        gt_path = self.dataset_path / "ground_truth.json"
        if gt_path.exists():
            with open(gt_path) as f:
                data["disruptions"] = json.load(f).get("disruptions", [])
        else:
            data["disruptions"] = []

        return data

    def _count_supplier_tiers(self, suppliers: list[dict]) -> dict[str, int]:
        counts = Counter()
        for s in suppliers:
            tier = s.get("tier", "unknown")
            counts[tier] += 1
        return dict(counts)

    def _count_component_categories(self, components: list[dict]) -> dict[str, int]:
        counts = Counter()
        for c in components:
            cat = c.get("category", "unknown")
            counts[cat] += 1
        return dict(counts)

    def _inventory_by_tier(
        self, inventory: list[dict], components: list[dict]
    ) -> dict[str, int]:
        # Map component SKU to tier (via supplier)
        # For simplicity, just count total inventory by component
        tier_counts = Counter()
        for inv in self.data.get("inventory", []):
            tier = "unknown"
            # Could map through BOM -> product -> factory -> supplier -> tier
            # For now just aggregate
            tier_counts["all"] = tier_counts.get("all", 0) + int(
                inv.get("quantity", 0)
            )
        return dict(tier_counts)

    def _count_order_statuses(self, orders: list[dict]) -> dict[str, int]:
        counts = Counter()
        for o in orders:
            status = o.get("status", "unknown")
            counts[status] += 1
        return dict(counts)

    def _count_scenario_types(self, disruptions: list[dict]) -> dict[str, int]:
        counts = Counter()
        for d in disruptions:
            st = d.get("disruption_type", "unknown")
            counts[st] += 1
        return dict(counts)

    def _avg_supplier_degree(self, data: dict) -> float:
        """Average out-degree of supplier nodes in the graph."""
        edges = data.get("edges", [])
        supplier_edges = [e for e in edges if e.get("from_type") == "supplier"]
        if not supplier_edges:
            return 0.0
        supplier_names = set(e.get("from_ref") for e in supplier_edges)
        return len(supplier_edges) / max(1, len(supplier_names))

    def _avg_component_degree(self, data: dict) -> float:
        """Average degree of component nodes."""
        edges = data.get("edges", [])
        component_edges = [
            e for e in edges if e.get("from_type") == "component" or e.get("to_type") == "component"
        ]
        if not component_edges:
            return 0.0
        component_nodes = set()
        for e in component_edges:
            if e.get("from_type") == "component":
                component_nodes.add(e.get("from_ref"))
            if e.get("to_type") == "component":
                component_nodes.add(e.get("to_ref"))
        return len(component_edges) / max(1, len(component_nodes))


def compute_statistics(
    dataset_path: Path, schema_version: str = "2.0"
) -> DatasetStatistics:
    """Convenience function to compute dataset statistics."""
    computer = StatisticsComputer(Path(dataset_path), SchemaVersion(schema_version))
    return computer.compute()


__all__ = ["StatisticsComputer", "compute_statistics"]
