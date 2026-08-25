"""Nexus Spine Orchestrator — End-to-End Data-Driven Pipeline.

Drives the full spine from uploaded data to governed execution:

    CanonicalDataset → World State → Operational Graph → Signals / RCA →
    SwarmTask → Agent Proposals → Twin Counterfactual → Policy Gate →
    Human Approval → Execution → Outcome → World State Event → Evidence DAG

The orchestrator is the ONLY module that knows how to stitch the full
pipeline together. Each stage delegates to a domain module via a
pluggable callback, so stages can be wired incrementally and tested in
isolation.

Stages (numbered to match the 20-step acceptance test):
    1. Schema Discovery      — canonical dataset is the schema
    2. Data Profiling         — column types, row counts
    3. Entity Resolution      — canonical entities from rows
    4. Operational Graph      — build_graph from canonical dataset
    5. Topology Metrics       — coverage, gini, orphans (computed)
    6. World State            — write events for each entity
    7. Signal Detection       — evaluate from world + graph
    8. Blast Radius / RCA     — traverse graph dependencies
    9. Agent Selection        — DynamicAgentRouter by signal type
   10. Authorized Context     — SwarmTaskContext with real refs
   11. Agent Proposals        — supervisor runs selected agents
   12. Twin Simulation        — simulate each proposal
   13. Counterfactual Compare — baseline vs option KPIs
   14. Governed Recommendation— policy gate
   15. Human Approval          — decision card + approval state
   16. Execution              — dispatch to adapter (post-approval)
   17. Record Outcome         — write outcome WorldEvent
   18. World State Event      — version bump
   19. Stale Decision Invalidate — (future: version comparison)
   20. Frontend Show          — (spine result is the payload)

Evidence DAG (A10): every stage emits an EvidenceNode linked to its
parent, producing a traversable chain from SOURCE_RECORD → OUTCOME.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.common.ids import uuid7
from app.modules.data_intelligence.decision_evidence_graph import (
    DecisionEvidenceGraph,
)
from app.modules.data_intelligence.operational_graph import (
    GraphAnalyticsSummary,
    OperationalGraphEngine,
)
from app.modules.nexus_spine.canonical_schema import (
    CanonicalDataset,
    CanonicalTable,
    EntityType,
)
from app.modules.nexus_spine.evidence_chain import (
    ROOT_PARENT_ID,
    EvidenceChain,
)
from app.modules.nexus_spine.governed_execution_models import (
    ApprovalRecord,
    ExecutionOutcome,
)
from app.modules.nexus_spine.governed_execution_service import (
    GovernedExecutionError,
    GovernedExecutionService,
)
from app.modules.nexus_spine.models import (
    AgentProposal,
    SpineResult,
    SpineStageResult,
    SpineStageStatus,
    SpineStatus,
    SwarmTask,
    SwarmTaskContext,
    compute_proposal_hash,
    compute_world_state_hash,
)

if TYPE_CHECKING:
    from app.modules.world.world_service import WorldStateService


# ─────────────────────────────────────────────────────────────────────────────
# In-memory world state (lightweight V1 stand-in for async WorldStateService)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class _WorldEvent:
    event_id: str
    entity_type: str
    entity_id: str
    event_type: str
    payload: dict[str, Any]
    version: int
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class _InMemoryWorldState:
    """Lightweight in-memory world state for V1 spine.

    Follows the same contracts as WorldStateService: append-only events,
    monotonic version, workspace isolation. Can be swapped for the full
    async WorldStateService later.
    """

    def __init__(self, workspace_id: str, world_id: str) -> None:
        self.workspace_id = workspace_id
        self.world_id = world_id
        self.version = 0
        self.variables: dict[str, dict[str, Any]] = {}  # variable_id → {value, ...}
        self.events: list[_WorldEvent] = []

    def submit_entity_event(
        self,
        entity_type: str,
        entity_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> _WorldEvent:
        self.version += 1
        event = _WorldEvent(
            event_id=f"evt_{uuid7()[:8]}",
            entity_type=entity_type,
            entity_id=entity_id,
            event_type=event_type,
            payload=payload,
            version=self.version,
        )
        self.events.append(event)
        # Update variable store
        var_id = f"{entity_type.lower()}.{entity_id}.{event_type}"
        self.variables[var_id] = {
            "value": payload,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "event_type": event_type,
            "version": self.version,
        }
        return event

    def submit_outcome_event(
        self,
        execution_result: dict[str, Any],
    ) -> _WorldEvent:
        return self.submit_entity_event(
            entity_type="EXECUTION",
            entity_id=execution_result.get("plan_id", "unknown"),
            event_type="EXECUTION_OUTCOME",
            payload=execution_result,
        )


# ─────────────────────────────────────────────────────────────────────────────
# World State Tracker — abstracts V1 (in-memory) and V2 (persistent) paths
# ─────────────────────────────────────────────────────────────────────────────


class _WorldStateTracker:
    """Unified interface over in-memory and persistent world state.

    When ``world_service`` is provided, events flow through the real
    J.2.3 ``WorldStateService`` (async, PostgreSQL/SQLite). When ``None``,
    the V1 in-memory fallback is used so existing tests keep passing.
    """

    def __init__(
        self,
        ws_id: str,
        w_id: str,
        world_service: WorldStateService | None = None,
    ) -> None:
        self._ws_id = ws_id
        self._w_id = w_id
        self._service = world_service
        self._memory: _InMemoryWorldState | None = None
        self._version = 0

    async def initialize(self) -> None:
        """Initialize the world state (genesis or in-memory)."""
        if self._service is not None:
            # already initialized — idempotent
            with contextlib.suppress(ValueError):
                await self._service.initialize_world(
                    workspace_id=self._ws_id,
                    world_id=self._w_id,
                )
            state = await self._service.get_current_state(
                workspace_id=self._ws_id,
                world_id=self._w_id,
            )
            if state is not None:
                self._version = state.version
        else:
            self._memory = _InMemoryWorldState(self._ws_id, self._w_id)

    @property
    def version(self) -> int:
        if self._memory is not None:
            return self._memory.version
        return self._version

    @property
    def memory(self) -> _InMemoryWorldState | None:
        """Expose the in-memory world for V1 twin simulation callbacks."""
        return self._memory

    async def submit_entity_event(
        self,
        entity_type: str,
        entity_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> _WorldEvent | None:
        """Submit an entity event to world state.

        Returns a ``_WorldEvent`` (in-memory path) or ``None`` (persistent
        path — callers should use ``version`` for the latest state).
        """
        if self._service is not None:
            from app.modules.events.event_models import EntityIngested
            event = EntityIngested(
                event_id=f"evt_ingest_{uuid7()}",
                world_id=self._w_id,
                workspace_id=self._ws_id,
                entity_type=entity_type,
                entity_id=entity_id,
                attributes=payload,
                source_file=payload.get("_source_file", ""),
            )
            idem_key = f"{self._ws_id}.{entity_type}.{entity_id}"
            result = await self._service.submit_event(
                event, idempotency_key=idem_key,
            )
            self._version = result.version
            return None
        else:
            assert self._memory is not None
            return self._memory.submit_entity_event(
                entity_type, entity_id, event_type, payload,
            )

    async def submit_outcome_event(
        self,
        execution_result: dict[str, Any],
    ) -> _WorldEvent | None:
        """Submit an execution outcome event."""
        if self._service is not None:
            from app.modules.events.event_models import ExecutionOutcome
            event = ExecutionOutcome(
                event_id=f"evt_outcome_{uuid7()}",
                world_id=self._w_id,
                workspace_id=self._ws_id,
                entity_type="EXECUTION",
                entity_id=execution_result.get("plan_id", "unknown"),
                plan_id=execution_result.get("plan_id", ""),
                action=execution_result.get("action", ""),
                result_status=execution_result.get("status", ""),
            )
            result = await self._service.submit_event(event)
            self._version = result.version
            return None
        else:
            assert self._memory is not None
            return self._memory.submit_outcome_event(execution_result)


# ─────────────────────────────────────────────────────────────────────────────
# Stage callbacks (pluggable — wired incrementally)
# ─────────────────────────────────────────────────────────────────────────────

# Type aliases for stage callbacks
SupervisorFn = Callable[[SwarmTask], list[AgentProposal]]
TwinSimulationFn = Callable[..., dict[str, Any]]
PolicyGateFn = Callable[[list[AgentProposal], dict[str, Any]], dict[str, Any]]
ExecutionFn = Callable[[AgentProposal, dict[str, Any]], dict[str, Any]]


def _default_supervisor(task: SwarmTask) -> list[AgentProposal]:
    """Real supervisor that reads context from SwarmTask (A5/A6/A7)."""
    from app.modules.nexus_spine.pipeline_stages import real_supervisor_fn
    return real_supervisor_fn(task)


def _default_twin_simulation(
    proposals: list[AgentProposal],
    world: _InMemoryWorldState | None,
    *,
    world_state_version: int = 0,
) -> dict[str, Any]:
    """Real twin counterfactual simulator (A9 / V2.2)."""
    from app.modules.nexus_spine.pipeline_stages import twin_simulation_fn
    return twin_simulation_fn(
        proposals, world, world_state_version=world_state_version,
    )


def _default_policy_gate(
    proposals: list[AgentProposal], twin_result: dict[str, Any]
) -> dict[str, Any]:
    """Real policy gate (A8 partial)."""
    from app.modules.nexus_spine.pipeline_stages import policy_gate_fn
    return policy_gate_fn(proposals, twin_result)


def _default_execution(
    proposal: AgentProposal, approval: dict[str, Any]
) -> dict[str, Any]:
    """Real execution gate with hard rejection reasons (A8 / V2.2).

    Reads V2.2 context from the ``approval`` dict (injected by the
    orchestrator): ``_twin_result``, ``_organization_id``,
    ``_workspace_id``, ``_current_world_version``.
    """
    from app.modules.nexus_spine.pipeline_stages import execution_gate_fn
    return execution_gate_fn(
        proposal,
        approval,
        organization_id=approval.get("_organization_id", "default"),
        workspace_id=approval.get("_workspace_id", "default"),
        world_state_version=proposal.world_state_version,
        current_world_version=approval.get("_current_world_version", 0),
        twin_result=approval.get("_twin_result"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────────────────────────────────────


class RealDataSpine:
    """End-to-end spine orchestrator.

    Accepts a ``CanonicalDataset`` and drives every stage, producing a
    ``SpineResult`` with the full evidence DAG.

    Stage callbacks (supervisor, twin, policy, execution) are pluggable
    so they can be wired incrementally during the hardening program.
    """

    def __init__(
        self,
        *,
        supervisor_fn: SupervisorFn = _default_supervisor,
        twin_simulation_fn: TwinSimulationFn = _default_twin_simulation,
        policy_gate_fn: PolicyGateFn = _default_policy_gate,
        execution_fn: ExecutionFn = _default_execution,
    ) -> None:
        self._supervisor_fn = supervisor_fn
        self._twin_fn = twin_simulation_fn
        self._policy_fn = policy_gate_fn
        self._execution_fn = execution_fn

    async def run(
        self,
        canonical_dataset: CanonicalDataset,
        *,
        organization_id: str = "",
        workspace_id: str | None = None,
        world_id: str | None = None,
        world_service: WorldStateService | None = None,
        operator_id: str = "system_auto",
    ) -> SpineResult:
        """Run the full spine end-to-end on a canonical dataset.

        When ``world_service`` is provided, events are persisted through the
        real J.2.3 ``WorldStateService`` (PostgreSQL/SQLite). When ``None``,
        the in-memory fallback is used (V1 test path).
        """
        ws_id = workspace_id or canonical_dataset.workspace_id or f"ws_{uuid7()[:8]}"
        w_id = world_id or f"world_{uuid7()[:8]}"
        result = SpineResult(
            workspace_id=ws_id,
            organization_id=organization_id,
            world_id=w_id,
        )
        evidence = DecisionEvidenceGraph(decision_id=f"DEC_{uuid7()[:8]}")

        # V2.4 — Evidence & Outcome Integrity chain (11-field contract).
        # Header is finalized below once the SwarmTask (correlation/decision
        # id) is created. Until then the chain carries a placeholder header
        # so node additions stay in order.
        v24_chain = EvidenceChain(
            organization_id=organization_id,
            workspace_id=ws_id,
            correlation_id="PENDING",
            decision_id="PENDING",
        )
        last_v24_id: str | None = None

        # V2: persistent world state via WorldStateService, or V1 in-memory fallback
        tracker = _WorldStateTracker(
            ws_id=ws_id,
            w_id=w_id,
            world_service=world_service,
        )
        await tracker.initialize()

        graph_engine = OperationalGraphEngine()
        last_evidence_node: str | None = None

        # ── Stage 1-2: Schema discovery + data profiling ───────────────
        started = datetime.now(UTC)
        profile = self._profile_dataset(canonical_dataset)
        source_node = evidence.add_evidence_step(
            node_type="SOURCE_RECORD",
            label="Uploaded dataset",
            payload=profile,
        )
        last_evidence_node = source_node.node_id
        # V2.4: SOURCE evidence node (root of the chain).
        last_v24_id = self._emit_v24(
            v24_chain,
            last_v24_id,
            node_type="SOURCE",
            input_payload={
                "workspace_id": ws_id,
                "schema_version": canonical_dataset.schema_version,
                "table_count": len(canonical_dataset.tables),
            },
            output_payload=profile,
            world_state_version=0,
            actor="spine.source_profiler",
        )
        result.stages.append(SpineStageResult(
            stage_name="schema_discovery_and_profiling",
            status=SpineStageStatus.SUCCESS,
            started_at=started,
            completed_at=datetime.now(UTC),
            output=profile,
            evidence_node_id=source_node.node_id,
        ))

        # ── Stage 3: Entity resolution ─────────────────────────────────
        started = datetime.now(UTC)
        entity_count = self._count_entities(canonical_dataset)
        entity_node = evidence.add_evidence_step(
            node_type="ENTITY",
            label=f"Resolved {entity_count} entities",
            payload={"entity_count": entity_count, "types": [et.value for et in canonical_dataset.entity_types()]},
            parent_node_id=last_evidence_node,
            relation="GROUNDED_IN",
        )
        last_evidence_node = entity_node.node_id
        # V2.4: CANONICAL_ENTITY evidence node.
        last_v24_id = self._emit_v24(
            v24_chain,
            last_v24_id,
            node_type="CANONICAL_ENTITY",
            input_payload={"source_node": last_v24_id or ""},
            output_payload={
                "entity_count": entity_count,
                "types": [et.value for et in canonical_dataset.entity_types()],
            },
            world_state_version=0,
            actor="spine.entity_resolver",
        )
        result.stages.append(SpineStageResult(
            stage_name="entity_resolution",
            status=SpineStageStatus.SUCCESS,
            started_at=started,
            completed_at=datetime.now(UTC),
            output={"entity_count": entity_count},
            evidence_node_id=entity_node.node_id,
        ))

        # ── Stage 4-5: Operational graph + metrics ─────────────────────
        started = datetime.now(UTC)
        coverage = graph_engine.build_graph(
            canonical_dataset,
            workspace_id=ws_id,
            world_state_version=tracker.version,
        )
        analytics = graph_engine.compute_graph_analytics(
            graph_version=coverage.graph_version,
            world_state_version=coverage.world_state_version,
        )
        result.graph_version = coverage.graph_version
        result.graph_summary = analytics.to_dict()

        graph_node = evidence.add_evidence_step(
            node_type="ENTITY",
            label=f"Graph: {coverage.total_nodes_created} nodes, {coverage.total_edges_created} edges",
            payload=coverage.to_dict(),
            parent_node_id=last_evidence_node,
            relation="GENERATED_BY",
        )
        last_evidence_node = graph_node.node_id
        # V2.4: GRAPH evidence node.
        last_v24_id = self._emit_v24(
            v24_chain,
            last_v24_id,
            node_type="GRAPH",
            input_payload={"canonical_entities": last_v24_id or ""},
            output_payload=coverage.to_dict(),
            world_state_version=tracker.version,
            actor="spine.graph_engine",
        )
        result.stages.append(SpineStageResult(
            stage_name="operational_graph",
            status=SpineStageStatus.SUCCESS,
            started_at=started,
            completed_at=datetime.now(UTC),
            output=coverage.to_dict(),
            evidence_node_id=graph_node.node_id,
        ))

        # ── Stage 6: World State — write events for each entity ────────
        started = datetime.now(UTC)
        events_written = await self._write_world_events(canonical_dataset, tracker)
        result.world_state_version = tracker.version

        ws_node = evidence.add_evidence_step(
            node_type="ENTITY",
            label=f"World State v{tracker.version}: {events_written} events",
            payload={"world_state_version": tracker.version, "events_written": events_written},
            parent_node_id=last_evidence_node,
            relation="RESULTED_IN",
        )
        last_evidence_node = ws_node.node_id
        # V2.4: WORLD_STATE evidence node (binds world_state_version).
        last_v24_id = self._emit_v24(
            v24_chain,
            last_v24_id,
            node_type="WORLD_STATE",
            input_payload={"graph_node": last_v24_id or ""},
            output_payload={
                "world_state_version": tracker.version,
                "events_written": events_written,
            },
            world_state_version=tracker.version,
            actor="spine.world_tracker",
        )
        result.stages.append(SpineStageResult(
            stage_name="world_state",
            status=SpineStageStatus.SUCCESS,
            started_at=started,
            completed_at=datetime.now(UTC),
            output={"world_state_version": tracker.version, "events_written": events_written},
            evidence_node_id=ws_node.node_id,
        ))

        # ── Stage 7: Signal detection ──────────────────────────────────
        started = datetime.now(UTC)
        signals = self._detect_signals(graph_engine, analytics, canonical_dataset)
        result.signals = signals

        signal_status = SpineStageStatus.SUCCESS if signals else SpineStageStatus.SUCCESS
        signal_node = evidence.add_evidence_step(
            node_type="SIGNAL",
            label=f"{len(signals)} signal(s) detected",
            payload={"signal_count": len(signals), "signals": signals[:5]},
            parent_node_id=last_evidence_node,
            relation="GENERATED_BY",
        )
        last_evidence_node = signal_node.node_id
        # V2.4: SIGNAL evidence node.
        last_v24_id = self._emit_v24(
            v24_chain,
            last_v24_id,
            node_type="SIGNAL",
            input_payload={
                "world_state_version": tracker.version,
                "graph_analytics": result.graph_summary,
            },
            output_payload={"signal_count": len(signals), "signals": signals[:5]},
            world_state_version=tracker.version,
            actor="spine.signal_detector",
        )
        result.stages.append(SpineStageResult(
            stage_name="signal_detection",
            status=signal_status,
            started_at=started,
            completed_at=datetime.now(UTC),
            output={"signal_count": len(signals)},
            evidence_node_id=signal_node.node_id,
        ))

        # ── Stage 8: Blast radius / RCA ────────────────────────────────
        started = datetime.now(UTC)
        blast_radius = self._compute_blast_radius(signals, graph_engine, canonical_dataset)
        result.blast_radius = blast_radius

        rca_node = evidence.add_evidence_step(
            node_type="HYPOTHESIS",
            label=f"Blast radius: {blast_radius.get('affected_orders_count', 0)} orders",
            payload=blast_radius,
            parent_node_id=last_evidence_node,
            relation="HYPOTHESIZES",
        )
        last_evidence_node = rca_node.node_id
        # V2.4: ROOT_CAUSE evidence node.
        last_v24_id = self._emit_v24(
            v24_chain,
            last_v24_id,
            node_type="ROOT_CAUSE",
            input_payload={
                "signal_node": last_v24_id or "",
                "signals": signals[:3],
            },
            output_payload=blast_radius,
            world_state_version=tracker.version,
            actor="spine.rca_engine",
        )
        result.stages.append(SpineStageResult(
            stage_name="blast_radius_rca",
            status=SpineStageStatus.SUCCESS,
            started_at=started,
            completed_at=datetime.now(UTC),
            output=blast_radius,
            evidence_node_id=rca_node.node_id,
        ))

        # ── Stage 9-10: Agent selection + authorized context ───────────
        started = datetime.now(UTC)
        signal_type = signals[0]["signal_type"] if signals else "UNKNOWN"
        signal_severity = signals[0]["severity"] if signals else "LOW"
        incident_id = signals[0]["entity_id"] if signals else ""
        incident_type = signals[0].get("entity_type", "SUPPLIER") if signals else "SUPPLIER"

        ws_hash = compute_world_state_hash(ws_id, tracker.version)
        context = SwarmTaskContext(
            world_state_version=tracker.version,
            world_state_hash=ws_hash,
            graph_version=coverage.graph_version,
            incident_entity_id=incident_id,
            incident_entity_type=EntityType(incident_type) if incident_type in EntityType.__members__ else EntityType.SUPPLIER,
            affected_entity_ids=blast_radius.get("affected_entity_ids", []),
            signals=signals,
            blast_radius=blast_radius,
            workspace_id=ws_id,
            organization_id=organization_id,
        )
        task = SwarmTask.create(
            organization_id=organization_id,
            workspace_id=ws_id,
            world_id=w_id,
            world_state_version=tracker.version,
            incident_id=incident_id,
            incident_entity_type=context.incident_entity_type,
            signal_type=signal_type,
            signal_severity=signal_severity,
            context=context,
        )
        result.swarm_task = task

        # V2.4: finalize the chain header now that the decision id is known.
        # Earlier nodes were stamped with a placeholder correlation_id;
        # finalize_correlation rewrites their hashes in one pass.
        v24_chain.finalize_correlation(task.task_id, task.task_id)

        context_node = evidence.add_evidence_step(
            node_type="MODEL_OUTPUT",
            label=f"SwarmTask {task.task_id} — signal={signal_type}",
            payload=task.to_dict(),
            parent_node_id=last_evidence_node,
            relation="GENERATED_BY",
        )
        last_evidence_node = context_node.node_id
        # V2.4: AGENT_OBSERVATION evidence node (supervisor context package).
        last_v24_id = self._emit_v24(
            v24_chain,
            last_v24_id,
            node_type="AGENT_OBSERVATION",
            input_payload={
                "rca_node": last_v24_id or "",
                "world_state_version": tracker.version,
                "world_state_hash": ws_hash,
                "graph_version": coverage.graph_version,
            },
            output_payload={
                "task_id": task.task_id,
                "signal_type": signal_type,
                "signal_severity": signal_severity,
                "incident_id": incident_id,
                "affected_count": len(blast_radius.get("affected_entity_ids", [])),
            },
            world_state_version=tracker.version,
            actor="spine.supervisor",
        )
        result.stages.append(SpineStageResult(
            stage_name="agent_selection_and_context",
            status=SpineStageStatus.SUCCESS,
            started_at=started,
            completed_at=datetime.now(UTC),
            output={"task_id": task.task_id, "signal_type": signal_type},
            evidence_node_id=context_node.node_id,
        ))

        # ── Stage 11: Agent proposals ──────────────────────────────────
        started = datetime.now(UTC)
        raw_proposals = self._supervisor_fn(task)
        # Stamp V2.2 provenance onto each proposal
        proposals = [
            replace(
                p,
                world_state_version=tracker.version,
                world_state_hash=ws_hash,
                correlation_id=task.task_id,
            )
            for p in raw_proposals
        ]
        # Compute deterministic hash over canonical fields (now includes version)
        proposals = [
            replace(p, proposal_hash=compute_proposal_hash(p))
            for p in proposals
        ]
        result.agent_proposals = proposals

        proposal_node = evidence.add_evidence_step(
            node_type="PROPOSAL",
            label=f"{len(proposals)} proposal(s)",
            payload={"proposals": [p.to_dict() for p in proposals]},
            parent_node_id=last_evidence_node,
            relation="GENERATED_BY",
        )
        last_evidence_node = proposal_node.node_id
        # V2.4: PROPOSAL evidence node (one per chain — collates all proposals
        # in output_payload; the canonical proposal_hash is included so the
        # chain carries the tamper-evident link to authorization).
        last_v24_id = self._emit_v24(
            v24_chain,
            last_v24_id,
            node_type="PROPOSAL",
            input_payload={
                "observation_node": last_v24_id or "",
                "task_id": task.task_id,
            },
            output_payload={
                "proposal_count": len(proposals),
                "proposal_hashes": [p.proposal_hash for p in proposals],
            },
            world_state_version=tracker.version,
            actor="spine.agents",
        )
        result.stages.append(SpineStageResult(
            stage_name="agent_proposals",
            status=SpineStageStatus.SUCCESS if proposals else SpineStageStatus.SKIPPED,
            started_at=started,
            completed_at=datetime.now(UTC),
            output={"proposal_count": len(proposals)},
            evidence_node_id=proposal_node.node_id,
        ))

        # ── Stage 12-13: Twin simulation + counterfactual ──────────────
        started = datetime.now(UTC)
        twin_result = (
            self._twin_fn(
                proposals,
                tracker.memory,
                world_state_version=tracker.version,
            )
            if proposals
            else {}
        )
        result.twin_comparison = twin_result

        twin_node = evidence.add_evidence_step(
            node_type="SIMULATION",
            label=f"Twin: {twin_result.get('status', 'SKIPPED')}",
            payload=twin_result,
            parent_node_id=last_evidence_node,
            relation="EVALUATED_IN",
        )
        last_evidence_node = twin_node.node_id
        # V2.4: SIMULATION evidence node (carries simulation_hash).
        last_v24_id = self._emit_v24(
            v24_chain,
            last_v24_id,
            node_type="SIMULATION",
            input_payload={
                "proposal_node": last_v24_id or "",
                "world_state_version": tracker.version,
            },
            output_payload={
                "status": twin_result.get("status", "SKIPPED"),
                "simulation_hash": twin_result.get("simulation_hash", ""),
            },
            world_state_version=tracker.version,
            actor="spine.twin",
        )
        result.stages.append(SpineStageResult(
            stage_name="twin_simulation",
            status=SpineStageStatus.SUCCESS if twin_result else SpineStageStatus.SKIPPED,
            started_at=started,
            completed_at=datetime.now(UTC),
            output=twin_result,
            evidence_node_id=twin_node.node_id,
        ))

        # ── Stage 14: Policy gate ──────────────────────────────────────────
        started = datetime.now(UTC)
        policy_result = self._policy_fn(proposals, twin_result) if proposals else {"approved": False, "reason": "NO_PROPOSALS"}

        policy_node = evidence.add_evidence_step(
            node_type="DECISION",
            label=f"Policy: {'APPROVED' if policy_result.get('approved') else 'REJECTED'}",
            payload=policy_result,
            parent_node_id=last_evidence_node,
            relation="EVALUATED_IN",
        )
        last_evidence_node = policy_node.node_id
        # V2.4: POLICY evidence node.
        last_v24_id = self._emit_v24(
            v24_chain,
            last_v24_id,
            node_type="POLICY",
            input_payload={
                "simulation_node": last_v24_id or "",
                "proposal_count": len(proposals),
            },
            output_payload={
                "approved": bool(policy_result.get("approved")),
                "reason": policy_result.get("reason", ""),
                "policy_version": policy_result.get("policy_version", "v1"),
            },
            world_state_version=tracker.version,
            actor="spine.policy_gate",
        )

        # ── Stage 15: Human approval — ApprovalRecord (V2.3) ───────────────
        best_proposal = self._select_best_proposal(proposals) if proposals else None
        simulation_hash = twin_result.get("simulation_hash", "")

        approval_record = ApprovalRecord.create(
            decision_id=task.task_id,
            operator_id=operator_id,
            operator_role="operator",
            decision="APPROVE" if policy_result.get("approved") else "REJECT",
            proposal_hash=best_proposal.proposal_hash if best_proposal else "",
            simulation_hash=simulation_hash,
            world_state_version=tracker.version,
        )
        result.approval_record = approval_record.to_dict()
        result.approval_state = "APPROVED" if policy_result.get("approved") else "REJECTED"

        # V2.4: APPROVAL evidence node (carries approval_hash).
        last_v24_id = self._emit_v24(
            v24_chain,
            last_v24_id,
            node_type="APPROVAL",
            input_payload={
                "policy_node": last_v24_id or "",
                "proposal_hash": best_proposal.proposal_hash if best_proposal else "",
                "simulation_hash": simulation_hash,
                "operator_id": operator_id,
            },
            output_payload={
                "approval_id": approval_record.approval_id,
                "decision": approval_record.decision,
                "approval_hash": approval_record.approval_hash,
                "operator_id": operator_id,
            },
            world_state_version=tracker.version,
            actor="spine.approval",
        )

        # Build decision card
        result.decision_card = {
            "card_id": f"DC_{uuid7()[:8]}",
            "proposals": [p.to_dict() for p in proposals],
            "twin_comparison": twin_result,
            "policy": policy_result,
            "recommendation": best_proposal.to_dict() if best_proposal else None,
            "approval_record": approval_record.to_dict(),
        }

        result.stages.append(SpineStageResult(
            stage_name="policy_gate_and_approval",
            status=SpineStageStatus.SUCCESS,
            started_at=started,
            completed_at=datetime.now(UTC),
            output={
                "approved": policy_result.get("approved", False),
                "approval_record": approval_record.to_dict(),
            },
            evidence_node_id=policy_node.node_id,
        ))

        # ── Stage 16: Governed execution (V2.3) ────────────────────────────
        started = datetime.now(UTC)
        execution_outcome: ExecutionOutcome | None = None

        if policy_result.get("approved") and best_proposal:
            try:
                ges = GovernedExecutionService()
                execution_outcome = ges.authorize_and_execute(
                    proposal=best_proposal,
                    approval=approval_record,
                    twin_result=twin_result,
                    policy_result=policy_result,
                    world_state_version=tracker.version,
                    world_state_hash=ws_hash,
                    evidence_root_id=source_node.node_id,
                    organization_id=organization_id,
                    workspace_id=ws_id,
                    current_world_version=tracker.version,
                    agent_identity=best_proposal.agent_id,
                    agent_capability=["EXECUTE"],
                    execution_budget_usd=50000.0,
                )
                result.execution_outcome = execution_outcome.to_dict()
                result.execution_result = execution_outcome.adapter_result

                # V2.4: AUTHORIZATION evidence node — proves the 15+ checks
                # all passed (recorded on the ledger for audit).
                last_v24_id = self._emit_v24(
                    v24_chain,
                    last_v24_id,
                    node_type="AUTHORIZATION",
                    input_payload={
                        "approval_node": last_v24_id or "",
                        "proposal_hash": best_proposal.proposal_hash,
                        "simulation_hash": simulation_hash,
                        "world_state_version": tracker.version,
                        "agent_identity": best_proposal.agent_id,
                        "execution_budget_usd": 50000.0,
                    },
                    output_payload={
                        "authorization_hash": execution_outcome.authorization_hash,
                        "decision": "APPROVED",
                        "agent_capability": ["EXECUTE"],
                    },
                    world_state_version=tracker.version,
                    actor="spine.governed_execution",
                )
                # V2.4: EXECUTION evidence node — the dispatch itself.
                last_v24_id = self._emit_v24(
                    v24_chain,
                    last_v24_id,
                    node_type="EXECUTION",
                    input_payload={
                        "authorization_node": last_v24_id or "",
                        "proposal_hash": best_proposal.proposal_hash,
                    },
                    output_payload={
                        "execution_id": execution_outcome.execution_id,
                        "action": best_proposal.action,
                        "agent_id": best_proposal.agent_id,
                        "workspace_id": ws_id,
                    },
                    world_state_version=tracker.version,
                    actor="spine.adapter_dispatch",
                )

                exec_node = evidence.add_evidence_step(
                    node_type="DECISION",
                    label=f"Executed: {best_proposal.action}",
                    payload=execution_outcome.to_dict(),
                    parent_node_id=last_evidence_node,
                    relation="RESULTED_IN",
                )
                last_evidence_node = exec_node.node_id
                result.stages.append(SpineStageResult(
                    stage_name="execution",
                    status=SpineStageStatus.SUCCESS,
                    started_at=started,
                    completed_at=datetime.now(UTC),
                    output=execution_outcome.to_dict(),
                    evidence_node_id=exec_node.node_id,
                ))
            except GovernedExecutionError as exc:
                # V2.4: AUTHORIZATION node records the denial (failure cause)
                # even when execution is blocked — that's exactly the audit
                # signal operators need.
                last_v24_id = self._emit_v24(
                    v24_chain,
                    last_v24_id,
                    node_type="AUTHORIZATION",
                    input_payload={
                        "approval_node": last_v24_id or "",
                        "proposal_hash": best_proposal.proposal_hash if best_proposal else "",
                    },
                    output_payload={
                        "decision": "DENIED",
                        "reason": exc.reason,
                        "failures": list(exc.failures),
                    },
                    world_state_version=tracker.version,
                    actor="spine.governed_execution",
                )

                exec_node = evidence.add_evidence_step(
                    node_type="DECISION",
                    label=f"Execution BLOCKED: {exc.reason}",
                    payload={"blocked": True, "reason": exc.reason, "failures": exc.failures},
                    parent_node_id=last_evidence_node,
                    relation="RESULTED_IN",
                )
                last_evidence_node = exec_node.node_id
                result.stages.append(SpineStageResult(
                    stage_name="execution",
                    status=SpineStageStatus.FAILED,
                    started_at=started,
                    completed_at=datetime.now(UTC),
                    output={"blocked": True, "reason": exc.reason, "failures": exc.failures},
                    error=str(exc),
                    evidence_node_id=exec_node.node_id,
                ))
        else:
            result.stages.append(SpineStageResult(
                stage_name="execution",
                status=SpineStageStatus.SKIPPED,
                started_at=started,
                completed_at=datetime.now(UTC),
                output={"reason": "NOT_APPROVED" if not policy_result.get("approved") else "NO_PROPOSALS"},
            ))

        # ── Stage 17: Record outcome → World State event ───────────────────
        if execution_outcome is not None:
            outcome_dict = execution_outcome.to_dict()
            outcome_event = await tracker.submit_outcome_event(outcome_dict)
            outcome_event_id = outcome_event.event_id if outcome_event else f"evt_outcome_{execution_outcome.execution_id}"

            # V2.4: OUTCOME evidence node (carries outcome_hash + provenance).
            last_v24_id = self._emit_v24(
                v24_chain,
                last_v24_id,
                node_type="OUTCOME",
                input_payload={
                    "execution_node": last_v24_id or "",
                    "authorization_hash": execution_outcome.authorization_hash,
                },
                output_payload={
                    "event_id": outcome_event_id,
                    "outcome_hash": execution_outcome.outcome_hash,
                    "world_state_version_before": execution_outcome.world_state_version_before,
                    "world_state_version_after": execution_outcome.world_state_version_after,
                    "adapter_status": execution_outcome.adapter_result.get("status", ""),
                },
                world_state_version=execution_outcome.world_state_version_after,
                actor="spine.outcome_recorder",
            )
            # V2.4: WORLD_STATE_NEW evidence node (the new world state
            # version produced by the outcome — proves the chain caused
            # the world state update).
            last_v24_id = self._emit_v24(
                v24_chain,
                last_v24_id,
                node_type="WORLD_STATE_NEW",
                input_payload={
                    "outcome_node": last_v24_id or "",
                    "outcome_hash": execution_outcome.outcome_hash,
                },
                output_payload={
                    "world_state_version": tracker.version,
                    "world_state_hash": compute_world_state_hash(ws_id, tracker.version),
                    "event_id": outcome_event_id,
                },
                world_state_version=tracker.version,
                actor="spine.world_tracker",
            )

            outcome_node = evidence.add_evidence_step(
                node_type="OUTCOME",
                label=f"Outcome: {outcome_dict.get('adapter_result', {}).get('status', 'UNKNOWN')}",
                payload={"event_id": outcome_event_id, "outcome": outcome_dict},
                parent_node_id=last_evidence_node,
                relation="RESULTED_IN",
            )
            last_evidence_node = outcome_node.node_id
            result.outcome = {
                "event_id": outcome_event_id,
                "world_state_version": tracker.version,
                "execution_outcome": outcome_dict,
            }
            result.stages.append(SpineStageResult(
                stage_name="outcome_recorded",
                status=SpineStageStatus.SUCCESS,
                started_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
                output={"event_id": outcome_event_id, "outcome_hash": execution_outcome.outcome_hash},
                evidence_node_id=outcome_node.node_id,
            ))

        # ── V2.4: Evidence chain root replaces V2.3 chain hash.
        # V2.3 contract preserved: 64-char SHA-256 hex string. V2.4 adds
        # the serialized chain + verification + node count.
        result.evidence_chain_hash = v24_chain.chain_root
        result.evidence_chain_v24 = v24_chain.serialize()
        result.evidence_chain_node_count = len(v24_chain.nodes)
        v24_ok, v24_failures = v24_chain.verify()
        result.evidence_chain_verification = {
            "ok": v24_ok,
            "failures": v24_failures,
        }
        if not v24_ok:
            raise RuntimeError(
                f"V2.4 evidence chain failed self-verification: {v24_failures}"
            )

        # ── Finalize ───────────────────────────────────────────────────
        result.world_state_version = tracker.version
        result.evidence_root_id = source_node.node_id
        result.status = SpineStatus.COMPLETED
        return result

    # ── Internal helpers ────────────────────────────────────────────────

    @staticmethod
    def _profile_dataset(dataset: CanonicalDataset) -> dict[str, Any]:
        """Stage 1-2: schema discovery and data profiling."""
        profile: dict[str, Any] = {
            "workspace_id": dataset.workspace_id,
            "schema_version": dataset.schema_version,
            "entity_types": [et.value for et in dataset.entity_types()],
            "total_rows": dataset.total_rows(),
            "tables": {},
        }
        for et, table in dataset.tables.items():
            profile["tables"][et.value] = {
                "row_count": table.row_count(),
                "columns": list(table.column_types.keys()),
                "column_types": dict(table.column_types),
                "source_file": table.source_file,
            }
        return profile

    @staticmethod
    def _count_entities(dataset: CanonicalDataset) -> int:
        return dataset.total_rows()

    @staticmethod
    async def _write_world_events(
        dataset: CanonicalDataset, tracker: _WorldStateTracker
    ) -> int:
        """Stage 6: write a WorldEvent for each entity in each table."""
        count = 0
        for entity_type, table in dataset.tables.items():
            id_field = _detect_id_field_for_table(table)
            for row in table.rows:
                raw_id = row.get(id_field, "") if id_field else ""
                if not raw_id:
                    continue
                payload = {k: v for k, v in row.items() if not k.startswith("_")}
                await tracker.submit_entity_event(
                    entity_type=entity_type.value,
                    entity_id=str(raw_id),
                    event_type=f"{entity_type.value}_INGESTED",
                    payload=payload,
                )
                count += 1
        return count

    @staticmethod
    def _detect_signals(
        graph_engine: OperationalGraphEngine,
        analytics: GraphAnalyticsSummary,
        dataset: CanonicalDataset,
    ) -> list[dict[str, Any]]:
        """Stage 7: detect signals from graph analytics.

        Current V1 implementation derives signals from SPOFs and
        concentration — a real implementation will use OperationalSignalEngine
        with world state variables (Step 4).
        """
        signals: list[dict[str, Any]] = []

        # Supplier degradation signal from SPOFs
        for spof_id in analytics.high_dependency_spofs:
            node = graph_engine.nodes.get(spof_id)
            if node and node.node_type in ("SUPPLIER", "SELLER"):
                signals.append({
                    "signal_id": f"sig_{uuid7()[:8]}",
                    "entity_id": spof_id,
                    "entity_type": node.node_type,
                    "signal_type": "SUPPLIER_DEGRADATION",
                    "severity": "HIGH" if node.pagerank > (2.0 / len(graph_engine.nodes)) else "MEDIUM",
                    "confidence": min(1.0, node.pagerank * len(graph_engine.nodes)),
                    "metric_value": round(node.pagerank, 6),
                    "baseline_threshold": 1.0 / max(1, len(graph_engine.nodes)),
                    "deviation_pct": round(
                        (node.pagerank - 1.0 / max(1, len(graph_engine.nodes)))
                        / max(0.001, 1.0 / max(1, len(graph_engine.nodes)))
                        * 100,
                        1,
                    ),
                    "evidence": [f"pagerank={node.pagerank:.6f}", f"degree={len(graph_engine.adjacency.get(spof_id, set()))}"],
                })

        # Route congestion signal from critical routes
        for route_info in analytics.top_critical_routes[:3]:
            route_id = route_info["route_id"]
            signals.append({
                "signal_id": f"sig_{uuid7()[:8]}",
                "entity_id": route_id,
                "entity_type": "ROUTE",
                "signal_type": "ROUTE_CONGESTION",
                "severity": "HIGH" if route_info["active_orders"] > 10 else "MEDIUM",
                "confidence": 0.85,
                "metric_value": route_info["active_orders"],
                "baseline_threshold": 5,
                "deviation_pct": round((route_info["active_orders"] - 5) / max(1, 5) * 100, 1),
                "evidence": [f"active_orders={route_info['active_orders']}"],
            })

        # Concentration signal if gini is high
        if analytics.supplier_concentration_gini > 0.5:
            signals.append({
                "signal_id": f"sig_{uuid7()[:8]}",
                "entity_id": "WORKSPACE",
                "entity_type": "WORKSPACE",
                "signal_type": "SUPPLIER_CONCENTRATION",
                "severity": "HIGH" if analytics.supplier_concentration_gini > 0.7 else "MEDIUM",
                "confidence": 0.90,
                "metric_value": analytics.supplier_concentration_gini,
                "baseline_threshold": 0.4,
                "deviation_pct": round(
                    (analytics.supplier_concentration_gini - 0.4) / 0.4 * 100, 1
                ),
                "evidence": [f"gini={analytics.supplier_concentration_gini:.3f}"],
            })

        return signals

    @staticmethod
    def _compute_blast_radius(
        signals: list[dict[str, Any]],
        graph_engine: OperationalGraphEngine,
        dataset: CanonicalDataset,
    ) -> dict[str, Any]:
        """Stage 8: compute blast radius by traversing graph dependencies.

        Traverses from signal entities through graph edges to find affected
        orders, customers, and revenue.
        """
        if not signals:
            return {
                "root_cause_entity_id": "",
                "affected_orders_count": 0,
                "affected_customers_count": 0,
                "affected_entity_ids": [],
                "geographic_exposure_regions": [],
                "total_revenue_at_risk_usd": 0.0,
                "confidence": 0.0,
            }

        primary_signal = signals[0]
        entity_id = primary_signal["entity_id"]

        # BFS from signal entity through graph edges
        affected_entities: set[str] = set()
        affected_orders: set[str] = set()
        affected_customers: set[str] = set()
        affected_regions: set[str] = set()
        total_revenue = 0.0

        visited: set[str] = set()
        queue = [entity_id]
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            affected_entities.add(current)

            node = graph_engine.nodes.get(current)
            if node:
                if node.node_type == "ORDER":
                    affected_orders.add(current)
                    price = node.attributes.get("price", 0)
                    freight = node.attributes.get("freight_value", 0)
                    total_revenue += float(price or 0) + float(freight or 0)
                elif node.node_type == "CUSTOMER":
                    affected_customers.add(current)
                elif node.node_type == "LOCATION":
                    state = node.attributes.get("state", "")
                    if state:
                        affected_regions.add(str(state))

            # Traverse neighbors (limit depth to 3)
            if len(visited) < 500:
                for neighbor in graph_engine.adjacency.get(current, set()):
                    if neighbor not in visited:
                        queue.append(neighbor)

        return {
            "root_cause_entity_id": entity_id,
            "root_cause_type": primary_signal.get("signal_type", "UNKNOWN"),
            "affected_orders_count": len(affected_orders),
            "affected_customers_count": len(affected_customers),
            "affected_entity_ids": list(affected_entities)[:20],
            "geographic_exposure_regions": list(affected_regions),
            "total_revenue_at_risk_usd": round(total_revenue, 2),
            "confidence": primary_signal.get("confidence", 0.8),
        }

    @staticmethod
    def _select_best_proposal(proposals: list[AgentProposal]) -> AgentProposal:
        """Select the proposal with the highest confidence * (1 - risk)."""
        return max(
            proposals,
            key=lambda p: p.confidence * (1.0 - p.expected_risk_score),
        )

    @staticmethod
    def _emit_v24(
        chain: EvidenceChain,
        last_v24_id: str | None,
        *,
        node_type: str,
        input_payload: dict[str, Any],
        output_payload: dict[str, Any],
        world_state_version: int,
        actor: str = "spine",
        causation_id: str | None = None,
    ) -> str:
        """Append a V2.4 evidence node and return its event_id.

        For the chain root, ``last_v24_id`` is None — the parent is
        ``ROOT_PARENT_ID``. For subsequent nodes the parent and (by
        default) the causation_id are the previous node's event_id,
        encoding a strict single-thread lineage.
        """
        parent = last_v24_id if last_v24_id else ROOT_PARENT_ID
        cause = causation_id if causation_id is not None else (last_v24_id or "")
        node = chain.add(
            node_type=node_type,
            parent_id=parent,
            world_state_version=world_state_version,
            causation_id=cause,
            actor=actor,
            input_payload=input_payload,
            output_payload=output_payload,
        )
        return node.event_id


# ─────────────────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────────────────


def _detect_id_field_for_table(table: CanonicalTable) -> str | None:
    """Detect the primary ID column for a canonical table."""
    if not table.rows:
        return None
    sample = table.rows[0]
    # Prefer entity-specific ID columns
    et = table.entity_type.value.lower()
    preferred = f"{et}_id"
    if preferred in sample:
        return preferred
    # Fall back to any *_id column
    for col in sample:
        if col.endswith("_id") and not col.startswith("_"):
            return col
    return None
