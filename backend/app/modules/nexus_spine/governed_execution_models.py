"""V2.3 Governed Execution Models.

Frozen dataclasses for the hardened execution boundary:

    * ``ApprovalRecord`` — persistent human approval with provenance hashing.
    * ``ExecutionAuthorization`` — independent verification of all 15+ fields
      before execution is dispatched.
    * ``ExecutionOutcome`` — outcome record linking execution back to world
      state with full provenance chain.

Invariant: the execution service independently verifies every field. The
frontend has zero authority over these checks.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.common.ids import uuid7

# ─────────────────────────────────────────────────────────────────────────────
# ApprovalRecord
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ApprovalRecord:
    """Persistent human approval record.

    Captures who approved what, when, and against which provenance hashes.
    The approval is cryptographically linked to the proposal and simulation
    that were reviewed.
    """

    approval_id: str
    decision_id: str  # correlation_id from SwarmTask
    operator_id: str
    operator_role: str  # "operator" | "executive"
    decision: str  # "APPROVE" | "REJECT" | "DEFER"
    proposal_hash: str
    simulation_hash: str
    world_state_version: int
    approved_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    approval_expiry: datetime | None = None
    approval_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "decision_id": self.decision_id,
            "operator_id": self.operator_id,
            "operator_role": self.operator_role,
            "decision": self.decision,
            "proposal_hash": self.proposal_hash,
            "simulation_hash": self.simulation_hash,
            "world_state_version": self.world_state_version,
            "approved_at": self.approved_at.isoformat(),
            "approval_expiry": self.approval_expiry.isoformat() if self.approval_expiry else None,
            "approval_hash": self.approval_hash,
        }

    @classmethod
    def create(
        cls,
        *,
        decision_id: str,
        operator_id: str,
        operator_role: str = "operator",
        decision: str = "APPROVE",
        proposal_hash: str = "",
        simulation_hash: str = "",
        world_state_version: int = 0,
        approval_expiry: datetime | None = None,
    ) -> ApprovalRecord:
        """Factory that creates and hashes an approval record."""
        record = cls(
            approval_id=f"appr_{uuid7()[:8]}",
            decision_id=decision_id,
            operator_id=operator_id,
            operator_role=operator_role,
            decision=decision,
            proposal_hash=proposal_hash,
            simulation_hash=simulation_hash,
            world_state_version=world_state_version,
            approval_expiry=approval_expiry,
        )
        from dataclasses import replace
        return replace(record, approval_hash=compute_approval_hash(record))


def compute_approval_hash(record: ApprovalRecord) -> str:
    """SHA-256 over canonical approval fields."""
    canonical = {
        "approval_id": record.approval_id,
        "decision_id": record.decision_id,
        "operator_id": record.operator_id,
        "decision": record.decision,
        "proposal_hash": record.proposal_hash,
        "simulation_hash": record.simulation_hash,
        "world_state_version": record.world_state_version,
    }
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# ExecutionAuthorization
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ExecutionAuthorization:
    """Independent verification context for governed execution.

    Every field is independently verified before execution is dispatched.
    The frontend has zero authority over these checks.
    """

    organization_id: str = ""
    workspace_id: str = ""
    decision_id: str = ""
    proposal_hash: str = ""
    simulation_hash: str = ""
    world_state_version: int = 0
    world_state_hash: str = ""
    policy_decision: str = ""  # "APPROVED" | "REJECTED"
    policy_version: str = ""
    human_approval: ApprovalRecord | None = None
    approval_expiry: datetime | None = None
    agent_identity: str = ""
    agent_capability: list[str] = field(default_factory=list)
    execution_budget_usd: float = 0.0
    evidence_root: str = ""
    authorization_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "organization_id": self.organization_id,
            "workspace_id": self.workspace_id,
            "decision_id": self.decision_id,
            "proposal_hash": self.proposal_hash,
            "simulation_hash": self.simulation_hash,
            "world_state_version": self.world_state_version,
            "world_state_hash": self.world_state_hash,
            "policy_decision": self.policy_decision,
            "policy_version": self.policy_version,
            "human_approval": self.human_approval.to_dict() if self.human_approval else None,
            "approval_expiry": self.approval_expiry.isoformat() if self.approval_expiry else None,
            "agent_identity": self.agent_identity,
            "agent_capability": list(self.agent_capability),
            "execution_budget_usd": self.execution_budget_usd,
            "evidence_root": self.evidence_root,
            "authorization_hash": self.authorization_hash,
        }

    def verify(self, *, current_world_version: int = 0) -> tuple[bool, list[str]]:
        """Verify every field independently. Returns (passed, failures).

        Fail-closed: any missing or invalid field blocks execution.
        """
        failures: list[str] = []

        # Tenant
        if not self.organization_id:
            failures.append("TENANT_MISSING: organization_id is empty")
        if not self.workspace_id:
            failures.append("WORKSPACE_MISSING: workspace_id is empty")

        # Decision provenance
        if not self.decision_id:
            failures.append("DECISION_ID_MISSING")
        if not self.proposal_hash:
            failures.append("PROPOSAL_HASH_MISSING")
        if not self.simulation_hash:
            failures.append("SIMULATION_HASH_MISSING")

        # World state
        if self.world_state_version <= 0:
            failures.append("WORLD_STATE_VERSION_INVALID")
        if not self.world_state_hash:
            failures.append("WORLD_STATE_HASH_MISSING")

        # Policy
        if self.policy_decision != "APPROVED":
            failures.append(f"POLICY_NOT_APPROVED: {self.policy_decision}")
        if not self.policy_version:
            failures.append("POLICY_VERSION_MISSING")

        # Human approval
        if self.human_approval is None:
            failures.append("HUMAN_APPROVAL_MISSING")
        else:
            if self.human_approval.decision != "APPROVE":
                failures.append(f"HUMAN_APPROVAL_DENIED: {self.human_approval.decision}")
            if not self.human_approval.approval_hash:
                failures.append("APPROVAL_HASH_MISSING")

        # Approval expiry
        if self.approval_expiry is not None and datetime.now(UTC) > self.approval_expiry:
            failures.append("APPROVAL_EXPIRED")

        # Agent
        if not self.agent_identity:
            failures.append("AGENT_IDENTITY_MISSING")
        if not self.agent_capability:
            failures.append("AGENT_CAPABILITY_MISSING")
        elif "EXECUTE" not in self.agent_capability:
            failures.append("CAPABILITY_MISSING: EXECUTE not granted")

        # Budget
        if self.execution_budget_usd < 0:
            failures.append("EXECUTION_BUDGET_NEGATIVE")

        # Evidence
        if not self.evidence_root:
            failures.append("EVIDENCE_ROOT_MISSING")

        # Staleness
        if current_world_version > 0 and self.world_state_version < current_world_version - 1:
            failures.append(
                f"STALE_DECISION: decision at v{self.world_state_version}, "
                f"current is v{current_world_version}"
            )

        passed = len(failures) == 0
        return passed, failures


def compute_authorization_hash(auth: ExecutionAuthorization) -> str:
    """SHA-256 over all verification fields."""
    canonical = {
        "organization_id": auth.organization_id,
        "workspace_id": auth.workspace_id,
        "decision_id": auth.decision_id,
        "proposal_hash": auth.proposal_hash,
        "simulation_hash": auth.simulation_hash,
        "world_state_version": auth.world_state_version,
        "world_state_hash": auth.world_state_hash,
        "policy_decision": auth.policy_decision,
        "policy_version": auth.policy_version,
        "approval_hash": auth.human_approval.approval_hash if auth.human_approval else "",
        "agent_identity": auth.agent_identity,
        "agent_capability": sorted(auth.agent_capability),
        "evidence_root": auth.evidence_root,
    }
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# ExecutionOutcome
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ExecutionOutcome:
    """Outcome record linking execution back to world state.

    Carries all provenance hashes from the full pipeline:
    proposal_hash → simulation_hash → approval_hash → authorization_hash → outcome_hash.
    """

    outcome_id: str
    execution_id: str
    proposal_hash: str
    simulation_hash: str
    approval_hash: str
    authorization_hash: str
    world_state_version_before: int
    world_state_version_after: int
    adapter_result: dict[str, Any]
    outcome_hash: str = ""
    executed_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome_id": self.outcome_id,
            "execution_id": self.execution_id,
            "proposal_hash": self.proposal_hash,
            "simulation_hash": self.simulation_hash,
            "approval_hash": self.approval_hash,
            "authorization_hash": self.authorization_hash,
            "world_state_version_before": self.world_state_version_before,
            "world_state_version_after": self.world_state_version_after,
            "adapter_result": dict(self.adapter_result),
            "outcome_hash": self.outcome_hash,
            "executed_at": self.executed_at.isoformat(),
        }


def compute_outcome_hash(outcome: ExecutionOutcome) -> str:
    """SHA-256 linking all provenance hashes in the outcome."""
    canonical = {
        "outcome_id": outcome.outcome_id,
        "execution_id": outcome.execution_id,
        "proposal_hash": outcome.proposal_hash,
        "simulation_hash": outcome.simulation_hash,
        "approval_hash": outcome.approval_hash,
        "authorization_hash": outcome.authorization_hash,
        "world_state_version_before": outcome.world_state_version_before,
        "world_state_version_after": outcome.world_state_version_after,
    }
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()
