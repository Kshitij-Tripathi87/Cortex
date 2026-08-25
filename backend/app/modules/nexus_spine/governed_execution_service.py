"""V2.3 Governed Execution Service.

The hard boundary between policy approval and execution dispatch.
Independently verifies all 15+ provenance fields before execution is
dispatched to any adapter. The frontend has zero authority.

Flow:
    1. Build ExecutionAuthorization from all inputs
    2. Verify every field — fail closed on ANY missing/invalid field
    3. Check approval expiry
    4. Check world state freshness
    5. Dispatch to adapter
    6. Record outcome with all provenance hashes
    7. Return ExecutionOutcome
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from app.common.ids import uuid7
from app.modules.nexus_spine.governed_execution_models import (
    ApprovalRecord,
    ExecutionAuthorization,
    ExecutionOutcome,
    compute_authorization_hash,
    compute_outcome_hash,
)
from app.modules.nexus_spine.models import AgentProposal


class GovernedExecutionError(Exception):
    """Raised when governed execution is blocked or fails."""

    def __init__(self, reason: str, failures: list[str] | None = None) -> None:
        self.reason = reason
        self.failures = failures or []
        super().__init__(f"GOVERNED_EXECUTION_BLOCKED: {reason}")


class GovernedExecutionService:
    """Stateless governed execution service.

    Verifies all provenance fields independently, dispatches to a
    simulated adapter, and returns a fully-linked ExecutionOutcome.
    """

    def authorize_and_execute(
        self,
        proposal: AgentProposal,
        approval: ApprovalRecord,
        twin_result: dict[str, Any],
        policy_result: dict[str, Any],
        world_state_version: int,
        world_state_hash: str,
        evidence_root_id: str,
        organization_id: str,
        workspace_id: str,
        *,
        current_world_version: int = 0,
        agent_identity: str = "",
        agent_capability: list[str] | None = None,
        execution_budget_usd: float = 50000.0,
    ) -> ExecutionOutcome:
        """Authorize and execute, or fail closed.

        Returns an ExecutionOutcome with all provenance hashes linked.
        Raises GovernedExecutionError on any verification failure.
        """
        # 1. Build ExecutionAuthorization
        simulation_hash = twin_result.get("simulation_hash", "")
        policy_decision = "APPROVED" if policy_result.get("approved") else "REJECTED"
        policy_version = policy_result.get("policy_version", "")

        auth = ExecutionAuthorization(
            organization_id=organization_id,
            workspace_id=workspace_id,
            decision_id=approval.decision_id,
            proposal_hash=proposal.proposal_hash,
            simulation_hash=simulation_hash,
            world_state_version=world_state_version,
            world_state_hash=world_state_hash,
            policy_decision=policy_decision,
            policy_version=policy_version,
            human_approval=approval,
            approval_expiry=approval.approval_expiry,
            agent_identity=agent_identity or proposal.agent_id,
            agent_capability=agent_capability or ["EXECUTE"],
            execution_budget_usd=execution_budget_usd,
            evidence_root=evidence_root_id,
        )
        auth = replace(auth, authorization_hash=compute_authorization_hash(auth))

        # 2. Verify all fields — fail closed
        passed, failures = auth.verify(current_world_version=current_world_version)
        if not passed:
            raise GovernedExecutionError(
                "; ".join(failures),
                failures=failures,
            )

        # 3. Budget check
        if proposal.expected_cost_usd > execution_budget_usd:
            raise GovernedExecutionError(
                f"BUDGET_EXCEEDED: proposal cost ${proposal.expected_cost_usd:,.2f} "
                f"exceeds budget ${execution_budget_usd:,.2f}",
                failures=["BUDGET_EXCEEDED"],
            )

        # 4. Dispatch to adapter (simulated for V2.3)
        execution_id = f"exec_{uuid7()[:8]}"
        adapter_result = self._dispatch_adapter(
            execution_id=execution_id,
            proposal=proposal,
            workspace_id=workspace_id,
        )

        # 5. Record outcome
        outcome = ExecutionOutcome(
            outcome_id=f"out_{uuid7()[:8]}",
            execution_id=execution_id,
            proposal_hash=proposal.proposal_hash,
            simulation_hash=simulation_hash,
            approval_hash=approval.approval_hash,
            authorization_hash=auth.authorization_hash,
            world_state_version_before=world_state_version,
            world_state_version_after=current_world_version or world_state_version,
            adapter_result=adapter_result,
        )
        outcome = replace(outcome, outcome_hash=compute_outcome_hash(outcome))

        return outcome

    @staticmethod
    def _dispatch_adapter(
        execution_id: str,
        proposal: AgentProposal,
        workspace_id: str,
    ) -> dict[str, Any]:
        """Simulated adapter dispatch. Returns adapter result dict.

        In production, this routes to the appropriate enterprise adapter
        (ERP, WMS, TMS, Procurement) based on the proposal's action type.
        For V2.3, we simulate a successful dispatch with provenance.
        """
        return {
            "status": "EXECUTED",
            "execution_id": execution_id,
            "action": proposal.action,
            "agent_id": proposal.agent_id,
            "workspace_id": workspace_id,
            "adapter": "INTERNAL_API",
            "idempotency_key": f"{workspace_id}.{execution_id}",
            "executed_at": datetime.now(UTC).isoformat(),
        }
