"""Feature Extractors — Compute features from raw data."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import networkx as nx
from sqlalchemy import select

from app.modules.supply_chain.models import (
    Component,
    Customer,
    Edge,
    Factory,
    Inventory,
    Order,
    Product,
    Supplier,
    Warehouse,
)


class GraphFeatureExtractor:
    """Extracts graph structural features."""

    def __init__(self, workspace_id: UUID):
        self.workspace_id = workspace_id
        self.graph: nx.DiGraph | None = None

    async def build_graph(self, db) -> nx.DiGraph:
        """Build NetworkX graph from database."""
        G = nx.DiGraph()

        # Add nodes
        suppliers = await db.execute(
            select(Supplier).where(Supplier.workspace_id == self.workspace_id)
        )
        for s in suppliers.scalars():
            G.add_node(f"supplier:{s.id}", type="supplier", name=s.name, tier=s.tier)

        components = await db.execute(
            select(Component).where(Component.workspace_id == self.workspace_id)
        )
        for c in components.scalars():
            G.add_node(f"component:{c.id}", type="component", sku=c.sku, name=c.name)

        warehouses = await db.execute(
            select(Warehouse).where(Warehouse.workspace_id == self.workspace_id)
        )
        for w in warehouses.scalars():
            G.add_node(f"warehouse:{w.id}", type="warehouse", code=w.code, name=w.name)

        factories = await db.execute(
            select(Factory).where(Factory.workspace_id == self.workspace_id)
        )
        for f in factories.scalars():
            G.add_node(f"factory:{f.id}", type="factory", code=f.code, name=f.name)

        products = await db.execute(
            select(Product).where(Product.workspace_id == self.workspace_id)
        )
        for p in products.scalars():
            G.add_node(f"product:{p.id}", type="product", sku=p.sku, name=p.name)

        customers = await db.execute(
            select(Customer).where(Customer.workspace_id == self.workspace_id)
        )
        for c in customers.scalars():
            G.add_node(f"customer:{c.id}", type="customer", name=c.name)

        # Add edges
        edges = await db.execute(select(Edge).where(Edge.workspace_id == self.workspace_id))
        for e in edges.scalars():
            G.add_edge(
                f"{e.from_type}:{e.from_id}",
                f"{e.to_type}:{e.to_id}",
                relationship=e.edge_type,
                weight=e.weight or 1.0,
            )

        self.graph = G
        return G

    def extract_node_features(self, node_id: str) -> dict[str, float]:
        """Extract structural features for a single node."""
        if not self.graph:
            return {}

        features = {}

        # Degree features
        in_deg = self.graph.in_degree(node_id)
        out_deg = self.graph.out_degree(node_id)
        features["in_degree"] = float(in_deg)
        features["out_degree"] = float(out_deg)
        features["total_degree"] = float(in_deg + out_deg)

        # Centrality
        try:
            features["degree_centrality"] = nx.degree_centrality(self.graph).get(node_id, 0.0)
        except Exception:
            features["degree_centrality"] = 0.0

        # Reachability
        try:
            downstream = nx.descendants(self.graph, node_id)
            upstream = nx.ancestors(self.graph, node_id)
            features["downstream_reach"] = float(len(downstream))
            features["upstream_reach"] = float(len(upstream))
        except Exception:
            features["downstream_reach"] = 0.0
            features["upstream_reach"] = 0.0

        # Depth
        try:
            features["downstream_depth"] = float(
                max(
                    len(p)
                    for p in nx.all_simple_paths(
                        self.graph, node_id, list(nx.descendants(self.graph, node_id))
                    )
                )
                if nx.descendants(self.graph, node_id)
                else 0
            )
        except Exception:
            features["downstream_depth"] = 0.0

        try:
            features["upstream_depth"] = float(
                max(
                    len(p)
                    for p in nx.all_simple_paths(
                        self.graph, list(nx.ancestors(self.graph, node_id)), node_id
                    )
                )
                if nx.ancestors(self.graph, node_id)
                else 0
            )
        except Exception:
            features["upstream_depth"] = 0.0

        # Centrality measures (approximate for large graphs)
        try:
            features["betweenness"] = nx.betweenness_centrality(
                self.graph, k=min(100, self.graph.number_of_nodes())
            ).get(node_id, 0.0)
        except Exception:
            features["betweenness"] = 0.0

        try:
            features["closeness"] = nx.closeness_centrality(self.graph).get(node_id, 0.0)
        except Exception:
            features["closeness"] = 0.0

        # Structural roles
        features["is_source"] = 1.0 if self.graph.in_degree(node_id) == 0 else 0.0
        features["is_sink"] = 1.0 if self.graph.out_degree(node_id) == 0 else 0.0

        return features

    def extract_workspace_features(self) -> dict[str, Any]:
        """Extract workspace-level graph features."""
        if not self.graph:
            return {}

        features = {}
        G = self.graph

        features["node_count"] = float(G.number_of_nodes())
        features["edge_count"] = float(G.number_of_edges())
        features["connected_components"] = float(nx.number_weakly_connected_components(G))

        degrees = [d for _, d in G.degree()]
        if degrees:
            features["max_degree"] = float(max(degrees))
            features["avg_degree"] = float(sum(degrees) / len(degrees))
            sorted_deg = sorted(degrees)
            idx_95 = int(0.95 * len(sorted_deg))
            features["p95_degree"] = float(sorted_deg[min(idx_95, len(sorted_deg) - 1)])

        # SPOF nodes
        spof_count = sum(1 for n in G.nodes() if G.in_degree(n) == 1 and G.out_degree(n) > 1)
        features["single_point_of_failure_nodes"] = float(spof_count)

        # High betweenness
        try:
            bet = nx.betweenness_centrality(G, k=min(100, self.graph.number_of_nodes()))
            high_bet = sum(1 for v in bet.values() if v > 0.1)
            features["high_betweenness_nodes"] = float(high_bet)
        except Exception:
            features["high_betweenness_nodes"] = 0.0

        # Isolated nodes
        isolated = sum(1 for n in G.nodes() if G.degree(n) == 0)
        features["isolated_nodes"] = float(isolated)

        # Concentration risk
        try:
            bet = nx.betweenness_centrality(G, k=min(100, self.graph.number_of_nodes()))
            avg_bet = sum(bet.values()) / len(bet) if bet else 0
            features["avg_betweenness"] = float(avg_bet)
        except Exception:
            features["avg_betweenness"] = 0.0

        return features


class BusinessFeatureExtractor:
    """Extracts business-domain features."""

    def __init__(self, workspace_id: UUID):
        self.workspace_id = workspace_id

    def extract_supplier_features(self, supplier, db) -> dict[str, float]:
        features = {}

        # Basic attributes
        features["tier"] = float({"tier_1": 1, "tier_2": 2, "tier_3": 3}.get(str(supplier.tier), 3))
        features["lead_time_days"] = float(supplier.lead_time_days or 0)
        features["risk_score"] = float(supplier.risk_score or 0)

        # Status encoding
        status_map = {"active": 1, "disrupted": 0.5, "disabled": 0}
        features["status_encoded"] = float(status_map.get(str(supplier.status), 0))

        # Country risk (simplified)
        country_risk = {"CN": 0.7, "US": 0.2, "DE": 0.1, "JP": 0.2, "KR": 0.3, "TW": 0.4}
        features["country_risk"] = country_risk.get(supplier.country, 0.5)

        return features

    def extract_component_features(self, component, db) -> dict[str, float]:
        features = {}

        # Category encoding
        cat_map = {
            "Semiconductor": 1.0,
            "PCB": 2.0,
            "Sensor": 3.0,
            "Actuator": 3.0,
            "Resistor": 4.0,
            "Capacitor": 4.0,
            "Coil": 5.0,
            "Fastener": 6.0,
            "Housing": 7.0,
            "Wire": 8.0,
        }
        features["category_encoded"] = float(cat_map.get(component.category, 0))

        # Unit of measure
        uom_map = {"EA": 1.0, "KG": 2.0, "M": 3.0}
        features["uom_encoded"] = float(uom_map.get(component.unit_of_measure, 0))

        return features

    def extract_product_features(self, product, db) -> dict[str, float]:
        features = {}
        features["unit_price"] = float(product.unit_price or 0)
        features["lead_time_days"] = float(product.lead_time_days or 0)
        features["has_factory"] = 1.0 if product.factory_id else 0.0
        return features

    def extract_warehouse_features(self, warehouse, db) -> dict[str, float]:
        features = {}
        features["capacity_units"] = float(warehouse.capacity_units or 0)
        return features

    def extract_customer_features(self, customer, db) -> dict[str, float]:
        features = {}
        tier_map = {"gold": 3.0, "silver": 2.0, "bronze": 1.0}
        features["tier_encoded"] = float(tier_map.get(customer.tier, 1))
        features["contract_value"] = float(customer.contract_value_annual or 0)
        return features

    def extract_inventory_features(self, inventory, component, warehouse, db) -> dict[str, float]:
        features = {}
        features["quantity"] = float(inventory.quantity or 0)
        features["safety_stock"] = float(inventory.safety_stock or 0)
        features["coverage_ratio"] = (
            float(inventory.quantity) / max(1, float(inventory.safety_stock))
            if inventory.safety_stock and inventory.safety_stock > 0
            else 0.0
        )
        return features

    def extract_order_features(self, order, db) -> dict[str, float]:
        features = {}
        features["quantity"] = float(order.quantity or 0)
        status_map = {
            "pending": 1.0,
            "confirmed": 2.0,
            "in_production": 3.0,
            "shipped": 4.0,
            "delivered": 5.0,
            "delayed": 0.5,
        }
        features["status_encoded"] = float(status_map.get(str(order.status), 1.0))
        return features


class ContextFeatureExtractor:
    """Extracts temporal and operational context features."""

    def __init__(self, workspace_id: UUID):
        self.workspace_id = workspace_id

    def extract_temporal_features(self, db) -> dict[str, float]:
        """Extract time-based features."""
        now = datetime.now(UTC)
        features = {
            "hour_of_day": float(now.hour),
            "day_of_week": float(now.weekday()),
            "day_of_month": float(now.day),
            "month": float(now.month),
            "quarter": float((now.month - 1) // 3 + 1),
            "is_weekend": 1.0 if now.weekday() >= 5 else 0.0,
        }
        return features

    def extract_freshness_features(
        self, last_updated: datetime, now: datetime | None = None
    ) -> dict[str, float]:
        """Compute data freshness features."""
        if now is None:
            now = datetime.now(UTC)

        if last_updated.tzinfo is None:
            last_updated = last_updated.replace(tzinfo=UTC)

        age_hours = (now - last_updated).total_seconds() / 3600
        features = {
            "age_hours": age_hours,
            "is_fresh_1h": 1.0 if age_hours <= 1 else 0.0,
            "is_fresh_6h": 1.0 if age_hours <= 6 else 0.0,
            "is_fresh_24h": 1.0 if age_hours <= 24 else 0.0,
            "is_stale_7d": 1.0 if age_hours > 168 else 0.0,
        }
        return features


class FeatureExtractorOrchestrator:
    """Orchestrates all feature extractors."""

    def __init__(self, workspace_id: UUID):
        self.workspace_id = workspace_id
        self.graph_extractor = GraphFeatureExtractor(workspace_id)
        self.business_extractor = BusinessFeatureExtractor(workspace_id)
        self.context_extractor = ContextFeatureExtractor(workspace_id)

    async def extract_all(self, db) -> dict[str, dict[str, float]]:
        """Extract all features for all entities."""
        # Build graph first
        await self.graph_extractor.build_graph(db)

        all_features = {}

        # Supplier features
        suppliers = await db.execute(
            select(Supplier).where(Supplier.workspace_id == self.workspace_id)
        )
        for s in suppliers.scalars():
            node_id = f"supplier:{s.id}"
            feats = {}
            feats.update(self.business_extractor.extract_supplier_features(s, db))
            feats.update(self.graph_extractor.extract_node_features(node_id))
            all_features[node_id] = feats

        # Component features
        components = await db.execute(
            select(Component).where(Component.workspace_id == self.workspace_id)
        )
        for c in components.scalars():
            node_id = f"component:{c.id}"
            feats = {}
            feats.update(self.business_extractor.extract_component_features(c, db))
            feats.update(self.graph_extractor.extract_node_features(node_id))
            all_features[node_id] = feats

        # Warehouse features
        warehouses = await db.execute(
            select(Warehouse).where(Warehouse.workspace_id == self.workspace_id)
        )
        for w in warehouses.scalars():
            node_id = f"warehouse:{w.id}"
            feats = {}
            feats.update(self.business_extractor.extract_warehouse_features(w, db))
            feats.update(self.graph_extractor.extract_node_features(node_id))
            all_features[node_id] = feats

        # Factory features
        factories = await db.execute(
            select(Factory).where(Factory.workspace_id == self.workspace_id)
        )
        for f in factories.scalars():
            node_id = f"factory:{f.id}"
            feats = {}
            feats.update(
                self.business_extractor.extract_factory_features(f, db)
                if hasattr(self.business_extractor, "extract_factory_features")
                else {}
            )
            feats.update(self.graph_extractor.extract_node_features(node_id))
            all_features[node_id] = feats

        # Product features
        products = await db.execute(
            select(Product).where(Product.workspace_id == self.workspace_id)
        )
        for p in products.scalars():
            node_id = f"product:{p.id}"
            feats = {}
            feats.update(self.business_extractor.extract_product_features(p, db))
            feats.update(self.graph_extractor.extract_node_features(node_id))
            all_features[node_id] = feats

        # Customer features
        customers = await db.execute(
            select(Customer).where(Customer.workspace_id == self.workspace_id)
        )
        for c in customers.scalars():
            node_id = f"customer:{c.id}"
            feats = {}
            feats.update(self.business_extractor.extract_customer_features(c, db))
            feats.update(self.graph_extractor.extract_node_features(node_id))
            all_features[node_id] = feats

        # Inventory features
        inventory = await db.execute(
            select(Inventory).where(Inventory.workspace_id == self.workspace_id)
        )
        for inv in inventory.scalars():
            node_id = f"inventory:{inv.id}"
            comp = await db.get(Component, inv.component_id)
            wh = await db.get(Warehouse, inv.warehouse_id)
            if comp and wh:
                feats = self.business_extractor.extract_inventory_features(inv, comp, wh, db)
                all_features[node_id] = feats

        # Order features
        orders = await db.execute(select(Order).where(Order.workspace_id == self.workspace_id))
        for o in orders.scalars():
            node_id = f"order:{o.id}"
            feats = self.business_extractor.extract_order_features(o, db)
            all_features[node_id] = feats

        # Workspace-level features
        all_features["workspace"] = self.graph_extractor.extract_workspace_features()
        all_features["workspace"].update(self.context_extractor.extract_temporal_features(db))

        return all_features


__all__ = [
    "GraphFeatureExtractor",
    "BusinessFeatureExtractor",
    "ContextFeatureExtractor",
    "FeatureExtractorOrchestrator",
]
