"""Nexus v1.0 P0 Migration Package.

Production-grade stateful services replacing v0.7 in-memory singletons.

ARCHITECTURAL INVARIANTS:
  * ONE AUTHORITATIVE WORLD in PostgreSQL.
  * ONE TRACE (append-only event log + decisions).
  * ONE GOVERNED DECISION LOOP (authoritative transitions, no race).
  * ONE EVIDENCE CHAIN (no LLM-manufactured authority).

Write path:   API Request → AuthZ → Service → PostgreSQL (SELECT FOR UPDATE)
              → append transition/outbox → commit → publish to Redis
              → invalidate local projection caches.
Read path:    API Request → AuthZ → Service → per-process LRU projection
              (30s TTL, invalidated on write or peer-broadcast).

Tables are classified:
  AUTHORITATIVE   : ground truth in PG; must survive process restart
  PROJECTION      : derived from AUTHORITATIVE; fully rebuildable
  CACHE           : perf optimization; can be dropped at any time
  TEMPORARY       : ephemeral (ephemeral sessions, temp work)
"""

from app.modules.nexus_spine.p0_migration.authoritative_decisions import (
    AuthoritativeDecisionService,
    InvalidTransitionError,
    StaleWorldStateError,
    get_authoritative_decision_service,
)
from app.modules.nexus_spine.p0_migration.authoritative_inference import (
    AuthoritativeInferenceEngine,
    DemandPredictionOutput,
    GNNRiskScorer,
    ProbabilisticDemandForecaster,
    RiskPredictionOutput,
    compute_feature_hash,
    get_authoritative_inference_engine,
)
from app.modules.nexus_spine.p0_migration.authoritative_memory import (
    AuthoritativeDecisionMemory,
    get_authoritative_decision_memory,
)
from app.modules.nexus_spine.p0_migration.authoritative_models import (
    ALLOWED_MODEL_TRANSITIONS,
    AuthoritativeModelRegistry,
    DuplicateModelVersionError,
    InvalidModelTransitionError,
    ModelGovernanceError,
    ModelLifecycleStatus,
    ModelNotFoundError,
    ModelRollbackError,
    PromotionGateConfig,
    PromotionGateFailedError,
    PromotionGateResult,
    get_authoritative_model_registry,
    validate_promotion_gates,
)
from app.modules.nexus_spine.p0_migration.authoritative_truth import (
    AuthoritativeTruthLoop,
    get_authoritative_truth_loop,
)
from app.modules.nexus_spine.p0_migration.authz import (
    SYSTEM_PRINCIPAL,
    AuthorizationService,
    NexusRole,
    PermissionDenied,
    Principal,
    get_authz,
)
from app.modules.nexus_spine.p0_migration.table_classification import (
    TABLE_CLASSIFICATION,
    DataClassification,
    classify,
)
from app.modules.nexus_spine.p0_migration.vanessa_pipeline import (
    DeterministicLLMAdapter,
    IntentType,
    VanessaPipeline,
    VanessaResponse,
    get_vanessa_pipeline,
)

__all__ = [
    # Core services
    "AuthoritativeDecisionService",
    "AuthoritativeDecisionMemory",
    "AuthoritativeTruthLoop",
    "AuthoritativeModelRegistry",
    "AuthoritativeInferenceEngine",
    "InvalidTransitionError",
    "StaleWorldStateError",
    # Model governance & inference
    "ModelLifecycleStatus",
    "ALLOWED_MODEL_TRANSITIONS",
    "PromotionGateConfig",
    "PromotionGateResult",
    "ModelGovernanceError",
    "ModelNotFoundError",
    "DuplicateModelVersionError",
    "InvalidModelTransitionError",
    "PromotionGateFailedError",
    "ModelRollbackError",
    "validate_promotion_gates",
    "ProbabilisticDemandForecaster",
    "GNNRiskScorer",
    "DemandPredictionOutput",
    "RiskPredictionOutput",
    "compute_feature_hash",
    # AuthZ
    "AuthorizationService",
    "NexusRole",
    "PermissionDenied",
    "Principal",
    "SYSTEM_PRINCIPAL",
    "get_authz",
    # Vanessa pipeline
    "VanessaPipeline",
    "VanessaResponse",
    "IntentType",
    "DeterministicLLMAdapter",
    "get_vanessa_pipeline",
    # Table classification
    "DataClassification",
    "TABLE_CLASSIFICATION",
    "classify",
    # Singleton factories
    "get_authoritative_decision_service",
    "get_authoritative_decision_memory",
    "get_authoritative_truth_loop",
    "get_authoritative_model_registry",
    "get_authoritative_inference_engine",
]
