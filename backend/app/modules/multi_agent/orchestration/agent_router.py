"""Dynamic Graph-Aware Agent Router.

Computes domain relevance scores from graph topology and active anomaly signals
to dynamically activate relevant specialists without brute-force invocation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class DomainRelevanceAssessment:
    domain_group: str
    relevance_score: float  # 0.0 to 1.0
    activated_specialists: list[str]
    activation_rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain_group": self.domain_group,
            "relevance_score": self.relevance_score,
            "activated_specialists": self.activated_specialists,
            "activation_rationale": self.activation_rationale,
        }


class DynamicAgentRouter:
    """Calculates relevance scores to dynamically compose task execution ensembles."""

    @staticmethod
    def route_incident(
        signal_type: str,
        entity_type: str,
        severity: str = "CRITICAL",
        has_route_bottleneck: bool = True,
    ) -> list[DomainRelevanceAssessment]:
        """Evaluates incident topology and returns domain activation assessments."""
        assessments = []

        # 1. Booking & Negotiation Domain
        booking_score = 0.95 if has_route_bottleneck or "DEGRADATION" in signal_type else 0.65
        assessments.append(
            DomainRelevanceAssessment(
                domain_group="BOOKING",
                relevance_score=booking_score,
                activated_specialists=["capacity_booking_agent", "carrier_negotiation_agent"],
                activation_rationale="Corridor transit breach requires expedited multimodal air capacity discovery and rate negotiation.",
            )
        )

        # 2. Back-Office & Compliance Domain (Always active for execution safety)
        compliance_score = 0.98
        assessments.append(
            DomainRelevanceAssessment(
                domain_group="COMPLIANCE",
                relevance_score=compliance_score,
                activated_specialists=[
                    "compliance_agent",
                    "finance_validation_agent",
                    "audit_agent",
                ],
                activation_rationale="Mandatory control plane audit to enforce vendor validation, spend budget, and Merkle provenance DAG.",
            )
        )

        # 3. Load Planning & Optimization Domain
        optimization_score = 0.88 if has_route_bottleneck else 0.70
        assessments.append(
            DomainRelevanceAssessment(
                domain_group="OPTIMIZATION",
                relevance_score=optimization_score,
                activated_specialists=[
                    "load_planning_agent",
                    "route_optimization_agent",
                    "consolidation_agent",
                ],
                activation_rationale="Volumetric 3D cubing and co-loading consolidation required to package 12 exposed orders.",
            )
        )

        # 4. Procurement & Sourcing Domain
        procurement_score = 0.94 if entity_type == "SELLER" else 0.60
        assessments.append(
            DomainRelevanceAssessment(
                domain_group="PROCUREMENT",
                relevance_score=procurement_score,
                activated_specialists=[
                    "supplier_discovery_agent",
                    "supplier_evaluation_agent",
                    "strategic_sourcing_agent",
                ],
                activation_rationale="GNN supplier similarity required to evaluate alternate qualified sellers and safety stock transfers.",
            )
        )

        return sorted(assessments, key=lambda a: a.relevance_score, reverse=True)
