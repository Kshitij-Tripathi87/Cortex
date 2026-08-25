"""Program T3 — Graph & World State Query Execution Planner.

Converts an OperationalIntent into an executable QueryExecutionPlan across:
- Operational Graph Engine (Topological traversals, PageRank scans, SPOF filters)
- Signal Engine (Active anomalies, threshold crossings)
- Feature Store (Dispatch averages, transit variances)
- Digital Twin Simulator (Counterfactual candidate evaluations).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.modules.query.intent_parser import IntentType, OperationalIntent


@dataclass
class QueryStep:
    step_id: str
    target_engine: str  # "GRAPH_ENGINE" | "SIGNAL_ENGINE" | "FEATURE_STORE" | "SIMULATION_ENGINE"
    operation: str
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class QueryExecutionPlan:
    plan_id: str
    intent: OperationalIntent
    steps: list[QueryStep]
    estimated_cost_ms: float
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "intent": self.intent.to_dict(),
            "steps": [
                {
                    "step_id": s.step_id,
                    "target_engine": s.target_engine,
                    "operation": s.operation,
                    "parameters": s.parameters,
                }
                for s in self.steps
            ],
            "estimated_cost_ms": self.estimated_cost_ms,
            "created_at": self.created_at.isoformat(),
        }


class QueryPlanner:
    """Plans optimized multi-step queries over graph topology, features, and simulations."""

    def create_plan(self, intent: OperationalIntent) -> QueryExecutionPlan:
        steps: list[QueryStep] = []

        if intent.intent_type == IntentType.FIND_CRITICAL_ENTITIES:
            steps.append(QueryStep(
                step_id="step_1_spof_scan",
                target_engine="GRAPH_ENGINE",
                operation="FILTER_CRITICAL_SPOF_NODES",
                parameters={"node_type": "SELLER", "min_pagerank": 0.02},
            ))
            steps.append(QueryStep(
                step_id="step_2_signal_join",
                target_engine="SIGNAL_ENGINE",
                operation="SCAN_ACTIVE_DEGRADATION_SIGNALS",
                parameters={"signal_types": ["SELLER_DEGRADATION", "SLA_BREACH_RISK"]},
            ))

        elif intent.intent_type == IntentType.TRACE_BLAST_RADIUS:
            steps.append(QueryStep(
                step_id="step_1_graph_traversal",
                target_engine="GRAPH_ENGINE",
                operation="TRAVERSE_DOWNSTREAM_ORDERS_AND_CUSTOMERS",
                parameters={"max_hops": 2},
            ))
            steps.append(QueryStep(
                step_id="step_2_exposure_calc",
                target_engine="FEATURE_STORE",
                operation="AGGREGATE_REVENUE_AT_RISK",
            ))

        elif intent.intent_type == IntentType.IDENTIFY_ROUTE_RISK:
            steps.append(QueryStep(
                step_id="step_1_route_centrality",
                target_engine="GRAPH_ENGINE",
                operation="SCAN_ROUTE_NODES_BY_BETWEENNESS",
            ))

        elif intent.intent_type == IntentType.SCENARIO_SIMULATION:
            steps.append(QueryStep(
                step_id="step_1_clone_world_state",
                target_engine="SIMULATION_ENGINE",
                operation="EVALUATE_COUNTERFACTUAL_CANDIDATES",
                parameters={"target_entity_id": intent.target_entity_id},
            ))

        else:
            steps.append(QueryStep(
                step_id="step_1_generic_scan",
                target_engine="GRAPH_ENGINE",
                operation="EXTRACT_VIEWPORT_SUBGRAPH",
            ))

        return QueryExecutionPlan(
            plan_id=f"plan_{intent.intent_type.value.lower()[:10]}",
            intent=intent,
            steps=steps,
            estimated_cost_ms=12.5,
        )
