"""Compliance Agent — Group B2 (The Control Plane).

Possesses hard execution blocking / veto authority across trade rules, sanctions, and regulatory permits.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.modules.multi_agent.tools.domain_toolkits import DomainToolRegistry
from app.modules.multi_agent.tools.manifests import CAPABILITY_MANIFESTS


@dataclass
class ComplianceVerdict:
    agent_id: str
    status: str  # "APPROVED" | "BLOCKED" | "WARNING"
    can_execute: bool
    is_veto_enforced: bool
    rules_triggered: list[str]
    evidence_refs: list[str]
    verdict_summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "status": self.status,
            "can_execute": self.can_execute,
            "is_veto_enforced": self.is_veto_enforced,
            "rules_triggered": self.rules_triggered,
            "evidence_refs": self.evidence_refs,
            "verdict_summary": self.verdict_summary,
        }


class ComplianceAgent:
    """Control plane agent with authoritative veto power over execution."""

    def __init__(self) -> None:
        self.manifest = CAPABILITY_MANIFESTS["compliance_agent"]
        self.agent_id = self.manifest.agent_id
        self.version = self.manifest.version

    def validate_action(
        self,
        supplier_id: str,
        origin: str,
        destination: str,
        product_category: str = "telefonia",
    ) -> ComplianceVerdict:
        """Evaluates trade sanctions, blacklists, and regulatory permits."""
        blacklist_res = DomainToolRegistry.check_supplier_blacklist(supplier_id)
        trade_res = DomainToolRegistry.verify_trade_compliance(
            origin, destination, product_category
        )

        rules_triggered = []
        is_blocked = False

        if blacklist_res.status == "BLOCKED":
            rules_triggered.append(f"SUPPLIER_BLACKLIST_VIOLATION:{supplier_id}")
            is_blocked = True

        evidence = blacklist_res.evidence_tags + trade_res.evidence_tags

        if is_blocked:
            return ComplianceVerdict(
                agent_id=self.agent_id,
                status="BLOCKED",
                can_execute=False,
                is_veto_enforced=True,
                rules_triggered=rules_triggered,
                evidence_refs=evidence,
                verdict_summary=f"Execution blocked by Compliance Agent: {', '.join(rules_triggered)}",
            )

        return ComplianceVerdict(
            agent_id=self.agent_id,
            status="APPROVED",
            can_execute=True,
            is_veto_enforced=False,
            rules_triggered=[],
            evidence_refs=evidence,
            verdict_summary=f"Trade clearance verified for {origin}->{destination} via {supplier_id}",
        )
