"""Intelligence Plane — Cortex Intelligence Foundation & Production Runtime.

Provides:
- Intelligence Gateway: Single AI boundary with deterministic fallbacks and shadow evaluation
- Model Registry: Complete model lifecycle (Registration -> Validation -> Calibration -> Deployment -> Shadow -> Promotion -> Rollback)
- Inference Router: Task-to-model routing and shadow model matching
- Baselines Registry: Deterministic fallbacks that guarantee 100% availability
"""

from app.modules.intelligence.baselines_registry import BaselineRegistry
from app.modules.intelligence.gateway import IntelligenceGateway
from app.modules.intelligence.inference_router import InferenceRouter
from app.modules.intelligence.model_registry import (
    DeploymentStatus,
    ModelDeployment,
    ModelHealth,
    ModelRegistration,
    ModelRegistry,
    ModelStatus,
    ModelType,
)
from app.modules.intelligence.types import (
    InferenceStatus,
    IntelligenceRequest,
    IntelligenceResponse,
    IntelligenceTask,
)

# Optional research baselines (require numpy/scikit-learn)
try:
    from app.modules.intelligence.baselines import (
        BaselineMetrics,
        BaselineModel,
        CalibrationBaseline,
        RankingBaseline,
        SupplierRiskSimilarityBaseline,
    )
    from app.modules.intelligence.gnn_embeddings import (
        GNNEmbeddings,
        GNNGraphData,
        GNNModel,
        GNNResearchResult,
        GraphSAGEBaseline,
        Node2VecBaseline,
        build_gnn_graph_data,
    )
    from app.modules.intelligence.shadow_dispatcher import (
        ShadowComparison,
        compare_outputs,
        dispatch_shadow_models,
        extract_brief_features,
        run_shadow_inference,
    )
except ImportError:
    pass

__all__ = [
    # Gateway & Production Runtime
    "IntelligenceGateway",
    "IntelligenceRequest",
    "IntelligenceResponse",
    "IntelligenceTask",
    "InferenceStatus",
    "ModelRegistry",
    "ModelRegistration",
    "ModelDeployment",
    "ModelType",
    "ModelStatus",
    "DeploymentStatus",
    "ModelHealth",
    "InferenceRouter",
    "BaselineRegistry",
]
