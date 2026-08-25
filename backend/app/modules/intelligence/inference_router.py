"""Inference Router — routes tasks to registered model deployments."""

from __future__ import annotations

from app.modules.intelligence.model_registry import ModelDeployment, ModelRegistry, ModelType
from app.modules.intelligence.types import IntelligenceTask


class InferenceRouter:
    """Routes intelligence tasks to the correct model/service."""

    def __init__(self, registry: ModelRegistry | None = None) -> None:
        self.registry = registry or ModelRegistry()
        self.default_org_id = "default_org"

    def route(self, task: IntelligenceTask, model_version: str | None = None) -> ModelDeployment:
        """Route the task to an active model deployment."""
        model_type = self._task_to_model_type(task)
        deployment = self.registry.get_active(model_type, self.default_org_id)
        if not deployment:
            raise RuntimeError(f"No active deployment found for task {task} (type {model_type})")
        return deployment

    def get_shadow_model(self, task: IntelligenceTask) -> ModelDeployment | None:
        """Get a shadow model for the task, if one exists."""
        model_type = self._task_to_model_type(task)
        for d in self.registry._deployments.values():
            if d.model_type == model_type and d.status.value == "SHADOW":
                reg = self.registry._registrations.get(d.model_id)
                if reg and reg.organization_id == self.default_org_id:
                    return d
        return None

    def _task_to_model_type(self, task: IntelligenceTask) -> ModelType:
        """Map IntelligenceTask to ModelType."""
        mapping = {
            IntelligenceTask.SUPPLIER_SIMILARITY: ModelType.GNN,
            IntelligenceTask.CRITICAL_NODE_DETECTION: ModelType.GNN,
            IntelligenceTask.HIDDEN_DEPENDENCY_DISCOVERY: ModelType.GNN,
            IntelligenceTask.RISK_PROPAGATION: ModelType.GNN,
            IntelligenceTask.POLICY_OPTIMIZATION: ModelType.RL,
            IntelligenceTask.ACTION_RANKING: ModelType.RANKING,
            IntelligenceTask.DEMAND_FORECASTING: ModelType.FORECASTING,
            IntelligenceTask.ANOMALY_DETECTION: ModelType.ANOMALY,
        }
        return mapping[task]
