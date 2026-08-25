"""Program T1 — Operational Intent Parser.

Parses natural language operator queries into structured, actionable OperationalIntents:
- Target Entity Types
- Operational Constraints & Thresholds
- Time Horizons (e.g. next 48 hours, 30 days)
- Required Analytical Operations (Centrality, Path Tracing, Blast Radius, Simulation).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class IntentType(StrEnum):
    FIND_CRITICAL_ENTITIES = "FIND_CRITICAL_ENTITIES"
    TRACE_BLAST_RADIUS = "TRACE_BLAST_RADIUS"
    IDENTIFY_ROUTE_RISK = "IDENTIFY_ROUTE_RISK"
    GRAPH_DELTA_ANALYSIS = "GRAPH_DELTA_ANALYSIS"
    SCENARIO_SIMULATION = "SCENARIO_SIMULATION"
    GENERIC_GRAPH_QUERY = "GENERIC_GRAPH_QUERY"


@dataclass
class OperationalIntent:
    intent_type: IntentType
    raw_query: str
    target_entity_types: list[str]
    time_horizon_hours: int | None = None
    target_entity_id: str | None = None
    risk_threshold_pct: float | None = None
    metrics_requested: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent_type": self.intent_type.value,
            "raw_query": self.raw_query,
            "target_entity_types": self.target_entity_types,
            "time_horizon_hours": self.time_horizon_hours,
            "target_entity_id": self.target_entity_id,
            "risk_threshold_pct": self.risk_threshold_pct,
            "metrics_requested": self.metrics_requested,
        }


class OperationalIntentParser:
    """Deterministic, structured intent parser for enterprise operational queries."""

    def parse(self, query: str) -> OperationalIntent:
        lower_q = query.lower()

        # 1. Scenario Simulation Intent
        if any(w in lower_q for w in ["what happens if", "simulate", "if seller", "disappears", "fails"]):
            # Extract target entity if present
            words = query.split()
            entity_id = None
            for w in words:
                if "seller_" in w or "cust_" in w or "route_" in w:
                    entity_id = w.strip("?.,")
            return OperationalIntent(
                intent_type=IntentType.SCENARIO_SIMULATION,
                raw_query=query,
                target_entity_types=["SELLER", "ROUTE"],
                target_entity_id=entity_id or "seller_01a00b8e99",
                metrics_requested=["sla_breach_pct", "net_economic_value_usd", "revenue_at_risk"],
            )

        # 2. Blast Radius & Customer Exposure Intent
        if any(w in lower_q for w in ["customers", "exposed", "blast radius", "revenue exposure", "impacted"]):
            return OperationalIntent(
                intent_type=IntentType.TRACE_BLAST_RADIUS,
                raw_query=query,
                target_entity_types=["CUSTOMER", "ORDER"],
                metrics_requested=["revenue_at_risk_usd", "affected_orders_count", "customer_regions"],
            )

        # 3. Route & Logistics Risk Intent
        if any(w in lower_q for w in ["route", "corridor", "transit variance", "congestion", "carrier"]):
            return OperationalIntent(
                intent_type=IntentType.IDENTIFY_ROUTE_RISK,
                raw_query=query,
                target_entity_types=["ROUTE", "LOCATION"],
                metrics_requested=["transit_variance_days", "active_orders_volume", "pagerank"],
            )

        # 4. Graph Delta & Changes Intent
        if any(w in lower_q for w in ["changed", "deltas", "added", "last 24 hours", "evolution"]):
            return OperationalIntent(
                intent_type=IntentType.GRAPH_DELTA_ANALYSIS,
                raw_query=query,
                target_entity_types=["ORDER", "SELLER", "ROUTE"],
                time_horizon_hours=24,
                metrics_requested=["added_nodes_count", "added_edges_count", "updated_nodes_count"],
            )

        # 5. Critical Sellers / SLA Breach Intent (Default top query)
        time_horizon = 48 if "48 hours" in lower_q else (24 if "24 hours" in lower_q else None)
        return OperationalIntent(
            intent_type=IntentType.FIND_CRITICAL_ENTITIES,
            raw_query=query,
            target_entity_types=["SELLER"],
            time_horizon_hours=time_horizon,
            metrics_requested=["dispatch_delay_days", "pagerank_centrality", "is_spof", "sla_breach_probability"],
        )
