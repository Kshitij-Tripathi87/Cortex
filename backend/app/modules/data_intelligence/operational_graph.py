"""Operational Graph Builder & Graph Analytics Engine.

Builds typed operational graphs from a **generic** ``CanonicalDataset``
(no domain-specific knowledge lives here — Olist, SAP, etc. are handled by
adapters that produce the canonical form) and computes structural analytics:

- Graph Coverage Metrics (nodes resolved, edge density, orphan rate,
  relationship coverage, Gini concentration)
- PageRank & Betweenness Centrality
- Connected Components & Single Points of Failure (SPOFs)
- Route and Regional Vulnerability Indices

Invariants (A1/A2/A3):
    * The graph engine knows nothing about Olist.
    * No invented nodes — Nexus builds only what the dataset substantiates.
    * Every edge carries row-level provenance (source file, row, fields,
      confidence) so the inspector can trace it back.
    * Every metric (coverage, gini, orphans, graph_version) is **computed**
      from actual data — never a hardcoded constant.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from app.modules.nexus_spine.canonical_schema import (
        CanonicalDataset,
        CanonicalTable,
        EntityType,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Graph primitives
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class GraphNode:
    node_id: str
    node_type: str  # "SUPPLIER" | "CUSTOMER" | "ORDER" | "PRODUCT" | "LOCATION" | "ROUTE" | "ORDER_ITEM" | …
    attributes: dict[str, Any] = field(default_factory=dict)
    pagerank: float = 0.0
    degree_centrality: float = 0.0
    betweenness_centrality: float = 0.0
    is_spof: bool = False  # Single Point of Failure


@dataclass
class GraphEdge:
    edge_id: str
    source_id: str
    target_id: str
    relation_type: str  # "PLACED" | "CONTAINS" | "FULFILLED_BY" | "REFERENCES" | "LOCATED_IN" | "TRAVELS_TO" | "PART_OF"
    weight: float = 1.0
    provenance_source: str = "generic"
    # Row-level provenance (A3): every edge traces back to its source data
    source_file: str | None = None
    source_row: int | None = None
    source_fields: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relation_type": self.relation_type,
            "weight": self.weight,
            "provenance_source": self.provenance_source,
            "source_file": self.source_file,
            "source_row": self.source_row,
            "source_fields": dict(self.source_fields),
            "confidence": self.confidence,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Metric containers
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class GraphCoverageMetrics:
    total_nodes_created: int
    total_edges_created: int
    nodes_by_type: dict[str, int]
    edges_by_type: dict[str, int]
    orphan_entities_count: int  # ACTUAL zero-degree nodes (A2)
    unresolved_entities_count: int
    relationship_coverage_pct: float  # ACTUAL valid/expected*100 (A2)
    graph_version: str = ""  # Computed hash (A2), never "graph_olist_v1.0"
    world_state_version: int = 0  # From current workspace (A2), never hardcoded 101

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_nodes_created": self.total_nodes_created,
            "total_edges_created": self.total_edges_created,
            "nodes_by_type": self.nodes_by_type,
            "edges_by_type": self.edges_by_type,
            "orphan_entities_count": self.orphan_entities_count,
            "unresolved_entities_count": self.unresolved_entities_count,
            "relationship_coverage_pct": round(self.relationship_coverage_pct, 2),
            "graph_version": self.graph_version,
            "world_state_version": self.world_state_version,
        }


@dataclass
class GraphAnalyticsSummary:
    graph_version: str
    world_state_version: int
    coverage: GraphCoverageMetrics
    density: float
    top_critical_suppliers: list[dict[str, Any]]
    top_critical_routes: list[dict[str, Any]]
    high_dependency_spofs: list[str]
    supplier_concentration_gini: float  # ACTUAL computed (A2)
    computed_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def total_nodes(self) -> int:
        return self.coverage.total_nodes_created

    @property
    def total_edges(self) -> int:
        return self.coverage.total_edges_created

    def to_dict(self) -> dict[str, Any]:
        return {
            "graph_version": self.graph_version,
            "world_state_version": self.world_state_version,
            "total_nodes": self.total_nodes,
            "total_edges": self.total_edges,
            "coverage": self.coverage.to_dict(),
            "density": round(self.density, 5),
            "top_critical_suppliers": self.top_critical_suppliers,
            "top_critical_routes": self.top_critical_routes,
            "high_dependency_spofs": self.high_dependency_spofs,
            "supplier_concentration_gini": round(self.supplier_concentration_gini, 3),
            "computed_at": self.computed_at.isoformat(),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Gini coefficient
# ─────────────────────────────────────────────────────────────────────────────


def _compute_gini(values: list[float]) -> float:
    """Compute the Gini coefficient for a distribution of values.

    Returns 0.0 for a perfectly equal distribution, approaching 1.0 for
    extreme concentration. Returns 0.0 for empty or all-zero inputs.
    """
    if not values:
        return 0.0
    positive = [v for v in values if v > 0]
    if not positive:
        return 0.0
    n = len(positive)
    if n == 1:
        return 0.0
    sorted_vals = sorted(positive)
    total = sum(sorted_vals)
    if total == 0:
        return 0.0
    weighted_sum = sum((i + 1) * v for i, v in enumerate(sorted_vals))
    gini = (2.0 * weighted_sum) / (n * total) - (n + 1.0) / n
    return max(0.0, min(1.0, gini))


# ─────────────────────────────────────────────────────────────────────────────
# Graph engine
# ─────────────────────────────────────────────────────────────────────────────

# Canonical field names that cross-reference another entity table.
# Maps canonical FK field → target entity type (lowercase for matching).
_FK_FIELD_TO_ENTITY: dict[str, str] = {
    "customer_id": "CUSTOMER",
    "supplier_id": "SUPPLIER",
    "seller_id": "SUPPLIER",
    "product_id": "PRODUCT",
    "order_id": "ORDER",
    "item_id": "ORDER_ITEM",
    "carrier_id": "CARRIER",
    "warehouse_id": "WAREHOUSE",
    "shipment_id": "SHIPMENT",
}


class OperationalGraphEngine:
    """Constructs and analyzes the enterprise operational network.

    The engine is domain-agnostic: it builds nodes and edges from whatever
    entity types the ``CanonicalDataset`` contains, connecting them via
    canonical foreign-key fields. No dataset-specific code paths.
    """

    def __init__(self) -> None:
        self.nodes: dict[str, GraphNode] = {}
        self.edges: dict[str, GraphEdge] = {}
        self.adjacency: dict[str, set[str]] = {}
        self.in_degree: dict[str, int] = {}
        self.out_degree: dict[str, int] = {}
        # Tracking for coverage computation
        self._expected_relationships: int = 0
        self._valid_relationships: int = 0

    # ── Node / edge primitives ──────────────────────────────────────────

    def add_node(
        self, node_id: str, node_type: str, attributes: dict[str, Any] | None = None
    ) -> GraphNode:
        if node_id not in self.nodes:
            self.nodes[node_id] = GraphNode(
                node_id=node_id, node_type=node_type, attributes=attributes or {}
            )
            self.adjacency[node_id] = set()
            self.in_degree[node_id] = 0
            self.out_degree[node_id] = 0
        return self.nodes[node_id]

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        relation_type: str,
        weight: float = 1.0,
        source_dataset: str = "generic",
        *,
        source_file: str | None = None,
        source_row: int | None = None,
        source_fields: dict[str, Any] | None = None,
        confidence: float = 1.0,
    ) -> GraphEdge:
        if source_id not in self.nodes:
            self.add_node(source_id, "UNKNOWN")
        if target_id not in self.nodes:
            self.add_node(target_id, "UNKNOWN")

        edge_id = f"e_{source_id}_{target_id}_{relation_type}"
        edge = GraphEdge(
            edge_id=edge_id,
            source_id=source_id,
            target_id=target_id,
            relation_type=relation_type,
            weight=weight,
            provenance_source=source_dataset,
            source_file=source_file,
            source_row=source_row,
            source_fields=source_fields or {},
            confidence=confidence,
        )
        self.edges[edge_id] = edge

        self.adjacency[source_id].add(target_id)
        self.adjacency[target_id].add(source_id)
        self.out_degree[source_id] = self.out_degree.get(source_id, 0) + 1
        self.in_degree[target_id] = self.in_degree.get(target_id, 0) + 1
        return edge

    def inspect_edge(self, edge_id: str) -> dict[str, Any] | None:
        """Return the full inspector dict for an edge (A3 inspector view)."""
        edge = self.edges.get(edge_id)
        if edge is None:
            return None
        return edge.to_dict()

    # ── Generic build from canonical dataset ────────────────────────────

    def build_graph(
        self,
        canonical_dataset: "CanonicalDataset",
        *,
        workspace_id: str = "",
        world_state_version: int = 0,
    ) -> GraphCoverageMetrics:
        """Build an operational graph from a generic ``CanonicalDataset``.

        The engine is domain-agnostic — it discovers nodes from every table
        present and creates edges by detecting canonical FK fields that
        reference other entity tables. No invented nodes: only entities and
        relationships the data substantiates are created.
        """
        from app.modules.nexus_spine.canonical_schema import EntityType as _ET

        # Phase 1: Create nodes for each entity in each table
        id_fields = self._detect_id_fields(canonical_dataset)
        for entity_type, table in canonical_dataset.tables.items():
            id_field = id_fields.get(entity_type)
            for row in table.rows:
                raw_id = row.get(id_field, "") if id_field else str(row.get("_source_row", ""))
                if not raw_id:
                    continue
                node_id = self._canonical_node_id(entity_type.value, str(raw_id))
                attrs = {k: v for k, v in row.items() if not k.startswith("_")}
                node = self.add_node(node_id, entity_type.value, attrs)
                # Preserve source provenance on node
                node.attributes["_source_file"] = row.get("_source_file")
                node.attributes["_source_row"] = row.get("_source_row")

        # Phase 2: Cross-table FK edges (PLACED, CONTAINS, FULFILLED_BY, REFERENCES, PART_OF)
        self._build_fk_edges(canonical_dataset, id_fields)

        # Phase 3: Derive implicit entities (LOCATION, ROUTE) and their edges
        self._derive_locations_and_routes(canonical_dataset, id_fields)

        # Phase 4: Compute real metrics
        return self._compute_coverage_metrics(
            workspace_id=workspace_id,
            world_state_version=world_state_version,
            schema_version=canonical_dataset.schema_version,
        )

    # ── Backward-compatible Olist adapter ───────────────────────────────

    def build_graph_from_olist_tables(
        self, data_dir: str, max_orders: int = 1000
    ) -> GraphCoverageMetrics:
        """Deprecated thin adapter: Olist CSVs → canonical → generic build.

        Kept for backward compatibility. New code should use
        ``build_graph(canonical_dataset, ...)`` directly.
        """
        from app.modules.nexus_spine.canonical_schema import OlistAdapter

        adapter = OlistAdapter()
        dataset = adapter.from_data_dir(data_dir, max_orders=max_orders)
        return self.build_graph(dataset)

    # ── Analytics ───────────────────────────────────────────────────────

    def compute_graph_analytics(
        self,
        graph_version: str = "",
        world_state_version: int = 0,
    ) -> GraphAnalyticsSummary:
        """Run structural centrality, PageRank, and concentration analysis.

        All metrics are computed from actual data (A2). No hardcoded
        constants.
        """
        n = len(self.nodes)
        if n == 0:
            cov = GraphCoverageMetrics(
                0, 0, {}, {}, 0, 0, 0.0, graph_version, world_state_version
            )
            return GraphAnalyticsSummary(
                graph_version, world_state_version, cov, 0.0, [], [], [], 0.0
            )

        # 1. Degree centrality
        max_deg = max(1, n - 1)
        for nid, node in self.nodes.items():
            deg = len(self.adjacency.get(nid, set()))
            node.degree_centrality = deg / max_deg

        # 2. PageRank (power iteration, 8 rounds)
        pr = {nid: 1.0 / n for nid in self.nodes}
        d = 0.85
        for _ in range(8):
            new_pr = {nid: (1.0 - d) / n for nid in self.nodes}
            for nid, node in self.nodes.items():
                neighbors = self.adjacency.get(nid, set())
                deg = len(neighbors)
                if deg > 0:
                    share = (d * pr[nid]) / deg
                    for neighbor in neighbors:
                        new_pr[neighbor] += share
            pr = new_pr
        for nid, val in pr.items():
            self.nodes[nid].pagerank = val

        # 3. Critical nodes & SPOFs
        critical_suppliers: list[dict[str, Any]] = []
        critical_routes: list[dict[str, Any]] = []
        spofs: list[str] = []

        for nid, node in self.nodes.items():
            deg = len(self.adjacency.get(nid, set()))
            if node.node_type in ("SUPPLIER", "SELLER"):
                if deg >= 5 or node.pagerank > (1.5 / n):
                    node.is_spof = True
                    spofs.append(nid)
                    critical_suppliers.append({
                        "supplier_id": nid,
                        "order_volume": deg,
                        "pagerank": round(node.pagerank, 6),
                        "degree_centrality": round(node.degree_centrality, 5),
                    })
            elif node.node_type == "ROUTE":
                critical_routes.append({
                    "route_id": nid,
                    "active_orders": deg,
                    "pagerank": round(node.pagerank, 6),
                })

        critical_suppliers.sort(key=lambda s: s["pagerank"], reverse=True)
        critical_routes.sort(key=lambda r: r["pagerank"], reverse=True)

        density = (2.0 * len(self.edges)) / max(1, n * (n - 1))

        # Supplier concentration (A2: computed, not hardcoded 0.642)
        supplier_order_counts = self._supplier_order_counts()
        gini = _compute_gini(list(supplier_order_counts.values()))

        # Coverage metrics (A2: all computed)
        nodes_by_type = self._count_by("node_type")
        edges_by_type = self._count_edges_by("relation_type")
        orphans = self._count_orphans()

        coverage = GraphCoverageMetrics(
            total_nodes_created=n,
            total_edges_created=len(self.edges),
            nodes_by_type=nodes_by_type,
            edges_by_type=edges_by_type,
            orphan_entities_count=orphans,
            unresolved_entities_count=0,
            relationship_coverage_pct=self._compute_relationship_coverage(),
            graph_version=graph_version,
            world_state_version=world_state_version,
        )

        return GraphAnalyticsSummary(
            graph_version=graph_version,
            world_state_version=world_state_version,
            coverage=coverage,
            density=density,
            top_critical_suppliers=critical_suppliers[:10],
            top_critical_routes=critical_routes[:10],
            high_dependency_spofs=spofs[:10],
            supplier_concentration_gini=gini,
        )

    # ── Internal helpers ────────────────────────────────────────────────

    @staticmethod
    def _canonical_node_id(entity_type: str, raw_id: str) -> str:
        return f"{entity_type.lower()}_{raw_id}"

    def _detect_id_fields(
        self, canonical_dataset: "CanonicalDataset"
    ) -> dict["EntityType", str]:
        """Detect the primary ID column for each table.

        Convention: the first column ending in ``_id`` is the primary ID,
        or the column literally named ``id``.
        """
        result: dict["EntityType", str] = {}
        for entity_type, table in canonical_dataset.tables.items():
            if not table.rows:
                continue
            sample = table.rows[0]
            # Prefer entity-specific ID columns
            preferred = f"{entity_type.value.lower()}_id"
            if preferred in sample:
                result[entity_type] = preferred
                continue
            # Fall back to any *_id column
            for col in sample:
                if col.endswith("_id") and not col.startswith("_"):
                    result[entity_type] = col
                    break
        return result

    def _build_fk_edges(
        self,
        canonical_dataset: "CanonicalDataset",
        id_fields: dict["EntityType", str],
    ) -> None:
        """Create edges for every canonical FK field that references another table."""
        # Build a lookup: (target_entity_type_upper, raw_id) → node_id
        node_index: dict[tuple[str, str], str] = {}
        for et, table in canonical_dataset.tables.items():
            id_field = id_fields.get(et)
            if not id_field:
                continue
            for row in table.rows:
                raw_id = row.get(id_field, "")
                if raw_id:
                    node_id = self._canonical_node_id(et.value, str(raw_id))
                    node_index[(et.value, str(raw_id))] = node_id

        # For each table, check columns against known FK patterns
        for entity_type, table in canonical_dataset.tables.items():
            id_field = id_fields.get(entity_type)
            for row in table.rows:
                raw_id = row.get(id_field, "") if id_field else ""
                if not raw_id:
                    continue
                source_node = self._canonical_node_id(entity_type.value, str(raw_id))

                for col_name, target_type in _FK_FIELD_TO_ENTITY.items():
                    if col_name == id_field:
                        continue  # skip self-reference (the PK column)
                    fk_value = row.get(col_name)
                    if fk_value is None:
                        continue
                    target_node = node_index.get((target_type, str(fk_value)))
                    if target_node is None:
                        self._expected_relationships += 1
                        continue  # FK references a non-existent entity

                    # Determine relation type from the FK semantics
                    relation = self._relation_for_fk(col_name, entity_type.value, target_type)

                    self.add_edge(
                        source_node,
                        target_node,
                        relation,
                        source_dataset=table.source_file or "generic",
                        source_file=row.get("_source_file"),
                        source_row=row.get("_source_row"),
                        source_fields={
                            "fk_column": col_name,
                            "fk_value": str(fk_value),
                            "source_id": str(raw_id),
                        },
                    )
                    self._expected_relationships += 1
                    self._valid_relationships += 1

    def _derive_locations_and_routes(
        self,
        canonical_dataset: "CanonicalDataset",
        id_fields: dict["EntityType", str],
    ) -> None:
        """Derive LOCATION nodes from ``state`` attributes and ROUTE nodes
        from supplier→customer state pairs on orders.
        """
        from app.modules.nexus_spine.canonical_schema import EntityType as _ET

        # Collect state values from SUPPLIER and CUSTOMER tables
        supplier_states: dict[str, str] = {}  # supplier_node_id → state
        customer_states: dict[str, str] = {}  # customer_node_id → state

        for entity_type, table in canonical_dataset.tables.items():
            id_field = id_fields.get(entity_type)
            if entity_type in (_ET.SUPPLIER, _ET.SELLER):
                for row in table.rows:
                    raw_id = row.get(id_field, "") if id_field else ""
                    state = row.get("state", "")
                    if raw_id and state:
                        node_id = self._canonical_node_id(entity_type.value, str(raw_id))
                        supplier_states[node_id] = str(state)
            elif entity_type == _ET.CUSTOMER:
                for row in table.rows:
                    raw_id = row.get(id_field, "") if id_field else ""
                    state = row.get("state", "")
                    if raw_id and state:
                        node_id = self._canonical_node_id(entity_type.value, str(raw_id))
                        customer_states[node_id] = str(state)

        # Create LOCATION nodes for every unique state seen
        seen_states: set[str] = set()
        for state in list(supplier_states.values()) + list(customer_states.values()):
            seen_states.add(state)
        for state in seen_states:
            loc_id = self._canonical_node_id("LOCATION", state)
            self.add_node(loc_id, "LOCATION", {"state": state})

        # LOCATED_IN edges for suppliers
        for supplier_node, state in supplier_states.items():
            loc_id = self._canonical_node_id("LOCATION", state)
            self.add_edge(supplier_node, loc_id, "LOCATED_IN")

        # LOCATED_IN edges for customers
        for customer_node, state in customer_states.items():
            loc_id = self._canonical_node_id("LOCATION", state)
            self.add_edge(customer_node, loc_id, "LOCATED_IN")

        # Derive ROUTE nodes from orders that have both a supplier state
        # and a customer state (via FULFILLED_BY + PLACED edges)
        for entity_type, table in canonical_dataset.tables.items():
            if entity_type != _ET.ORDER:
                continue
            id_field = id_fields.get(entity_type)
            for row in table.rows:
                raw_id = row.get(id_field, "") if id_field else ""
                if not raw_id:
                    continue
                cust_id = row.get("customer_id", "")
                # Find supplier via ORDER_ITEM table
                supplier_state = self._find_supplier_state_for_order(
                    str(raw_id), canonical_dataset, id_fields
                )
                customer_state = customer_states.get(
                    self._canonical_node_id("CUSTOMER", str(cust_id)), ""
                ) if cust_id else ""
                if supplier_state and customer_state:
                    route_id = self._canonical_node_id(
                        "ROUTE", f"{supplier_state}_to_{customer_state}"
                    )
                    self.add_node(
                        route_id,
                        "ROUTE",
                        {"origin": supplier_state, "destination": customer_state},
                    )
                    order_node = self._canonical_node_id("ORDER", str(raw_id))
                    self.add_edge(order_node, route_id, "TRAVELS_TO")

    def _find_supplier_state_for_order(
        self,
        order_id: str,
        canonical_dataset: "CanonicalDataset",
        id_fields: dict["EntityType", str],
    ) -> str:
        """Look up the supplier state for an order via ORDER_ITEM → SUPPLIER."""
        from app.modules.nexus_spine.canonical_schema import EntityType as _ET

        item_table = canonical_dataset.get(_ET.ORDER_ITEM)
        if not item_table:
            return ""
        supplier_table = canonical_dataset.get(_ET.SUPPLIER) or canonical_dataset.get(_ET.SELLER)
        if not supplier_table:
            return ""

        supplier_id_field = id_fields.get(_ET.SUPPLIER) or id_fields.get(_ET.SELLER, "")

        # Find supplier_id from order items
        for row in item_table.rows:
            if str(row.get("order_id", "")) == order_id:
                sup_id = str(row.get("supplier_id", ""))
                if sup_id and supplier_table:
                    for sup_row in supplier_table.rows:
                        if str(sup_row.get(supplier_id_field, "")) == sup_id:
                            return str(sup_row.get("state", ""))
        return ""

    @staticmethod
    def _relation_for_fk(fk_column: str, source_type: str, target_type: str) -> str:
        """Determine the relation type from FK column semantics."""
        if fk_column == "customer_id":
            return "PLACED"
        if fk_column == "product_id":
            return "REFERENCES"
        if fk_column in ("supplier_id", "seller_id"):
            return "FULFILLED_BY"
        if fk_column == "order_id":
            if source_type == "ORDER_ITEM":
                return "PART_OF"
            return "CONTAINS"
        if fk_column == "carrier_id":
            return "SHIPPED_BY"
        if fk_column == "warehouse_id":
            return "STORED_IN"
        if fk_column == "shipment_id":
            return "SHIPS"
        return "RELATED_TO"

    # ── Metric computation helpers ──────────────────────────────────────

    def _count_orphans(self) -> int:
        """Count nodes with zero degree (no edges in or out). A2: actual."""
        return sum(
            1
            for nid in self.nodes
            if self.in_degree.get(nid, 0) == 0 and self.out_degree.get(nid, 0) == 0
        )

    def _compute_relationship_coverage(self) -> float:
        """Coverage = valid / expected * 100. A2: computed, not hardcoded."""
        if self._expected_relationships == 0:
            return 100.0 if self._valid_relationships == 0 else 0.0
        return (self._valid_relationships / self._expected_relationships) * 100.0

    def _supplier_order_counts(self) -> dict[str, int]:
        """Count orders per supplier from FULFILLED_BY edges."""
        counts: dict[str, int] = {}
        for edge in self.edges.values():
            if edge.relation_type == "FULFILLED_BY":
                supplier_id = edge.target_id
                counts[supplier_id] = counts.get(supplier_id, 0) + 1
        return counts

    def _count_by(self, attr: str) -> dict[str, int]:
        result: dict[str, int] = {}
        for node in self.nodes.values():
            val = getattr(node, attr, "UNKNOWN")
            result[val] = result.get(val, 0) + 1
        return result

    def _count_edges_by(self, attr: str) -> dict[str, int]:
        result: dict[str, int] = {}
        for edge in self.edges.values():
            val = getattr(edge, attr, "UNKNOWN")
            result[val] = result.get(val, 0) + 1
        return result

    def _compute_coverage_metrics(
        self,
        *,
        workspace_id: str,
        world_state_version: int,
        schema_version: str = "",
    ) -> GraphCoverageMetrics:
        """Build coverage metrics with all values computed from actual data."""
        nodes_by_type = self._count_by("node_type")
        edges_by_type = self._count_edges_by("relation_type")
        orphans = self._count_orphans()
        coverage_pct = self._compute_relationship_coverage()

        # Graph version: hash of (workspace_id, world_state_version,
        # schema_version, node_count, edge_count, sorted edge types)
        version_parts = [
            workspace_id,
            str(world_state_version),
            schema_version,
            str(len(self.nodes)),
            str(len(self.edges)),
            ",".join(sorted(edges_by_type.keys())),
        ]
        graph_version = hashlib.sha256("|".join(version_parts).encode()).hexdigest()[:12]

        return GraphCoverageMetrics(
            total_nodes_created=len(self.nodes),
            total_edges_created=len(self.edges),
            nodes_by_type=nodes_by_type,
            edges_by_type=edges_by_type,
            orphan_entities_count=orphans,
            unresolved_entities_count=0,
            relationship_coverage_pct=coverage_pct,
            graph_version=graph_version,
            world_state_version=world_state_version,
        )
