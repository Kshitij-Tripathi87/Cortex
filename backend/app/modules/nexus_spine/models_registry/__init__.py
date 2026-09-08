"""Nexus v0.7 — Model Registry.

Manages the lifecycle of ML models (forecast, GNN, RL, risk, ETA, SLA)
through training → evaluation → shadow → calibration → approval →
deployment → monitoring → rollback.

No model jumps directly from development to production. This enforces
governance on ML components just like Decisions require approval.
"""

from __future__ import annotations

from app.modules.nexus_spine.models_registry.registry import (
    ModelRegistry,
    ModelLifecycleStatus,
    get_model_registry,
    reset_model_registry,
)

__all__ = [
    "ModelRegistry",
    "ModelLifecycleStatus",
    "get_model_registry",
    "reset_model_registry",
]
