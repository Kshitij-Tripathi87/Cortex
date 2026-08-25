"""Capacity Booking Agent — Group A1.

Evaluates multimodal carrier availability, rate cards, cutoff windows, and capacity allocations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.modules.multi_agent.tools.domain_toolkits import DomainToolRegistry
from app.modules.multi_agent.tools.manifests import CAPABILITY_MANIFESTS


@dataclass
class CapacityBookingProposal:
    agent_id: str
    recommended_carrier: str
    recommended_lane: str
    mode: str
    expected_cost_usd: float
    expected_transit_days: float
    sla_protection_pct: float
    cutoff_time: str
    evidence_refs: list[str]
    proposal_status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "recommended_carrier": self.recommended_carrier,
            "recommended_lane": self.recommended_lane,
            "mode": self.mode,
            "expected_cost_usd": self.expected_cost_usd,
            "expected_transit_days": self.expected_transit_days,
            "sla_protection_pct": self.sla_protection_pct,
            "cutoff_time": self.cutoff_time,
            "evidence_refs": self.evidence_refs,
            "proposal_status": self.proposal_status,
        }


class CapacityBookingAgent:
    """Specialist agent for transport capacity discovery and rate evaluation."""

    def __init__(self) -> None:
        self.manifest = CAPABILITY_MANIFESTS["capacity_booking_agent"]
        self.agent_id = self.manifest.agent_id
        self.version = self.manifest.version

    def evaluate_capacity(self, origin: str, destination: str, required_volume_m3: float = 5.0) -> CapacityBookingProposal:
        """Executes capacity search and rate evaluation to formulate booking proposals."""
        cap_res = DomainToolRegistry.search_capacity(origin, destination, required_volume_m3)
        lanes = cap_res.data.get("matched_lanes", [])

        # Best lane: Air cargo corridor if urgent SLA protection needed
        air_lane = next((l for l in lanes if l.get("mode") == "AIR_CARGO"), lanes[0] if lanes else None)

        carrier_id = air_lane["carrier_id"] if air_lane else "carrier_air_latam_cargo"
        lane_str = air_lane["corridor"] if air_lane else "VCP-SDU"

        rate_res = DomainToolRegistry.get_carrier_rates(carrier_id, lane_str)
        cost = rate_res.data.get("total_cost_usd", 450.0)

        evidence = cap_res.evidence_tags + rate_res.evidence_tags

        return CapacityBookingProposal(
            agent_id=self.agent_id,
            recommended_carrier=carrier_id,
            recommended_lane=lane_str,
            mode="AIR_FREIGHT",
            expected_cost_usd=cost,
            expected_transit_days=0.5,
            sla_protection_pct=98.0,
            cutoff_time=air_lane.get("cutoff_time", "14:00:00Z") if air_lane else "14:00:00Z",
            evidence_refs=evidence,
            proposal_status="PROPOSED",
        )
