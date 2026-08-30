"""Model Registry Models — Model metadata and lifecycle management."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.common.ids import uuid7


class ModelType(StrEnum):
    """Types of ML models."""

    GNN = "gnn"
    XGBOOST = "xgboost"
    LIGHTGBM = "lightgbm"
    CATBOOST = "catboost"
    RANDOM_FOREST = "random_forest"
    LOGISTIC_REGRESSION = "logistic_regression"
    LINEAR_REGRESSION = "linear_regression"
    NEURAL_NETWORK = "neural_network"
    TRANSFORMER = "transformer"
    RL_POLICY = "rl_policy"
    ENSEMBLE = "ensemble"
    CUSTOM = "custom"


class ModelStage(StrEnum):
    """Model lifecycle stage."""

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    ARCHIVED = "archived"
    FAILED = "failed"


class ModelFramework(StrEnum):
    """ML frameworks."""

    PYTORCH = "pytorch"
    TENSORFLOW = "tensorflow"
    JAX = "jax"
    SKLEARN = "sklearn"
    XGBOOST = "xgboost"
    LIGHTGBM = "lightgbm"
    CATBOOST = "catboost"
    ONNX = "onnx"
    CUSTOM = "custom"


class ModelMetadata(BaseModel):
    """Complete model metadata."""

    model_id: UUID = Field(default_factory=uuid7)
    name: str
    model_type: ModelType
    framework: ModelFramework
    version: str = "1.0.0"
    stage: ModelStage = ModelStage.DEVELOPMENT

    # Description
    description: str = ""
    tags: list[str] = []

    # Training
    training_data_version: str = ""
    training_samples: int = 0
    hyperparameters: dict[str, Any] = {}
    training_duration_seconds: float | None = None
    training_hardware: str | None = None

    # Artifacts
    artifact_path: str | None = None
    artifact_size_bytes: int = 0
    artifact_checksum: str | None = None
    parent_model_id: UUID | None = None

    # Performance
    metrics: dict[str, float] = {}
    evaluation_dataset: str | None = None
    evaluation_timestamp: datetime | None = None

    # Deployment
    deployment_config: dict[str, Any] = {}
    deployment_endpoint: str | None = None
    deployment_status: str = "not_deployed"

    # Monitoring
    drift_threshold: float = 0.1
    performance_threshold: float = 0.9
    last_monitoring_check: datetime | None = None

    # Metadata
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    created_by: str | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None

    # Lineage
    parent_model_id: UUID | None = None
    git_commit: str | None = None
    git_branch: str | None = None
    training_config_hash: str | None = None


class ModelEvaluation(BaseModel):
    """Model evaluation results."""

    evaluation_id: UUID = Field(default_factory=uuid7)
    model_id: UUID
    model_version: str
    evaluation_name: str
    dataset_name: str
    dataset_version: str

    # Metrics
    metrics: dict[str, float] = {}
    confusion_matrix: list[list[int]] | None = None

    # Detailed results
    per_class_metrics: dict[str, dict[str, float]] = {}
    per_slice_metrics: dict[str, dict[str, float]] = {}

    # Metadata
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    evaluated_by: str | None = None
    metadata: dict = {}


class ModelVersion(BaseModel):
    """Model version information."""

    model_id: UUID
    version: str
    stage: ModelStage
    created_at: datetime
    created_by: str | None
    metrics: dict[str, float] = {}
    artifact_path: str | None = None
    git_commit: str | None = None
    is_latest: bool = False
    is_production: bool = False


class ModelDeployment(BaseModel):
    """Model deployment record."""

    deployment_id: UUID = Field(default_factory=uuid7)
    model_id: UUID
    model_version: str
    environment: str  # "staging", "production"
    endpoint: str
    status: str = "pending"  # pending, deploying, active, failed, rolled_back
    config: dict = {}
    deployed_at: datetime | None = None
    rolled_back_at: datetime | None = None
    rollback_reason: str | None = None
    deployed_by: str | None = None


class ModelComparisonRequest(BaseModel):
    """Request to compare models."""

    model_a_id: UUID
    model_a_version: str
    model_b_id: UUID
    model_b_version: str
    dataset_id: str
    dataset_version: int
    metrics: list[str] = []


class ModelPromotionRequest(BaseModel):
    """Request to promote a model to a new stage."""

    model_id: UUID
    version: str
    target_stage: ModelStage
    approved_by: str
    reason: str = ""


class ModelRollbackRequest(BaseModel):
    """Request to rollback a deployment."""

    deployment_id: UUID
    reason: str
    rolled_back_by: str


class ModelExportRequest(BaseModel):
    """Request to export a model."""

    model_id: UUID
    version: str
    format: str = "onnx"  # onnx, torchscript, tensorflow_saved_model
    include_preprocessing: bool = True
    target_platform: str | None = None


class ModelImportRequest(BaseModel):
    """Request to import a model."""

    name: str
    model_type: str  # ModelType
    framework: str  # ModelFramework
    artifact_path: str
    version: str = "1.0.0"
    description: str = ""
    tags: list[str] = []


__all__ = [
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
]
