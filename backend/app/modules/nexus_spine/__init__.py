"""Nexus Spine — Supply Chain Decision Intelligence & Operations Platform.

Cortex Nexus is the operational decision system that sits on top of the
Cortex data foundation. It connects:

    Ontology (supply-chain entities)
        + World Model (live operational truth)
        + Decision Memory (organizational history)
        + Demand Engine (probabilistic forecasts + truth-loop calibration)
        + Digital Twin (counterfactual scenarios)
        + Vanessa (grounded AI interface with tool registry)

This module is the spine that stitches the full pipeline together:

    USER DATA → INGESTION → (schema discovery / data quality / entity
    resolution / provenance) → WORLD STATE → OPERATIONAL GRAPH + FEATURES
    → SIGNALS / RCA / BLAST RADIUS → AUTHORIZED CONTEXT → SUPERVISOR
    (dynamic agent set) → PROPOSALS → DIGITAL TWIN → COUNTERFACTUALS →
    POLICY GATE → HUMAN APPROVAL → EXECUTION → OUTCOME → WORLD STATE EVENT
    → EVIDENCE DAG

The Nexus ontology (Phase A) extends this with a closed vocabulary of
entity and relationship kinds — every entity in the world model carries
identity, tenant/workspace isolation, source, timestamp, confidence,
current state, historical state, relationships, permissions, and
provenance. Demand Intelligence (Phase B) adds a probabilistic forecast
engine + truth-loop calibration. Decision Memory (Phase E) records every
completed decision with full context. Vanessa (Phase F) provides the
grounded natural-language interface backed by a deterministic tool
registry.
"""

from app.modules.nexus_spine.canonical_schema import (
    CanonicalDataset,
    CanonicalEntity,
    CanonicalTable,
    EntityType,
    OlistAdapter,
    SchemaMapping,
)
from app.modules.nexus_spine.demand import (
    CalibrationBucket,
    DemandDriver,
    DemandEngine,
    ForecastActual,
    ForecastEvaluation,
    HistoricalDemandPoint,
    ProbabilisticForecast,
    TruthLoop,
    get_demand_engine,
    get_truth_loop,
    reset_demand_engine,
    reset_truth_loop,
)
from app.modules.nexus_spine.memory import (
    AnalogousDecision,
    DecisionMemory,
    DecisionRecord,
    get_decision_memory,
    reset_decision_memory,
)
from app.modules.nexus_spine.models import (
    AgentProposal,
    SpineResult,
    SpineStageResult,
    SwarmTask,
    SwarmTaskContext,
)
from app.modules.nexus_spine.ontology import (
    ENTITY_KIND_TO_DOMAIN,
    ComponentEntity,
    DecisionEntity,
    DisruptionEntity,
    Entity,
    EntityDomain,
    EntityKind,
    EntityPage,
    EntityQuery,
    ForecastEntity,
    InventoryPositionEntity,
    PermissionGrant,
    PlantEntity,
    ProductEntity,
    ProvenanceRecord,
    PurchaseOrderEntity,
    RelationshipEdge,
    RelationshipKind,
    SalesOrderEntity,
    SignalEntity,
    StateSnapshot,
    SupplierEntity,
    WarehouseEntity,
    WorldModelRepository,
    canonical_state_hash,
    domain_of,
    get_world_model,
    reset_world_model,
)
from app.modules.nexus_spine.pipeline_stages import (
    execution_gate_fn,
    policy_gate_fn,
    real_supervisor_fn,
    twin_simulation_fn,
)
from app.modules.nexus_spine.risk import (
    RiskAssessment,
    RiskEngine,
    RootCauseCandidate,
    Severity,
    get_risk_engine,
    reset_risk_engine,
)
from app.modules.nexus_spine.scenarios import (
    DigitalTwin,
    KPIMetrics,
    MutationKind,
    ScenarioDefinition,
    ScenarioMutation,
    ScenarioResult,
    ScenarioStudio,
    get_scenario_studio,
    reset_scenario_studio,
)
from app.modules.nexus_spine.governance import (
    ALLOWED_TRANSITIONS,
    TERMINAL_END_STATES,
    TERMINAL_STATES,
    DecisionLifecycle,
    DecisionLifecycleManager,
    DecisionPhase,
    DecisionTransition,
    get_decision_lifecycle_manager,
    reset_decision_lifecycle_manager,
    validate_world_state_consistent,
)
from app.modules.nexus_spine.spine_orchestrator import RealDataSpine
from app.modules.nexus_spine.vanessa import (
    Intent,
    IntentClassification,
    Tool,
    ToolCall,
    ToolPermission,
    ToolRegistry,
    ToolResult,
    VanessaAnswer,
    VanessaOrchestrator,
    VanessaQuery,
    build_default_registry,
    classify_intent,
    get_tool_registry,
    get_vanessa,
    render_answer,
    reset_tool_registry,
    reset_vanessa,
)

