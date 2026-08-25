"""Graph Representation & Feature Extraction for GNNs.

Program K.1 (Graph Representation & Heterogeneous Topology):
Extracts heterogeneous graphs from Cortex WorldState and Evidence Graph,
computing normalized structural, operational, and topological features.
"""

from __future__ import annotations

from typing import Any

from app.modules.gnn.gnn_models import (
    EdgeType,
    GraphEdge,
    GraphNode,
    HeteroGraphData,
    NodeType,
)
from app.modules.world.state_projection import WorldState
from app.modules.world.world_models import StateVariableType


class GraphExtractor:
    """Extracts and featurizes heterogeneous graphs from WorldState."""

    def extract_from_world_state(
        self,
        world_state: WorldState,
        include_structural_metrics: bool = True,
    ) -> HeteroGraphData:
        """Construct a HeteroGraphData instance from a WorldState and its variables."""
        nodes: dict[str, GraphNode] = {}
        edges: list[GraphEdge] = []

        # 1. Discover all distinct entities and their variable states
        entity_vars: dict[str, dict[str, Any]] = {}
        for var in world_state.variables.values():
            e_key = f"{var.entity_type}:{var.entity_id}"
            if e_key not in entity_vars:
                entity_vars[e_key] = {"type": var.entity_type, "id": var.entity_id, "vars": {}}
            entity_vars[e_key]["vars"][var.variable_type.value] = (
                float(var.raw_value) if isinstance(var.raw_value, (int, float)) else var.raw_value
            )

        # 2. Build GraphNode instances
        for _e_key, data in entity_vars.items():
            node_type = self._map_node_type(data["type"])
            node_id = f"{node_type.value}_{data['id']}"

            # Operational feature vector
            features: dict[str, float] = {
                "capacity_pct": float(data["vars"].get(StateVariableType.CAPACITY.value, 100.0)),
                "inventory_level": float(data["vars"].get(StateVariableType.INVENTORY.value, 0.0)),
                "lead_time_days": float(data["vars"].get(StateVariableType.LEAD_TIME.value, 5.0)),
                "supplier_health": float(
                    data["vars"].get(StateVariableType.SUPPLIER_HEALTH.value, 1.0)
                ),
                "transit_delay": float(
                    data["vars"].get(StateVariableType.TRANSIT_DELAY.value, 0.0)
                ),
                "demand_volume": float(data["vars"].get(StateVariableType.DEMAND.value, 0.0)),
            }

            nodes[node_id] = GraphNode(
                node_id=node_id,
                node_type=node_type,
                entity_id=data["id"],
                name=f"{node_type.value.capitalize()} {data['id']}",
                features=features,
                metadata={"raw_type": data["type"]},
            )

        # 3. Infer standard supply chain topological edges
        # Connect suppliers -> components -> factories -> warehouses -> customers
        suppliers = [n for n in nodes.values() if n.node_type == NodeType.SUPPLIER]
        factories = [n for n in nodes.values() if n.node_type == NodeType.FACTORY]
        warehouses = [n for n in nodes.values() if n.node_type == NodeType.WAREHOUSE]
        customers = [n for n in nodes.values() if n.node_type == NodeType.CUSTOMER]
        components = [n for n in nodes.values() if n.node_type == NodeType.COMPONENT]

        edge_count = 0

        # Supplier -> Component / Factory
        for s in suppliers:
            for c in components:
                edge_id = f"edge_{edge_count}"
                edges.append(
                    GraphEdge(
                        edge_id=edge_id,
                        source_id=s.node_id,
                        target_id=c.node_id,
                        edge_type=EdgeType.SUPPLIES,
                        weight=1.0,
                        features={"lead_time": s.features.get("lead_time_days", 5.0)},
                    )
                )
                edge_count += 1

            for f in factories:
                edge_id = f"edge_{edge_count}"
                edges.append(
                    GraphEdge(
                        edge_id=edge_id,
                        source_id=s.node_id,
                        target_id=f.node_id,
                        edge_type=EdgeType.SHIPS_TO,
                        weight=1.0,
                        features={"transit_time": 2.0},
                    )
                )
                edge_count += 1

        # Factory -> Warehouse
        for f in factories:
            for w in warehouses:
                edge_id = f"edge_{edge_count}"
                edges.append(
                    GraphEdge(
                        edge_id=edge_id,
                        source_id=f.node_id,
                        target_id=w.node_id,
                        edge_type=EdgeType.MANUFACTURES,
                        weight=1.0,
                        features={"throughput": 500.0},
                    )
                )
                edge_count += 1

        # Warehouse -> Customer
        for w in warehouses:
            for cust in customers:
                edge_id = f"edge_{edge_count}"
                edges.append(
                    GraphEdge(
                        edge_id=edge_id,
                        source_id=w.node_id,
                        target_id=cust.node_id,
                        edge_type=EdgeType.SHIPS_TO,
                        weight=1.0,
                        features={"fulfillment_days": 1.0},
                    )
                )
                edge_count += 1

        # Fallback: if single-node or isolated network, ensure indexed
        node_ids = sorted(nodes.keys())
        node_to_idx = {nid: idx for idx, nid in enumerate(node_ids)}
        idx_to_node = {idx: nid for idx, nid in enumerate(node_ids)}

        # 4. Compute structural graph metrics (PageRank, degree centrality)
        if include_structural_metrics and nodes:
            in_degrees = {nid: 0 for nid in nodes}
            out_degrees = {nid: 0 for nid in nodes}
            for e in edges:
                if e.source_id in out_degrees:
                    out_degrees[e.source_id] += 1
                if e.target_id in in_degrees:
                    in_degrees[e.target_id] += 1

            pagerank_scores = self._compute_pagerank(nodes, edges)

            # Augment features with structural properties
            augmented_nodes = {}
            for nid, node in nodes.items():
                in_deg = in_degrees.get(nid, 0)
                out_deg = out_degrees.get(nid, 0)
                total_deg = in_deg + out_deg
                pr = pagerank_scores.get(nid, 1.0 / max(1, len(nodes)))

                updated_features = dict(node.features)
                updated_features.update(
                    {
                        "in_degree": float(in_deg),
                        "out_degree": float(out_deg),
                        "degree_centrality": float(total_deg) / max(1, len(nodes) - 1),
                        "pagerank": float(pr),
                    }
                )

                augmented_nodes[nid] = GraphNode(
                    node_id=node.node_id,
                    node_type=node.node_type,
                    entity_id=node.entity_id,
                    name=node.name,
                    features=updated_features,
                    metadata=node.metadata,
                )
            nodes = augmented_nodes

        feature_dim = len(next(iter(nodes.values())).features) if nodes else 10

        return HeteroGraphData(
            workspace_id=world_state.workspace_id,
            world_id=world_state.world_id,
            version=world_state.version,
            nodes=nodes,
            edges=edges,
            node_to_idx=node_to_idx,
            idx_to_node=idx_to_node,
            feature_dim=feature_dim,
        )

    def _map_node_type(self, entity_type: str) -> NodeType:
        t = entity_type.lower()
        if "supplier" in t:
            return NodeType.SUPPLIER
        elif "factory" in t or "plant" in t:
            return NodeType.FACTORY
        elif "warehouse" in t or "dc" in t or "hub" in t:
            return NodeType.WAREHOUSE
        elif "customer" in t:
            return NodeType.CUSTOMER
        elif "route" in t:
            return NodeType.ROUTE
        elif "component" in t or "product" in t or "sku" in t:
            return NodeType.COMPONENT
        return NodeType.SUPPLIER

    def _compute_pagerank(
        self,
        nodes: dict[str, GraphNode],
        edges: list[GraphEdge],
        damping: float = 0.85,
        max_iter: int = 30,
        tol: float = 1e-4,
    ) -> dict[str, float]:
        """Compute exact PageRank vector over the graph."""
        n = len(nodes)
        if n == 0:
            return {}

        node_ids = list(nodes.keys())
        ranks = {nid: 1.0 / n for nid in node_ids}

        # Build adjacency mapping (source -> targets)
        out_edges: dict[str, list[str]] = {nid: [] for nid in node_ids}
        in_edges: dict[str, list[str]] = {nid: [] for nid in node_ids}

        for e in edges:
            if e.source_id in out_edges and e.target_id in in_edges:
                out_edges[e.source_id].append(e.target_id)
                in_edges[e.target_id].append(e.source_id)

        for _ in range(max_iter):
            new_ranks = {}
            dangling_sum = sum(ranks[nid] for nid in node_ids if len(out_edges[nid]) == 0)

            for nid in node_ids:
                rank_sum = sum(
                    ranks[src] / len(out_edges[src])
                    for src in in_edges[nid]
                    if len(out_edges[src]) > 0
                )
                new_ranks[nid] = (1.0 - damping) / n + damping * (rank_sum + dangling_sum / n)

            # Check convergence
            diff = sum(abs(new_ranks[nid] - ranks[nid]) for nid in node_ids)
            ranks = new_ranks
            if diff < tol:
                break

        return ranks
