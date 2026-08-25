"""Operational Graph — Phase 3 Program A + B + C + D + E + F + G + H.

The Evidence → Graph Compiler transforms trusted evidence claims into a
versioned, provenance-bearing operational graph. Programs C, D, E, F, G, H consume
this graph exclusively through the service layer.

Program A (Phase 3, completed):
    compiler     — compile_approved_claims → graph write events
    snapshots    — hash-chained immutable snapshot sealing
    integrity    — provenance + orphan + consistency checks

Program B (Phase 3, completed):
    repository   — storage abstraction (Protocol + SqlGraphRepository)
    reader       — EvidenceReader interface (decouples compiler from data source)
    traversal    — BFS, DFS, shortest path, reachability (pure functions)
    temporal     — snapshot replay + diff (historical graph state)
    validation   — comprehensive CI gate
    cache        — graph cache (NoOp / Redis implementations)
    service      — GraphService orchestrator (Programs C–H depend on this)

Program C (Phase 3, completed):
    features     — pure deterministic feature functions over InMemoryGraph
    feature_models — NodeFeatures, WorkspaceFeatures, FeatureSnapshot DTOs
    feature_engine — FeatureEngine orchestrator (consumes only GraphService)

Program D (Phase 3, completed):
    signal_models — SignalInstance, SignalSnapshot, SignalDefinition DTOs
    signal_registry — SIGNAL_REGISTRY with 5 signal definitions
    detectors — pure functions: FeatureSnapshot → list[SignalInstance]
    signal_engine — SignalEngine orchestrator (consumes only FeatureEngine)

Program E (Phase 3, completed):
    propagation_models — PropagationSnapshot, PropagationStep, ImpactSummary DTOs
    propagation_rules — propagation policy (attenuation, severity, confidence)
    propagation_service — PropagationService orchestrator

Program F (Phase 3, completed):
    scenario_models — ScenarioSnapshot, ScenarioDefinition, ScenarioImpact DTOs
    scenario_rules — scenario execution rules
    scenario_engine — ScenarioEngine for what-if simulation
    scenario_service — ScenarioService orchestrator

Program G (Phase 3, completed):
    recommendation_models — RecommendationSnapshot, RankedRecommendation DTOs
    recommendation_rules — recommendation generation rules
    recommendation_engine — RecommendationEngine
    recommendation_service — RecommendationService orchestrator

Program H (Phase 3, completed):
    decision_models — DecisionRecord, DecisionOutcome, DecisionLesson DTOs
    decision_taxonomy — closed vocabulary of decision types
    decision_repository — append-only persistence layer
    decision_service — DecisionService orchestrator
"""

from app.modules.graph.cache import GraphCache, NoOpCache, RedisCache, make_cache_key
from app.modules.graph.compiler import compile_evidence_to_graph

