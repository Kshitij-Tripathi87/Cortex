"""Nexus Spine — Real Data Vertical Slice Orchestrator.

Provides the canonical schema layer and the end-to-end spine that drives:

    USER DATA → INGESTION → (schema discovery / data quality / entity
    resolution / provenance) → WORLD STATE → OPERATIONAL GRAPH + FEATURES
    → SIGNALS / RCA / BLAST RADIUS → AUTHORIZED CONTEXT → SUPERVISOR
    (dynamic agent set) → PROPOSALS → DIGITAL TWIN → COUNTERFACTUALS →
    POLICY GATE → HUMAN APPROVAL → EXECUTION → OUTCOME → WORLD STATE EVENT
    → EVIDENCE DAG

This module is the only place that knows how to stitch the full pipeline
together. Individual domain modules (graph, world, twin, agents, execution)
remain focused on their own contracts.
"""

from app.modules.nexus_spine.canonical_schema import (
    CanonicalDataset,
    CanonicalEntity,
    CanonicalTable,
    EntityType,
    OlistAdapter,
    SchemaMapping,
)
from app.modules.nexus_spine.models import (
    AgentProposal,
    SpineResult,
    SpineStageResult,
    SwarmTask,
    SwarmTaskContext,
)
from app.modules.nexus_spine.pipeline_stages import (
    execution_gate_fn,
    policy_gate_fn,
    real_supervisor_fn,
    twin_simulation_fn,
)
from app.modules.nexus_spine.spine_orchestrator import RealDataSpine

__all__ = [
    "AgentProposal",
    "CanonicalDataset",
    "CanonicalEntity",
    "CanonicalTable",
    "EntityType",
    "OlistAdapter",
    "RealDataSpine",
    "SchemaMapping",
    "SpineResult",
    "SpineStageResult",
    "SwarmTask",
    "SwarmTaskContext",
    "execution_gate_fn",
    "policy_gate_fn",
    "real_supervisor_fn",
    "twin_simulation_fn",
]
