"""Governance & Closed-Loop Flywheel Models.

Program O (Closed-Loop Continuous Learning & Governance):
Tracks the ongoing performance, calibration, and convergence of:
- GNN intelligence predictions
- RL policy value estimates
- Specialist agent consensus recommendations
- Human operator acceptance rates
- Actual real-world enterprise operational outcomes
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class ModelCalibrationMetric:
    """Calibration and error tracking for a specific intelligence subsystem."""

    subsystem_name: str
    sample_count: int
    mean_absolute_error_pct: float
    brier_score_or_r2: float
    drift_detected: bool
    status: str  # "calibrated", "under_review", "recalibrating"

    def to_dict(self) -> dict[str, Any]:
        return {
            "subsystem_name": self.subsystem_name,
            "sample_count": self.sample_count,
            "mean_absolute_error_pct": round(self.mean_absolute_error_pct, 2),
            "brier_score_or_r2": round(self.brier_score_or_r2, 4),
            "drift_detected": self.drift_detected,
            "status": self.status,
        }


@dataclass(frozen=True)
class ClosedLoopGovernanceReport:
    """Overall report assessing the operational feedback loop and decision accuracy."""

    workspace_id: str
    total_decisions_executed: int
    total_revenue_saved_usd: float
    operator_acceptance_rate_pct: float
    subsystem_calibrations: list[ModelCalibrationMetric]
    flywheel_health_score: float  # 0.0 - 1.0
    continuous_learning_summary: str
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "total_decisions_executed": self.total_decisions_executed,
            "total_revenue_saved_usd": round(self.total_revenue_saved_usd, 2),
            "operator_acceptance_rate_pct": round(self.operator_acceptance_rate_pct, 2),
            "subsystem_calibrations": [c.to_dict() for c in self.subsystem_calibrations],
            "flywheel_health_score": round(self.flywheel_health_score, 4),
            "continuous_learning_summary": self.continuous_learning_summary,
            "generated_at": self.generated_at.isoformat(),
        }
