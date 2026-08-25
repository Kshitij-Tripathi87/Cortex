"""Supplier Discovery & Evaluation Agents — Groups D1 & D2.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.modules.multi_agent.tools.domain_toolkits import DomainToolRegistry
from app.modules.multi_agent.tools.manifests import CAPABILITY_MANIFESTS


@dataclass
class SupplierDiscoveryResult:
    agent_id: str
    focal_seller_id: str
    product_category: str
    candidate_suppliers: list[dict[str, Any]]
    top_replacement: str
    evidence_refs: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "focal_seller_id": self.focal_seller_id,
            "product_category": self.product_category,
            "candidate_suppliers": self.candidate_suppliers,
            "top_replacement": self.top_replacement,
            "evidence_refs": self.evidence_refs,
        }


class SupplierDiscoveryAgent:
    """Leverages GNN embedding similarity and supplier graphs to find alternative sources."""

    def __init__(self) -> None:
        self.manifest = CAPABILITY_MANIFESTS["supplier_discovery_agent"]
        self.agent_id = self.manifest.agent_id
        self.version = self.manifest.version

    def discover_alternatives(self, product_category: str, focal_seller_id: str) -> SupplierDiscoveryResult:
        res = DomainToolRegistry.query_gnn_supplier_similarity(product_category, focal_seller_id)
        candidates = res.data.get("candidate_suppliers", [])
        top = candidates[0]["seller_id"] if candidates else "seller_bb99112233"

        return SupplierDiscoveryResult(
            agent_id=self.agent_id,
            focal_seller_id=focal_seller_id,
            product_category=product_category,
            candidate_suppliers=candidates,
            top_replacement=top,
            evidence_refs=res.evidence_tags,
        )


class SupplierEvaluationAgent:
    """Produces multi-dimensional supplier risk scorecards."""

    def __init__(self) -> None:
        self.manifest = CAPABILITY_MANIFESTS["supplier_evaluation_agent"]
        self.agent_id = self.manifest.agent_id
        self.version = self.manifest.version

    def evaluate_supplier(self, supplier_id: str) -> dict[str, Any]:
        res = DomainToolRegistry.calculate_supplier_scorecard(supplier_id)
        return {
            "agent_id": self.agent_id,
            "supplier_id": supplier_id,
            "scorecard": res.data.get("scorecard", {}),
            "composite_grade": res.data.get("composite_grade", "A"),
            "evidence_refs": res.evidence_tags,
        }