__all__ = [
    "ALLOWED_TRANSITIONS",
    "TERMINAL_END_STATES",
    "TERMINAL_STATES",
    "ENTITY_KIND_TO_DOMAIN",
    "AgentProposal",
    "AnalogousDecision",
    "CalibrationBucket",
    "CanonicalDataset",
    "CanonicalEntity",
    "CanonicalTable",
    "ComponentEntity",
    "DecisionLifecycle",
    "DecisionLifecycleManager",
    "DecisionMemory",
    "DecisionRecord",
    "DecisionEntity",
    "DemandDriver",
    "DemandEngine",
    "DigitalTwin",
    "DisruptionEntity",
    "Entity",
    "EntityDomain",
    "EntityKind",
    "EntityPage",
    "EntityQuery",
    "EntityType",
    "ForecastActual",
    "ForecastEntity",
    "ForecastEvaluation",
    "HistoricalDemandPoint",
    "Intent",
    "IntentClassification",
    "InventoryPositionEntity",
    "KPIMetrics",
    "MutationKind",
    "OlistAdapter",
    "PermissionGrant",
    "PlantEntity",
    "ProbabilisticForecast",
    "ProductEntity",
    "ProvenanceRecord",
    "PurchaseOrderEntity",
    "RealDataSpine",
    "RelationshipEdge",
    "RelationshipKind",
    "RiskAssessment",
    "RiskEngine",
    "RootCauseCandidate",
    "SalesOrderEntity",
    "ScenarioDefinition",
    "ScenarioMutation",
    "ScenarioResult",
    "ScenarioStudio",
    "SchemaMapping",
    "Severity",
    "SignalEntity",
    "SpineResult",
    "SpineStageResult",
    "StateSnapshot",
    "SupplierEntity",
    "SwarmTask",
    "SwarmTaskContext",
    "Tool",
    "ToolCall",
    "ToolPermission",
    "ToolRegistry",
    "ToolResult",
    "TruthLoop",
    "VanessaAnswer",
    "VanessaOrchestrator",
    "VanessaQuery",
    "WarehouseEntity",
    "WorldModelRepository",
    "build_default_registry",
    "canonical_state_hash",
    "classify_intent",
    "domain_of",
    "execution_gate_fn",
    "get_demand_engine",
    "get_decision_lifecycle_manager",
    "get_decision_memory",
    "get_risk_engine",
    "get_scenario_studio",
    "get_tool_registry",
    "get_truth_loop",
    "get_vanessa",
    "get_world_model",
    "policy_gate_fn",
    "real_supervisor_fn",
    "render_answer",
    "reset_demand_engine",
    "reset_decision_lifecycle_manager",
    "reset_decision_memory",
    "reset_risk_engine",
    "reset_scenario_studio",
    "reset_tool_registry",
    "reset_truth_loop",
    "reset_vanessa",
    "reset_world_model",
    "twin_simulation_fn",
    "validate_world_state_consistent",
]
