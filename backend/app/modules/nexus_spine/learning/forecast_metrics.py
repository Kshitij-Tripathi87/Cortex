"""Nexus v0.7 — Forecast learning metrics.

Expands the TruthLoop foundation to track:
  MAE, RMSE, WAPE, MAPE, MPE
  P50/P80/P95 coverage
  Bias, drift
Segmented by: SKU, supplier, region, product family, time horizon, model version.

This enables Nexus to answer:
  "Where is our forecast wrong?"
rather than just:
  "What is our forecast?"
"""

from __future__ import annotations

import math
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.modules.nexus_spine.demand.engine import ForecastEvaluation


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class SegmentKey:
    """Multi-dimensional segmentation key for forecast accuracy."""
    sku: str | None = None
    supplier_id: str | None = None
    region: str | None = None
    product_family: str | None = None
    horizon_days: int | None = None
    model_version: str | None = None

    def as_tuple(self) -> tuple:
        return (self.sku, self.supplier_id, self.region, self.product_family, self.horizon_days, self.model_version)

    def as_dict(self) -> dict[str, Any]:
        return {
            "sku": self.sku,
            "supplier_id": self.supplier_id,
            "region": self.region,
            "product_family": self.product_family,
            "horizon_days": self.horizon_days,
            "model_version": self.model_version,
        }


@dataclass
class ForecastAccuracyMetrics:
    """Full suite of accuracy metrics for a segment."""
    segment: dict[str, Any]
    sample_count: int
    mae: float                      # Mean Absolute Error
    rmse: float                     # Root Mean Squared Error
    wape: float                     # Weighted Absolute Percentage Error
    mape: float                     # Mean Absolute Percentage Error
    mpe: float                      # Mean Percentage Error (signed: + = under-forecast)
    p50_coverage: float             # Fraction of actuals within P50 (ideally 0.5)
    p80_coverage: float             # Fraction within P80 (ideally 0.8)
    p95_coverage: float             # Fraction within P95 (ideally 0.95)
    bias: float                     # Systematic bias (signed)
    drift_detected: bool = False    # Whether drift exceeds threshold
    drift_magnitude: float = 0.0    # Size of recent drift vs historical
    last_updated: datetime = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment": self.segment,
            "sample_count": self.sample_count,
            "mae": round(self.mae, 4),
            "rmse": round(self.rmse, 4),
            "wape": round(self.wape, 4),
            "mape": round(self.mape, 4),
            "mpe": round(self.mpe, 4),
            "p50_coverage": round(self.p50_coverage, 4),
            "p80_coverage": round(self.p80_coverage, 4),
            "p95_coverage": round(self.p95_coverage, 4),
            "bias": round(self.bias, 4),
            "drift_detected": self.drift_detected,
            "drift_magnitude": round(self.drift_magnitude, 4),
            "last_updated": self.last_updated.isoformat(),
            "reliability_score": round(self._reliability(), 4),
        }

    def _reliability(self) -> float:
        """Compute a single reliability score (0-1) combining multiple factors.

        Used by the Supply Chain Truth dashboard (item 13).
        """
        if self.sample_count < 3:
            return 0.5  # Insufficient data
        # Calibration: how close coverage is to ideal
        cal_p50 = 1.0 - min(1.0, abs(self.p50_coverage - 0.5) / 0.5)
        cal_p80 = 1.0 - min(1.0, abs(self.p80_coverage - 0.8) / 0.8)
        cal_p95 = 1.0 - min(1.0, abs(self.p95_coverage - 0.95) / 0.95)
        calibration = (cal_p50 + cal_p80 + cal_p95) / 3
        # Bias penalization
        bias_penalty = max(0.0, 1.0 - abs(self.mpe) * 2)
        # WAPE: lower is better, but cap at 0.3 (30% error = poor but usable)
        wape_score = max(0.0, 1.0 - self.wape / 0.5)
        # Drift penalty
        drift_penalty = 0.7 if self.drift_detected else 1.0
        return max(0.0, min(1.0, (calibration * 0.4 + bias_penalty * 0.25 + wape_score * 0.25) * drift_penalty))


@dataclass
class DriftAlert:
    """Detected forecast drift in a segment."""
    segment: dict[str, Any]
    metric: str            # which metric drifted (mpe, wape, p80_coverage)
    historical_value: float
    recent_value: float
    magnitude: float
    detected_at: datetime = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment": self.segment,
            "metric": self.metric,
            "historical_value": round(self.historical_value, 4),
            "recent_value": round(self.recent_value, 4),
            "magnitude": round(self.magnitude, 4),
            "detected_at": self.detected_at.isoformat(),
        }


