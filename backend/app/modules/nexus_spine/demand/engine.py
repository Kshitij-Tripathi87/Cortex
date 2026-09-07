"""Nexus Demand Intelligence — Forecast Models.

The forecast model is intentionally simple: it computes a baseline from
historical demand, then applies adjustments for known drivers (seasonality,
promotions, inventory constraint, recent orders, prices, lead times) and
produces a probabilistic output (P50, P80, P95) plus a confidence score.

The output is rich enough to drive the truth-loop (Phase B.5): every
forecast records its inputs so later when actuals arrive we can compute
the error and bias.

This is NOT a real ML model — it's a transparent, deterministic engine
that:
- documents its assumptions explicitly
- computes confidence from data freshness, volatility, and driver certainty
- exposes its math so Vanessa can explain every number

A future iteration can swap the heuristic baseline for a trained model
without changing the output schema.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class HistoricalDemandPoint:
    """One observation of realized demand at a specific point in time."""

    timestamp: datetime
    sku: str
    quantity: float


@dataclass(frozen=True)
class DemandDriver:
    """One explicit adjustment to the baseline forecast.

    Drivers are first-class so they show up in Vanessa's explanations and
    feed the truth-loop's bias detection (which drivers systematically
    under/over-predict?).
    """

    name: str
    magnitude_pct: float  # signed: +0.10 = +10% lift, -0.05 = -5% reduction
    confidence: float = 0.8  # 0.0-1.0
    rationale: str = ""


@dataclass(frozen=True)
class ProbabilisticForecast:
    """The output of one forecast run.

    Carries:
    - Point forecast (P50)
    - Quantile bounds (P80, P95)
    - Confidence (0-1)
    - Drivers (each contributes to the explanation)
    - Model version (for truth-loop audit)
    - Backtest WAPE on a held-out window (data quality signal)
    """

    forecast_id: str
    sku: str
    horizon_days: int
    forecast_timestamp: datetime
    p50: float
    p80: float
    p95: float
    confidence: float
    primary_drivers: list[DemandDriver]
    model_version: str
    backtest_wape: float
    baseline_qty: float
    data_freshness_seconds: float
    volatility_coefficient: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "forecast_id": self.forecast_id,
            "sku": self.sku,
            "horizon_days": self.horizon_days,
            "forecast_timestamp": self.forecast_timestamp.isoformat(),
            "p50": self.p50,
            "p80": self.p80,
            "p95": self.p95,
            "confidence": self.confidence,
            "primary_drivers": [
                {
                    "name": d.name,
                    "magnitude_pct": d.magnitude_pct,
                    "confidence": d.confidence,
                    "rationale": d.rationale,
                }
                for d in self.primary_drivers
            ],
            "model_version": self.model_version,
            "backtest_wape": self.backtest_wape,
            "baseline_qty": self.baseline_qty,
            "data_freshness_seconds": self.data_freshness_seconds,
            "volatility_coefficient": self.volatility_coefficient,
        }


@dataclass(frozen=True)
class ForecastActual:
    """One realized demand observation used for truth-loop evaluation."""

    forecast_id: str
    sku: str
    horizon_days: int
    observed_at: datetime
    actual_quantity: float


@dataclass(frozen=True)
class ForecastEvaluation:
    """The result of comparing a forecast against its realized actual.

    Used to drive model calibration (e.g. "we systematically over-predict
    perishable SKUs in Region West").
    """

    forecast_id: str
    sku: str
    predicted_p50: float
    actual: float
    absolute_error: float
    percentage_error: float
    bias: float  # signed: positive = under-predicted
    is_within_p80: bool
    is_within_p95: bool


class DemandEngine:
    """Transparent probabilistic forecast engine.

    Inputs:
    - Historical demand observations
    - Demand drivers (seasonality, promotions, inventory, etc.)
    - Horizon (days into the future)
    - Model version (for audit)

    Outputs:
    - ProbabilisticForecast with P50/P80/P95, confidence, drivers, baseline,
      data freshness, volatility, backtest WAPE
    """

    MODEL_VERSION = "Demand-v0.1-heuristic"

    def __init__(self) -> None:
        self._history: list[HistoricalDemandPoint] = []

    def record_history(self, points: Sequence[HistoricalDemandPoint]) -> None:
        """Add historical demand observations (in order, oldest-first)."""
        self._history.extend(points)

    def clear_history(self) -> None:
        self._history = []

    def forecast(
        self,
        *,
        sku: str,
        horizon_days: int,
        drivers: Sequence[DemandDriver] | None = None,
        forecast_id: str | None = None,
        now: datetime | None = None,
        history_for_sku: Sequence[HistoricalDemandPoint] | None = None,
    ) -> ProbabilisticForecast:
        """Produce a probabilistic forecast for `sku` over `horizon_days`.

        `history_for_sku` overrides the engine's recorded history for this
        call (used by tests and by callers that manage history elsewhere).
        """
        now = now or _utc_now()
        drivers_list = list(drivers or [])
        history = list(history_for_sku if history_for_sku is not None else [p for p in self._history if p.sku == sku])

        baseline = self._compute_baseline(history, horizon_days)
        adjusted = self._apply_drivers(baseline, drivers_list)
        p50, p80, p95 = self._derive_quantiles(adjusted, history)
        confidence = self._compute_confidence(history, drivers_list, now)
        volatility = self._volatility_coefficient(history)
        wape = self._backtest_wape(history)
        freshness = (now - max((p.timestamp for p in history), default=now)).total_seconds() if history else 0.0

        return ProbabilisticForecast(
            forecast_id=forecast_id or f"fc_{now.strftime('%Y%m%d%H%M%S')}_{sku}",
            sku=sku,
            horizon_days=horizon_days,
            forecast_timestamp=now,
            p50=p50,
            p80=p80,
            p95=p95,
            confidence=confidence,
            primary_drivers=drivers_list,
            model_version=self.MODEL_VERSION,
            backtest_wape=wape,
            baseline_qty=baseline,
            data_freshness_seconds=freshness,
            volatility_coefficient=volatility,
        )

    def evaluate(
        self,
        forecast: ProbabilisticForecast,
        actual: ForecastActual,
    ) -> ForecastEvaluation:
        """Compare a forecast against a realized actual.

        Bias is signed: positive = under-predicted (actual > forecast),
        negative = over-predicted.
        """
        absolute_error = actual.actual_quantity - forecast.p50
        percentage_error = (
            absolute_error / forecast.p50 if forecast.p50 != 0 else 0.0
        )
        return ForecastEvaluation(
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

    # ── Internals ──────────────────────────────────────────────────────────

    def _compute_baseline(
        self,
        history: Sequence[HistoricalDemandPoint],
        horizon_days: int,
    ) -> float:
        if not history:
            return 0.0
        # Average daily rate from last 30 days (or all available if <30)
        cutoff = max(p.timestamp for p in history) - timedelta(days=30)
        recent = [p for p in history if p.timestamp >= cutoff]
        if not recent:
            recent = list(history)
        total_qty = sum(p.quantity for p in recent)
        # Use total_seconds for sub-day precision — .days truncates toward
        # zero and can drop a whole day when the span is just under N days.
        span_seconds = (max(p.timestamp for p in recent) - min(p.timestamp for p in recent)).total_seconds()
        days = max(span_seconds / 86400.0, 1.0)
        daily_rate = total_qty / days
        return daily_rate * horizon_days

    def _apply_drivers(
        self,
        baseline: float,
        drivers: Sequence[DemandDriver],
    ) -> float:
        adjusted = baseline
        for d in drivers:
            adjusted *= 1.0 + d.magnitude_pct
        return max(adjusted, 0.0)

    def _derive_quantiles(
        self,
        point: float,
        history: Sequence[HistoricalDemandPoint],
    ) -> tuple[float, float, float]:
        """Spread P50/P80/P95 using historical volatility.

        Uses a log-normal-style spread so the upper tail is wider than the
        lower tail (matches real demand distributions).
        """
        vol = self._volatility_coefficient(history)
        sigma = max(vol, 0.05)  # floor sigma to avoid zero-width intervals
        # Approximate normal quantiles (1.28 for P80, 1.65 for P95)
        p80 = point * math.exp(1.28 * sigma * 0.5)
        p95 = point * math.exp(1.65 * sigma * 0.5)
        return point, max(p80, point), max(p95, p80)

    def _compute_confidence(
        self,
        history: Sequence[HistoricalDemandPoint],
        drivers: Sequence[DemandDriver],
        now: datetime,
    ) -> float:
        if not history:
            return 0.0
        # Base confidence from sample size (capped at 30 observations)
        sample_conf = min(len(history) / 30.0, 1.0) * 0.4
        # Freshness confidence (linear decay over 14 days)
        freshness_days = (now - max(p.timestamp for p in history)).total_seconds() / 86400.0
        freshness_conf = max(0.0, 1.0 - freshness_days / 14.0) * 0.3
        # Driver confidence (weighted average)
        if drivers:
            driver_conf = sum(d.confidence for d in drivers) / len(drivers) * 0.3
        else:
            driver_conf = 0.0
        return round(min(sample_conf + freshness_conf + driver_conf, 1.0), 4)

    def _volatility_coefficient(
        self,
        history: Sequence[HistoricalDemandPoint],
    ) -> float:
        if len(history) < 2:
            return 0.0
        qtys = [p.quantity for p in history]
        mean = sum(qtys) / len(qtys)
        if mean == 0:
            return 0.0
        variance = sum((q - mean) ** 2 for q in qtys) / len(qtys)
        stddev = math.sqrt(variance)
        return stddev / mean

    def _backtest_wape(
        self,
        history: Sequence[HistoricalDemandPoint],
        holdout_fraction: float = 0.2,
    ) -> float:
        """Held-out WAPE on the most recent `holdout_fraction` of history."""
        if len(history) < 5:
            return 0.0
        split = int(len(history) * (1 - holdout_fraction))
        if split < 1:
            return 0.0
        train = history[:split]
        holdout = history[split:]
        if not holdout:
            return 0.0
        train_mean = sum(p.quantity for p in train) / len(train)
        if train_mean == 0:
            return 0.0
        abs_errors = [abs(p.quantity - train_mean) for p in holdout]
        wape = sum(abs_errors) / (train_mean * len(holdout))
        return round(min(wape, 1.0), 4)


_singleton: DemandEngine | None = None


def get_demand_engine() -> DemandEngine:
    """Return the process-wide singleton DemandEngine."""
    global _singleton
    if _singleton is None:
        _singleton = DemandEngine()
    return _singleton


def reset_demand_engine() -> None:
    """Reset the singleton — used by tests only."""
    global _singleton
    _singleton = None
