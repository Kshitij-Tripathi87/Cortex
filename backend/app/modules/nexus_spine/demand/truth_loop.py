"""Nexus Demand Intelligence — Truth Loop (Forecast vs Reality Calibration).

Closes the loop between predicted and actual. For every forecast we:

1. Record the prediction with its inputs (model version, world state, etc.)
2. When actual demand is observed, evaluate the prediction
3. Aggregate the errors into calibration statistics per (sku, model_version)
4. Expose those statistics so Vanessa can answer "where are we systematically
   wrong?" and the model registry can trigger shadow mode for a new model.

This is what makes Nexus an actual *learning system* rather than a static
forecast dashboard.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.modules.nexus_spine.demand.engine import (
    ForecastActual,
    ForecastEvaluation,
    ProbabilisticForecast,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class CalibrationBucket:
    """Calibration statistics for one (sku, model_version) bucket."""

    sku: str
    model_version: str
    sample_count: int
    mean_absolute_error: float
    mean_percentage_error: float
    bias: float  # signed: positive = systematic under-prediction
    p80_coverage: float  # fraction of actuals that fell within P80
    p95_coverage: float  # fraction of actuals that fell within P95
    last_updated: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "sku": self.sku,
            "model_version": self.model_version,
            "sample_count": self.sample_count,
            "mean_absolute_error": self.mean_absolute_error,
            "mean_percentage_error": self.mean_percentage_error,
            "bias": self.bias,
            "p80_coverage": self.p80_coverage,
            "p95_coverage": self.p95_coverage,
            "last_updated": self.last_updated.isoformat(),
        }


class TruthLoop:
    """Records forecasts, observes actuals, computes calibration statistics.

    All methods are thread-safe.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._pending: dict[str, ProbabilisticForecast] = {}
        self._evaluations: list[ForecastEvaluation] = []
        self._calibration: dict[tuple[str, str], list[ForecastEvaluation]] = defaultdict(list)

    # ── Recording ──────────────────────────────────────────────────────────

    def record_forecast(self, forecast: ProbabilisticForecast) -> None:
        with self._lock:
            self._pending[forecast.forecast_id] = forecast

    def observe(self, actual: ForecastActual) -> ForecastEvaluation | None:
        """Record a realized actual and produce an evaluation if a matching
        forecast exists. Returns None when no forecast matches.
        """
        with self._lock:
            forecast = self._pending.pop(actual.forecast_id, None)
            if forecast is None:
                return None
            # Find the engine and evaluate — but to avoid a circular import
            # we re-derive the math here. This is intentional: the engine
            # class is the source of truth for forecast math but the truth
            # loop only needs the public evaluation semantics.
            absolute_error = actual.actual_quantity - forecast.p50
            percentage_error = (
                absolute_error / forecast.p50 if forecast.p50 != 0 else 0.0
            )
            evaluation = ForecastEvaluation(
                forecast_id=forecast.forecast_id,
                sku=forecast.sku,
                predicted_p50=forecast.p50,
                actual=actual.actual_quantity,
                absolute_error=absolute_error,
                percentage_error=percentage_error,
                bias=absolute_error,
                is_within_p80=actual.actual_quantity <= forecast.p80,
                is_within_p95=actual.actual_quantity <= forecast.p95,
            )
            self._evaluations.append(evaluation)
            self._calibration[(forecast.sku, forecast.model_version)].append(evaluation)
            return evaluation

    # ── Calibration accessors ──────────────────────────────────────────────

    def calibration_for(
        self,
        sku: str,
        model_version: str | None = None,
    ) -> list[CalibrationBucket]:
        """Return one CalibrationBucket per model_version for `sku`."""
        with self._lock:
            results: list[CalibrationBucket] = []
            keys = (
                [(sku, model_version)]
                if model_version is not None
                else [k for k in self._calibration if k[0] == sku]
            )
            for key in keys:
                if key not in self._calibration:
                    continue
                results.append(self._aggregate(key[0], key[1], self._calibration[key]))
            return results

    def systematic_bias(
        self,
        min_samples: int = 5,
        bias_threshold: float = 0.05,
    ) -> list[dict[str, Any]]:
        """Find SKUs with significant systematic bias.

        Returns buckets whose mean percentage error exceeds `bias_threshold`
        with at least `min_samples` observations. This drives Vanessa's
        "where are we systematically wrong?" answer and the model registry's
        shadow-mode promotion trigger.
        """
        with self._lock:
            flagged: list[dict[str, Any]] = []
            for (sku, model_version), evaluations in self._calibration.items():
                if len(evaluations) < min_samples:
                    continue
                mean_pct = sum(e.percentage_error for e in evaluations) / len(evaluations)
                if abs(mean_pct) >= bias_threshold:
                    flagged.append(
                        {
                            "sku": sku,
                            "model_version": model_version,
                            "samples": len(evaluations),
                            "mean_pct_error": round(mean_pct, 4),
                            "direction": "under-predicting" if mean_pct > 0 else "over-predicting",
                        }
                    )
            return flagged

    # ── Internals ──────────────────────────────────────────────────────────

    def _aggregate(
        self,
        sku: str,
        model_version: str,
        evaluations: list[ForecastEvaluation],
    ) -> CalibrationBucket:
        n = len(evaluations)
        mae = sum(abs(e.absolute_error) for e in evaluations) / n
        mpe = sum(e.percentage_error for e in evaluations) / n
        bias = sum(e.bias for e in evaluations) / n
        p80 = sum(1 for e in evaluations if e.is_within_p80) / n
        p95 = sum(1 for e in evaluations if e.is_within_p95) / n
        return CalibrationBucket(
            sku=sku,
            model_version=model_version,
            sample_count=n,
            mean_absolute_error=round(mae, 4),
            mean_percentage_error=round(mpe, 4),
            bias=round(bias, 4),
            p80_coverage=round(p80, 4),
            p95_coverage=round(p95, 4),
            last_updated=_utc_now(),
        )


_singleton: TruthLoop | None = None


def get_truth_loop() -> TruthLoop:
    """Return the process-wide singleton TruthLoop."""
    global _singleton
    if _singleton is None:
        _singleton = TruthLoop()
    return _singleton


def reset_truth_loop() -> None:
    """Reset the singleton — used by tests only."""
    global _singleton
    _singleton = None
