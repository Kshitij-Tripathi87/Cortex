"""Program S5 — Graph Delta Engine & Incremental Topology Mutation.

Computes and applies incremental graph deltas (added/removed/updated nodes and edges)
without re-constructing the entire operational graph from scratch. Enables live streaming
operational world updates and efficient WebSocket delta broadcasts to frontend clients.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.common.ids import uuid7
from app.modules.data_intelligence.operational_graph import (
    OperationalGraphEngine,
)


@dataclass
class NodeDelta:
    node_id: str
    action: str  # "ADDED" | "UPDATED" | "REMOVED"
    node_type: str
    attributes: dict[str, Any] = field(default_factory=dict)
    pagerank: float = 0.0
    is_spof: bool = False


@dataclass
class EdgeDelta:
    edge_id: str
    action: str  # "ADDED" | "UPDATED" | "REMOVED"
    source_id: str
    target_id: str
    relation_type: str
    weight: float = 1.0


@dataclass
class GraphDelta:
    delta_id: str
    previous_graph_version: str
    new_graph_version: str
    world_state_version: int
    event_type: str = "STREAM_EVENT"
    # E1 (realtime seq/version/resync): monotonic per-engine sequence number.
    # Assigned at the moment `apply_stream_event` constructs the delta.
    # Clients use `seq` to detect gaps; the server uses `since_seq` to
    # replay missed deltas. The value is engine-local and resets only
    # on process restart — clients must re-handshake across restarts.
    seq: int = 0
    added_nodes: list[NodeDelta] = field(default_factory=list)
    updated_nodes: list[NodeDelta] = field(default_factory=list)
    removed_nodes: list[str] = field(default_factory=list)
    added_edges: list[EdgeDelta] = field(default_factory=list)
    updated_edges: list[EdgeDelta] = field(default_factory=list)
    removed_edges: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def total_changes_count(self) -> int:
        return (
            len(self.added_nodes)
            + len(self.updated_nodes)
            + len(self.removed_nodes)
            + len(self.added_edges)
            + len(self.updated_edges)
            + len(self.removed_edges)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "delta_id": self.delta_id,
            "event_type": self.event_type,
            "previous_graph_version": self.previous_graph_version,
            "new_graph_version": self.new_graph_version,
            "world_state_version": self.world_state_version,
            "seq": self.seq,
            "total_changes_count": self.total_changes_count,
            "added_nodes": [
                {
                    "node_id": n.node_id,
                    "action": n.action,
                    "node_type": n.node_type,
                    "attributes": n.attributes,
                    "pagerank": round(n.pagerank, 6),
                    "is_spof": n.is_spof,
                }
                for n in self.added_nodes
            ],
            "updated_nodes": [
                {
                    "node_id": n.node_id,
                    "action": n.action,
                    "node_type": n.node_type,
                    "attributes": n.attributes,
                    "pagerank": round(n.pagerank, 6),
                    "is_spof": n.is_spof,
                }
                for n in self.updated_nodes
            ],
            "removed_nodes": self.removed_nodes,
            "added_edges": [
                {
                    "edge_id": e.edge_id,
                    "action": e.action,
                    "source_id": e.source_id,
                    "target_id": e.target_id,
                    "relation_type": e.relation_type,
                    "weight": e.weight,
                }
                for e in self.added_edges
            ],
            "updated_edges": [
                {
                    "edge_id": e.edge_id,
                    "action": e.action,
                    "source_id": e.source_id,
                    "target_id": e.target_id,
                    "relation_type": e.relation_type,
                    "weight": e.weight,
                }
                for e in self.updated_edges
            ],
            "removed_edges": self.removed_edges,
            "timestamp": self.timestamp.isoformat(),
        }


class GraphDeltaEngine:
    """Computes, records, and applies delta mutations on an operational graph."""

    def __init__(self, graph_engine: OperationalGraphEngine) -> None:
        self.graph_engine = graph_engine
        self.delta_history: list[GraphDelta] = []
        self.current_version_counter = 1

    def apply_stream_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        world_state_version: int,
    ) -> GraphDelta:
        """Incrementally updates graph from an incoming operational stream event."""
        prev_ver = f"graph_v{self.current_version_counter}"
        self.current_version_counter += 1
        new_ver = f"graph_v{self.current_version_counter}"

        delta_id = f"delta_{uuid7()[:8]}"
        # E1: stamp the seq at construction time. Use the post-increment
        # counter value so the first delta has seq=2 (matching
        # `current_version_counter` for that snapshot). The
        # regression test pins monotonicity across N consecutive
        # apply_stream_event calls.
        delta = GraphDelta(
            delta_id=delta_id,
            previous_graph_version=prev_ver,
            new_graph_version=new_ver,
            world_state_version=world_state_version,
            event_type=event_type,
            seq=self.current_version_counter,
        )

        if event_type in {"ORDER_PLACED", "ORDER_CREATED"}:
            order_id = payload.get("order_id", f"ord_{uuid7()[:8]}")
            customer_id = payload.get("customer_id", "cust_anonymous")
            seller_id = payload.get("seller_id", "seller_default")
            product_id = payload.get("product_id", "prod_generic")
            origin = payload.get("origin", "SP")
            dest = payload.get("destination", "RJ")
            route_id = f"route_{origin}_to_{dest}"

            # 1. Order Node
            is_new_order = order_id not in self.graph_engine.nodes
            order_node = self.graph_engine.add_node(order_id, "ORDER", payload)
            if is_new_order:
                delta.added_nodes.append(NodeDelta(order_id, "ADDED", "ORDER", payload))
            else:
                delta.updated_nodes.append(NodeDelta(order_id, "UPDATED", "ORDER", payload))

            # 2. Customer Node & Edge
            if customer_id not in self.graph_engine.nodes:
                self.graph_engine.add_node(customer_id, "CUSTOMER", {"state": dest})
                delta.added_nodes.append(NodeDelta(customer_id, "ADDED", "CUSTOMER", {"state": dest}))
            e1 = self.graph_engine.add_edge(customer_id, order_id, "PLACED")
            delta.added_edges.append(EdgeDelta(e1.edge_id, "ADDED", customer_id, order_id, "PLACED"))

            # 3. Product Node & Edge
            if product_id not in self.graph_engine.nodes:
                self.graph_engine.add_node(product_id, "PRODUCT", {"category": payload.get("category", "general")})
                delta.added_nodes.append(NodeDelta(product_id, "ADDED", "PRODUCT"))
            e2 = self.graph_engine.add_edge(order_id, product_id, "CONTAINS")
            delta.added_edges.append(EdgeDelta(e2.edge_id, "ADDED", order_id, product_id, "CONTAINS"))

            # 4. Supplier (alias: seller) Node & Edge
            if seller_id not in self.graph_engine.nodes:
                self.graph_engine.add_node(seller_id, "SUPPLIER", {"state": origin})
                delta.added_nodes.append(NodeDelta(seller_id, "ADDED", "SUPPLIER", {"state": origin}))
            e3 = self.graph_engine.add_edge(order_id, seller_id, "FULFILLED_BY")
            delta.added_edges.append(EdgeDelta(e3.edge_id, "ADDED", order_id, seller_id, "FULFILLED_BY"))

            # 5. Route Node & Edge
            if route_id not in self.graph_engine.nodes:
                self.graph_engine.add_node(route_id, "ROUTE", {"origin": origin, "destination": dest})
                delta.added_nodes.append(NodeDelta(route_id, "ADDED", "ROUTE", {"origin": origin, "destination": dest}))
            e4 = self.graph_engine.add_edge(order_id, route_id, "TRAVELS_TO")
            delta.added_edges.append(EdgeDelta(e4.edge_id, "ADDED", order_id, route_id, "TRAVELS_TO"))

        elif event_type in {"SELLER_STATUS_CHANGED", "SELLER_DEGRADATION", "SUPPLIER_STATUS_CHANGED", "SUPPLIER_DEGRADATION"}:
            seller_id = payload.get("seller_id", "seller_default")
            if seller_id in self.graph_engine.nodes:
                node = self.graph_engine.nodes[seller_id]
                node.attributes.update(payload)
                delta.updated_nodes.append(NodeDelta(seller_id, "UPDATED", "SUPPLIER", node.attributes, node.pagerank, node.is_spof))

        self.delta_history.append(delta)
        return delta

    def get_deltas_since(self, version: str) -> list[GraphDelta]:
        """Returns all recorded graph deltas that occurred after the given graph version."""
        if not version:
            return self.delta_history
        result = []
        found = False
        for d in self.delta_history:
            if found or d.previous_graph_version == version:
                found = True
                result.append(d)
        return result if found else self.delta_history

    def get_deltas_since_seq(self, since_seq: int) -> list[GraphDelta]:
        """E1: replay deltas with `seq > since_seq`, ordered by seq ascending.

        Used by the SSE /workspace/stream handler when a client
        reconnects with `?since_seq=N` to fill in the gap. Returns
        the full history if `since_seq` is negative (the client is
        past the head; caller must decide whether to emit a resync).
        """
        if since_seq < 0:
            return list(self.delta_history)
        return [d for d in self.delta_history if d.seq > since_seq]

    def min_known_seq(self) -> int:
        """E1: the seq of the oldest delta still in the in-memory
        history. Clients reconnecting with `since_seq < min_known_seq`
        have a gap larger than the server can replay — caller must
        emit a `resync` event so the client does a full refresh.
        """
        if not self.delta_history:
            return self.current_version_counter
        return self.delta_history[0].seq
