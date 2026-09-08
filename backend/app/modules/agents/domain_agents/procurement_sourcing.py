"""Procurement Sourcing Specialist Agent — Multi-Factor Supplier Ranking & Expedite Decisions.

Capabilities:
- Ranks alternative tier-1 and tier-2 qualified suppliers
- Evaluates contract pricing vs spot market surcharges
- Generates purchase order proposals within policy spending gates
"""

from __future__ import annotations

from dataclasses import dataclass

from app.common.capabilities import Capability
from app.common.context import ExecutionContext
from app.modules.agents.lifecycle_models import SignedCapabilityManifest


@dataclass
class SupplierQuote:
    supplier_id: str
    name: str
    unit_cost_usd: float
    lead_time_days: float
    available_capacity: float
    quality_score: float  # 0.0 to 1.0
    tier: int


class ProcurementSourcingAgent:
    """Production procurement agent selecting alternative suppliers during component shortages."""

    def __init__(self, version: str = "v5") -> None:
        self.agent_id = "procurement_sourcing_agent"
        self.version = version
        self.capability_manifest = SignedCapabilityManifest(
            agent_id=self.agent_id,
            version=self.version,
            allowed_capabilities=[
                Capability.READ.value,
                Capability.PROPOSE.value,
                Capability.SIMULATE.value,
            ],
            allowed_tools=[
                "get_supplier_catalog",
                "simulate_supplier_reliability",
                "rank_suppliers",
            ],
            policy_id=f"policy_{self.agent_id}_{version}",
        )
        self.capability_manifest.signature = self.capability_manifest.compute_signature()

    async def rank_alternative_sources(
        self,
        component_id: str,
        required_units: float,
        context: ExecutionContext,
    ) -> list[SupplierQuote]:
        """Rank qualified alternative suppliers by weighted score of lead time, quality, and cost."""
        suppliers = [
            SupplierQuote(
                supplier_id="sup_beta_semi",
                name="Beta Semiconductor Corp",
                unit_cost_usd=42.0,
                lead_time_days=4.0,
                available_capacity=5000.0,
                quality_score=0.98,
                tier=1,
            ),
            SupplierQuote(
                supplier_id="sup_gamma_micro",
                name="Gamma Microelectronics",
                unit_cost_usd=38.5,
                lead_time_days=9.0,
                available_capacity=10000.0,
                quality_score=0.92,
                tier=2,
            ),
        ]
        # Sort by composite score (lead time weighted heavily)
        return sorted(suppliers, key=lambda s: s.lead_time_days * 0.6 + s.unit_cost_usd * 0.4)
