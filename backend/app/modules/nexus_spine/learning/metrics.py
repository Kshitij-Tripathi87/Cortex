"""Nexus v0.7 — Forecast Truth Metrics (Forecast vs Reality).

Extends the Phase-B truth loop with a full accuracy/calibration surface:

    MAE, RMSE, WAPE, MAPE, MPE,
    P50 / P80 / P95 coverage,
    signed bias,
    drift (recent-window MPE minus prior-window MPE)

All functions are pure and deterministic. Evaluations are plain dicts with
at least: `predicted` (P50), `actual`, and optionally `p80`, `p95`,
`observed_at`, plus arbitrary segmentation keys (sku, model_version,
horizon_days, region, supplier_id, product_family).

Aggregation is segmented (`aggregate_segments`) so Nexus can answer
"where is our forecast wrong?" rather than just "what is our forecast?".
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


def _utc_now() -> datetime:
    return datetime.now(UTC)


_EPS = 1e-9


@dataclass(frozen=True)
class MetricPoint:
    """One forecast-vs-actual observation (already matched)."""

    predicted: float
    actual: float
    p50: float
    p80: float | None = None
    p95: float | None = None
    observed_at: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "predicted": self.predicted,
            "actual": self.actual,
            "p50": self.p50,
            "p80": self.p80,
            "p95": self.p95,
            "observed_at": self.observed_at.isoformat() if self.observed_at else None,
        }


@dataclass(frozen=True)
class TruthMetrics:
    """Aggregated accuracy/calibration metrics for one bucket."""

    sample_count: int
    mae: float
    rmse: float
    wape: float | None
    mape: float | None
    mpe: float | None
    bias: float
    bias_pct: float | None
    p50_coverage: float
    p80_coverage: float | None
    p95_coverage: float | None
    accuracy_score: float | None  # 1 - WAPE, clamped to [0, 1]
    drift: float | None = None  # recent-window MPE minus prior-window MPE

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_count": self.sample_count,
            "mae": round(self.mae, 4),
            "rmse": round(self.rmse, 4),
            "wape": None if self.wape is None else round(self.wape, 4),
            "mape": None if self.mape is None else round(self.mape, 4),
            "mpe": None if self.mpe is None else round(self.mpe, 4),
            "bias": round(self.bias, 4),
            "bias_pct": None if self.bias_pct is None else round(self.bias_pct, 4),
            "p50_coverage": round(self.p50_coverage, 4),
            "p80_coverage": None if self.p80_coverage is None else round(self.p80_coverage, 4),
            "p95_coverage": None if self.p95_coverage is None else round(self.p95_coverage, 4),
            "accuracy_score": None
            if self.accuracy_score is None
            else round(self.accuracy_score, 4),
            "drift": None if self.drift is None else round(self.drift, 4),
        }


@dataclass(frozen=True)
class SegmentMetrics:
    """TruthMetrics keyed by one segment combination."""

    segment: dict[str, str]
    metrics: TruthMetrics

    def to_dict(self) -> dict[str, Any]:
        return {"segment": dict(self.segment), "metrics": self.metrics.to_dict()}


def _pct_errors(points: Iterable[MetricPoint]) -> list[float]:
    out: list[float] = []
    for p in points:
        if abs(p.actual) > _EPS:
            out.append((p.actual - p.predicted) / abs(p.actual))
    return out


def compute_truth_metrics(
    points: list[MetricPoint],
    *,
    drift_window: int = 10,
) -> TruthMetrics:
    """Aggregate one bucket of forecast-vs-actual points.

    Drift is computed between the most recent `drift_window` observations
    (by observed_at) and the `drift_window` observations immediately before
    them. If fewer than 2 * drift_window points exist, drift is None.
    """
    n = len(points)
    if n == 0:
        return TruthMetrics(
            sample_count=0,
            mae=0.0,
            rmse=0.0,
            wape=None,
            mape=None,
            mpe=None,
            bias=0.0,
            bias_pct=None,
            p50_coverage=0.0,
            p80_coverage=None,
            p95_coverage=None,
            accuracy_score=None,
            drift=None,
        )

    abs_errors = [abs(p.actual - p.predicted) for p in points]
    errors = [p.actual - p.predicted for p in points]
    mae = sum(abs_errors) / n
    rmse = math.sqrt(sum(e * e for e in errors) / n)

    total_actual = sum(abs(p.actual) for p in points)
    wape = (sum(abs_errors) / total_actual) if total_actual > _EPS else None
    accuracy = None if wape is None else max(0.0, min(1.0, 1.0 - wape))

    pct = _pct_errors(points)
    mpe = (sum(pct) / len(pct)) if pct else None

    abs_pct = [abs(p.actual - p.predicted) / abs(p.actual) for p in points if abs(p.actual) > _EPS]
    mape = (sum(abs_pct) / len(abs_pct)) if abs_pct else None

    bias = sum(errors) / n
    bias_pct = None
    if total_actual > _EPS:
        bias_pct = sum(errors) / total_actual

    p50_cov = sum(1 for p in points if p.actual <= p.p50) / n

    p80_points = [p for p in points if p.p80 is not None]
    p80_cov = (
        sum(1 for p in p80_points if p.actual <= float(p.p80)) / len(p80_points)
        if p80_points
        else None
    )
    p95_points = [p for p in points if p.p95 is not None]
    p95_cov = (
        sum(1 for p in p95_points if p.actual <= float(p.p95)) / len(p95_points)
        if p95_points
        else None
    )

    drift: float | None = None
    if len(points) >= 2 * drift_window:
        ordered = sorted(
            points,
            key=lambda p: p.observed_at or datetime.min.replace(tzinfo=UTC),
        )
        recent = ordered[-drift_window:]
        prior = ordered[-2 * drift_window : -drift_window]
        recent_pct = _pct_errors(recent)
        prior_pct = _pct_errors(prior)
        if recent_pct and prior_pct:
            drift = (sum(recent_pct) / len(recent_pct)) - (sum(prior_pct) / len(prior_pct))

    return TruthMetrics(
        sample_count=n,
        mae=mae,
        rmse=rmse,
        wape=wape,
        mape=mape,
        mpe=mpe,
        bias=bias,
        bias_pct=bias_pct,
        p50_coverage=p50_cov,
        p80_coverage=p80_cov,
        p95_coverage=p95_cov,
        accuracy_score=accuracy,
        drift=drift,
    )


def aggregate_segments(
    points: list[dict[str, Any]],
    *,
    segment_keys: list[str],
    drift_window: int = 10,
) -> list[SegmentMetrics]:
    """Group raw evaluation rows by `segment_keys` and aggregate each.

    Each row needs prediction/actual fields; missing segment values are
    bucketed under "unknown" so every evaluation is accounted for.
    """
    groups: dict[tuple[str, ...], list[MetricPoint]] = {}
    segs: dict[tuple[str, ...], dict[str, str]] = {}
    for row in points:
        key = tuple(str(row.get(k) or "unknown") for k in segment_keys)
        groups.setdefault(key, []).append(_row_to_point(row))
        segs[key] = dict(zip(segment_keys, key, strict=True))
    results: list[SegmentMetrics] = []
    for key, bucket in groups.items():
        results.append(
            SegmentMetrics(
                segment=segs[key],
                metrics=compute_truth_metrics(bucket, drift_window=drift_window),
            )
        )
    results.sort(key=lambda s: (-s.metrics.sample_count, tuple(sorted(s.segment.items()))))
    return results


def _row_to_point(row: dict[str, Any]) -> MetricPoint:
    observed = row.get("observed_at")
    if isinstance(observed, str):
        observed_dt: datetime | None = datetime.fromisoformat(observed)
    else:
        observed_dt = observed if isinstance(observed, datetime) else None
    predicted = float(row.get("predicted_p50", row.get("predicted", 0.0)))
    actual = float(row.get("actual", 0.0))
    p80 = row.get("p80")
    p95 = row.get("p95")
    return MetricPoint(
        predicted=predicted,
        actual=actual,
        p50=float(row.get("p50", predicted)),
        p80=float(p80) if p80 is not None else None,
        p95=float(p95) if p95 is not None else None,
        observed_at=observed_dt,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Legacy bridge — convert engine ForecastEvaluation rows to metric points
# ─────────────────────────────────────────────────────────────────────────────


def evaluation_rows_to_points(rows: list[dict[str, Any]]) -> list[MetricPoint]:
    return [_row_to_point(r) for r in rows]
