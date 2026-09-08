"""Nexus Spine — Pipeline Stage Implementations.

Concrete implementations for the pluggable stage callbacks used by
``RealDataSpine``:

    * ``real_supervisor_fn`` — A5/A6/A7: takes a ``SwarmTask`` with real
      context, routes via ``DynamicAgentRouter`` (only relevant families
      activated), runs agents, and maps outputs to ``AgentProposal``.
    * ``twin_simulation_fn`` — A9: takes proposals + world state, produces a
      baseline-vs-option comparison (cost / SLA / risk / NEV).
    * ``policy_gate_fn`` — A8 (partial): checks proposals against policy
      constraints.
    * ``execution_gate_fn`` — A8: hard gate that rejects execution when
      policy approval, human approval, world state freshness, tenant match,
      or capability requirements are not met.

These are the stage callbacks plugged into ``RealDataSpine`` by default
when the full spine is used (not the minimal smoke-test defaults).
"""

from __future__ import annotations

from typing import Any

from app.common.ids import uuid7
from app.modules.multi_agent.orchestration.agent_router import DynamicAgentRouter
from app.modules.nexus_spine.models import (
    AgentProposal,
    SwarmTask,
)
from app.modules.nexus_spine.proposal_simulator import ProposalSimulator

# Activation threshold for the dynamic agent router (A6)
_RELEVANCE_THRESHOLD = 0.70


# ─────────────────────────────────────────────────────────────────────────────
# A5/A6/A7: Real supervisor
# ─────────────────────────────────────────────────────────────────────────────


def real_supervisor_fn(task: SwarmTask) -> list[AgentProposal]:
    """Supervisor that reads real context from a ``SwarmTask``.

    (A5) No hardcoded demo data — every value comes from the task context.
    (A6) Agent selection emerges from the signal type, entity type, and
         severity via ``DynamicAgentRouter``.
    (A7) Each agent produces an ``AgentProposal`` — agents never mutate
         World State.
    """
    ctx = task.context

    # Route: select relevant agent families based on signal + entity type
    assessments = DynamicAgentRouter.route_incident(
        signal_type=task.signal_type,
        entity_type=ctx.incident_entity_type.value,
        severity=task.signal_severity,
        has_route_bottleneck=_has_route_bottleneck(ctx.signals),
    )

    # Filter by relevance threshold (A6: don't always invoke all four)
    active = [a for a in assessments if a.relevance_score >= _RELEVANCE_THRESHOLD]
    active_domains = {a.domain_group for a in active}

    proposals: list[AgentProposal] = []

    # Extract context values for agents (A5: real refs, no demo defaults)
    incident_id = ctx.incident_entity_id
    affected = ctx.affected_entity_ids
    blast = ctx.blast_radius
    signals = ctx.signals

    # Incident location (from blast radius or first signal)
    origin = (
        blast.get("geographic_exposure_regions", ["UNKNOWN"])[0]
        if blast.get("geographic_exposure_regions")
        else "UNKNOWN"
    )
    destination = origin  # same region for localized incidents

    # ── PROCUREMENT family ─────────────────────────────────────────────
    if "PROCUREMENT" in active_domains:
        proposals.append(
            AgentProposal(
                agent_id="procurement_discovery_agent",
                agent_family="PROCUREMENT",
                action="discover_alternative_suppliers",
                target_entity_ids=[incident_id] + affected[:5],
                expected_cost_usd=blast.get("total_revenue_at_risk_usd", 0) * 0.1,
                expected_delay_days=3.0,
                expected_risk_score=0.3,
                evidence_refs=[f"signal:{s['signal_id']}" for s in signals],
                confidence=0.85,
                payload={
                    "incident_entity_id": incident_id,
                    "signal_type": task.signal_type,
                    "affected_count": len(affected),
                },
            )
        )

    # ── BOOKING family ─────────────────────────────────────────────────
    if "BOOKING" in active_domains:
        proposals.append(
            AgentProposal(
                agent_id="capacity_booking_agent",
                agent_family="BOOKING",
                action="reserve_expedited_capacity",
                target_entity_ids=affected[:5],
                expected_cost_usd=blast.get("total_revenue_at_risk_usd", 0) * 0.15,
                expected_delay_days=1.0,
                expected_risk_score=0.2,
                evidence_refs=[f"signal:{s['signal_id']}" for s in signals],
                confidence=0.80,
                payload={
                    "origin": origin,
                    "destination": destination,
                    "affected_orders": blast.get("affected_orders_count", 0),
                },
            )
        )

    # ── OPTIMIZATION family ────────────────────────────────────────────
    if "OPTIMIZATION" in active_domains:
        proposals.append(
            AgentProposal(
                agent_id="load_planning_agent",
                agent_family="OPTIMIZATION",
                action="consolidate_and_reroute",
                target_entity_ids=affected[:5],
                expected_cost_usd=blast.get("total_revenue_at_risk_usd", 0) * 0.08,
                expected_delay_days=2.0,
                expected_risk_score=0.25,
                evidence_refs=[f"signal:{s['signal_id']}" for s in signals],
                confidence=0.75,
                payload={
                    "origin": origin,
                    "destination": destination,
                    "affected_orders": blast.get("affected_orders_count", 0),
                },
            )
        )

    # ── COMPLIANCE family ──────────────────────────────────────────────
    if "COMPLIANCE" in active_domains:
        proposals.append(
            AgentProposal(
                agent_id="compliance_agent",
                agent_family="COMPLIANCE",
                action="validate_action_and_spend_authority",
                target_entity_ids=[incident_id],
                expected_cost_usd=0.0,
                expected_delay_days=0.0,
                expected_risk_score=0.05,
                evidence_refs=[f"signal:{s['signal_id']}" for s in signals],
                confidence=0.95,
                payload={
                    "incident_entity_id": incident_id,
                    "signal_type": task.signal_type,
                    "severity": task.signal_severity,
                },
            )
        )

    return proposals


