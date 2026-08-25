"""Experiment Tracking Models — Track ML experiments and their results."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.common.ids import uuid7


class ExperimentStatus(str, Enum):
    """Experiment lifecycle status."""

    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


class ExperimentType(str, Enum):
    """Types of experiments."""

    TRAINING = "training"
    HYPERPARAMETER_TUNING = "hyperparameter_tuning"
    ARCHITECTURE_SEARCH = "architecture_search"
    CALIBRATION = "calibration"
    EVALUATION = "evaluation"
    ABLATION = "ablation"
    BASELINE = "baseline"
    CUSTOM = "custom"


class Experiment(BaseModel):
    """ML Experiment record."""

    experiment_id: UUID = Field(default_factory=uuid7)
    name: str
    description: str = ""
    experiment_type: ExperimentType = ExperimentType.TRAINING

    # Configuration
    config: dict = {}
    hyperparameters: dict = {}
    tags: list[str] = []

    # Dataset
    dataset_id: str | None = None
    dataset_version: int | None = None
    train_split: float = 0.8
    val_split: float = 0.1
    test_split: float = 0.1

    # Model
    model_type: str | None = None
    model_config: dict = {}
    framework: str | None = None

    # Status
    status: str = "created"

    # Results
    metrics: dict[str, list[dict]] = {}  # metric_name -> [{"step": int, "value": float, "epoch": int}]
    best_metrics: dict[str, float] = {}
    best_epoch: int = 0

    # Artifacts
    artifacts: list[dict] = []  # [{"name": str, "path": str, "type": str, "size_bytes": int}]

    # Timing
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: float | None = None

    # Status
    status: str = "created"
    error: str | None = None

    # Metadata
    created_by: str | None = None
    tags: list[str] = []
    metadata: dict = {}
    git_commit: str | None = None
    git_branch: str | None = None


class ExperimentRun(BaseModel):
    """A single run of an experiment (for multi-run experiments like HPO)."""

    run_id: UUID = Field(default_factory=uuid7)
    experiment_id: UUID
    run_number: int
    run_name: str | None = None

    # Config
    hyperparameters: dict = {}
    seed: int | None = None

    # Status
    status: str = "pending"
    started_at: datetime | None = None
    completed_at: datetime | None = None

    # Results
    metrics: dict[str, float] = {}
    artifacts: list[dict] = []

    # Status
    status: str = "pending"
    error: str | None = None


class ExperimentArtifact(BaseModel):
    """An artifact produced by an experiment."""

    artifact_id: UUID = Field(default_factory=uuid7)
    experiment_id: UUID
    run_id: UUID | None = None

    name: str
    type: str  # "model", "checkpoint", "plot", "log", "dataset", "config", "report"
    path: str
    size_bytes: int
    checksum: str | None = None
    content_type: str | None = None

    # Metadata
    description: str = ""
    metadata: dict = {}

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    uploaded_by: str | None = None


class ExperimentComparison(BaseModel):
    """Comparison between experiments."""

    comparison_id: UUID = Field(default_factory=uuid7)
    experiment_ids: list[UUID]
    primary_metric: str
    higher_is_better: bool = True

    results: dict[str, dict] = {}  # exp_id -> metrics
    ranking: list[str] = []  # experiment_ids in ranked order
    best_experiment_id: UUID | None = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ExperimentComparisonRequest(BaseModel):
    """Request to compare experiments."""

    experiment_ids: list[UUID]
    primary_metric: str
    higher_is_better: bool = True


class ExperimentTemplate(BaseModel):
    """Template for creating similar experiments."""

    template_id: UUID = Field(default_factory=uuid7)
    name: str
    description: str = ""

    # Base config
    base_config: dict = {}
    base_hyperparameters: dict = {}
    base_model_config: dict = {}

    # Parameter space for HPO
    param_space: dict = {}

    # Tags
    tags: list[str] = []

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    created_by: str | None = None


class ExperimentComparisonResult(BaseModel):
    """Result of comparing experiments."""

    experiment_id: UUID
    experiment_name: str
    metrics: dict[str, float]
    rank: int
    is_best: bool = False


class ExperimentManager:
    """Manages experiments and their runs."""

    def __init__(self):
        self.experiments: dict[str, dict] = {}
        self.runs: dict[str, dict] = {}

    def create_experiment(
        self,
        name: str,
        description: str = "",
        experiment_type: str = "training",
        config: dict | None = None,
        hyperparameters: dict | None = None,
        tags: list[str] | None = None,
        created_by: str | None = None,
    ) -> str:
        """Create a new experiment."""
        exp = Experiment(
            name=name,
            description=description,
            experiment_type=ExperimentType(experiment_type),
            config=config or {},
            hyperparameters=hyperparameters or {},
            tags=tags or [],
            created_by=created_by,
        )
        self.experiments[str(exp.experiment_id)] = exp.model_dump()
        return str(exp.experiment_id)

    def start_experiment(self, experiment_id: UUID) -> bool:
        exp = self.experiments.get(str(experiment_id))
        if not exp:
            return False
        exp["status"] = "running"
        exp["started_at"] = datetime.now(UTC).isoformat()
        return True

    def log_metric(
        self,
        experiment_id: UUID,
        metric_name: str,
        value: float,
        step: int,
        epoch: int | None = None,
    ) -> bool:
        exp = self.experiments.get(str(experiment_id))
        if not exp:
            return False

        if metric_name not in exp["metrics"]:
            exp["metrics"][metric_name] = []
        exp["metrics"][metric_name].append({
            "step": step,
            "value": value,
            "epoch": epoch,
            "timestamp": datetime.now(UTC).isoformat(),
        })

        # Update best metrics
        if metric_name not in exp["best_metrics"] or value > exp["best_metrics"][metric_name]:
            exp["best_metrics"][metric_name] = value
        return True

    def log_artifact(
        self,
        experiment_id: UUID,
        name: str,
        artifact_type: str,
        path: str,
        size_bytes: int,
        checksum: str | None = None,
        content_type: str | None = None,
        metadata: dict | None = None,
    ) -> bool:
        exp = self.experiments.get(str(experiment_id))
        if not exp:
            return False

        exp["artifacts"].append({
            "name": name,
            "type": artifact_type,
            "path": path,
            "size_bytes": size_bytes,
            "checksum": checksum,
            "content_type": content_type,
            "metadata": metadata or {},
            "uploaded_at": datetime.now(UTC).isoformat(),
        })
        return True

    def complete_experiment(self, experiment_id: UUID, status: str = "completed", error: str | None = None) -> bool:
        exp = self.experiments.get(str(experiment_id))
        if not exp:
            return False
        exp["status"] = status
        exp["completed_at"] = datetime.now(UTC).isoformat()
        if exp.get("started_at"):
            start = datetime.fromisoformat(exp["started_at"])
            exp["duration_seconds"] = (datetime.now(UTC) - start).total_seconds()
        if error:
            exp["error"] = error
        return True

    def get_experiment(self, experiment_id: UUID) -> dict | None:
        return self.experiments.get(str(experiment_id))

    def list_experiments(
        self,
        status: str | None = None,
        experiment_type: str | None = None,
        tags: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        experiments = list(self.experiments.values())

        if status:
            experiments = [e for e in experiments if e["status"] == status]
        if experiment_type:
            experiments = [e for e in experiments if e["experiment_type"] == experiment_type]
        if tags:
            experiments = [e for e in experiments if any(t in e["tags"] for t in tags)]

        experiments.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return experiments[offset:offset + limit]

    def compare_experiments(
        self,
        experiment_ids: list[UUID],
        primary_metric: str,
        higher_is_better: bool = True,
    ) -> dict:
        """Compare multiple experiments on a primary metric."""
        experiments = []
        for exp_id in experiment_ids:
            exp = self.experiments.get(str(exp_id))
            if not exp:
                continue
            metric_val = exp["best_metrics"].get(primary_metric)
            experiments.append({
                "experiment_id": str(exp["experiment_id"]),
                "name": exp["name"],
                "metric_value": metric_val,
                "best_metrics": exp["best_metrics"],
            })

        if not experiments:
            return {"error": "No valid experiments found"}

        # Rank
        reverse = higher_is_better
        experiments.sort(key=lambda x: x["metric_value"] or -float('inf'), reverse=reverse)

        for i, exp in enumerate(experiments):
            exp["rank"] = i + 1
            exp["is_best"] = (i == 0)

        best_id = experiments[0]["experiment_id"] if experiments else None

        return {
            "primary_metric": primary_metric,
            "higher_is_better": higher_is_better,
            "experiments": experiments,
            "best_experiment_id": best_id,
            "ranking": [e["experiment_id"] for e in experiments],
        }


class ExperimentRegistry:
    """Registry for experiment metadata persistence."""

    def __init__(self, db):
        self.db = db

    async def save_experiment(self, experiment: dict) -> None:
        """Save experiment to database."""
        pass  # Implementation would use ORM

    async def get_experiment(self, experiment_id: UUID) -> dict | None:
        pass

    async def list_experiments(self, filters: dict, limit: int = 50) -> list[dict]:
        return []


class MLflowIntegration:
    """Integration with MLflow for experiment tracking."""

    def __init__(self, tracking_uri: str = "http://localhost:5000"):
        self.tracking_uri = tracking_uri
        self.client = None

    def connect(self):
        import mlflow
        mlflow.set_tracking_uri(self.tracking_uri)
        self.client = mlflow.tracking.MlflowClient()

    def create_experiment(self, name: str) -> str:
        import mlflow
        return mlflow.create_experiment(name)

    def start_run(self, experiment_id: str, run_name: str | None = None):
        import mlflow
        return mlflow.start_run(experiment_id=experiment_id, run_name=run_name)

    def log_param(self, key: str, value: Any):
        import mlflow
        mlflow.log_param(key, value)

    def log_metric(self, key: str, value: float, step: int | None = None):
        import mlflow
        mlflow.log_metric(key, value, step=step)

    def log_artifact(self, path: str, artifact_path: str | None = None):
        import mlflow
        mlflow.log_artifact(path, artifact_path)

    def end_run(self, status: str = "FINISHED"):
        import mlflow
        mlflow.end_run(status=status)


__all__ = [
    "ExperimentStatus",
    "ExperimentType",
    "Experiment",
    "ExperimentRun",
    "ExperimentArtifact",
    "ExperimentComparison",
    "ExperimentComparisonRequest",
    "ExperimentTemplate",
    "ExperimentComparisonResult",
    "ExperimentManager",
    "ExperimentRegistry",
    "MLflowIntegration",
]
