"""Freight Tender & Booking Exception Agents — Groups A3 & A4.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.modules.multi_agent.tools.manifests import CAPABILITY_MANIFESTS


@dataclass
class TenderInstruction:
    tender_id: str
    carrier_id: str
    origin: str
    destination: str
    equipment_type: str
    total_cost_usd: float
    cutoff_time: str
    status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "tender_id": self.tender_id,
            "carrier_id": self.carrier_id,
            "origin": self.origin,
            "destination": self.destination,
            "equipment_type": self.equipment_type,
            "total_cost_usd": self.total_cost_usd,
            "cutoff_time": self.cutoff_time,
            "status": self.status,
        }


class FreightTenderAgent:
    """Specialist agent for tender documentation and booking dispatch validation."""

    def __init__(self) -> None:
        self.manifest = CAPABILITY_MANIFESTS["freight_tender_agent"]
        self.agent_id = self.manifest.agent_id
        self.version = self.manifest.version

    def prepare_tender(self, carrier_id: str, lane: str, cost_usd: float) -> TenderInstruction:
        return TenderInstruction(
            tender_id=f"TND_{lane.replace('-', '_')}_{int(cost_usd)}",
            carrier_id=carrier_id,
            origin=lane.split("-")[0] if "-" in lane else "SP",
            destination=lane.split("-")[1] if "-" in lane else "RJ",
            equipment_type="AIR_CONTAINER_LD3",
            total_cost_usd=cost_usd,
            cutoff_time="14:00:00Z",
            status="READY_FOR_GOVERNANCE_SIGN_OFF",
        )


class BookingExceptionAgent:
    """Handles carrier rejections, missed cutoffs, and automated backup re-routing."""

    def __init__(self) -> None:
        self.manifest = CAPABILITY_MANIFESTS["booking_exception_agent"]
        self.agent_id = self.manifest.agent_id
        self.version = self.manifest.version

    def handle_rejection(self, failed_carrier_id: str, origin: str, destination: str) -> dict[str, Any]:
        return {
            "exception_type": "CARRIER_REJECTION_OR_CUTOFF_MISSED",
            "failed_carrier": failed_carrier_id,
            "fallback_strategy": "TRIGGER_SECONDARY_AIR_CARRIER_OR_CROSS_DOCK",
            "fallback_carrier": "carrier_road_azul_express",
            "re_priced_cost_usd": 380.0,
            "expected_delay_penalty_hours": 4.0,
        }
