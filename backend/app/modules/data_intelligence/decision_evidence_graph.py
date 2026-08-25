"""Program Q & R — Decision Evidence Graph & Full Attribution Traceability.

Links every synthesized decision in Nexus to an explicit, cryptographically verifiable
provenance chain:
Source Records -> Canonical Entity -> Operational Signal -> Root-Cause Hypothesis ->
GNN / Model Output -> Agent Proposals -> Simulation Counterfactuals -> Synthesized Decision ->
Execution -> Realized Outcome -> Retraining Dataset.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.common.ids import uuid7


@dataclass
class EvidenceNode:
    node_id: str
    node_type: str  # "SOURCE_RECORD" | "ENTITY" | "SIGNAL" | "HYPOTHESIS" | "MODEL_OUTPUT" | "PROPOSAL" | "SIMULATION" | "DECISION" | "OUTCOME"
    label: str
    payload: dict[str, Any]
    checksum_sha256: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class EvidenceEdge:
    edge_id: str
    source_node_id: str
    target_node_id: str
    relation: str  # "GROUNDED_IN" | "GENERATED_BY" | "HYPOTHESIZES" | "EVALUATED_IN" | "RESULTED_IN"


@dataclass
class SimulationCounterfactual:
    candidate_id: str  # "CANDIDATE_A_DO_NOTHING" | "CANDIDATE_B_GREEDY_REROUTE" | "CANDIDATE_C_AIR_EXPEDITE" | "CANDIDATE_D_STOCK_XFER"
    action_type: str
    predicted_delay_days: float
    sla_breach_pct: float
    operational_cost_usd: float
    revenue_protected_usd: float
    net_economic_value_usd: float  # Loss_without - Loss_with - Intervention_Cost
    is_optimal_choice: bool


class DecisionEvidenceGraph:
    """Traversable provenance graph linking decisions back to raw evidence and forward to realized outcomes."""

    def __init__(self, decision_id: str) -> None:
        self.decision_id = decision_id
        self.nodes: dict[str, EvidenceNode] = {}
        self.edges: list[EvidenceEdge] = []
        self.counterfactuals: list[SimulationCounterfactual] = []

    def add_evidence_step(
        self,
        node_type: str,
        label: str,
        payload: dict[str, Any],
        parent_node_id: str | None = None,
        relation: str = "GENERATED_BY",
    ) -> EvidenceNode:
        raw_json = json.dumps(payload, sort_keys=True, default=str)
        checksum = hashlib.sha256(raw_json.encode("utf-8")).hexdigest()
        node_id = f"ev_{node_type.lower()}_{uuid7()[:8]}"

        node = EvidenceNode(
            node_id=node_id,
            node_type=node_type,
            label=label,
            payload=payload,
            checksum_sha256=checksum,
        )
        self.nodes[node_id] = node

        if parent_node_id and parent_node_id in self.nodes:
            edge = EvidenceEdge(
                edge_id=f"edge_{parent_node_id}_{node_id}",
                source_node_id=parent_node_id,
                target_node_id=node_id,
                relation=relation,
            )
            self.edges.append(edge)

        return node

    def record_counterfactual_simulations(
        self,
        simulations: list[SimulationCounterfactual],
    ) -> None:
        self.counterfactuals = simulations

    def compute_chain_hash(self) -> str:
        """SHA-256 over ordered evidence node checksums (source to outcome).

        Proves the full provenance chain is intact and unmodified.
        Deterministic: same nodes in same order → same chain_hash.
        """
        # Order nodes by creation time (insertion order in dict)
        checksums = [n.checksum_sha256 for n in self.nodes.values()]
        blob = json.dumps(checksums, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()

    def get_lineage_trace(self) -> dict[str, Any]:
        """Produce full audit trace from source data to decision and outcome."""
        return {
            "decision_id": self.decision_id,
            "total_evidence_nodes": len(self.nodes),
            "total_attribution_edges": len(self.edges),
            "nodes": [
                {
                    "node_id": n.node_id,
                    "node_type": n.node_type,
                    "label": n.label,
                    "checksum": n.checksum_sha256[:12],
                    "payload": n.payload,
                }
                for n in self.nodes.values()
            ],
            "attribution_edges": [
                {
                    "from": e.source_node_id,
                    "to": e.target_node_id,
                    "relation": e.relation,
                }
                for e in self.edges
            ],
            "counterfactual_simulations": [
                {
                    "candidate": c.candidate_id,
                    "action": c.action_type,
                    "delay_days": c.predicted_delay_days,
                    "sla_breach_pct": c.sla_breach_pct,
                    "cost_usd": c.operational_cost_usd,
                    "revenue_protected_usd": c.revenue_protected_usd,
                    "net_economic_value_usd": c.net_economic_value_usd,
                    "is_optimal": c.is_optimal_choice,
                }
                for c in self.counterfactuals
            ],
        }