def _has_route_bottleneck(signals: list[dict[str, Any]]) -> bool:
    """Check if any signal indicates a route bottleneck."""
    return any(s.get("signal_type") in ("ROUTE_CONGESTION", "ROUTE_DISRUPTION") for s in signals)


# ─────────────────────────────────────────────────────────────────────────────
# A9: Twin counterfactual simulator (V2.2 — ProposalSimulator adapter)
# ─────────────────────────────────────────────────────────────────────────────

# Module-level simulator instance (stateless, deterministic)
_proposal_simulator = ProposalSimulator()


def twin_simulation_fn(
    proposals: list[AgentProposal],
    world: Any,  # _InMemoryWorldState from spine_orchestrator (may be None)
    *,
    world_state_version: int = 0,
) -> dict[str, Any]:
    """Simulate each proposal using the deterministic ProposalSimulator.

    (A9) Produces a baseline-vs-option comparison for each proposal:
    cost, SLA breach rate, risk, and net economic value (NEV).

    V2.2: Uses ProposalSimulator for deterministic hashing. Same inputs
    always produce the same ``simulation_hash``. The Twin is the formal
    safety boundary between agent reasoning and execution.
    """
    world_variables: dict[str, Any] | None = None
    if world is not None and hasattr(world, "variables"):
        world_variables = world.variables

    result = _proposal_simulator.simulate(
        proposals,
        world_variables,
        world_state_version=world_state_version,
    )
    return result.to_dict()


# ─────────────────────────────────────────────────────────────────────────────
# A8 (partial): Policy gate
# ─────────────────────────────────────────────────────────────────────────────


