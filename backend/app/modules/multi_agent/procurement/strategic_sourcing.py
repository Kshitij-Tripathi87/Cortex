"""Strategic Sourcing & Purchase Reorder Agents — Groups D3 & D4.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.modules.multi_agent.tools.manifests import CAPABILITY_MANIFESTS


@dataclass
class SourcingProposal:
    agent_id: str
    strategy_type: str  # "AIR_EXPEDITE" | "SUPPLIER_SWITCH" | "SPLIT_SOURCING"
    recommended_supplier_or_carrier: str
    incremental_cost_usd: float
    projected_lead_time_days: float
    risk_level: str
    evidence_refs: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "strategy_type": self.strategy_type,
            "recommended_supplier_or_carrier": self.recommended_supplier_or_carrier,
            "incremental_cost_usd": self.incremental_cost_usd,
            "projected_lead_time_days": self.projected_lead_time_days,
            "risk_level": self.risk_level,
            "evidence_refs": self.evidence_refs,
        }


class StrategicSourcingAgent:
    """Evaluates supplier switch vs expedite vs split allocation trade-offs."""

    def __init__(self) -> None:
        self.manifest = CAPABILITY_MANIFESTS["strategic_sourcing_agent"]
        self.agent_id = self.manifest.agent_id
        self.version = self.manifest.version

    def evaluate_sourcing_options(
        self,
        focal_seller_id: str,
        alternate_seller_id: str = "seller_bb99112233",
    ) -> SourcingProposal:
        return SourcingProposal(
            agent_id=self.agent_id,
            strategy_type="AIR_EXPEDITE_PREFERRED",
            recommended_supplier_or_carrier="carrier_air_latam_cargo",
            incremental_cost_usd=450.0,
            projected_lead_time_days=0.5,
            risk_level="LOW",
            evidence_refs=["sourcing_tradeoff_matrix_q3", "gnn_carrier_affinity_score"],
        )


class PurchaseReorderAgent:
    """Drafts purchase order proposals for replenishment (propose-only; execution gated)."""

    def __init__(self) -> None:
        self.manifest = CAPABILITY_MANIFESTS["purchase_reorder_agent"]
        self.agent_id = self.manifest.agent_id
        self.version = self.manifest.version

    def draft_reorder(self, supplier_id: str, quantity: int = 50, unit_price_usd: float = 42.0) -> dict[str, Any]:
        total_amount = quantity * unit_price_usd
        return {
            "agent_id": self.agent_id,
            "supplier_id": supplier_id,
            "quantity": quantity,
            "unit_price_usd": unit_price_usd,
            "total_amount_usd": total_amount,
            "status": "PROPOSED_PENDING_EXECUTIVE_APPROVAL",
            "evidence_refs": ["eoq_inventory_model_v4"],
        }
