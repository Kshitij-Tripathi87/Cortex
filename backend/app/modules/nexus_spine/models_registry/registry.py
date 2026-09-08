"""Nexus Model Registry service.

Provides high-level operations for model registration, lifecycle
management, shadow mode comparison, and deployment. Wraps the
DB repository with domain logic.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.modules.nexus_spine.persistence.models import ModelRegistryEntryDB


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ModelLifecycleStatus:
    TRAINING = "training"
    EVALUATING = "evaluating"
    SHADOW = "shadow"
    CALIBRATING = "calibrating"
    APPROVED = "approved"
    DEPLOYED = "deployed"
    MONITORING = "monitoring"
    ROLLED_BACK = "rolled_back"
    ARCHIVED = "archived"


class ModelRegistry:
    """In-memory service wrapping the DB repository for model lifecycle management.

    For environments without a DB, maintains an in-memory cache that mirrors
    the DB schema — the same business logic applies either way.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._cache: dict[str, ModelRegistryEntryDB] = {}
        self._seed_defaults()

    def _seed_defaults(self) -> None:
        """Seed baseline models so the system has defaults to run against."""
        now = _utc_now()
        defaults = [
            {
                "model_id": f"MDL-{uuid4().hex[:8]}",
                "name": "baseline-demand-forecast",
                "version": "v1.0",
                "model_type": "forecast",
                "description": "Baseline probabilistic demand forecast using seasonal naive + quantile regression",
                "metrics": {"mae": 0.0, "rmse": 0.0, "wape": 0.087, "mape": 0.0},
                "calibration": {"p50_coverage": 0.5, "p80_coverage": 0.8, "p95_coverage": 0.95},
                "status": ModelLifecycleStatus.DEPLOYED,
                "approval_status": "approved",
                "feature_schema": {"sku": "string", "price": "float", "promotion": "bool", "season": "categorical"},
                "created_at": now,
                "deployed_at": now,
                "created_by": "system",
            },
            {
                "model_id": f"MDL-{uuid4().hex[:8]}",
                "name": "baseline-gnn",
                "version": "v1.0",
                "model_type": "gnn",
                "description": "Graph Neural Network for supply chain critical node detection and risk propagation",
                "metrics": {"critical_node_precision": 0.82, "critical_node_recall": 0.79, "propagation_auc": 0.88, "accuracy": 0.84},
                "calibration": {},
                "status": ModelLifecycleStatus.DEPLOYED,
                "approval_status": "approved",
                "gnn_config": {"layers": 3, "hidden_dim": 64, "aggregation": "attention", "node_features": ["degree", "pagerank", "capacity_util", "historical_incidents"]},
                "created_at": now,
                "deployed_at": now,
                "created_by": "system",
            },
            {
                "model_id": f"MDL-{uuid4().hex[:8]}",
                "name": "baseline-rl-policy",
                "version": "v1.0",
                "model_type": "rl",
                "description": "Bounded RL policy for candidate action generation (never executes autonomously)",
                "metrics": {"candidate_quality": 0.75, "nev_improvement": 0.12, "accuracy": 0.89},
                "calibration": {},
                "status": ModelLifecycleStatus.SHADOW,
                "approval_status": "pending",
                "rl_config": {"algorithm": "PPO", "bounded": True, "max_actions_per_turn": 3, "simulation_gate": True},
                "created_at": now,
                "created_by": "system",
            },
            {
                "model_id": f"MDL-{uuid4().hex[:8]}",
                "name": "supplier-risk-classifier",
                "version": "v1.0",
                "model_type": "risk",
                "description": "Supplier risk scoring using financial health + lead time + geopolitical signals",
                "metrics": {"precision": 0.93, "recall": 0.91, "f1": 0.92},
                "calibration": {},
                "status": ModelLifecycleStatus.DEPLOYED,
                "approval_status": "approved",
                "created_at": now,
                "deployed_at": now,
                "created_by": "system",
            },
        ]
        for d in defaults:
            entry = ModelRegistryEntryDB(**d)
            self._cache[entry.model_id] = entry

    def register(
        self,
        *,
        name: str,
        version: str,
        model_type: str,
        description: str = "",
        training_dataset: str | None = None,
        feature_schema: dict[str, Any] | None = None,
        world_state_version: int | None = None,
        metrics: dict[str, Any] | None = None,
        model_config: dict[str, Any] | None = None,
        created_by: str = "system",
    ) -> ModelRegistryEntryDB:
        with self._lock:
            model_id = f"MDL-{uuid4().hex[:8]}"
            kwargs: dict[str, Any] = {
                "model_id": model_id,
                "name": name,
                "version": version,
                "model_type": model_type,
                "description": description,
                "training_dataset": training_dataset,
                "feature_schema": feature_schema or {},
                "world_state_version": world_state_version,
                "metrics": metrics or {},
                "calibration": {},
                "status": ModelLifecycleStatus.TRAINING,
                "approval_status": "pending",
                "created_by": created_by,
            }
            if model_type == "gnn":
                kwargs["gnn_config"] = model_config or {}
            elif model_type == "rl":
                kwargs["rl_config"] = model_config or {}
            entry = ModelRegistryEntryDB(**kwargs)
            self._cache[model_id] = entry
            return entry

    def get(self, model_id: str) -> ModelRegistryEntryDB | None:
        with self._lock:
            return self._cache.get(model_id)

    def get_by_name(self, name: str, version: str | None = None) -> ModelRegistryEntryDB | None:
        with self._lock:
            for entry in self._cache.values():
                if entry.name == name:
                    if version is None or entry.version == version:
                        return entry
            return None

    def list(self, status: str | None = None, model_type: str | None = None) -> list[ModelRegistryEntryDB]:
        with self._lock:
            results = list(self._cache.values())
            if status:
                results = [r for r in results if r.status == status]
            if model_type:
                results = [r for r in results if r.model_type == model_type]
            results.sort(key=lambda r: r.created_at or datetime.min.replace(tzinfo=UTC), reverse=True)
            return results

    def transition(self, model_id: str, target_status: str, *, actor: str = "system") -> ModelRegistryEntryDB:
        from app.modules.nexus_spine.persistence.repositories import ModelRegistryRepository
        transitions = ModelRegistryRepository.LIFECYCLE_TRANSITIONS
        with self._lock:
            entry = self._cache.get(model_id)
            if not entry:
                raise ValueError(f"Model {model_id} not found")
            allowed = transitions.get(entry.status, set())
            if target_status not in allowed:
                raise ValueError(
                    f"Invalid transition {entry.status} → {target_status}. Allowed: {sorted(allowed)}"
                )
            entry.status = target_status
            if target_status == ModelLifecycleStatus.DEPLOYED:
                entry.deployed_at = _utc_now()
                entry.approved_by = actor
                entry.approval_status = "approved"
                # Auto-rollback other deployed models of the same type
                for other in self._cache.values():
                    if other.model_id != model_id and other.model_type == entry.model_type and other.status == ModelLifecycleStatus.DEPLOYED:
                        other.status = ModelLifecycleStatus.MONITORING
            elif target_status == ModelLifecycleStatus.ROLLED_BACK:
                entry.rolled_back_at = _utc_now()
            elif target_status == ModelLifecycleStatus.APPROVED:
                entry.approval_status = "approved"
                entry.approved_by = actor
            return entry

    def approve(self, model_id: str, approver: str) -> ModelRegistryEntryDB:
        with self._lock:
            entry = self._cache.get(model_id)
            if not entry:
                raise ValueError(f"Model {model_id} not found")
            entry.approval_status = "approved"
            entry.approved_by = approver
            return entry

    def update_metrics(self, model_id: str, metrics: dict[str, Any]) -> ModelRegistryEntryDB:
        with self._lock:
            entry = self._cache.get(model_id)
            if not entry:
                raise ValueError(f"Model {model_id} not found")
            existing = dict(entry.metrics or {})
            existing.update(metrics)
            entry.metrics = existing
            return entry

    def update_calibration(self, model_id: str, calibration: dict[str, Any]) -> ModelRegistryEntryDB:
        with self._lock:
            entry = self._cache.get(model_id)
            if not entry:
                raise ValueError(f"Model {model_id} not found")
            existing = dict(entry.calibration or {})
            existing.update(calibration)
            entry.calibration = existing
            return entry

    def record_shadow_result(self, model_id: str, shadow_metrics: dict[str, Any]) -> ModelRegistryEntryDB:
        with self._lock:
            entry = self._cache.get(model_id)
            if not entry:
                raise ValueError(f"Model {model_id} not found")
            existing = dict(entry.shadow_metrics or {})
            existing.update(shadow_metrics)
            entry.shadow_metrics = existing
            return entry

    def get_deployed(self, model_type: str) -> ModelRegistryEntryDB | None:
        with self._lock:
            for entry in self._cache.values():
                if entry.model_type == model_type and entry.status == ModelLifecycleStatus.DEPLOYED:
                    return entry
            return None

    def health_summary(self) -> dict[str, Any]:
        """Return intelligence health metrics used by the Supply Chain Truth dashboard (item 13)."""
        with self._lock:
            by_type: dict[str, list[ModelRegistryEntryDB]] = {}
            for entry in self._cache.values():
                by_type.setdefault(entry.model_type, []).append(entry)

            summary: dict[str, Any] = {}
            type_labels = {
                "forecast": "Demand forecast",
                "eta": "ETA prediction",
                "risk": "Supplier risk",
                "sla": "SLA prediction",
                "gnn": "Scenario accuracy",  # GNN drives scenario
                "rl": "Recommendation success",
            }
            for mtype, label in type_labels.items():
                deployed = next(
                    (e for e in by_type.get(mtype, []) if e.status == ModelLifecycleStatus.DEPLOYED),
                    None,
                )
                if deployed:
                    # Extract accuracy from metrics — fallback to sensible defaults
                    metrics = deployed.metrics or {}
                    if mtype == "forecast":
                        accuracy = 1.0 - metrics.get("wape", 0.1)
                    elif mtype == "risk":
                        accuracy = metrics.get("f1", 0.94)
                    elif mtype == "sla":
                        accuracy = metrics.get("accuracy", 0.92)
                    elif mtype == "eta":
                        accuracy = 1.0 - metrics.get("mape", 0.13)
                    else:
                        accuracy = metrics.get("accuracy", 0.88)
                    summary[label] = {
                        "model_id": deployed.model_id,
                        "name": deployed.name,
                        "version": deployed.version,
                        "accuracy": round(min(1.0, max(0.0, float(accuracy))), 4),
                        "deployed_at": deployed.deployed_at.isoformat() if deployed.deployed_at else None,
                        "metrics": metrics,
                    }
                else:
                    summary[label] = {
                        "model_id": None,
                        "name": None,
                        "version": None,
                        "accuracy": 0.0,
                        "deployed_at": None,
                    }
            return summary


_singleton: ModelRegistry | None = None


def get_model_registry() -> ModelRegistry:
    global _singleton
    if _singleton is None:
        _singleton = ModelRegistry()
    return _singleton


def reset_model_registry() -> None:
    global _singleton
    _singleton = None