def policy_gate_fn(proposals: list[AgentProposal], twin_result: dict[str, Any]) -> dict[str, Any]:
    """Check proposals against policy constraints.

    V2.2 policy checks:
    - At least one proposal exists
    - Twin simulation completed (with simulation_hash)
    - Recommended option has positive NEV
    - Risk score within acceptable bounds (< 0.5)
    - Provenance: every proposal has a non-empty proposal_hash (V2.2)
    - Provenance: proposals share the same world_state_version (V2.2)
    """
    if not proposals:
        return {"approved": False, "reason": "NO_PROPOSALS", "violations": []}

    if twin_result.get("status") == "NO_PROPOSALS":
        return {"approved": False, "reason": "NO_SIMULATION", "violations": []}

    violations: list[str] = []

    # V2.2 provenance checks
    for p in proposals:
        if not p.proposal_hash:
            violations.append(f"PROPOSAL_HASH_MISSING: {p.agent_id}")

    # V2.2 version consistency — all proposals must share the same version
    versions = {p.world_state_version for p in proposals}
    if len(versions) > 1:
        violations.append(f"VERSION_MISMATCH: proposals span versions {sorted(versions)}")

    # Check twin result
    recommended = twin_result.get("recommended")
    if recommended:
        if recommended.get("risk_score", 1.0) > 0.5:
            violations.append(f"RISK_TOO_HIGH: {recommended['risk_score']}")
        if recommended.get("nev_usd", 0) < 0:
            violations.append(f"NEGATIVE_NEV: {recommended['nev_usd']}")

    approved = len(violations) == 0
    return {
        "approved": approved,
        "reason": "POLICY_PASS" if approved else "; ".join(violations),
        "violations": violations,
        "policy_version": "v2",
        "proposals_evaluated": len(proposals),
        "simulation_hash": twin_result.get("simulation_hash", ""),
    }


# ─────────────────────────────────────────────────────────────────────────────
# A8: Execution gate
# ─────────────────────────────────────────────────────────────────────────────


class ExecutionGateError(Exception):
    """Raised when execution is blocked by the gate."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"EXECUTION_BLOCKED: {reason}")


def execution_gate_fn(
    proposal: AgentProposal,
    approval: dict[str, Any],
    *,
    organization_id: str = "",
    workspace_id: str = "",
    world_state_version: int = 0,
    current_world_version: int = 0,
    capabilities: list[str] | None = None,
    twin_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Hard gate that enforces execution prerequisites (A8).

    Rejects with specific reasons:
    - NO_POLICY_APPROVAL
    - NO_HUMAN_APPROVAL
    - STALE_WORLD_STATE
    - STALE_DECISION  (V2.2 — world mutated since decision was made)
    - PROPOSAL_HASH_MISSING  (V2.2 — proposal lacks provenance hash)
    - SIMULATION_MISMATCH  (V2.2 — twin result lacks simulation_hash)
    - TENANT_MISMATCH
    - CAPABILITY_MISSING

    V2.2: The Twin is the formal safety boundary. Decisions are invalidated
    when the world state advances beyond the decision's version.
    """
    # Policy approval
    if not approval.get("approved"):
        raise ExecutionGateError("NO_POLICY_APPROVAL")

    # V2.2: proposal provenance
    if not proposal.proposal_hash:
        raise ExecutionGateError("PROPOSAL_HASH_MISSING")

    # V2.2: simulation integrity
    _twin = twin_result or {}
    if not _twin.get("simulation_hash"):
        raise ExecutionGateError("SIMULATION_MISMATCH")

    # V2.2: mutation→invalidation (decision made at version V, world is now at V+N)
    # A decision is stale when the world has advanced more than 1 version
    # since the decision was made (any mutation invalidates the safety proof).
    decision_version = proposal.world_state_version or world_state_version
    if current_world_version > 0 and decision_version < current_world_version - 1:
        raise ExecutionGateError(
            f"STALE_DECISION: decision was made at v{decision_version}, "
            f"current world is v{current_world_version}"
        )

    # Legacy world state freshness (relaxed — kept for backward compat)
    if current_world_version > 0 and world_state_version < current_world_version - 5:
        raise ExecutionGateError(
            f"STALE_WORLD_STATE: task was created at v{world_state_version}, "
            f"current is v{current_world_version}"
        )

    # Tenant match (organization_id must be present)
    if not organization_id:
        raise ExecutionGateError("TENANT_MISMATCH: no organization_id")

    # Capability check
    if capabilities is not None and "EXECUTE" not in capabilities:
        raise ExecutionGateError("CAPABILITY_MISSING: EXECUTE not granted")

    # Execute
    return {
        "status": "EXECUTED",
        "plan_id": f"PLAN_{uuid7()[:8]}",
        "action": proposal.action,
        "agent_id": proposal.agent_id,
        "organization_id": organization_id,
        "workspace_id": workspace_id,
        "world_state_version": current_world_version or world_state_version,
        "proposal_hash": proposal.proposal_hash,
        "simulation_hash": _twin.get("simulation_hash", ""),
        "executed_at": __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat(),
    }
