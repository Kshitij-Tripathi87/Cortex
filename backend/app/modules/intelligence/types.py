"""Intelligence Types and Enums — Shared across Intelligence Gateway, Routers, and Baselines."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class IntelligenceTask(StrEnum):
    """Standard intelligence task types supported by the gateway."""

    SUPPLIER_SIMILARITY = "SUPPLIER_SIMILARITY"
    CRITICAL_NODE_DETECTION = "CRITICAL_NODE_DETECTION"
    HIDDEN_DEPENDENCY_DISCOVERY = "HIDDEN_DEPENDENCY_DISCOVERY"
    RISK_PROPAGATION = "RISK_PROPAGATION"
    POLICY_OPTIMIZATION = "POLICY_OPTIMIZATION"
    ACTION_RANKING = "ACTION_RANKING"
    DEMAND_FORECASTING = "DEMAND_FORECASTING"
    ANOMALY_DETECTION = "ANOMALY_DETECTION"


class InferenceStatus(StrEnum):
    """Execution status of an AI inference request."""

    SUCCESS = "SUCCESS"
    FALLBACK = "FALLBACK"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"


class ModelProvenance(BaseModel):
    """Complete 5-part AI governance & provenance record."""

    model_version: str = "v1.0.0"
    dataset_version: str = "ds-2026-08-16"
    feature_version: str = "feat-v1"
    evaluation_version: str = "eval-prod-pass"
    policy_version: str = "pol-v1"


class IntelligenceRequest(BaseModel):
    """Incoming inference request model."""

    request_id: str
    task: IntelligenceTask
    tenant_id: str
    workspace_id: str
    correlation_id: str
    world_state_version: int
    input_data: dict[str, Any] = Field(default_factory=dict)
    model_version: str | None = None
    timeout_seconds: float = 30.0
    enable_shadow: bool = False
    fallback_to_deterministic: bool = True


class IntelligenceResponse(BaseModel):
    """Outgoing inference response model."""

    request_id: str
    task: IntelligenceTask
    status: InferenceStatus
    model_id: str
    model_version: str
    output: dict[str, Any]
    confidence: float | None = None
    calibration_score: float | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    duration_ms: float
    shadow_comparison: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)
    provenance: ModelProvenance = Field(default_factory=ModelProvenance)
