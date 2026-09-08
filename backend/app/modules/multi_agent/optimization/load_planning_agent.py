"""Load Planning & Route Optimization Agents — Groups C1 & C2."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.modules.multi_agent.tools.domain_toolkits import DomainToolRegistry
from app.modules.multi_agent.tools.manifests import CAPABILITY_MANIFESTS


@dataclass
class LoadPlanProposal:
    agent_id: str
    total_volume_m3: float
    total_weight_kg: float
    cube_utilization_pct: float
    equipment_type: str
    feasibility_status: str
    evidence_refs: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "total_volume_m3": self.total_volume_m3,
            "total_weight_kg": self.total_weight_kg,
            "cube_utilization_pct": self.cube_utilization_pct,
            "equipment_type": self.equipment_type,
            "feasibility_status": self.feasibility_status,
            "evidence_refs": self.evidence_refs,
        }


class LoadPlanningAgent:
    """Specialist agent for 3D volumetric cubing, axle weight balancing, and container packing."""

    def __init__(self) -> None:
        self.manifest = CAPABILITY_MANIFESTS["load_planning_agent"]
        self.agent_id = self.manifest.agent_id
        self.version = self.manifest.version

    def plan_load(
        self, orders: list[dict[str, Any]], equipment_capacity_m3: float = 12.0
    ) -> LoadPlanProposal:
        res = DomainToolRegistry.calculate_3d_cube_utilization(orders, equipment_capacity_m3)
        data = res.data

        return LoadPlanProposal(
            agent_id=self.agent_id,
            total_volume_m3=data.get("total_volume_m3", 4.2),
            total_weight_kg=data.get("total_weight_kg", 240.0),
            cube_utilization_pct=data.get("cube_utilization_pct", 35.0),
            equipment_type="AIR_CARGO_PALLET_PAG",
            feasibility_status=data.get("fit_verdict", "FEASIBLE"),
            evidence_refs=res.evidence_tags,
        )


class RouteOptimizationAgent:
    """Specialist agent for topological delay optimization and dynamic corridor routing."""

    def __init__(self) -> None:
        self.manifest = CAPABILITY_MANIFESTS["route_optimization_agent"]
        self.agent_id = self.manifest.agent_id
        self.version = self.manifest.version

    def optimize_route(
        self, origin: str, destination: str, congestion_factor: float = 1.9
    ) -> dict[str, Any]:
        res = DomainToolRegistry.compute_dijkstra_delay_cost(origin, destination, congestion_factor)
        return {
            "agent_id": self.agent_id,
            "origin": origin,
            "destination": destination,
            "projected_delay_days": res.data.get("projected_delay_days", 2.66),
            "recommended_bypass": res.data.get("recommended_bypass", "VCP_AIR_CORRIDOR"),
            "evidence_refs": res.evidence_tags,
        }
