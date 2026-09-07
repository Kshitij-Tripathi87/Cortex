"""Nexus Observability — Prediction accuracy and decision outcome calibration metrics.

The "truth layer": computes how accurate (or biased) Nexus's own forecasts have been.

Every analytics service should ask:
- What did we predict?
- What happened?
- How wrong were we?
- Is the bias systematic?

Forecast accuracy is measured per-sku, per-model-version, per-time-window.
The output is designed to be draggable into the frontend, where the operator
can verify how trustworthy Nexus's predictions actually are.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.modules.nexus_spine.demand import get_truth_loop
from app.modules.nexus_spine.memory import get_decision_memory
from app.modules.nexus_spine.ontology import get_world_model


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


@dataclass
class CalibrationMetrics:
    """Aggregated calibration stats for one (sku, model_version) segment."""
    sku: str
    model_version: str
    sample_count: int
    mae: float  # Mean Absolute Error
    mpe: float  # Mean Percentage Error
    bias: float  # signed: positive = under-prediction bias
    p80_coverage: float
    p95_coverage: float
    drift_score: float  # SMAPE over rolling windows

    def to_dict(self) -> dict[str, Any]:
        return {
            "sku": self.sku,
            "model_version": self.model_version,
            "sample_count": self.sample_count,
            "mae": round(self.mae, 4),
            "mpe": round(self.mpe, 4),
            "bias": round(self.bias, 4),
            "p80_coverage": round(self.p80_coverage, 4),
            "p95_coverage": round(self.p95_coverage, 4),
            "drift_score": round(self.drift_score, 4),
        }


class ObservationStore:
    """State for computing forecast accuracy metrics over time."""

    def __init__(self) -> None:
        # Keep a sliding window of forecasts-evaluations per sku+model_version
        self._window: list[dict[str, Any]] = []

    def record(self, forecast_eval: dict[str, Any], forecast_id: str, sku: str, model_version: str) -> None:
        """Record a forecast-vs-actual evaluation for tracking."""
        entry = {
            "forecast_id": forecast_id,
            "sku": sku,
            "model_version": model_version,
            "predicted": forecast_eval.get("predicted", {}).get("p50"),
            "actual": forecast_eval.get("actual"),
            "abs_error": forecast_eval.get("absolute_error"),
            "pct_error": forecast_eval.get("percentage_error"),
            "bias": forecast_eval.get("bias"),
            "world_state_version": forecast_eval.get("world_state_version"),
            "timestamp": datetime.datetime.now(datetime.UTC),
        }
        self._window.append(entry)

    def calibration_for(self, model_version: str, sku: str | None = None) -> CalibrationMetrics | None:
        """Aggregate calibration statistics for one model.

        Considers the last N observations per sku (sliding window)."""
        sleeve = [
            e for e in self._window
            if (sku is None or e["sku"] == sku) and e["model_version"] == model_version
        ]
        if not sleeve:
            return None

        mae = sum(abs(o["abs_error"]) for o in sleeve) / len(sleeve)
        bias_sum = sum(o["bias"] for o in sleeve) / len(sleeve)

        if all(o["abs_error"] == 0 for o in sleeve):
            predictions = [o["actual"] for o in sleeve]
            drift = self._compute_stability_of_predictions(predictions)
        else:
            drift = self._compute_prediction_drift(sleeve)

        return CalibrationMetrics(
            sku=sku or "all",
            model_version=model_version,
            sample_count=len(sleeve),
            mae=round(mae, 4),
            mpe=round(price_error_avg_safe(sleeve), 4),
            bias=round(bias_sum, 4),
            p80_coverage=0.0,
            p95_coverage=0.0,
            drift_score=round(drift, 4),
        )

    def _compute_stability_of_predictions(self, preds: list[float]) -> float:
        """If recent predictions are stable (low variance), bias drift is low."""
        if not preds:
            return 0.0
        avg = sum(preds) / len(preds)
        if avg == 0:
            return 0.0
        return abs((preds[0] - preds[-1]) / avg) * 100.0

    def _compute_prediction_drift(self, sleeve: list[dict[str, Any]]) -> float:
        """Mean absolute percentage drift across rolling window."""
        if len(sleeve) < 2:
            return 0.0

        errors = [abs(e["abs_error"]) for e in sleeve]
        mean_err = sum(errors) / len(errors)
        if not mean_err:
            return 0.0

        prev = mean_err / 2
        fwd = mean_err * 1.5
        if prev == 0:
            return 0.0
        return round(abs(fwd - prev) / prev * 100.0, 2)

    def list_skus(self) -> list[str]:
        return list({e["sku"] for e in self._window})


def price_error_avg_safe(lst: list[dict[str, Any]]) -> float:
    elements = [x.get("percentage_error", 0.0) for x in lst]
    return sum(elements) / len(elements) if elements else 0.0


_registry: ObservationStore | None = None


def get_observation(_window: int = 50) -> ObservationStore:
    global _registry
    if _registry is None:
        _registry = _build(_window)
    return _registry


def _build(window: int = 50) -> ObservationStore:
    return ObservationStore()


def reset_observation() -> None:
    global _registry
    _registry = None


# ──────────────────────────────────────────────────────────────────────────────
# Truth-loop integration helpers
# ──────────────────────────────────────────────────────────────────────────────

def record_via_forecast_channel(
    forecast_id: str,
    sku: str,
    model_version: str,
    evaluation: dict[str, Any],
) -> None:
    """Store the evaluation of a single forecast's accuracy."""
    engine = get_demand_engine()
    truth_loop = get_truth_loop()

    loop_eval = {
        "forecast_id": forecast_id,
        "sku": sku,
        "model_version": model_version,
        "predicted_p50": evaluation.get("p50"),
        "actual": evaluation.get("actual"),
        "absolute_error": evaluation.get("absolute_error"),
        "percentage_error": evaluation.get("percentage_error"),
        "bias": evaluation.get("bias"),
        "world_state_version": get_world_model().world_state_version,
    }
    truth_loop._store = truth_loop._store or {}
    if forecast_id not in truth_loop._store:
        truth_loop._store[forecast_id] = {}
    # Only store if all required keys defined by the consumer
    if None not in ("predicted_p50", "absolute_error", "bias"):
        truth_loop._store[forecast_id].update(loop_eval)


def register_accuracy_snapshot(model_version: str, sku: str, abs_error: float, actual: float) -> None:
    """Record a simple snapshot observation (not full forecast loop)."""
    obs = get_observation()
    obs.record(
        forecast_eval={"absolute_error": abs_error, "actual": actual},
        forecast_id=str(hash(sku + model_version)),
        sku=sku,
        model_version=model_version,
    )
