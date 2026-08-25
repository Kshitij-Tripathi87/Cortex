"""Training Platform Models — Training pipeline and data management."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field

from app.common.ids import uuid7


class TrainingStatus(str, Enum):
    """Training job status."""

    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TrainingFramework(str, Enum):
    """Training frameworks."""

    PYTORCH = "pytorch"
    TENSORFLOW = "tensorflow"
    JAX = "jax"
    SKLEARN = "sklearn"
    XGBOOST = "xgboost"
    LIGHTGBM = "lightgbm"
    CATBOOST = "catboost"
    CUSTOM = "custom"


class OptimizerType(str, Enum):
    """Optimizer types."""

    SGD = "sgd"
    ADAM = "adam"
    ADAMW = "adamw"
    RMSPROP = "rmsprop"
    ADAGRAD = "adagrad"


class SchedulerType(str, Enum):
    """Learning rate scheduler types."""

    STEP = "step"
    COSINE = "cosine"
    EXPONENTIAL = "exponential"
    REDUCE_ON_PLATEAU = "reduce_on_plateau"
    ONE_CYCLE = "one_cycle"
    CONSTANT = "constant"


class TrainingConfig(BaseModel):
    """Training configuration."""

    # Model
    model_type: str
    model_config: dict = {}

    # Data
    dataset_id: str
    dataset_version: int
    train_split: float = 0.8
    val_split: float = 0.1
    test_split: float = 0.1
    batch_size: int = 32
    num_workers: int = 4

    # Training
    epochs: int = 100
    optimizer: str = "adamw"
    learning_rate: float = 1e-3
    weight_decay: float = 1e-4
    scheduler: str = "cosine"
    scheduler_params: dict = {}

    # Regularization
    dropout: float = 0.1
    label_smoothing: float = 0.0
    gradient_clip: float = 1.0

    # Hardware
    device: str = "cuda"  # cuda, cpu, mps
    mixed_precision: bool = True
    compile_model: bool = False

    # Checkpointing
    save_every_n_epochs: int = 10
    save_best_only: bool = True
    early_stopping_patience: int = 10
    early_stopping_metric: str = "val_loss"
    early_stopping_mode: str = "min"

    # Logging
    log_every_n_steps: int = 100
    log_metrics: list[str] = ["loss", "accuracy", "f1"]
    use_wandb: bool = False
    wandb_project: str | None = None
    wandb_entity: str | None = None


class TrainingJob(BaseModel):
    """Training job record."""

    job_id: UUID = Field(default_factory=uuid7)
    name: str
    config: TrainingConfig

    # Status
    status: str = "pending"
    current_epoch: int = 0
    total_epochs: int = 0

    # Progress
    steps_completed: int = 0
    total_steps: int = 0

    # Metrics
    train_metrics: dict[str, list[float]] = {}
    val_metrics: dict[str, list[float]] = {}
    best_metric: float | None = None
    best_epoch: int = 0

    # Artifacts
    checkpoint_path: str | None = None
    best_checkpoint_path: str | None = None
    log_path: str | None = None

    # Timing
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: float | None = None

    # Error
    error: str | None = None

    # Metadata
    created_by: str | None = None
    tags: list[str] = []
    metadata: dict = {}


class TrainingPipeline:
    """Orchestrates training jobs."""

    def __init__(self):
        self.jobs: dict[str, TrainingJob] = {}

    def create_job(self, name: str, config: TrainingConfig, created_by: str | None = None) -> TrainingJob:
        """Create a new training job."""
        job = TrainingJob(
            name=name,
            config=config,
            created_by=created_by,
            total_epochs=config.epochs,
        )
        self.jobs[str(job.job_id)] = job
        return job

    async def run_job(self, job_id: UUID, train_loader, val_loader, model, device) -> dict:
        """Execute a training job (simplified interface)."""
        job = self.jobs.get(str(job_id))
        if not job:
            raise ValueError(f"Job {job_id} not found")

        job.status = "running"
        job.started_at = datetime.now(UTC)
        job.total_epochs = job.config.epochs

        # This is a skeleton - actual training would use PyTorch/TensorFlow
        # This is a placeholder showing the interface

        # Mock training loop
        for epoch in range(job.config.epochs):
            job.current_epoch = epoch + 1

            # Training step (placeholder)
            train_metrics = {"loss": 0.5 - epoch * 0.01, "accuracy": 0.7 + epoch * 0.01}
            job.train_metrics.setdefault("loss", []).append(train_metrics["loss"])
            job.train_metrics.setdefault("accuracy", []).append(train_metrics["accuracy"])

            # Validation step (placeholder)
            val_metrics = {"val_loss": 0.6 - epoch * 0.01, "val_accuracy": 0.65 + epoch * 0.01}
            job.val_metrics.setdefault("val_loss", []).append(val_metrics["val_loss"])
            job.val_metrics.setdefault("val_accuracy", []).append(val_metrics["val_accuracy"])

            # Check for best model
            metric_val = val_metrics.get(job.config.early_stopping_metric, 0)
            is_best = False
            if job.config.early_stopping_mode == "min":
                if job.best_metric is None or metric_val < job.best_metric:
                    job.best_metric = metric_val
                    is_best = True
            else:
                if job.best_metric is None or metric_val > job.best_metric:
                    job.best_metric = metric_val
                    is_best = True

            if is_best:
                job.best_epoch = job.current_epoch
                job.best_checkpoint_path = f"checkpoints/{job.job_id}_best.pt"

            # Early stopping check
            if job.current_epoch - job.best_epoch >= job.config.early_stopping_patience:
                break

        job.status = "completed"
        job.completed_at = datetime.now(UTC)
        job.duration_seconds = (job.completed_at - job.started_at).total_seconds()

        return {
            "job_id": str(job.job_id),
            "status": job.status,
            "epochs_completed": job.current_epoch,
            "best_metric": job.best_metric,
            "best_epoch": job.best_epoch,
            "duration_seconds": job.duration_seconds,
        }


class DatasetLoader:
    """Loads and prepares datasets for training."""

    def __init__(self, dataset_path: str):
        self.dataset_path = dataset_path

    def load_training_data(self, config: TrainingConfig):
        """Load and split data for training."""
        # Placeholder - would load from feature store or dataset registry
        pass

    def get_dataloaders(self, config: TrainingConfig):
        """Create DataLoaders for train/val/test."""
        # Placeholder
        pass


class Trainer:
    """Base trainer class."""

    def __init__(self, config: TrainingConfig, model, device):
        self.config = config
        self.model = model.to(config.device)
        self.device = config.device

        # Optimizer
        self.optimizer = self._create_optimizer()

        # Scheduler
        self.scheduler = self._create_scheduler()

        # Mixed precision
        self.scaler = torch.cuda.amp.GradScaler() if config.mixed_precision and "cuda" in config.device else None

    def _create_optimizer(self):
        import torch.optim as optim

        params = self.model.parameters()
        if self.config.optimizer.lower() == "adam":
            return optim.Adam(self.model.parameters(), lr=self.config.learning_rate, weight_decay=self.config.weight_decay)
        elif self.config.optimizer.lower() == "adamw":
            return optim.AdamW(self.model.parameters(), lr=self.config.learning_rate, weight_decay=self.config.weight_decay)
        elif self.config.optimizer.lower() == "sgd":
            return optim.SGD(self.model.parameters(), lr=self.config.learning_rate, momentum=0.9, weight_decay=self.config.weight_decay)
        else:
            return optim.AdamW(self.model.parameters(), lr=self.config.learning_rate, weight_decay=self.config.weight_decay)

    def _create_scheduler(self):
        import torch.optim.lr_scheduler as lr_scheduler

        if self.config.scheduler == "cosine":
            return lr_scheduler.CosineAnnealingLR(self.optimizer, T_max=self.config.epochs)
        elif self.config.scheduler == "step":
            return lr_scheduler.StepLR(self.optimizer, step_size=30, gamma=0.1)
        elif self.config.scheduler == "reduce_on_plateau":
            return lr_scheduler.ReduceLROnPlateau(self.optimizer, mode="min", patience=5)
        elif self.config.scheduler == "one_cycle":
            return lr_scheduler.OneCycleLR(self.optimizer, max_lr=self.config.learning_rate, total_steps=1000)
        else:
            return lr_scheduler.LambdaLR(self.optimizer, lr_lambda=lambda epoch: 1.0)

    def train_step(self, batch):
        """Single training step."""
        self.model.train()
        self.optimizer.zero_grad()

        inputs, targets = batch
        inputs = inputs.to(self.device)
        targets = targets.to(self.device)

        if self.config.mixed_precision and self.scaler:
            with torch.cuda.amp.autocast():
                outputs = self.model(inputs)
                loss = self.compute_loss(outputs, targets)
            self.scaler.scale(loss).backward()
            if self.config.gradient_clip > 0:
                self.scaler.unscale_(self.optimizer)
                torch.nn.utils.clip_grad_norm_(self.model.parameters(), self.config.gradient_clip)
            self.scaler.step(self.optimizer)
            self.scaler.update()
        else:
            outputs = self.model(inputs)
            loss = self.compute_loss(outputs, targets)
            loss.backward()
            if self.config.gradient_clip > 0:
                torch.nn.utils.clip_grad_norm_(self.model.parameters(), self.config.gradient_clip)
            self.optimizer.step()

        return loss.item()

    def validate(self, val_loader):
        """Run validation."""
        self.model.eval()
        metrics = {"loss": 0.0, "accuracy": 0.0}
        total = 0

        with torch.no_grad():
            for batch in val_loader:
                inputs, targets = batch
                inputs = inputs.to(self.device)
                targets = targets.to(self.device)

                outputs = self.model(inputs)
                loss = self.compute_loss(outputs, targets)

                metrics["loss"] += loss.item() * targets.size(0)
                total += targets.size(0)

        metrics["loss"] /= total if total > 0 else 1
        return metrics

    def compute_loss(self, outputs, targets):
        """Compute loss (to be overridden)."""
        import torch.nn.functional as F
        return F.cross_entropy(outputs, targets)


class ExperimentTracker:
    """Tracks experiments and their metrics."""

    def __init__(self):
        self.experiments: dict[str, dict] = {}

    def start_experiment(self, name: str, config: dict) -> str:
        exp_id = f"exp_{len(self.experiments) + 1}_{int(time.time())}"
        self.experiments[exp_id] = {
            "name": name,
            "config": config,
            "metrics": {},
            "artifacts": [],
            "started_at": datetime.now(UTC),
            "status": "running",
        }
        return exp_id

    def log_metric(self, exp_id: str, name: str, value: float, step: int):
        if exp_id not in self.experiments:
            return
        if name not in self.experiments[exp_id]["metrics"]:
            self.experiments[exp_id]["metrics"][name] = []
        self.experiments[exp_id]["metrics"][name].append({"step": step, "value": value})

    def log_artifact(self, exp_id: str, path: str, name: str):
        if exp_id in self.experiments:
            self.experiments[exp_id]["artifacts"].append({"name": name, "path": path})

    def finish_experiment(self, exp_id: str, status: str = "completed"):
        if exp_id in self.experiments:
            self.experiments[exp_id]["status"] = status
            self.experiments[exp_id]["completed_at"] = datetime.now(UTC)

    def get_experiment(self, exp_id: str) -> dict | None:
        return self.experiments.get(exp_id)


__all__ = [
    "TrainingStatus",
    "TrainingFramework",
    "OptimizerType",
    "SchedulerType",
    "TrainingConfig",
    "TrainingJob",
    "TrainingPipeline",
    "DatasetLoader",
    "Trainer",
    "ExperimentTracker",
]
