"""Nexus Spine Models — Shared Contracts for the Vertical Slice.

Defines the data shapes threaded through the full spine pipeline:

    * ``SwarmTask`` — the unit of work the supervisor receives, carrying
      references into the real world (never fabricated objects).
    * ``SwarmTaskContext`` — the authorized, graph-backed context package
      the supervisor hands to agents.
    * ``AgentProposal`` — the strict OUTPUT contract every agent must
      produce. Agents never directly mutate World State.
    * ``SpineStageResult`` — per-stage telemetry (timing, evidence node,
      status) emitted by the orchestrator for observability.
    * ``SpineResult`` — the top-level spine return value tying together
      graph, signals, blast radius, proposals, twin comparison, decision
      card, approval state, execution result, evidence root, and outcome.

Invariants (A5/A7/A10):
    * ``SwarmTask`` always carries real world references.
    * ``AgentProposal`` is the only output shape agents may produce.
    * Every stage result carries an ``evidence_node_id`` for DAG linkage.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from app.common.ids import uuid7
from app.modules.nexus_spine.canonical_schema import EntityType

# ─────────────────────────────────────────────────────────────────────────────
# Spine stage lifecycle
# ─────────────────────────────────────────────────────────────────────────────


class SpineStageStatus(StrEnum):
    SUCCESS = "SUCCESS"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


class SpineStatus(StrEnum):
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


# ─────────────────────────────────────────────────────────────────────────────
# Swarm task (the real-context input the supervisor consumes)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SwarmTaskContext:
    """Authorized context package passed to agents.

    Every field is a reference into the real world — no fabricated objects,
    no hardcoded demo defaults. Agents read from these references to produce
    proposals.
    """

    world_state_version: int
    world_state_hash: str = ""
    graph_version: str = ""
    incident_entity_id: str = ""  # canonical_id of the triggering entity
    incident_entity_type: EntityType = EntityType.SUPPLIER
    affected_entity_ids: list[str] = field(default_factory=list)
    signals: list[dict[str, Any]] = field(default_factory=list)
    blast_radius: dict[str, Any] = field(default_factory=dict)
    relevant_agent_families: list[str] = field(default_factory=list)
    workspace_id: str = ""
    organization_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "world_state_version": self.world_state_version,
            "world_state_hash": self.world_state_hash,
            "graph_version": self.graph_version,
            "incident_entity_id": self.incident_entity_id,
            "incident_entity_type": self.incident_entity_type,
            "affected_entity_ids": list(self.affected_entity_ids),
            "signals": [dict(s) for s in self.signals],
            "blast_radius": dict(self.blast_radius),
            "relevant_agent_families": list(self.relevant_agent_families),
            "workspace_id": self.workspace_id,
            "organization_id": self.organization_id,
        }


@dataclass(frozen=True)
class SwarmTask:
    """Unit of work dispatched to the supervisor.

    Carries only references — the supervisor and agents dereference into the
    real world. The old demo path (``dummy_items``, hardcoded
    ``seller_01a00b8e99``, ``merkle_root_5a3d76``) is physically impossible
    with this contract.
    """

    task_id: str
    organization_id: str
    workspace_id: str
    world_id: str
    world_state_version: int
    incident_id: str  # canonical_id of the incident entity
    incident_entity_type: EntityType
    signal_type: str
    signal_severity: str
    context: SwarmTaskContext

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "organization_id": self.organization_id,
            "workspace_id": self.workspace_id,
            "world_id": self.world_id,
            "world_state_version": self.world_state_version,
            "incident_id": self.incident_id,
            "incident_entity_type": self.incident_entity_type,
            "signal_type": self.signal_type,
            "signal_severity": self.signal_severity,
            "context": self.context.to_dict(),
        }

    @classmethod
    def create(
        cls,
        *,
        organization_id: str,
        workspace_id: str,
        world_id: str,
        world_state_version: int,
        incident_id: str,
        incident_entity_type: EntityType,
        signal_type: str,
        signal_severity: str,
        context: SwarmTaskContext,
    ) -> SwarmTask:
        return cls(
            task_id=f"TASK_{uuid7()[:8]}",
            organization_id=organization_id,
            workspace_id=workspace_id,
            world_id=world_id,
            world_state_version=world_state_version,
            incident_id=incident_id,
            incident_entity_type=incident_entity_type,
            signal_type=signal_type,
            signal_severity=signal_severity,
            context=context,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Agent proposal (the strict OUTPUT contract every agent must produce)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AgentProposal:
    """Strict OUTPUT contract for every agent (A7).

    Agents return proposals only — they never directly mutate World State
    and never trigger execution. The supervisor collects proposals, the Twin
    simulates them, the policy gate vets them, and only a human-approved
    execution can act.

    ``action`` is the canonical action verb (e.g. ``"reroute_shipment"``,
    ``"switch_supplier"``, ``"consolidate_load"``).

    ``payload`` carries action-specific parameters (carrier, route, volume,
    etc.) that the Twin and execution adapter consume.
    """

    agent_id: str
    agent_family: str  # "BOOKING" | "PROCUREMENT" | "OPTIMIZATION" | "COMPLIANCE"
    action: str
    target_entity_ids: list[str] = field(default_factory=list)
    expected_cost_usd: float = 0.0
    expected_delay_days: float = 0.0
    expected_risk_score: float = 0.0
    evidence_refs: list[str] = field(default_factory=list)
    confidence: float = 1.0
    payload: dict[str, Any] = field(default_factory=dict)
    # V2.2 provenance fields
    world_state_version: int = 0
    world_state_hash: str = ""
    correlation_id: str = ""
    proposal_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "agent_family": self.agent_family,
            "action": self.action,
            "target_entity_ids": list(self.target_entity_ids),
            "expected_cost_usd": self.expected_cost_usd,
            "expected_delay_days": self.expected_delay_days,
            "expected_risk_score": self.expected_risk_score,
            "evidence_refs": list(self.evidence_refs),
            "confidence": self.confidence,
            "payload": dict(self.payload),
            "world_state_version": self.world_state_version,
            "world_state_hash": self.world_state_hash,
            "correlation_id": self.correlation_id,
            "proposal_hash": self.proposal_hash,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Stage and spine results
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SpineStageResult:
    """Per-stage telemetry emitted by the orchestrator.

    ``evidence_node_id`` links this stage into the DecisionEvidenceGraph so
    the full chain (SOURCE_RECORD → … → OUTCOME) remains traversable.
    """

    stage_name: str
    status: SpineStageStatus
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    output: dict[str, Any] = field(default_factory=dict)
    evidence_node_id: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage_name": self.stage_name,
            "status": self.status,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "output": dict(self.output),
            "evidence_node_id": self.evidence_node_id,
            "error": self.error,
        }


@dataclass
class SpineResult:
    """Top-level result of a full spine run.

    Every field is real — computed from the actual uploaded data, world state,
    graph, agents, twin, and execution. Nothing is fabricated.
    """

    spine_id: str = field(default_factory=lambda: f"SPINE_{uuid7()[:8]}")
    workspace_id: str = ""
    organization_id: str = ""
    world_id: str = ""
    world_state_version: int = 0
    graph_version: str = ""
    stages: list[SpineStageResult] = field(default_factory=list)
    graph_summary: dict[str, Any] = field(default_factory=dict)
    signals: list[dict[str, Any]] = field(default_factory=list)
    blast_radius: dict[str, Any] | None = None
    swarm_task: SwarmTask | None = None
    agent_proposals: list[AgentProposal] = field(default_factory=list)
    twin_comparison: dict[str, Any] | None = None
    decision_card: dict[str, Any] | None = None
    approval_state: str = "PENDING"  # PENDING | APPROVED | REJECTED
    execution_result: dict[str, Any] | None = None
    evidence_root_id: str | None = None
    outcome: dict[str, Any] | None = None
    # V2.3 Governed Execution fields
    approval_record: dict[str, Any] | None = None
    execution_authorization: dict[str, Any] | None = None
    execution_outcome: dict[str, Any] | None = None
    evidence_chain_hash: str = ""
    # V2.4 Evidence & Outcome Integrity fields
    evidence_chain_v24: dict[str, Any] | None = None
    evidence_chain_node_count: int = 0
    evidence_chain_verification: dict[str, Any] | None = None
    status: SpineStatus = SpineStatus.COMPLETED
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "spine_id": self.spine_id,
            "workspace_id": self.workspace_id,
            "organization_id": self.organization_id,
            "world_id": self.world_id,
            "world_state_version": self.world_state_version,
            "graph_version": self.graph_version,
            "stages": [s.to_dict() for s in self.stages],
            "graph_summary": dict(self.graph_summary),
            "signals": [dict(s) for s in self.signals],
            "blast_radius": dict(self.blast_radius) if self.blast_radius else None,
            "swarm_task": self.swarm_task.to_dict() if self.swarm_task else None,
            "agent_proposals": [p.to_dict() for p in self.agent_proposals],
            "twin_comparison": dict(self.twin_comparison) if self.twin_comparison else None,
            "decision_card": dict(self.decision_card) if self.decision_card else None,
            "approval_state": self.approval_state,
            "execution_result": dict(self.execution_result) if self.execution_result else None,
            "evidence_root_id": self.evidence_root_id,
            "outcome": dict(self.outcome) if self.outcome else None,
            "approval_record": dict(self.approval_record) if self.approval_record else None,
            "execution_authorization": dict(self.execution_authorization) if self.execution_authorization else None,
            "execution_outcome": dict(self.execution_outcome) if self.execution_outcome else None,
            "evidence_chain_hash": self.evidence_chain_hash,
            "evidence_chain_v24": (
                dict(self.evidence_chain_v24) if self.evidence_chain_v24 else None
            ),
            "evidence_chain_node_count": self.evidence_chain_node_count,
            "evidence_chain_verification": (
                dict(self.evidence_chain_verification)
                if self.evidence_chain_verification
                else None
            ),
            "status": self.status,
            "created_at": self.created_at.isoformat(),
        }


# ─────────────────────────────────────────────────────────────────────────────
# V2.2 Provenance hashing
# ─────────────────────────────────────────────────────────────────────────────


def compute_world_state_hash(workspace_id: str, version: int) -> str:
    """Deterministic SHA-256 hash for a world state checkpoint.

    Same (workspace_id, version) → same hash. Used as the provenance
    anchor for proposals and twin simulations.
    """
    blob = json.dumps(
        {"workspace_id": workspace_id, "version": version},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def compute_proposal_hash(proposal: AgentProposal) -> str:
    """SHA-256 over canonical proposal fields (deterministic fingerprint).

    Same (agent_id, action, targets, cost, delay, risk, world_state_version)
    → identical proposal_hash. Used by execution gate to detect tampering.
    """
    canonical = {
        "agent_id": proposal.agent_id,
        "action": proposal.action,
        "target_entity_ids": sorted(proposal.target_entity_ids),
        "expected_cost_usd": proposal.expected_cost_usd,
        "expected_delay_days": proposal.expected_delay_days,
        "expected_risk_score": proposal.expected_risk_score,
        "world_state_version": proposal.world_state_version,
    }
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()
