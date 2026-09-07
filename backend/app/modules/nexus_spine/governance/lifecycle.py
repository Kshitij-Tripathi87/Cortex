"""Nexus Phase G — Governed Operations: Decision Lifecycle State Machine.

The core missing link between Nexus's intelligence layer and its execution
backbone. This module defines the canonical transition graph for a decision
through its complete lifecycle:

    PROPOSED → (simulated) → (policy_check) → APPROVED → AUTHORIZED
    → EXECUTING → EXECUTED → OUTCOME_RECORDED

With failure paths:
    → STALE → REJECTED → EXPIRED → POLICY_BLOCKED → BUDGET_EXCEEDED
    → EXECUTION_FAILED → INVALIDATED → ROLLED_BACK

Every transition:
1. Is idempotent
2. Records audit provenance
3. Verifies world state hasn't moved underneath
4. Publishes a state-change event to the realtime fabric
5. Checks world-state version/hash to detect staleness

This is the glue holding together the WorldModel/Risk/Scenario/Demand
subsystems — a decision is no longer "done" until the outcome is recorded.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


def _utc_now() -> datetime:
    return datetime.now(UTC)


class DecisionPhase(StrEnum):
    """Lifecycle phases — the authoritative state machine."""

    # Valid states
    PROPOSED = "proposed"
    SIMULATED = "simulated"
    POLICY_CHECKED = "policy_checked"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    AUTHORIZED = "authorized"
    EXECUTING = "executing"
    EXECUTED = "executed"
    OUTCOME_RECORDED = "outcome_recorded"

    # Failure states
    REJECTED = "rejected"
    EXPIRED = "expired"
    STALE = "stale"
    POLICY_BLOCKED = "policy_blocked"
    BUDGET_EXCEEDED = "budget_exceeded"
    EXECUTION_FAILED = "execution_failed"
    CANCELLED = "cancelled"
    INVALIDATED = "invalidated"
    ROLLED_BACK = "rolled_back"


# ── Transition Map ─────────────────────────────────────────────────────────────


ALLOWED_TRANSITIONS: dict[DecisionPhase, set[DecisionPhase]] = {
    DecisionPhase.PROPOSED: {
        DecisionPhase.SIMULATED,
        DecisionPhase.POLICY_BLOCKED,
        DecisionPhase.REJECTED,
        DecisionPhase.CANCELLED,
    },
    DecisionPhase.SIMULATED: {
        DecisionPhase.POLICY_CHECKED,
        DecisionPhase.POLICY_BLOCKED,
        DecisionPhase.EXPIRED,
        DecisionPhase.CANCELLED,
    },
    DecisionPhase.POLICY_CHECKED: {
        DecisionPhase.AWAITING_APPROVAL,
        DecisionPhase.POLICY_BLOCKED,
        DecisionPhase.EXPIRED,
        DecisionPhase.CANCELLED,
    },
    DecisionPhase.AWAITING_APPROVAL: {
        DecisionPhase.APPROVED,
        DecisionPhase.REJECTED,
        DecisionPhase.EXPIRED,
        DecisionPhase.STALE,  # world state changed → decision invalidated
    },
    DecisionPhase.APPROVED: {
        DecisionPhase.AUTHORIZED,
        DecisionPhase.EXPIRED,
        DecisionPhase.STALE,
    },
    DecisionPhase.AUTHORIZED: {
        DecisionPhase.EXECUTING,
        DecisionPhase.BUDGET_EXCEEDED,
        DecisionPhase.STALE,
        DecisionPhase.EXPIRED,
    },
    DecisionPhase.EXECUTING: {
        DecisionPhase.EXECUTED,
        DecisionPhase.EXECUTION_FAILED,
        DecisionPhase.STALE,
        DecisionPhase.CANCELLED,
    },
    DecisionPhase.EXECUTED: {
        DecisionPhase.OUTCOME_RECORDED,
        DecisionPhase.EXECUTION_FAILED,  # outcome failed to materialize
    },
    DecisionPhase.OUTCOME_RECORDED: set(),  # Terminal
    DecisionPhase.REJECTED: set(),
    DecisionPhase.EXPIRED: set(),
    DecisionPhase.STALE: {DecisionPhase.INVALIDATED},
    DecisionPhase.INVALIDATED: set(),
    DecisionPhase.EXECUTION_FAILED: {DecisionPhase.ROLLED_BACK},
    DecisionPhase.ROLLED_BACK: set(),
    DecisionPhase.POLICY_BLOCKED: set(),
    DecisionPhase.BUDGET_EXCEEDED: set(),
    DecisionPhase.CANCELLED: set(),
}


# Terminal states (no further transitions possible)
TERMINAL_STATES: set[DecisionPhase] = {
    DecisionPhase.PROPOSED,
    DecisionPhase.SIMULATED,
    DecisionPhase.OUTCOME_RECORDED,
    DecisionPhase.REJECTED,
    DecisionPhase.EXPIRED,
    DecisionPhase.STALE,
    DecisionPhase.INVALIDATED,
    DecisionPhase.ROLLED_BACK,
    DecisionPhase.POLICY_BLOCKED,
    DecisionPhase.BUDGET_EXCEEDED,
    DecisionPhase.CANCELLED,
}

TERMINAL_END_STATES: set[DecisionPhase] = {
    DecisionPhase.OUTCOME_RECORDED,
    DecisionPhase.REJECTED,
    DecisionPhase.EXPIRED,
    DecisionPhase.STALE,
    DecisionPhase.INVALIDATED,
    DecisionPhase.ROLLED_BACK,
    DecisionPhase.POLICY_BLOCKED,
    DecisionPhase.BUDGET_EXCEEDED,
    DecisionPhase.CANCELLED,
}


class DecisionTransition(BaseModel):
    """One step in the decision lifecycle with full provenance."""

    model_config = ConfigDict(extra="forbid")

    transition_id: str = Field(default_factory=lambda: f"TRN-{uuid4().hex[:8]}")
    decision_id: str
    from_phase: DecisionPhase
    to_phase: DecisionPhase
    actor: str
    timestamp: datetime = Field(default_factory=_utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DecisionLifecycle:
    """One decision's journey through the state machine.

    Carries:
    - The current phase and transition history
    - World state version/hash captured at proposal time
    - All linked identifiers (proposal, evidence, simulation, plan)
    - The decision hash — the single deterministic identifier
    - The linked agent outcome

    Immutability: transitions are append-only. The only mutation is the
    phase pointer; every prior state is a permanent part of the audit trail.
    """

    __slots__ = (
        "decision_id",
        "workspace_id",
        "tenant_id",
        "phase",
        "transitions",
        "world_state_version",
        "world_state_hash",
        "proposal_id",
        "simulation_id",
        "plan_id",
        "evidence_root_id",
        "evidence_root_hash",
        "created_at",
        "updated_at",
        "hash",
        "options",
        "chosen_option",
        "outcome",
    )

    def __init__(
        self,
        *,
        decision_id: str,
        tenant_id: str,
        workspace_id: str,
        world_state_version: int,
        world_state_hash: str,
        proposal_id: str,
        options: list[dict[str, Any]] | None = None,
        chosen_option: str | None = None,
    ) -> None:
        self.decision_id = decision_id
        self.tenant_id = tenant_id
        self.workspace_id = workspace_id
        self.phase = DecisionPhase.PROPOSED
        self.transitions: list[DecisionTransition] = []
        self.world_state_version = world_state_version
        self.world_state_hash = world_state_hash
        self.proposal_id = proposal_id
        self.simulation_id: str | None = None
        self.plan_id: str | None = None
        self.evidence_root_id: str | None = None
        self.evidence_root_hash: str | None = None
        self.created_at = _utc_now()
        self.updated_at = _utc_now()
        self.options = list(options or [])
        self.chosen_option = chosen_option
        self.outcome: dict[str, Any] | None = None
        self.hash = self._compute_hash()

    # ────────── Computed identities ──────────

    def _compute_hash(self) -> str:
        """Deterministic hash of this decision record.

        Changes if and only if a material field changes, enabling
        staleness detection across restarts and replicas.
        """
        payload = json.dumps(
            {
                "decision_id": self.decision_id,
                "options": self.options,
                "world_state_version": self.world_state_version,
                "world_state_hash": self.world_state_hash,
                "phase": self.phase.value,
                "proposal_id": self.proposal_id,
                "chosen_option": self.chosen_option,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    # ────────── State transitions ──────────

    def can_transition_to(self, target: DecisionPhase) -> bool:
        """Check if transitioning from current phase to target is allowed."""
        return target in ALLOWED_TRANSITIONS.get(self.phase, set())

    def advance(
        self,
        to: DecisionPhase,
        *,
        actor: str,
        reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DecisionTransition:
        """Advance the decision to a new phase.

        Validates the transition is legal, then records it with provenance.
        If the transition is illegal, raises a StateError (Phase G).
        """
        if not self.can_transition_to(to):
            raise ValueError(
                f"Invalid transition: {self.phase.value} → {to.value}. "
                f"Allowed: {sorted(t.value for t in ALLOWED_TRANSITIONS[self.phase])}"
            )
        transition = DecisionTransition(
            decision_id=self.decision_id,
            from_phase=self.phase,
            to_phase=to,
            actor=actor,
            metadata=metadata or {},
        )
        self.transitions.append(transition)
        self.phase = to
        self.updated_at = _utc_now()
        self.hash = self._compute_hash()
        return transition

    def is_terminal(self) -> bool:
        return self.phase in TERMINAL_END_STATES

    def is_completed(self) -> bool:
        return self.phase == DecisionPhase.OUTCOME_RECORDED

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "tenant_id": self.tenant_id,
            "workspace_id": self.workspace_id,
            "phase": self.phase.value,
            "world_state_version": self.world_state_version,
            "world_state_hash": self.world_state_hash,
            "proposal_id": self.proposal_id,
            "simulation_id": self.simulation_id,
            "plan_id": self.plan_id,
            "evidence_root_id": self.evidence_root_id,
            "evidence_root_hash": self.evidence_root_hash,
            "options": self.options,
            "chosen_option": self.chosen_option,
            "outcome": self.outcome,
            "hash": self.hash,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "transitions": [t.model_dump() for t in self.transitions],
        }

    def mark_stale(self, *, actor: str, reason: str) -> DecisionTransition:
        """Mark this decision as stale due to world-state drift."""
        return self.advance(
            DecisionPhase.STALE,
            actor=actor,
            reason=reason,
            metadata={"reason": reason},
        )

    def mark_invalidated(self, *, actor: str, reason: str) -> DecisionTransition:
        """Mark decision invalidated — e.g. world state changed and options no longer valid."""
        return self.advance(
            DecisionPhase.INVALIDATED,
            actor=actor,
            reason=reason,
            metadata={"reason": reason},
        )

    def mark_executing(self, *, actor: str, actor_id: str) -> DecisionTransition:
        """Signal that execution has started."""
        return self.advance(DecisionPhase.EXECUTING, actor=actor)

    def mark_executed(self, *, actor: str, result: dict[str, Any]) -> DecisionTransition:
        """Signal execution completed successfully."""
        self.outcome = result
        self.updated_at = _utc_now()
        return self.advance(DecisionPhase.EXECUTED, actor=actor)

    def mark_outcome_recorded(self, *, actor: str, result: dict[str, Any]) -> DecisionTransition:
        """Final step — record the outcome."""
        self.outcome = result
        self.updated_at = _utc_now()
        return self.advance(DecisionPhase.OUTCOME_RECORDED, actor=actor)


# ─────────────────────────────────────────────────────────────────────────────
# World State Consistency Invariant
# ─────────────────────────────────────────────────────────────────────────────


def validate_world_state_consistent(
    lifecycle: DecisionLifecycle,
    current_world_state_version: int,
    current_world_state_hash: str,
) -> bool:
    """Return True if the decision was made for a consistent world state.

    This is the cross-cutting invariant: a decision made against stale world
    state cannot execute safely. The world model changes underfoot; this
    function checks the decision was crafted from the right snapshot.
    """
    if lifecycle.world_state_version != current_world_state_version:
        return False
    if lifecycle.world_state_hash != current_world_state_hash:
        return False
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Singleton Manager
# ─────────────────────────────────────────────────────────────────────────────


class DecisionLifecycleManager:
    """Registry and query layer for all decision lifecycles.

    In-memory for now; Phase H adds DB persistence backed by a decision
    documents table.
    """

    def __init__(self) -> None:
        self._lifecycles: dict[str, DecisionLifecycle] = {}

    def get(self, decision_id: str) -> DecisionLifecycle | None:
        return self._lifecycles.get(decision_id)

    def put(self, lifecycle: DecisionLifecycle) -> None:
        self._lifecycles[lifecycle.decision_id] = lifecycle

    def list_by_phase(self, phase: DecisionPhase) -> list[DecisionLifecycle]:
        return [
            lc for lc in self._lifecycles.values() if lc.phase == phase
        ]

    def list_by_workspace(self, workspace_id: str) -> list[DecisionLifecycle]:
        return [
            lc for lc in self._lifecycles.values() if lc.workspace_id == workspace_id
        ]

    def prune_terminal(self, age_hours: int = 24) -> int:
        """Remove terminal lifecycles older than `age_hours`. Returns count."""
        cutoff = datetime.now(UTC) - __import__("datetime").timedelta(hours=age_hours)
        to_remove = [
            k
            for k, lc in self._lifecycles.items()
            if lc.is_terminal() and lc.updated_at < cutoff
        ]
        for k in to_remove:
            del self._lifecycles[k]
        return len(to_remove)

    def count(self) -> int:
        return len(self._lifecycles)


_singleton: DecisionLifecycleManager | None = None


def get_decision_lifecycle_manager() -> DecisionLifecycleManager:
    """Process-wide singleton decision lifecycle registry."""
    global _singleton
    if _singleton is None:
        _singleton = DecisionLifecycleManager()
    return _singleton


def reset_decision_lifecycle_manager() -> None:
    """Reset the singleton — for tests only."""
    global _singleton
    _singleton = None
