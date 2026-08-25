"""Model Registry Module — Model lifecycle management."""

from app.modules.registry.models import (
    ModelComparisonRequest,
    ModelDeployment,
    ModelEvaluation,
    ModelExportRequest,
    ModelFramework,
    ModelImportRequest,
    ModelMetadata,
    ModelPromotionRequest,
    ModelRollbackRequest,
    ModelStage,
    ModelType,
    ModelVersion,
)
from app.modules.registry.registry import (
    ModelDeploymentRecord,
    ModelEvaluationRecord,
    ModelRecord,
    ModelRegistry,
)

__all__ = [
    # Models
    "ModelType",
    "ModelStage",
    "ModelFramework",
    "ModelMetadata",
    "ModelEvaluation",
    "ModelVersion",
    "ModelDeployment",
    "ModelComparisonRequest",
    "ModelPromotionRequest",
    "ModelRollbackRequest",
    "ModelExportRequest",
    "ModelImportRequest",
    # Registry
    "ModelRecord",
    "ModelEvaluationRecord",
    "ModelDeploymentRecord",
    "ModelRegistry",
]
