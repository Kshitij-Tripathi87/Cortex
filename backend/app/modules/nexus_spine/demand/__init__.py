"""Nexus Demand Intelligence — Probabilistic Demand Engine + Truth Loop.

Public API:
- DemandEngine / get_demand_engine(): produce probabilistic forecasts
- ProbabilisticForecast, DemandDriver, HistoricalDemandPoint, ForecastActual
- TruthLoop / get_truth_loop(): record forecasts, observe actuals, compute
  per-(sku, model_version) calibration statistics
- CalibrationBucket, ForecastEvaluation, systematic_bias()

The engine is intentionally a transparent, deterministic heuristic. The
output schema (P50/P80/P95 + confidence + drivers + backtest WAPE) is
stable so a future trained model can drop in without breaking callers.
"""

from app.modules.nexus_spine.demand.engine import (
    DemandDriver,
    DemandEngine,
    ForecastActual,
    ForecastEvaluation,
    HistoricalDemandPoint,
    ProbabilisticForecast,
    get_demand_engine,
    reset_demand_engine,
)
from app.modules.nexus_spine.demand.truth_loop import (
    CalibrationBucket,
    TruthLoop,
    get_truth_loop,
    reset_truth_loop,
)

__all__ = [
    "CalibrationBucket",
    "DemandDriver",
    "DemandEngine",
    "ForecastActual",
    "ForecastEvaluation",
    "HistoricalDemandPoint",
    "ProbabilisticForecast",
    "TruthLoop",
    "get_demand_engine",
    "get_truth_loop",
    "reset_demand_engine",
    "reset_truth_loop",
]