class ForecastMetricsTracker:
    """Tracks forecast accuracy across all segments and detects drift.

    Thread-safe. Persists evaluations in memory (can be backfilled from DB
    on startup).
    """

    DRIFT_WINDOW = 10       # compare last N evaluations vs prior
    DRIFT_THRESHOLD = 0.15  # 15% change triggers drift alert

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._evaluations: list[dict[str, Any]] = []
        self._drift_alerts: list[DriftAlert] = []

    def record(
        self,
        evaluation: ForecastEvaluation,
        *,
        sku: str | None = None,
        supplier_id: str | None = None,
        region: str | None = None,
        product_family: str | None = None,
        horizon_days: int | None = None,
        model_version: str = "baseline-v1",
        predicted_p80: float | None = None,
        predicted_p95: float | None = None,
        predicted_p50_low: float | None = None,
        predicted_p50_high: float | None = None,
    ) -> None:
        """Record one forecast evaluation with full segmentation data."""
        with self._lock:
            self._evaluations.append({
                "sku": sku or evaluation.sku,
                "supplier_id": supplier_id,
                "region": region,
                "product_family": product_family,
                "horizon_days": horizon_days,
                "model_version": model_version,
                "predicted_p50": evaluation.predicted_p50,
                "predicted_p80": predicted_p80,
                "predicted_p95": predicted_p95,
                "actual": evaluation.actual,
                "absolute_error": evaluation.absolute_error,
                "percentage_error": evaluation.percentage_error,
                "bias": evaluation.bias,
                "within_p80": evaluation.is_within_p80 if predicted_p80 is not None else None,
                "within_p95": evaluation.is_within_p95 if predicted_p95 is not None else None,
                "timestamp": _utc_now(),
            })
            # Drift detection
            self._detect_drift_locked(
                SegmentKey(sku=evaluation.sku, supplier_id=supplier_id, model_version=model_version)
            )

    def get_metrics(
        self,
        *,
        sku: str | None = None,
        supplier_id: str | None = None,
        region: str | None = None,
        product_family: str | None = None,
        horizon_days: int | None = None,
        model_version: str | None = None,
    ) -> list[ForecastAccuracyMetrics]:
        """Get accuracy metrics for matching segments."""
        with self._lock:
            buckets: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
            for ev in self._evaluations:
                if sku and ev["sku"] != sku:
                    continue
                if supplier_id and ev["supplier_id"] != supplier_id:
                    continue
                if region and ev["region"] != region:
                    continue
                if product_family and ev["product_family"] != product_family:
                    continue
                if horizon_days and ev["horizon_days"] != horizon_days:
                    continue
                if model_version and ev["model_version"] != model_version:
                    continue
                key = SegmentKey(
                    sku=ev["sku"] if sku is None else None,
                    supplier_id=ev["supplier_id"] if supplier_id is None else None,
                    region=ev["region"] if region is None else None,
                    product_family=ev["product_family"] if product_family is None else None,
                    horizon_days=ev["horizon_days"] if horizon_days is None else None,
                    model_version=ev["model_version"] if model_version is None else None,
                ).as_tuple()
                buckets[key].append(ev)

            results = []
            for key, evs in buckets.items():
                sk, sup, reg, pf, hor, mv = key
                segment = {
                    "sku": sk, "supplier_id": sup, "region": reg,
                    "product_family": pf, "horizon_days": hor, "model_version": mv,
                }
                metrics = self._compute_metrics(segment, evs)
                if metrics:
                    results.append(metrics)
            results.sort(key=lambda m: (m.sample_count, -abs(m.mpe)), reverse=True)
            return results

    def get_drift_alerts(self, *, min_magnitude: float = DRIFT_THRESHOLD) -> list[DriftAlert]:
        with self._lock:
            return [a for a in self._drift_alerts if a.magnitude >= min_magnitude]

    def where_is_forecast_wrong(self, *, min_samples: int = 5, min_abs_mpe: float = 0.05) -> list[dict[str, Any]]:
        """Answer the key question: where is our forecast systematically wrong?

        Returns segments with significant systematic bias, sorted by |MPE|.
        """
        metrics = self.get_metrics()
        flagged = []
        for m in metrics:
            if m.sample_count < min_samples:
                continue
            if abs(m.mpe) < min_abs_mpe:
                continue
            flagged.append({
                **m.to_dict(),
                "direction": "under-forecasting" if m.mpe > 0 else "over-forecasting",
                "severity": "high" if abs(m.mpe) > 0.2 else "medium" if abs(m.mpe) > 0.1 else "low",
            })
        flagged.sort(key=lambda x: abs(x["mpe"]), reverse=True)
        return flagged

    def overall_health(self) -> dict[str, Any]:
        """Aggregate health for the Supply Chain Truth dashboard (item 13)."""
        with self._lock:
            if not self._evaluations:
                return {
                    "accuracy": 0.0,
                    "samples": 0,
                    "wape": 0.0,
                    "bias": 0.0,
                    "drift_alerts": 0,
                    "status": "insufficient_data",
                }
            all_evs = self._evaluations
            n = len(all_evs)
            total_abs_error = sum(abs(e["absolute_error"]) for e in all_evs)
            total_actual = sum(abs(e["actual"]) for e in all_evs)
            mae = total_abs_error / n
            rmse = math.sqrt(sum(e["absolute_error"] ** 2 for e in all_evs) / n)
            wape = total_abs_error / total_actual if total_actual > 0 else 0
            mpe = sum(e["percentage_error"] for e in all_evs) / n
            mape = sum(abs(e["percentage_error"]) for e in all_evs) / n
            p80_cov = sum(1 for e in all_evs if e["within_p80"]) / n if any(e["within_p80"] is not None for e in all_evs) else 0.8
            p95_cov = sum(1 for e in all_evs if e["within_p95"]) / n if any(e["within_p95"] is not None for e in all_evs) else 0.95
            active_drifts = len([a for a in self._drift_alerts if a.magnitude >= self.DRIFT_THRESHOLD])

            reliability = ForecastAccuracyMetrics(
                segment={"scope": "global"},
                sample_count=n,
                mae=mae, rmse=rmse, wape=wape, mape=mape, mpe=mpe,
                p50_coverage=0.5, p80_coverage=p80_cov, p95_coverage=p95_cov,
                bias=sum(e["bias"] for e in all_evs) / n,
                drift_detected=active_drifts > 0,
                drift_magnitude=0.0,
            )._reliability()

            return {
                "accuracy": round(reliability, 4),
                "samples": n,
                "mae": round(mae, 4),
                "rmse": round(rmse, 4),
                "wape": round(wape, 4),
                "mape": round(mape, 4),
                "mpe": round(mpe, 4),
                "p80_coverage": round(p80_cov, 4),
                "p95_coverage": round(p95_cov, 4),
                "drift_alerts": active_drifts,
                "status": "degraded" if active_drifts > 0 or reliability < 0.7 else "healthy",
            }

    # ── Internals ──────────────────────────────────────────────────────

    def _compute_metrics(self, segment: dict[str, Any], evs: list[dict[str, Any]]) -> ForecastAccuracyMetrics | None:
        if not evs:
            return None
        n = len(evs)
        abs_errors = [abs(e["absolute_error"]) for e in evs]
        pct_errors = [e["percentage_error"] for e in evs]
        actuals = [e["actual"] for e in evs]
        biases = [e["bias"] for e in evs]

        mae = sum(abs_errors) / n
        rmse = math.sqrt(sum(e ** 2 for e in abs_errors) / n)
        total_abs_error = sum(abs_errors)
        total_actual = sum(abs(a) for a in actuals)
        wape = total_abs_error / total_actual if total_actual > 0 else mae
        mape = sum(abs(p) for p in pct_errors) / n
        mpe = sum(pct_errors) / n
        bias = sum(biases) / n

        within_p80 = [e for e in evs if e["within_p80"] is True]
        within_p95 = [e for e in evs if e["within_p95"] is True]
        p80_cov = len(within_p80) / n if within_p80 else 0.8
        p95_cov = len(within_p95) / n if within_p95 else 0.95

        # Drift: compare recent half vs first half
        drift_detected = False
        drift_magnitude = 0.0
        if n >= self.DRIFT_WINDOW * 2:
            mid = n // 2
            old_mpe = sum(pct_errors[:mid]) / mid
            new_mpe = sum(pct_errors[mid:]) / mid
            drift_magnitude = abs(new_mpe - old_mpe)
            drift_detected = drift_magnitude >= self.DRIFT_THRESHOLD

        return ForecastAccuracyMetrics(
            segment=segment,
            sample_count=n,
            mae=mae, rmse=rmse, wape=wape, mape=mape, mpe=mpe,
            p50_coverage=0.5, p80_coverage=p80_cov, p95_coverage=p95_cov,
            bias=bias,
            drift_detected=drift_detected,
            drift_magnitude=drift_magnitude,
        )

    def _detect_drift_locked(self, key: SegmentKey) -> None:
        matching = [e for e in self._evaluations if (
            (key.sku is None or e["sku"] == key.sku) and
            (key.supplier_id is None or e["supplier_id"] == key.supplier_id) and
            (key.model_version is None or e["model_version"] == key.model_version)
        )]
        if len(matching) < self.DRIFT_WINDOW * 2:
            return
        recent = matching[-self.DRIFT_WINDOW:]
        historical = matching[-self.DRIFT_WINDOW*2:-self.DRIFT_WINDOW]
        rec_mpe = sum(e["percentage_error"] for e in recent) / len(recent)
        hist_mpe = sum(e["percentage_error"] for e in historical) / len(historical)
        magnitude = abs(rec_mpe - hist_mpe)
        if magnitude >= self.DRIFT_THRESHOLD:
            self._drift_alerts.append(DriftAlert(
                segment=key.as_dict(),
                metric="mpe",
                historical_value=hist_mpe,
                recent_value=rec_mpe,
                magnitude=magnitude,
            ))


_singleton: ForecastMetricsTracker | None = None


def get_forecast_metrics_tracker() -> ForecastMetricsTracker:
    global _singleton
    if _singleton is None:
        _singleton = ForecastMetricsTracker()
    return _singleton


def reset_forecast_metrics_tracker() -> None:
    global _singleton
    _singleton = None
