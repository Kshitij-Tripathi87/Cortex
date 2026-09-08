"""Tests for the Nexus Demand Intelligence subsystem.

Covers:
- DemandEngine forecast math (baseline, drivers, quantiles, confidence)
- TruthLoop calibration (record forecast, observe actual, compute bias)
- Systematic bias detection
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.nexus_spine.demand import (
    DemandDriver,
    DemandEngine,
    ForecastActual,
    HistoricalDemandPoint,
    ProbabilisticForecast,
    TruthLoop,
    get_demand_engine,
    get_truth_loop,
    reset_demand_engine,
    reset_truth_loop,
)


@pytest.fixture
def engine() -> DemandEngine:
    reset_demand_engine()
    return get_demand_engine()


@pytest.fixture
def truth_loop() -> TruthLoop:
    reset_truth_loop()
    return get_truth_loop()


def _now() -> datetime:
    return datetime.now(UTC)


def _point(days_ago: int, qty: float, sku: str = "SKU-1") -> HistoricalDemandPoint:
    return HistoricalDemandPoint(
        timestamp=_now() - timedelta(days=days_ago),
        sku=sku,
        quantity=qty,
    )


# ──────────────────────────────────────────────────────────────────────────────
# DemandEngine
# ──────────────────────────────────────────────────────────────────────────────


def test_engine_with_empty_history_returns_zero(engine: DemandEngine):
    f = engine.forecast(sku="UNKNOWN", horizon_days=7)
    assert f.p50 == 0.0
    assert f.confidence == 0.0


def test_engine_baseline_uses_recent_history(engine: DemandEngine):
    for d in range(30):
        engine.record_history([_point(d, qty=100.0)])
    f = engine.forecast(sku="SKU-1", horizon_days=7)
    # 100/day * 7 days = 700
    assert f.p50 == pytest.approx(700.0, rel=0.05)


def test_engine_drivers_modify_baseline(engine: DemandEngine):
    for d in range(30):
        engine.record_history([_point(d, qty=100.0)])
    f = engine.forecast(
        sku="SKU-1",
        horizon_days=7,
        drivers=[
            DemandDriver(name="promo", magnitude_pct=0.20, confidence=0.9),
            DemandDriver(name="inventory_constraint", magnitude_pct=-0.10, confidence=0.8),
        ],
    )
    # baseline 700 * 1.20 * 0.90 = 756
    assert f.p50 == pytest.approx(756.0, rel=0.05)
    assert {d.name for d in f.primary_drivers} == {"promo", "inventory_constraint"}


def test_engine_quantiles_spread_proportional_to_volatility(engine: DemandEngine):
    # Low-volatility series
    for d in range(30):
        engine.record_history([_point(d, qty=100.0)])
    f_low = engine.forecast(sku="SKU-1", horizon_days=7)
    engine.clear_history()
    # High-volatility series
    for d in range(30):
        engine.record_history([_point(d, qty=100.0 + (50 if d % 2 == 0 else -50))])
    f_high = engine.forecast(sku="SKU-1", horizon_days=7)
    assert f_high.p95 > f_low.p95


def test_engine_confidence_uses_sample_size_and_freshness(engine: DemandEngine):
    # Many fresh points → high confidence
    for d in range(30):
        engine.record_history([_point(d, qty=100.0)])
    f = engine.forecast(sku="SKU-1", horizon_days=7)
    assert f.confidence > 0.5

    engine.clear_history()
    # Single stale point → low confidence
    engine.record_history([_point(60, qty=100.0)])
    f = engine.forecast(sku="SKU-1", horizon_days=7)
    assert f.confidence < 0.5


def test_engine_backtest_wape_is_bounded(engine: DemandEngine):
    for d in range(40):
        engine.record_history([_point(d, qty=100.0)])
    f = engine.forecast(sku="SKU-1", horizon_days=7)
    assert 0.0 <= f.backtest_wape <= 1.0


def test_engine_volatility_coefficient_is_zero_for_constant_series(engine: DemandEngine):
    for d in range(30):
        engine.record_history([_point(d, qty=100.0)])
    f = engine.forecast(sku="SKU-1", horizon_days=7)
    assert f.volatility_coefficient == 0.0


def test_engine_to_dict_round_trips(engine: DemandEngine):
    for d in range(30):
        engine.record_history([_point(d, qty=100.0)])
    f = engine.forecast(sku="SKU-1", horizon_days=7)
    d = f.to_dict()
    assert d["sku"] == "SKU-1"
    assert d["model_version"] == engine.MODEL_VERSION
    assert "primary_drivers" in d


# ──────────────────────────────────────────────────────────────────────────────
# TruthLoop
# ──────────────────────────────────────────────────────────────────────────────


def test_truth_loop_records_forecast_and_observes_actual(truth_loop: TruthLoop):
    f = ProbabilisticForecast(
        forecast_id="fc-1",
        sku="SKU-1",
        horizon_days=7,
        forecast_timestamp=_now(),
        p50=100.0,
        p80=120.0,
        p95=140.0,
        confidence=0.8,
        primary_drivers=[],
        model_version="v0",
        backtest_wape=0.05,
        baseline_qty=100.0,
        data_freshness_seconds=0.0,
        volatility_coefficient=0.0,
    )
    truth_loop.record_forecast(f)
    evaluation = truth_loop.observe(
        ForecastActual(
            forecast_id="fc-1",
            sku="SKU-1",
            horizon_days=7,
            observed_at=_now(),
            actual_quantity=110.0,
        )
    )
    assert evaluation is not None
    assert evaluation.absolute_error == pytest.approx(10.0)
    assert evaluation.percentage_error == pytest.approx(0.10)
    assert evaluation.is_within_p80 is True
    assert evaluation.is_within_p95 is True


def test_truth_loop_returns_none_for_unknown_forecast(truth_loop: TruthLoop):
    e = truth_loop.observe(
        ForecastActual(
            forecast_id="unknown",
            sku="X",
            horizon_days=1,
            observed_at=_now(),
            actual_quantity=10.0,
        )
    )
    assert e is None


def test_truth_loop_aggregates_calibration(truth_loop: TruthLoop):
    # Three forecasts, two over-predicts and one under-predict
    for i, actual in enumerate([90, 95, 110]):
        f = ProbabilisticForecast(
            forecast_id=f"fc-{i}",
            sku="SKU-1",
            horizon_days=7,
            forecast_timestamp=_now(),
            p50=100.0,
            p80=130.0,
            p95=150.0,
            confidence=0.7,
            primary_drivers=[],
            model_version="v0",
            backtest_wape=0.05,
            baseline_qty=100.0,
            data_freshness_seconds=0.0,
            volatility_coefficient=0.1,
        )
        truth_loop.record_forecast(f)
        truth_loop.observe(
            ForecastActual(
                forecast_id=f"fc-{i}",
                sku="SKU-1",
                horizon_days=7,
                observed_at=_now(),
                actual_quantity=actual,
            )
        )
    buckets = truth_loop.calibration_for("SKU-1")
    assert len(buckets) == 1
    bucket = buckets[0]
    assert bucket.sample_count == 3
    assert bucket.sku == "SKU-1"
    assert bucket.mean_percentage_error < 0  # over-prediction on average


def test_truth_loop_flags_systematic_bias(truth_loop: TruthLoop):
    # Forecast always 100, actual always 130 → 30% under-prediction bias
    for i in range(10):
        f = ProbabilisticForecast(
            forecast_id=f"fc-{i}",
            sku="SKU-A",
            horizon_days=7,
            forecast_timestamp=_now(),
            p50=100.0,
            p80=200.0,
            p95=300.0,
            confidence=0.7,
            primary_drivers=[],
            model_version="v0",
            backtest_wape=0.0,
            baseline_qty=100.0,
            data_freshness_seconds=0.0,
            volatility_coefficient=0.0,
        )
        truth_loop.record_forecast(f)
        truth_loop.observe(
            ForecastActual(
                forecast_id=f"fc-{i}",
                sku="SKU-A",
                horizon_days=7,
                observed_at=_now(),
                actual_quantity=130.0,
            )
        )
    flagged = truth_loop.systematic_bias(min_samples=5, bias_threshold=0.05)
    assert any(b["sku"] == "SKU-A" and b["direction"] == "under-predicting" for b in flagged)


def test_truth_loop_does_not_flag_minor_bias(truth_loop: TruthLoop):
    # Small bias below threshold → not flagged
    for i in range(10):
        f = ProbabilisticForecast(
            forecast_id=f"fc-{i}",
            sku="SKU-B",
            horizon_days=7,
            forecast_timestamp=_now(),
            p50=100.0,
            p80=200.0,
            p95=300.0,
            confidence=0.7,
            primary_drivers=[],
            model_version="v0",
            backtest_wape=0.0,
            baseline_qty=100.0,
            data_freshness_seconds=0.0,
            volatility_coefficient=0.0,
        )
        truth_loop.record_forecast(f)
        truth_loop.observe(
            ForecastActual(
                forecast_id=f"fc-{i}",
                sku="SKU-B",
                horizon_days=7,
                observed_at=_now(),
                actual_quantity=102.0,
            )
        )
    flagged = truth_loop.systematic_bias(min_samples=5, bias_threshold=0.05)
    assert not any(b["sku"] == "SKU-B" for b in flagged)