# Program H — Decision Memory
from app.modules.graph.decision_models import (
    DecisionExport,
    DecisionLesson,
    DecisionOutcome,
    DecisionRecord,
    DecisionRequest,
    DecisionSnapshot,
    DecisionStatus,
    DecisionType,
    LessonCategory,
    OutcomeStatus,
)
from app.modules.graph.decision_service import (
    DecisionService,
    DecisionServiceResult,
    LessonServiceResult,
    OutcomeServiceResult,
)
from app.modules.graph.detectors import (
    DETECTORS,
    detect_bottleneck_signals,
    detect_concentration_signals,
    detect_criticality_signals,
    detect_isolation_signals,
    detect_spof_signals,
    get_detector,
)
from app.modules.graph.feature_engine import (
    FeatureComputationResult,
    FeatureEngine,
)
from app.modules.graph.feature_models import (
    FeatureSnapshot,
    NodeFeatures,
    WorkspaceFeatures,
)
from app.modules.graph.features import (
    betweenness,
    concentration_risk,
    connected_components,
    criticality,
    degree_centrality,
    downstream_depth,
    downstream_reach_count,
    in_degree,
    out_degree,
    p95,
    redundancy,
    single_point_of_failure,
    total_degree,
    upstream_depth,
    upstream_reach_count,
)
from app.modules.graph.integrity import run_integrity_checks
from app.modules.graph.reader import (
    EvidenceReader,
    ObjectStorageEvidenceReader,
    ProfilerEvidenceReader,
)
from app.modules.graph.repository import (
    EdgeDTO,
    GraphRepository,
    NodeDTO,
    SnapshotDTO,
    SqlGraphRepository,
    WriteEventDTO,
)
from app.modules.graph.service import GraphService, WorkspaceGraph
from app.modules.graph.signal_engine import (
    SignalComputationResult,
    SignalEngine,
)
from app.modules.graph.signal_models import (
    SignalCategory,
    SignalDefinition,
    SignalInstance,
    SignalSeverity,
    SignalSnapshot,
)
from app.modules.graph.signal_registry import (
    SIGNAL_REGISTRY,
    compute_signal_severity,
    format_explanation,
    get_signal_definition,
    validate_signal_evidence,
)
from app.modules.graph.snapshots import (
    get_latest_snapshot,
    get_snapshot,
    list_snapshots,
    seal_snapshot,
    verify_snapshot_chain,
)
from app.modules.graph.temporal import (
    diff_snapshots,
    load_graph_at_snapshot,
    summarize_diff,
)
from app.modules.graph.traversal import (
    InMemoryGraph,
    bfs,
    build_in_memory_graph,
    dfs,
    find_paths,
    neighbors,
    reachable_from,
    reachable_to,
    shortest_path,
)
from app.modules.graph.validation import (
    ValidationReport,
    validate_workspace_graph,
)

__all__ = [
    # Program A
    "compile_evidence_to_graph",
    "seal_snapshot",
    "get_latest_snapshot",
    "get_snapshot",
    "list_snapshots",
    "verify_snapshot_chain",
    "run_integrity_checks",
    # Program B
    "GraphService",
    "WorkspaceGraph",
    "GraphRepository",
    "SqlGraphRepository",
    "NodeDTO",
    "EdgeDTO",
    "SnapshotDTO",
    "WriteEventDTO",
    "InMemoryGraph",
    "build_in_memory_graph",
    "neighbors",
    "bfs",
    "dfs",
    "shortest_path",
    "reachable_from",
    "reachable_to",
    "find_paths",
    "load_graph_at_snapshot",
    "diff_snapshots",
    "summarize_diff",
    "validate_workspace_graph",
    "ValidationReport",
    "GraphCache",
    "NoOpCache",
    "RedisCache",
    "make_cache_key",
    "EvidenceReader",
    "ProfilerEvidenceReader",
    "ObjectStorageEvidenceReader",
    # Program C
    "in_degree",
    "out_degree",
    "total_degree",
    "degree_centrality",
    "downstream_reach_count",
    "upstream_reach_count",
    "downstream_depth",
    "upstream_depth",
    "criticality",
    "single_point_of_failure",
    "redundancy",
    "concentration_risk",
    "betweenness",
    "connected_components",
    "p95",
    "NodeFeatures",
    "WorkspaceFeatures",
    "FeatureSnapshot",
    "FeatureEngine",
    "FeatureComputationResult",
    # Program D
    "SignalSeverity",
    "SignalCategory",
    "SignalDefinition",
    "SignalInstance",
    "SignalSnapshot",
    "SIGNAL_REGISTRY",
    "get_signal_definition",
    "validate_signal_evidence",
    "compute_signal_severity",
    "format_explanation",
    "detect_spof_signals",
    "detect_concentration_signals",
    "detect_bottleneck_signals",
    "detect_isolation_signals",
    "detect_criticality_signals",
    "get_detector",
    "DETECTORS",
    "SignalEngine",
    "SignalComputationResult",
    # Program H — Decision Memory
    "DecisionType",
    "DecisionStatus",
    "OutcomeStatus",
    "LessonCategory",
    "DecisionRequest",
    "DecisionRecord",
    "DecisionOutcome",
    "DecisionLesson",
    "DecisionSnapshot",
    "DecisionExport",
    "DecisionService",
    "DecisionServiceResult",
    "OutcomeServiceResult",
    "LessonServiceResult",
]
