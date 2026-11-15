"""Decision-1 — Decision Room as a projection of the durable runtime.

The Decision Room is NOT a second state machine and NOT an independent
recommendation engine. It consumes the durable artifacts already produced by
the MAF-4/MAF-5 runtime:

    Task
     ├── Plan
     ├── Runs
     ├── Invocations
     ├── Evidence
     ├── Proposals
     ├── Policy results
     ├── Approval
     ├── Execution
     └── Outcome
          ↓
     Decision Room (read-only projection)

Every field is derived from PostgreSQL durable records via
``NexusTaskRuntime.build_nexus_trace`` — the same reconstruction the
NexusTrace proof relies on. Nothing in this module writes, mutates state,
or advances a lifecycle.
"""

from __future__ import annotations

from typing import Any

from app.modules.orchestration.task_runtime_service import NexusTaskRuntime, TaskScope

_AWAITING_APPROVAL = "AWAITING_APPROVAL"


class DecisionRoomService:
    """Read-only projection of one task's durable runtime for the Decision Room."""

    def __init__(self, *, session_factory: Any) -> None:
        self._runtime = NexusTaskRuntime(session_factory=session_factory)

    async def build_decision_view(self, task_id: str, *, scope: TaskScope) -> dict[str, Any]:
        """Assemble the Decision Room view from durable records only."""

        trace = await self._runtime.build_nexus_trace(task_id, scope=scope)
        return {
            "task": _task_view(trace),
            "pending_decision": _pending_decision_view(trace),
            "recommendation": _recommendation_view(trace),
            "plan": trace["plan"],
            "runs": trace["runs"],
            "steps": trace["steps"],
            "invocations": trace["invocations"],
            "evidence": trace["evidence"],
            "proposals": trace["proposals"],
            "policy_results": _policy_results_view(trace["invocations"]),
            "approvals": trace["approvals"],
            "execution": trace["execution"],
            "outcome": trace["outcome"],
            "consequential_capabilities": _consequential_capabilities(trace["invocations"]),
        }


def _task_view(trace: dict[str, Any]) -> dict[str, Any]:
    """Task identity and lifecycle state, verbatim from the durable record."""

    return {
        "task_id": trace["task_id"],
        "trace_id": trace["trace_id"],
        "status": trace["status"],
        "objective": trace["objective"],
        "world_state_version": trace["world_state_version"],
        "budget": trace["budget"],
        "deadline": trace["deadline"],
        "requires_approval": trace["requires_approval"],
    }


def _pending_decision_view(trace: dict[str, Any]) -> dict[str, Any] | None:
    """The human decision currently awaited, or None when there is none.

    Derived from durable artifacts: the AWAITING_APPROVAL status, the
    REQUESTED approval record, and the gateway's APPROVAL_REQUIRED blocks.
    """

    if trace["status"] != _AWAITING_APPROVAL:
        return None
    requested = next(
        (record for record in reversed(trace["approvals"]) if record["decision"] == "REQUESTED"),
        None,
    )
    blocked_capabilities = tuple(
        dict.fromkeys(
            record["capability_id"]
            for record in trace["invocations"]
            if record["status"] == "BLOCKED" and record["error"] == "APPROVAL_REQUIRED"
        )
    )
    return {
        "awaited_since": requested["decided_at"] if requested else None,
        "reason": requested["reason"] if requested else None,
        "approval_required_for": blocked_capabilities,
        "consequential_proposals": [
            proposal for proposal in trace["proposals"] if proposal["actions"]
        ],
        "evidence_refs": [ref for record in trace["evidence"] for ref in [record["ref"]]],
    }


def _recommendation_view(trace: dict[str, Any]) -> dict[str, Any] | None:
    """The durable recommendation, from the outcome or the top proposal."""

    outcome = trace["outcome"]
    if outcome is not None and outcome.get("recommendation"):
        return {
            "statement": outcome["recommendation"],
            "evidence_refs": [record["ref"] for record in trace["evidence"]],
            "source": "outcome",
        }
    proposals = trace["proposals"]
    if not proposals:
        return None
    top = max(proposals, key=lambda proposal: proposal["confidence"])
    return {
        "statement": top["statement"],
        "evidence_refs": list(top["evidence_refs"]),
        "confidence": top["confidence"],
        "source": "proposal",
    }


def _policy_results_view(invocations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The durable policy decision captured for every capability invocation."""

    return [
        {
            "capability_id": record["capability_id"],
            "capability_version": record["capability_version"],
            "status": record["status"],
            "error": record["error"],
            "allowed": record["authorization"].get("allowed"),
            "policy_id": record["authorization"].get("policy_id"),
            "reason": record["authorization"].get("reason"),
        }
        for record in invocations
    ]


def _consequential_capabilities(invocations: list[dict[str, Any]]) -> tuple[str, ...]:
    """Capability ids whose side effects are consequential, in first-seen order."""

    return tuple(
        dict.fromkeys(
            record["capability_id"]
            for record in invocations
            if record["side_effect"] == "WRITE_CONSEQUENTIAL"
        )
    )
