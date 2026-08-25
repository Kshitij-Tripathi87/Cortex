"""Model Registry and Lifecycle.

Handles model lifecycle: Registration -> Validation -> Calibration -> Deployment -> Shadow -> Promotion -> Rollback.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.common.ids import uuid7


class ModelType(StrEnum):
    """Supported model types."""
    GNN = "GNN"
    RL = "RL"
    RANKING = "RANKING"
    FORECASTING = "FORECASTING"
    ANOMALY = "ANOMALY"


class ModelStatus(StrEnum):
    """Model registration lifecycle status."""
    REGISTERED = "REGISTERED"
    VALIDATING = "VALIDATING"
    VALIDATED = "VALIDATED"
    CALIBRATING = "CALIBRATING"
    CALIBRATED = "CALIBRATED"
    DEPLOYING = "DEPLOYING"
    DEPLOYED = "DEPLOYED"
    SHADOW = "SHADOW"
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"
    ROLLED_BACK = "ROLLED_BACK"


class DeploymentStatus(StrEnum):
    """Status of a deployed model."""
    DEPLOYING = "DEPLOYING"
    ACTIVE = "ACTIVE"
    SHADOW = "SHADOW"
    DRAINING = "DRAINING"
    ROLLED_BACK = "ROLLED_BACK"


class ModelHealth(StrEnum):
    """Health status of a model deployment."""
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"


class ValidationResult(BaseModel):
    passed: bool
    metrics: dict[str, float]
    baseline_comparison: dict[str, Any]
    issues: list[str]


class CalibrationResult(BaseModel):
    calibration_score: float
    reliability_diagram: dict[str, Any]
    adjustments_applied: dict[str, Any]


class ModelRegistration(BaseModel):
    model_id: str
    model_type: ModelType
    version: str
    status: ModelStatus
    artifact_uri: str
    training_metadata: dict[str, Any]
    validation_results: ValidationResult | None = None
    calibration_results: CalibrationResult | None = None
    registered_at: datetime
    deployed_at: datetime | None = None
    promoted_at: datetime | None = None
    registered_by: str
    organization_id: str
    tags: dict[str, str] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


class ModelDeployment(BaseModel):
    deployment_id: str
    model_id: str
    model_type: ModelType
    version: str
    status: DeploymentStatus
    endpoint: str | None = None
    deployed_at: datetime
    health: ModelHealth = ModelHealth.HEALTHY
    metrics: dict[str, float] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


class ModelDefinition(BaseModel):
    model_type: ModelType
    version: str
    artifact_uri: str
    training_metadata: dict[str, Any]
    registered_by: str
    organization_id: str
    tags: dict[str, str] = Field(default_factory=dict)


class DeploymentTarget(BaseModel):
    endpoint: str


class ModelRegistry:
    """In-memory model registry for lifecycle management."""

    def __init__(self) -> None:
        self._registrations: dict[str, ModelRegistration] = {}
        self._deployments: dict[str, ModelDeployment] = {}

    def register(self, definition: ModelDefinition) -> ModelRegistration:
        model_id = f"mod_{uuid7()}"
        registration = ModelRegistration(
            model_id=model_id,
            model_type=definition.model_type,
            version=definition.version,
            status=ModelStatus.REGISTERED,
            artifact_uri=definition.artifact_uri,
            training_metadata=definition.training_metadata,
            registered_at=datetime.now(UTC),
            registered_by=definition.registered_by,
            organization_id=definition.organization_id,
            tags=definition.tags,
        )
        self._registrations[model_id] = registration
        return registration

    def validate(self, model_id: str, validation_data: dict[str, Any]) -> ValidationResult:
        registration = self._registrations.get(model_id)
        if not registration:
            raise ValueError(f"Model {model_id} not found")

        registration.status = ModelStatus.VALIDATING

        # Simulate validation logic
        result = ValidationResult(
            passed=True,
            metrics={"accuracy": 0.95, "f1_score": 0.94},
            baseline_comparison={"improvement": 0.05},
            issues=[]
        )

        registration.validation_results = result
        registration.status = ModelStatus.VALIDATED
        return result

    def calibrate(self, model_id: str, calibration_data: dict[str, Any]) -> CalibrationResult:
        registration = self._registrations.get(model_id)
        if not registration:
            raise ValueError(f"Model {model_id} not found")

        registration.status = ModelStatus.CALIBRATING

        # Simulate calibration logic
        result = CalibrationResult(
            calibration_score=0.98,
            reliability_diagram={"bins": 10, "ece": 0.02},
            adjustments_applied={"temperature": 1.5}
        )

        registration.calibration_results = result
        registration.status = ModelStatus.CALIBRATED
        return result

    def deploy(self, model_id: str, target: DeploymentTarget) -> ModelDeployment:
        registration = self._registrations.get(model_id)
        if not registration:
            raise ValueError(f"Model {model_id} not found")

        registration.status = ModelStatus.DEPLOYING

        deployment_id = f"dep_{uuid7()}"
        deployment = ModelDeployment(
            deployment_id=deployment_id,
            model_id=model_id,
            model_type=registration.model_type,
            version=registration.version,
            status=DeploymentStatus.DEPLOYING,
            endpoint=target.endpoint,
            deployed_at=datetime.now(UTC),
            health=ModelHealth.HEALTHY,
            metrics={"latency_p50_ms": 0.0, "latency_p99_ms": 0.0, "error_rate": 0.0, "inference_count": 0.0}
        )

        self._deployments[deployment_id] = deployment
        registration.deployed_at = datetime.now(UTC)

        # Deploy as SHADOW initially
        deployment.status = DeploymentStatus.SHADOW
        registration.status = ModelStatus.SHADOW

        return deployment

    def promote(self, model_id: str) -> ModelDeployment:
        registration = self._registrations.get(model_id)
        if not registration:
            raise ValueError(f"Model {model_id} not found")

        # Find the deployment
        deployment = next((d for d in self._deployments.values() if d.model_id == model_id), None)
        if not deployment:
            raise ValueError(f"Deployment for model {model_id} not found")

        # Demote current active models of the same type for this organization
        # Simplified: Demote all active models of this type
        for d in self._deployments.values():
            if d.model_type == registration.model_type and d.status == DeploymentStatus.ACTIVE and d.deployment_id != deployment.deployment_id:
                d.status = DeploymentStatus.DRAINING
                if d.model_id in self._registrations:
                    self._registrations[d.model_id].status = ModelStatus.DEPRECATED

        deployment.status = DeploymentStatus.ACTIVE
        registration.status = ModelStatus.ACTIVE
        registration.promoted_at = datetime.now(UTC)

        return deployment

    def rollback(self, model_id: str) -> ModelDeployment:
        registration = self._registrations.get(model_id)
        if not registration:
            raise ValueError(f"Model {model_id} not found")

        deployment = next((d for d in self._deployments.values() if d.model_id == model_id), None)
        if not deployment:
            raise ValueError(f"Deployment for model {model_id} not found")

        deployment.status = DeploymentStatus.ROLLED_BACK
        registration.status = ModelStatus.ROLLED_BACK

        return deployment

    def deprecate(self, model_id: str) -> None:
        registration = self._registrations.get(model_id)
        if not registration:
            raise ValueError(f"Model {model_id} not found")

        registration.status = ModelStatus.DEPRECATED
        deployment = next((d for d in self._deployments.values() if d.model_id == model_id), None)
        if deployment:
            deployment.status = DeploymentStatus.DRAINING

    def get_active(self, model_type: ModelType, org_id: str) -> ModelDeployment | None:
        # For simplicity in this implementation, org_id filtering relies on the registrations
        active_deps = []
        for d in self._deployments.values():
            if d.status == DeploymentStatus.ACTIVE and d.model_type == model_type:
                reg = self._registrations.get(d.model_id)
                if reg and reg.organization_id == org_id:
                    active_deps.append(d)

        # Return the most recently deployed active model if multiple
        if not active_deps:
            return None
        return sorted(active_deps, key=lambda d: d.deployed_at, reverse=True)[0]

    def get_deployment(self, model_id: str) -> ModelDeployment | None:
        return next((d for d in self._deployments.values() if d.model_id == model_id), None)

    def list_models(self, org_id: str, model_type: ModelType | None = None) -> list[ModelRegistration]:
        results = []
        for reg in self._registrations.values():
            if reg.organization_id == org_id:
                if model_type is None or reg.model_type == model_type:
                    results.append(reg)
        return results
