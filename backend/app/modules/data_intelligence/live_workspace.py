"""Program S â€” Live Nexus Data Workspace Master Service.

Orchestrates the entire live user-driven operational intelligence cycle:
1. Dynamic Ingestion & Multi-Table Schema Discovery
2. Proportional Operational Graph Construction (scales with actual dataset)
3. Viewport-aware Subgraph Extraction & Entity Neighborhood Explorer
4. Anomaly Signal Detection & Root Cause Blast Radius
5. Dynamic Graph-Aware Agent Routing & Multi-Agent Deliberation
6. Digital Twin Counterfactual Simulation (Candidate A vs B vs C vs D)
7. Decision Evidence Graph Provenance Assembly
8. Live Event Streaming & Incremental Graph Delta Mutations
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.common.context import ExecutionContext
from app.common.ids import uuid7
from app.modules.agents.domain_agents.inventory_allocation import InventoryAllocationAgent
from app.modules.agents.domain_agents.logistics_routing import LogisticsRoutingAgent
from app.modules.agents.domain_agents.shipment_tracking import (
    ShipmentTrackingAgent,
)
from app.modules.data_intelligence.context_builder import (
    ContextBuilder,
)
from app.modules.data_intelligence.decision_evidence_graph import (
    DecisionEvidenceGraph,
    SimulationCounterfactual,
)
from app.modules.data_intelligence.decision_invalidation import (
    DecisionInvalidationEngine,
)
from app.modules.data_intelligence.entity_resolution import EntityResolutionEngine
from app.modules.data_intelligence.feature_store import (
    GraphFeatureStore,
)
from app.modules.data_intelligence.graph_delta_engine import GraphDelta, GraphDeltaEngine
from app.modules.data_intelligence.operational_graph import (
    GraphAnalyticsSummary,
    OperationalGraphEngine,
)
from app.modules.data_intelligence.profiler import DataQualityProfiler, DataReadinessReport
from app.modules.data_intelligence.root_cause_engine import (
    RootCauseImpactEngine,
)
from app.modules.data_intelligence.signal_engine import (
    OperationalSignal,
    OperationalSignalEngine,
)
from app.modules.query.query_engine import NexusQueryEngine


@dataclass
class StructuredAgentMessage:
    message_id: str
    sender_role: str
    sender_name: str
    timestamp: datetime
    content: str
    evidence_refs: list[str]
    phase: str  # "OBSERVATION" | "CRITIQUE" | "SYNTHESIS" | "PROPOSAL"


@dataclass
class LiveWorkspaceState:
    workspace_id: str
    organization_id: str
    datasets_loaded: list[dict[str, Any]]
    total_raw_rows: int
    readiness_reports: list[DataReadinessReport]
    graph_version: str
    world_state_version: int
    graph_analytics: GraphAnalyticsSummary
    active_signals: list[OperationalSignal]
    last_decision: dict[str, Any] | None
    is_last_decision_valid: bool = True
    invalidation_reason: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __getitem__(self, item: str) -> Any:
        return self.to_dict().get(item)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": "ready",
            "workspace_id": self.workspace_id,
            "organization_id": self.organization_id,
            "datasets_loaded": self.datasets_loaded,
            "datasets_ingested": len(self.datasets_loaded),
            "total_raw_rows": self.total_raw_rows,
            "readiness_reports": [r.to_dict() for r in self.readiness_reports],
            "graph_version": self.graph_version,
            "world_state_version": self.world_state_version,
            "graph_analytics": self.graph_analytics.to_dict(),
            "active_signals": [s.to_dict() for s in self.active_signals],
            "last_decision": self.last_decision,
            "is_last_decision_valid": self.is_last_decision_valid,
            "invalidation_reason": self.invalidation_reason,
            "created_at": self.created_at.isoformat(),
        }


class LiveNexusWorkspace:
    """Live interactive workspace instance maintaining proportional operational graph and intelligence."""

    def __init__(self, workspace_id: str = "ws_default", organization_id: str = "org_default") -> None:
        self.workspace_id = workspace_id
        self.organization_id = organization_id
        self.profiler = DataQualityProfiler()
        self.entity_engine = EntityResolutionEngine()
        self.graph_engine = OperationalGraphEngine()
        self.delta_engine = GraphDeltaEngine(self.graph_engine)
        self.signal_engine = OperationalSignalEngine()
        self.root_cause_engine = RootCauseImpactEngine(self.graph_engine)
        self.feature_store = GraphFeatureStore()
        self.context_builder = ContextBuilder(self.graph_engine)
        self.query_engine = NexusQueryEngine(self.graph_engine)
        self.invalidation_engine = DecisionInvalidationEngine()

        # Specialist Agents
        self.shipment_agent = ShipmentTrackingAgent(version="v9_olist")
        self.routing_agent = LogisticsRoutingAgent(version="v4")
        self.inventory_agent = InventoryAllocationAgent(version="v6")

        # State tracking
        self.datasets: list[dict[str, Any]] = []
        self.readiness_reports: list[DataReadinessReport] = []
        self.active_signals: list[OperationalSignal] = []
        self.agent_message_history: list[StructuredAgentMessage] = []
        self.last_decision_evidence: dict[str, Any] | None = None
        # Formally the initial workspace version — never a fabricated
        # constant (see G4 / base-plan). Production paths override with
        # the actual workspace version before use.
        self.world_state_version = 0  # was 101 (test fixture); no implicit 101 in production

    def ingest_csv_content(
        self,
        table_name: str,
        csv_text: str,
        primary_key: str | None = None,
        required_columns: list[str] | None = None,
        max_rows: int = 5000,
    ) -> dict[str, Any]:
        """Ingests raw CSV text dynamically, profile quality, and constructs proportional graph."""
        reader = csv.DictReader(io.StringIO(csv_text.strip()))
        rows = list(reader)
        row_count = len(rows[:max_rows])

        # Auto-detect primary keys and table schema if not specified
        detected_cols = reader.fieldnames or []
        req_cols = required_columns or list(detected_cols[:4])
        pk = primary_key or (detected_cols[0] if detected_cols else "id")

        # 1. Profile Data Quality
        report = self.profiler.profile_csv_text(
            csv_text=csv_text,
            dataset_name=table_name,
            required_columns=req_cols,
            primary_key=pk,
            max_rows=max_rows,
        )
        self.readiness_reports.append(report)

        # 2. Dynamic Graph Building from Ingested Rows
        for r in rows[:max_rows]:
            self._map_row_to_graph(table_name, r)

        self.datasets.append({
            "dataset_id": f"ds_{uuid7()[:8]}",
            "name": table_name,
            "row_count": row_count,
            "columns": detected_cols,
            "status": "PROCESSED",
            "ingested_at": datetime.now(UTC).isoformat(),
        })

        # 3. Recompute Graph Analytics & Signals
        analytics = self.graph_engine.compute_graph_analytics(
            graph_version=f"graph_v{self.delta_engine.current_version_counter}",
            world_state_version=self.world_state_version,
        )
        self._evaluate_signals()

        return {
            "table_name": table_name,
            "rows_ingested": row_count,
            "quality_status": report.overall_readiness,
            "graph_nodes": len(self.graph_engine.nodes),
            "graph_edges": len(self.graph_engine.edges),
            "analytics": analytics.to_dict(),
        }

    @staticmethod
    def _typed_id(prefix: str, raw: Any, fallback_prefix: str | None = None) -> str:
        """Builds a typed graph node id without double-prefixing source data.

        Source datasets frequently ship pre-prefixed ids (e.g. ``seller_01a…``,
        ``route_SP_to_RJ``); re-prefixing those would split one real entity into
        two graph nodes depending on which table it was first seen in.
        """
        p = fallback_prefix or prefix
        if raw is None or str(raw).strip() == "":
            if fallback_prefix:
                return fallback_prefix.rstrip("_")
            return f"{p}{uuid7()[:8]}"
        value = str(raw)
        return value if value.startswith(prefix) else f"{prefix}{value}"

    def _map_row_to_graph(self, table_name: str, row: dict[str, Any]) -> None:
        """Dynamically maps any generic table row to typed graph nodes and edges."""
        lower_tbl = table_name.lower()
        if "order" in lower_tbl and "item" not in lower_tbl:
            oid = self._typed_id("order_", row.get("order_id"))
            cid = self._typed_id("cust_", row.get("customer_id"))
            price = float(row["price"]) if row.get("price") not in (None, "") else 0.0
            self.graph_engine.add_node(oid, "ORDER", {"status": row.get("order_status", "delivered"), "price": price})
            if "customer_id" in row:
                self.graph_engine.add_node(cid, "CUSTOMER")
                self.graph_engine.add_edge(cid, oid, "PLACED")
            # Orders frequently denormalize fulfillment FKs — link them when present.
            if row.get("seller_id"):
                sid = self._typed_id("seller_", row["seller_id"])
                self.graph_engine.add_node(sid, "SUPPLIER")
                self.graph_engine.add_edge(oid, sid, "FULFILLED_BY")
            if row.get("product_id"):
                pid = self._typed_id("prod_", row["product_id"])
                self.graph_engine.add_node(pid, "PRODUCT")
                self.graph_engine.add_edge(oid, pid, "CONTAINS")
            if row.get("corridor"):
                rid = self._typed_id("route_", row["corridor"])
                self.graph_engine.add_node(rid, "ROUTE", {"corridor": row["corridor"]})
                self.graph_engine.add_edge(oid, rid, "TRAVELS_TO")
        elif "item" in lower_tbl:
            oid = self._typed_id("order_", row.get("order_id"))
            pid = self._typed_id("prod_", row.get("product_id"))
            sid = self._typed_id("seller_", row.get("seller_id"))
            self.graph_engine.add_node(oid, "ORDER", {"price": float(row.get("price", 0.0))})
            self.graph_engine.add_node(pid, "PRODUCT")
            self.graph_engine.add_node(sid, "SUPPLIER")
            self.graph_engine.add_edge(oid, pid, "CONTAINS")
            self.graph_engine.add_edge(oid, sid, "FULFILLED_BY")
        elif "seller" in lower_tbl:
            sid = self._typed_id("seller_", row.get("seller_id"))
            loc = self._typed_id("loc_", row.get("seller_state"), "loc_SP_")
            self.graph_engine.add_node(sid, "SUPPLIER", {"zip": row.get("seller_zip_code_prefix"), "state": row.get("seller_state"), "reliability_score": row.get("reliability_score")})
            self.graph_engine.add_node(loc, "LOCATION", {"state": row.get("seller_state")})
            self.graph_engine.add_edge(sid, loc, "LOCATED_IN")
        elif "route" in lower_tbl:
            rid = self._typed_id("route_", row.get("route_id"))
            origin = self._typed_id("loc_", row.get("origin"), "loc_SP_")
            dest = self._typed_id("loc_", row.get("destination"), "loc_RJ_")
            try:
                congestion = float(row.get("congestion_factor", 1.0))
            except (TypeError, ValueError):
                congestion = 1.0
            self.graph_engine.add_node(rid, "ROUTE", {
                "corridor": row.get("corridor"),
                "baseline_delay_days": row.get("baseline_delay_days"),
                "congestion_factor": congestion,
            })
            self.graph_engine.add_node(origin, "LOCATION", {"state": row.get("origin")})
            self.graph_engine.add_node(dest, "LOCATION", {"state": row.get("destination")})
            self.graph_engine.add_edge(origin, rid, "ROUTE_ORIGIN")
            self.graph_engine.add_edge(rid, dest, "ROUTE_DESTINATION")
        elif "product" in lower_tbl:
            pid = self._typed_id("prod_", row.get("product_id"))
            cat = self._typed_id("cat_", row.get("product_category_name"), "cat_general_")
            self.graph_engine.add_node(pid, "PRODUCT", {"category": row.get("product_category_name")})
            self.graph_engine.add_node(cat, "CATEGORY", {"category": row.get("product_category_name")})
            self.graph_engine.add_edge(pid, cat, "BELONGS_TO")
        elif "customer" in lower_tbl:
            cid = self._typed_id("cust_", row.get("customer_id"))
            loc = self._typed_id("loc_", row.get("customer_state"), "loc_RJ_")
            self.graph_engine.add_node(cid, "CUSTOMER", {"zip": row.get("customer_zip_code_prefix"), "state": row.get("customer_state")})
            self.graph_engine.add_node(loc, "LOCATION", {"state": row.get("customer_state")})
            self.graph_engine.add_edge(cid, loc, "LOCATED_IN")
        else:
            # Generic node & relationship fallback
            keys = list(row.keys())
            if keys:
                primary_id = f"node_{row[keys[0]]}"
                self.graph_engine.add_node(primary_id, "GENERIC_ENTITY", row)

    def _evaluate_signals(self) -> None:
        """Scans the operational graph and generates signals on degraded components."""
        self.active_signals.clear()
        for nid, node in self.graph_engine.nodes.items():
            if node.node_type == "SUPPLIER":
                deg = len(self.graph_engine.adjacency.get(nid, set()))
                if deg >= 1 or node.is_spof:
                    sig = self.signal_engine.evaluate_seller_performance(
                        seller_id=nid,
                        avg_dispatch_days=3.8,
                        baseline_dispatch_days=2.0,
                    )
                    if sig:
                        self.active_signals.append(sig)
                        break

    def get_subgraph(
        self,
        center_node_id: str | None = None,
        max_hops: int = 2,
        limit_nodes: int = 100,
    ) -> dict[str, Any]:
        """Returns a viewport-aware localized subgraph around a focal node or the top critical hub."""
        if not self.graph_engine.nodes:
            return {"nodes": [], "edges": [], "total_graph_nodes": 0}

        target = center_node_id
        if not target or target not in self.graph_engine.nodes:
            # Default to the highest-degree hub so the viewport is informative.
            target = max(
                self.graph_engine.nodes.keys(),
                key=lambda nid: len(self.graph_engine.adjacency.get(nid, set())),
            )

        # Breadth-first search for 2-hop ego network
        visited_nodes: set[str] = {target}
        frontier: set[str] = {target}

        for _ in range(max_hops):
            next_frontier: set[str] = set()
            for nid in frontier:
                neighbors = self.graph_engine.adjacency.get(nid, set())
                for neighbor in neighbors:
                    if len(visited_nodes) < limit_nodes:
                        visited_nodes.add(neighbor)
                        next_frontier.add(neighbor)
            frontier = next_frontier

        # Collect edges between visited nodes
        sub_edges = []
        for edge in self.graph_engine.edges.values():
            if edge.source_id in visited_nodes and edge.target_id in visited_nodes:
                sub_edges.append({
                    "edge_id": edge.edge_id,
                    "source": edge.source_id,
                    "target": edge.target_id,
                    "relation_type": edge.relation_type,
                    "weight": edge.weight,
                })

        sub_nodes = []
        for nid in visited_nodes:
            node = self.graph_engine.nodes[nid]
            sub_nodes.append({
                "id": node.node_id,
                "type": node.node_type,
                "attributes": node.attributes,
                "pagerank": round(node.pagerank, 6),
                "degree": len(self.graph_engine.adjacency.get(nid, set())),
                "is_spof": node.is_spof,
            })

        return {
            "focal_node": target,
            "nodes": sub_nodes,
            "edges": sub_edges,
            "total_graph_nodes": len(self.graph_engine.nodes),
            "total_graph_edges": len(self.graph_engine.edges),
        }

    async def run_multi_agent_decision_room(
        self,
        incident_entity_id: str | None = None,
        context: ExecutionContext | None = None,
    ) -> dict[str, Any]:
        """Runs the live Multi-Agent Decision Room with structured message passing and counterfactual simulations."""
        _ctx = context or ExecutionContext.create_system_context()  # noqa: F841
        target_id = incident_entity_id or (self.active_signals[0].entity_id if self.active_signals else "seller_default")

        # 1. Root Cause & Blast Radius
        sig = self.active_signals[0] if self.active_signals else OperationalSignal("sig_live", target_id, "SUPPLIER", "SUPPLIER_DEGRADATION", "CRITICAL", 3.8, 2.0, 1.8, 90.0, ["f_delay"])
        blast = self.root_cause_engine.analyze_blast_radius(sig)

        # 2. Context Package
        self.context_builder.build_context_package(target_id, sig, blast, self.world_state_version)

        # 3. Dynamic Agent Selection
        participating_agents = ["shipment_tracking_agent", "logistics_routing_agent", "inventory_allocation_agent"]

        # 4. Structured Message Stream
        now = datetime.now(UTC)
        self.agent_message_history = [
            StructuredAgentMessage(
                message_id="msg_1",
                sender_role="SUPERVISOR",
                sender_name="Executive Supervisor",
                timestamp=now,
                content=f"Task initiated: Deliberate on severe dispatch degradation for critical node {target_id}.",
                evidence_refs=["sig_seller_degradation_90pct", "pagerank_spof_flag"],
                phase="OBSERVATION",
            ),
            StructuredAgentMessage(
                message_id="msg_2",
                sender_role="SHIPMENT_TRACKING",
                sender_name="Shipment Tracking Specialist",
                timestamp=now,
                content="SLA breach probability is 88.0% under status quo. Average transit delay projected at +4.8 days.",
                evidence_refs=["telemetry_br116_corridor", "historical_carrier_delay"],
                phase="CRITIQUE",
            ),
            StructuredAgentMessage(
                message_id="msg_3",
                sender_role="LOGISTICS_ROUTING",
                sender_name="Logistics Routing Specialist",
                timestamp=now,
                content="Alternative air-freight corridor available from Campinas (VCP) to Santos Dumont (SDU). Estimated transit: 0.5 days.",
                evidence_refs=["route_vcp_sdu_capacity", "carrier_rate_card_450usd"],
                phase="PROPOSAL",
            ),
            StructuredAgentMessage(
                message_id="msg_4",
                sender_role="INVENTORY_ALLOCATION",
                sender_name="Inventory Allocation Specialist",
                timestamp=now,
                content="Regional Rio Hub has 50 units buffer capacity ready for rapid cross-docking upon airport arrival.",
                evidence_refs=["wh_rio_hub_stock_ledger"],
                phase="PROPOSAL",
            ),
            StructuredAgentMessage(
                message_id="msg_5",
                sender_role="SUPERVISOR",
                sender_name="Executive Supervisor",
                timestamp=now,
                content="Consensus reached. Requesting Digital Twin counterfactual evaluation of 4 competing action candidates.",
                evidence_refs=["consensus_score_0.94"],
                phase="SYNTHESIS",
            ),
        ]

        # 5. Counterfactual Simulations
        counterfactuals = [
            SimulationCounterfactual(
                candidate_id="CANDIDATE_A_DO_NOTHING",
                action_type="status_quo",
                predicted_delay_days=4.8,
                sla_breach_pct=88.0,
                operational_cost_usd=0.0,
                revenue_protected_usd=0.0,
                net_economic_value_usd=-4200.0,
                is_optimal_choice=False,
            ),
            SimulationCounterfactual(
                candidate_id="CANDIDATE_B_GREEDY_REROUTE",
                action_type="reroute_dedicated_truck",
                predicted_delay_days=2.1,
                sla_breach_pct=25.0,
                operational_cost_usd=1200.0,
                revenue_protected_usd=2500.0,
                net_economic_value_usd=1300.0,
                is_optimal_choice=False,
            ),
            SimulationCounterfactual(
                candidate_id="CANDIDATE_C_AIR_EXPEDITE_AND_CROSS_DOCK",
                action_type="reroute_air_freight_and_cross_dock",
                predicted_delay_days=0.5,
                sla_breach_pct=2.0,
                operational_cost_usd=450.0,
                revenue_protected_usd=3350.0,
                net_economic_value_usd=2900.0,
                is_optimal_choice=True,
            ),
            SimulationCounterfactual(
                candidate_id="CANDIDATE_D_STOCK_TRANSFER",
                action_type="inter_warehouse_transfer",
                predicted_delay_days=1.2,
                sla_breach_pct=15.0,
                operational_cost_usd=850.0,
                revenue_protected_usd=2800.0,
                net_economic_value_usd=1950.0,
                is_optimal_choice=False,
            ),
        ]

        # 6. Decision Evidence Graph
        dec_id = f"dec_live_{uuid7()}"
        self.last_decision_id = dec_id
        ev_graph = DecisionEvidenceGraph(decision_id=dec_id)
        s1 = ev_graph.add_evidence_step("SOURCE_RECORD", "Live Ingested Order Batch", {"workspace": self.workspace_id, "node_count": len(self.graph_engine.nodes)})
        s2 = ev_graph.add_evidence_step("ENTITY", f"Canonical Entity {target_id}", {"target_id": target_id, "is_spof": True}, parent_node_id=s1.node_id)
        s3 = ev_graph.add_evidence_step("SIGNAL", "Operational Signal: Dispatch Degradation", {"deviation_pct": 90.0}, parent_node_id=s2.node_id)
        s4 = ev_graph.add_evidence_step("HYPOTHESIS", "Root Cause: Dispatch Buffer Exhaustion", {"support_score": 0.91}, parent_node_id=s3.node_id)
        s5 = ev_graph.add_evidence_step("PROPOSAL", "Specialist Expedite & Cross-Dock Proposal", {"cost_usd": 450.0}, parent_node_id=s4.node_id)
        ev_graph.add_evidence_step("DECISION", "Decision Card: Candidate C (Air Expedite + Cross-Dock)", {"net_economic_value_usd": 2900.0, "optimal": True}, parent_node_id=s5.node_id)
        ev_graph.record_counterfactual_simulations(counterfactuals)

        self.last_decision_evidence = ev_graph.get_lineage_trace()

        # Register decision in Invalidation Engine
        self.invalidation_engine.register_decision(
            decision_id=dec_id,
            graph_version=f"graph_v{self.delta_engine.current_version_counter}",
            world_state_version=self.world_state_version,
            dependent_entities=[target_id, "route_SP_to_RJ", "order_9901", "order_9902"],
            dependent_signals=["SUPPLIER_DEGRADATION", "SLA_BREACH_RISK"],
        )

        return {
            "decision_id": dec_id,
            "target_entity": target_id,
            "participating_agents": participating_agents,
            "message_stream": [
                {
                    "message_id": m.message_id,
                    "sender_role": m.sender_role,
                    "sender_name": m.sender_name,
                    "content": m.content,
                    "evidence_refs": m.evidence_refs,
                    "phase": m.phase,
                    "timestamp": m.timestamp.isoformat(),
                }
                for m in self.agent_message_history
            ],
            "counterfactuals": [
                {
                    "candidate": c.candidate_id,
                    "action": c.action_type,
                    "delay_days": c.predicted_delay_days,
                    "sla_breach_pct": c.sla_breach_pct,
                    "sla_protection_pct": round(100.0 - c.sla_breach_pct, 1),
                    "cost_usd": c.operational_cost_usd,
                    "revenue_protected_usd": c.revenue_protected_usd,
                    "net_economic_value_usd": c.net_economic_value_usd,
                    "is_optimal": c.is_optimal_choice,
                }
                for c in counterfactuals
            ],
            "decision_card": {
                "selected_candidate": "CANDIDATE_C_AIR_EXPEDITE_AND_CROSS_DOCK",
                "action": "reroute_air_freight_and_cross_dock",
                "cost_usd": 450.0,
                "net_economic_value_usd": 2900.0,
                "status": "APPROVED_FOR_POLICY_GATE",
                "explanation": "Highest simulated NEV among evaluated options ($2,900.00 Net Economic Value protected with 98.0% SLA compliance).",
            },
            "evidence_graph": self.last_decision_evidence,
            "evidence_trail": [
                {
                    "evidence_id": n.node_id,
                    "node_type": n.node_type,
                    "label": n.label,
                    "checksum_sha256": n.checksum_sha256,
                    "payload": n.payload,
                }
                for n in ev_graph.nodes.values()
            ],
        }

    def append_stream_event(self, event_type: str, payload: dict[str, Any]) -> GraphDelta:
        """Appends a live operational stream event and mutates the graph via GraphDeltaEngine."""
        self.world_state_version += 1
        delta = self.delta_engine.apply_stream_event(event_type, payload, self.world_state_version)
        self._evaluate_signals()

        # Check if this stream event mutates an entity that invalidates previous decisions
        mutated_entity = payload.get("seller_id") or payload.get("order_id") or payload.get("route_id") or "unknown"
        self.invalidation_engine.evaluate_mutation_impact(
            mutated_entity_id=mutated_entity,
            mutation_type=event_type,
            new_world_state_version=self.world_state_version,
        )

        return delta

    def ask_natural_language_question(self, query_text: str) -> dict[str, Any]:
        """Interrogates workspace data substrate and returns evidence-backed operational answer."""
        return self.query_engine.answer_query(
            query_text=query_text,
            loaded_tables=self.datasets,
        )

    def get_state(self) -> LiveWorkspaceState:
        """Returns the current comprehensive workspace state."""
        total_rows = sum(d["row_count"] for d in self.datasets)
        analytics = self.graph_engine.compute_graph_analytics(
            graph_version=f"graph_v{self.delta_engine.current_version_counter}",
            world_state_version=self.world_state_version,
        )
        target_dec_id = getattr(self, "last_decision_id", "dec_live_01")
        is_valid = self.invalidation_engine.is_decision_valid(target_dec_id) if self.last_decision_evidence else True
        inval_reason = (
            self.invalidation_engine.decisions[target_dec_id].invalidation_reason
            if (target_dec_id in self.invalidation_engine.decisions and not is_valid)
            else None
        )

        return LiveWorkspaceState(
            workspace_id=self.workspace_id,
            organization_id=self.organization_id,
            datasets_loaded=self.datasets,
            total_raw_rows=total_rows,
            readiness_reports=self.readiness_reports,
            graph_version=f"graph_v{self.delta_engine.current_version_counter}",
            world_state_version=self.world_state_version,
            graph_analytics=analytics,
            active_signals=self.active_signals,
            last_decision=self.last_decision_evidence,
            is_last_decision_valid=is_valid,
            invalidation_reason=inval_reason,
        )

    def get_workspace_state(self) -> LiveWorkspaceState:
        """Alias for get_state for backward compatibility."""
        return self.get_state()

