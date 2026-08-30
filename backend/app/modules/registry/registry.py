"""Model Registry — Enterprise model lifecycle management."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, select
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.common.ids import uuid7_uuid
from app.infrastructure.database import Base
from app.modules.registry.models import (
    ModelFramework,
    ModelMetadata,
    ModelStage,
    ModelType,
)


class ModelRecord(Base):
    """ORM model for model registry."""

    __tablename__ = "model_registry"
    __table_args__ = (
        Index("ix_model_registry_name", "name"),
        Index("ix_model_registry_type", "model_type"),
        Index("ix_model_registry_stage", "stage"),
        Index("ix_model_registry_created", "created_at"),
        {"schema": "analytics"},
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid7_uuid
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    model_type: Mapped[str] = mapped_column(String(64), nullable=False)
    framework: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default=ModelStage.DEVELOPMENT.value)

    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    training_data_version: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    training_samples: Mapped[int] = mapped_column(default=0)
    hyperparameters: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    training_duration_seconds: Mapped[float | None] = mapped_column(nullable=True)
    training_hardware: Mapped[str | None] = mapped_column(String(128), nullable=True)

    artifact_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    artifact_size_bytes: Mapped[int] = mapped_column(default=0)
    artifact_checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)

    metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    evaluation_dataset: Mapped[str | None] = mapped_column(String(256), nullable=True)
    evaluation_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    deployment_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    deployment_endpoint: Mapped[str | None] = mapped_column(String(512), nullable=True)
    deployment_status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_deployed")

    drift_threshold: Mapped[float] = mapped_column(default=0.1)
    performance_threshold: Mapped[float] = mapped_column(default=0.9)
    last_monitoring_check: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    parent_model_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True
    )
    git_commit: Mapped[str | None] = mapped_column(String(128), nullable=True)
    git_branch: Mapped[str | None] = mapped_column(String(128), nullable=True)
    training_config_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)


class ModelEvaluationRecord(Base):
    """ORM model for model evaluations."""

    __tablename__ = "model_evaluations"
    __table_args__ = (
        Index("ix_model_eval_model", "model_id"),
        Index("ix_model_eval_dataset", "dataset_name"),
        Index("ix_model_eval_date", "evaluated_at"),
        {"schema": "analytics"},
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid7_uuid)
    model_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("analytics.model_registry.id", ondelete="CASCADE"), nullable=False
    )
    model_version: Mapped[str] = mapped_column(String(32), nullable=False)
    evaluation_name: Mapped[str] = mapped_column(String(128), nullable=False)
    dataset_name: Mapped[str] = mapped_column(String(128), nullable=False)
    dataset_version: Mapped[str] = mapped_column(String(64), nullable=False)

    metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    confusion_matrix: Mapped[list | None] = mapped_column(JSON, nullable=True)
    per_class_metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    per_slice_metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    evaluated_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    extra_metadata: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)


class ModelDeploymentRecord(Base):
    """ORM model for model deployments."""

    __tablename__ = "model_deployments"
    __table_args__ = (
        Index("ix_model_deploy_model", "model_id"),
        Index("ix_model_deploy_env", "environment"),
        Index("ix_model_deploy_status", "status"),
        {"schema": "analytics"},
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid7_uuid)
    model_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("analytics.model_registry.id", ondelete="CASCADE"), nullable=False
    )
    model_version: Mapped[str] = mapped_column(String(32), nullable=False)
    environment: Mapped[str] = mapped_column(String(32), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    deployed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rollback_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    deployed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)


class ModelRegistry:
    """Model registry service."""

    def __init__(self, db):
        self.db = db

    async def register_model(self, metadata: ModelMetadata) -> ModelMetadata:
        """Register a new model."""

        record = ModelRecord(
            name=metadata.name,
            model_type=metadata.model_type.value,
            framework=metadata.framework.value,
            version=metadata.version,
            stage=metadata.stage.value,
            description=metadata.description,
            tags=list(metadata.tags),
            training_data_version=metadata.training_data_version,
            training_samples=metadata.training_samples,
            hyperparameters=metadata.hyperparameters,
            training_duration_seconds=metadata.training_duration_seconds,
            training_hardware=metadata.training_hardware,
            artifact_path=metadata.artifact_path,
            artifact_size_bytes=metadata.artifact_size_bytes,
            artifact_checksum=metadata.artifact_checksum,
            metrics=metadata.metrics,
            evaluation_dataset=metadata.evaluation_dataset,
            evaluation_timestamp=metadata.evaluation_timestamp,
            deployment_config=metadata.deployment_config,
            deployment_endpoint=metadata.deployment_endpoint,
            deployment_status=metadata.deployment_status,
            drift_threshold=metadata.drift_threshold,
            performance_threshold=metadata.performance_threshold,
            created_by=metadata.created_by,
            parent_model_id=metadata.parent_model_id,
            git_commit=metadata.git_commit,
            git_branch=metadata.git_branch,
            training_config_hash=metadata.training_config_hash,
        )
        self.db.add(record)
        await self.db.flush()
        return self._to_metadata(record)

    async def get_model(self, model_id: UUID) -> ModelMetadata | None:
        result = await self.db.execute(
            select(ModelRecord).where(ModelRecord.id == model_id)
        )
        record = result.scalar_one_or_none()
        return self._to_metadata(record) if record else None

    async def get_model_by_name(self, name: str, version: str | None = None) -> ModelMetadata | None:
        stmt = select(ModelRecord).where(ModelRecord.name == name)
        if version:
            stmt = stmt.where(ModelRecord.version == version)
        else:
            stmt = stmt.order_by(ModelRecord.updated_at.desc()).limit(1)

        result = await self.db.execute(stmt)
        record = result.scalar_one_or_none()
        return self._to_metadata(record) if record else None

    async def list_models(
        self,
        model_type: str | None = None,
        stage: str | None = None,
        framework: str | None = None,
        tags: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ModelMetadata]:
        stmt = select(ModelRecord)

        if model_type:
            stmt = stmt.where(ModelRecord.model_type == model_type)
        if stage:
            stmt = stmt.where(ModelRecord.stage == stage)
        if framework:
            stmt = stmt.where(ModelRecord.framework == framework)
        if tags:
            for tag in tags:
                stmt = stmt.where(ModelRecord.tags.op("@>")([tag]))

        stmt = stmt.order_by(ModelRecord.updated_at.desc()).limit(limit).offset(offset)
        result = await self.db.execute(stmt)
        records = result.scalars().all()
        return [self._to_metadata(r) for r in records]

    async def update_model(self, model_id: UUID, updates: dict) -> ModelMetadata | None:
        result = await self.db.execute(
            select(ModelRecord).where(ModelRecord.id == model_id)
        )
        record = result.scalar_one_or_none()
        if not record:
            return None

        for key, value in updates.items():
            if hasattr(record, key):
                setattr(record, key, value)

        record.updated_at = datetime.now(UTC)
        await self.db.flush()
        return self._to_metadata(record)

    async def promote_model(
        self,
        model_id: UUID,
        version: str,
        target_stage: ModelStage,
        approved_by: str,
        reason: str = "",
    ) -> ModelMetadata | None:
        """Promote a model to a new stage."""
        from app.modules.registry.models import ModelStage

        result = await self.db.execute(
            select(ModelRecord).where(ModelRecord.id == model_id, ModelRecord.version == version)
        )
        record = result.scalar_one_or_none()
        if not record:
            return None

        # Validate stage transition
        valid_transitions = {
            "development": ["staging", "archived"],
            "staging": ["production", "development", "archived"],
            "production": ["archived"],
            "archived": [],
        }

        current = ModelStage(record.stage)
        target = target_stage

        if target not in valid_transitions.get(current.value, []):
            raise ValueError(f"Invalid stage transition: {current.value} -> {target.value}")

        record.stage = target.value
        record.approved_by = approved_by
        record.approved_at = datetime.now(UTC)
        record.updated_at = datetime.now(UTC)

        # If promoting to production, demote current production model
        if target == ModelStage.PRODUCTION:
            await self._demote_current_production(record.name, record.id)

        await self.db.flush()
        return self._to_metadata(record)

    async def _demote_current_production(self, name: str, exclude_id: UUID) -> None:
        """Demote current production model to staging."""
        result = await self.db.execute(
            select(ModelRecord).where(
                ModelRecord.name == name,
                ModelRecord.stage == "production",
                ModelRecord.id != exclude_id,
            )
        )
        current_prod = result.scalar_one_or_none()
        if current_prod:
            current_prod.stage = "staging"
            current_prod.updated_at = datetime.now(UTC)

    async def deploy_model(
        self,
        model_id: UUID,
        version: str,
        environment: str,
        endpoint: str,
        config: dict | None = None,
        deployed_by: str | None = None,
    ) -> UUID:
        """Record a model deployment."""
        record = ModelDeploymentRecord(
            model_id=model_id,
            model_version=version,
            environment=environment,
            endpoint=endpoint,
            status="deploying",
            config=config or {},
            deployed_by=deployed_by,
        )
        self.db.add(record)
        await self.db.flush()
        return record.id

    async def update_deployment_status(
        self,
        deployment_id: UUID,
        status: str,
        error: str | None = None,
    ) -> bool:
        result = await self.db.execute(
            select(ModelDeploymentRecord).where(ModelDeploymentRecord.id == deployment_id)
        )
        record = result.scalar_one_or_none()
        if not record:
            return False

        record.status = status
        if status == "active":
            record.deployed_at = datetime.now(UTC)
        elif status == "failed":
            record.rollback_reason = error
        await self.db.flush()
        return True

    async def rollback_deployment(
        self,
        deployment_id: UUID,
        reason: str,
        rolled_back_by: str,
    ) -> bool:
        result = await self.db.execute(
            select(ModelDeploymentRecord).where(ModelDeploymentRecord.id == deployment_id)
        )
        record = result.scalar_one_or_none()
        if not record:
            return False

        record.status = "rolled_back"
        record.rolled_back_at = datetime.now(UTC)
        record.rollback_reason = reason
        await self.db.flush()
        return True

    async def record_evaluation(
        self,
        model_id: UUID,
        model_version: str,
        evaluation_name: str,
        dataset_name: str,
        dataset_version: str,
        metrics: dict,
        confusion_matrix: list[list[int]] | None = None,
        per_class_metrics: dict | None = None,
        per_slice_metrics: dict | None = None,
        evaluated_by: str | None = None,
        metadata: dict | None = None,
    ) -> UUID:
        record = ModelEvaluationRecord(
            model_id=model_id,
            model_version=model_version,
            evaluation_name=evaluation_name,
            dataset_name=dataset_name,
            dataset_version=dataset_version,
            metrics=metrics,
            confusion_matrix=confusion_matrix,
            per_class_metrics=per_class_metrics or {},
            per_slice_metrics=per_slice_metrics or {},
            evaluated_by=evaluated_by,
            metadata=metadata or {},
        )
        self.db.add(record)
        await self.db.flush()
        return record.id

    async def get_model_versions(self, model_id: UUID) -> list[dict]:
        """Get all versions of a model."""
        await self.db.execute(
            select(ModelRecord).where(ModelRecord.id == model_id)
        )
        # Actually, in this schema, each record is a different model.
        # For versioning, we'd need a separate approach.
        # This is a simplified implementation.
        return [{"version": "1.0.0", "stage": "development"}]

    async def compare_versions(
        self,
        model_id: UUID,
        version_a: str,
        version_b: str,
        dataset_id: str,
        dataset_version: int,
    ) -> dict:
        """Compare two versions of a model on a dataset."""
        # This would run both versions on the dataset and compare
        # Simplified implementation
        return {
            "model_id": str(model_id),
            "version_a": version_a,
            "version_b": version_b,
            "dataset_id": dataset_id,
            "comparison": {"note": "Comparison logic to be implemented"},
        }

    def _to_metadata(self, record: ModelRecord) -> ModelMetadata:
        from app.modules.registry.models import ModelMetadata as PydanticMetadata
        from app.modules.registry.models import ModelStage

        return PydanticMetadata(
            model_id=record.id,
            name=record.name,
            model_type=ModelType(record.model_type),
            framework=ModelFramework(record.framework),
            version=record.version,
            stage=ModelStage(record.stage),
            description=record.description,
            tags=list(record.tags),
            training_data_version=record.training_data_version,
            training_samples=record.training_samples,
            hyperparameters=record.hyperparameters,
            training_duration_seconds=record.training_duration_seconds,
            training_hardware=record.training_hardware,
            artifact_path=record.artifact_path,
            artifact_size_bytes=record.artifact_size_bytes,
            artifact_checksum=record.artifact_checksum,
            metrics=record.metrics,
            evaluation_dataset=record.evaluation_dataset,
            evaluation_timestamp=record.evaluation_timestamp,
            deployment_config=record.deployment_config,
            deployment_endpoint=record.deployment_endpoint,
            deployment_status=record.deployment_status,
            drift_threshold=record.drift_threshold,
            performance_threshold=record.performance_threshold,
            last_monitoring_check=record.last_monitoring_check,
            created_at=record.created_at,
            updated_at=record.updated_at,
            created_by=record.created_by,
            approved_by=record.approved_by,
            approved_at=record.approved_at,
            parent_model_id=record.parent_model_id,
            git_commit=record.git_commit,
            git_branch=record.git_branch,
            training_config_hash=record.training_config_hash,
        )


__all__ = ["ModelRecord", "ModelEvaluationRecord", "ModelDeploymentRecord", "ModelRegistry"]
