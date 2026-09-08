"""ProposalSimulator — Deterministic counterfactual simulation adapter (V2.2).

Bridges AgentProposal → deterministic KPI-like computation with hashing.

The simulator is a **pure function**: same ``(proposals, world_variables)``
always produces the same ``SimulationResult`` with identical hashes. This
is the V2.2 contract — the Twin becomes the formal safety boundary between
agent reasoning and execution.

Key invariants:
- ``option_hash`` = SHA-256 over (agent_id, action, cost_usd, delay_days,
  risk_score, baseline_hash) — same inputs ⇒ same hash.
- ``simulation_hash`` = SHA-256 over all option hashes — deterministic
  fingerprint for the full simulation result.
- NEV is computed from proposal parameters, not external state.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from app.modules.nexus_spine.models import AgentProposal

# ─────────────────────────────────────────────────────────────────────────────
# Result types
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ProposalOption:
    """One simulated option — deterministic and hashable."""

    agent_id: str
    agent_family: str
    action: str
    cost_usd: float
    delay_days: float
    risk_score: float
    nev_usd: float
    sla_breach_pct: float
    option_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "agent_family": self.agent_family,
            "action": self.action,
            "cost_usd": round(self.cost_usd, 2),
            "delay_days": round(self.delay_days, 2),
            "risk_score": round(self.risk_score, 4),
            "nev_usd": round(self.nev_usd, 2),
            "sla_breach_pct": round(self.sla_breach_pct, 1),
            "option_hash": self.option_hash,
        }


@dataclass(frozen=True)
class SimulationResult:
    """Full simulation result with deterministic hashes."""

    baseline: dict[str, float]
    options: list[ProposalOption]
    simulation_hash: str
    world_state_version: int = 0

    @property
    def recommended(self) -> ProposalOption | None:
        """Highest NEV option (None if no options)."""
        if not self.options:
            return None
        return max(self.options, key=lambda o: o.nev_usd)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": "COMPLETED" if self.options else "NO_PROPOSALS",
            "baseline": dict(self.baseline),
            "options": [o.to_dict() for o in self.options],
            "recommended": self.recommended.to_dict() if self.recommended else None,
            "simulation_hash": self.simulation_hash,
            "world_state_version": self.world_state_version,
        }


# ─────────────────────────────────────────────────────────────────────────────
# ProposalSimulator
# ─────────────────────────────────────────────────────────────────────────────


class ProposalSimulator:
    """Deterministic counterfactual simulator for agent proposals.

    Pure function: same inputs → identical ``SimulationResult`` with
    identical hashes. No side effects, no external state.
    """

    def simulate(
        self,
        proposals: list[AgentProposal],
        world_variables: dict[str, Any] | None = None,
        *,
        world_state_version: int = 0,
    ) -> SimulationResult:
        """Simulate each proposal and produce deterministic result.

        Args:
            proposals: Agent proposals from the supervisor stage.
            world_variables: Optional world state variables (used to derive
                revenue-at-risk for NEV computation). When ``None``, NEV
                is computed from proposal parameters only.
            world_state_version: The world state version the proposals were
                generated against (stamped into result for provenance).

        Returns:
            A ``SimulationResult`` with deterministic hashes.
        """
        if not proposals:
            return SimulationResult(
                baseline={},
                options=[],
                simulation_hash=self._empty_hash(),
                world_state_version=world_state_version,
            )

        # Derive revenue at risk from world variables or proposals
        revenue_at_risk = self._derive_revenue_at_risk(proposals, world_variables)

        # Baseline: do nothing — risk is higher than any proposal (inaction penalty)
        max_risk = max(p.expected_risk_score for p in proposals)
        baseline_risk = min(1.0, max_risk * 1.5) if max_risk > 0 else 0.5
        baseline_delay = max(p.expected_delay_days for p in proposals)
        baseline_cost = 0.0

        baseline = {
            "cost_usd": baseline_cost,
            "delay_days": round(baseline_delay, 2),
            "risk_score": round(baseline_risk, 4),
            "sla_breach_pct": round(baseline_risk * 100, 1),
        }

        baseline_hash = self._compute_baseline_hash(baseline)

        # Simulate each proposal as an option
        options: list[ProposalOption] = []
        for proposal in proposals:
            cost = proposal.expected_cost_usd
            delay = proposal.expected_delay_days
            risk = proposal.expected_risk_score

            # NEV = (baseline_risk_cost - option_risk_cost - option_cost)
            baseline_risk_cost = baseline_risk * revenue_at_risk
            option_risk_cost = risk * revenue_at_risk
            nev = baseline_risk_cost - option_risk_cost - cost

            option_hash = self._compute_option_hash(
                proposal.agent_id,
                proposal.action,
                cost,
                delay,
                risk,
                baseline_hash,
            )

            options.append(
                ProposalOption(
                    agent_id=proposal.agent_id,
                    agent_family=proposal.agent_family,
                    action=proposal.action,
                    cost_usd=cost,
                    delay_days=delay,
                    risk_score=risk,
                    nev_usd=round(nev, 2),
                    sla_breach_pct=round(risk * 100, 1),
                    option_hash=option_hash,
                )
            )

        # Sort by NEV descending (deterministic — same inputs → same order)
        options.sort(key=lambda o: (-o.nev_usd, o.agent_id))

        simulation_hash = self._compute_simulation_hash(options)

        return SimulationResult(
            baseline=baseline,
            options=options,
            simulation_hash=simulation_hash,
            world_state_version=world_state_version,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Internal helpers (all pure functions)
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _derive_revenue_at_risk(
        proposals: list[AgentProposal],
        world_variables: dict[str, Any] | None,
    ) -> float:
        """Derive revenue at risk from world variables or proposal payloads.

        When world_variables contains revenue data, use it. Otherwise,
        estimate from proposal payloads (affected_orders × avg order value).
        This is deterministic for the same inputs.
        """
        if world_variables:
            # Check for explicit revenue variable
            for var_id, var_data in world_variables.items():
                if "revenue" in var_id.lower():
                    val = var_data.get("value", {})
                    if isinstance(val, dict):
                        rev = val.get("total_revenue_at_risk_usd", 0)
                        if rev > 0:
                            return float(rev)

        # Estimate from proposal payloads (deterministic)
        total = 0.0
        for p in proposals:
            affected_orders = p.payload.get("affected_orders", 0)
            avg_order_value = p.payload.get("avg_order_value_usd", 150)
            total += float(affected_orders) * float(avg_order_value)
        return total

    @staticmethod
    def _compute_baseline_hash(baseline: dict[str, float]) -> str:
        """SHA-256 over canonical baseline fields."""
        canonical = {
            "cost_usd": baseline.get("cost_usd", 0.0),
            "delay_days": baseline.get("delay_days", 0.0),
            "risk_score": baseline.get("risk_score", 0.0),
            "sla_breach_pct": baseline.get("sla_breach_pct", 0.0),
        }
        blob = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()

    @staticmethod
    def _compute_option_hash(
        agent_id: str,
        action: str,
        cost_usd: float,
        delay_days: float,
        risk_score: float,
        baseline_hash: str,
    ) -> str:
        """SHA-256 over canonical option fields + baseline anchor."""
        canonical = {
            "agent_id": agent_id,
            "action": action,
            "cost_usd": round(cost_usd, 2),
            "delay_days": round(delay_days, 2),
            "risk_score": round(risk_score, 4),
            "baseline_hash": baseline_hash,
        }
        blob = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()

    @staticmethod
    def _compute_simulation_hash(options: list[ProposalOption]) -> str:
        """SHA-256 over all option hashes (deterministic ordering)."""
        option_hashes = [o.option_hash for o in options]
        blob = json.dumps(option_hashes, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()

    @staticmethod
    def _empty_hash() -> str:
        """Deterministic hash for empty simulation (no proposals)."""
        return hashlib.sha256(b"NO_PROPOSALS").hexdigest()
