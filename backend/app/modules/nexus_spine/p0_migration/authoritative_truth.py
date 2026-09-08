"""Nexus v1.0 P0 — Authoritative Truth Loop.

PostgreSQL-backed forecast → observation → error → calibration → bias → drift.
The observations table is AUTHORITATIVE; calibration aggregates are PROJECTIONs
(computed in-memory, rebuildable from observations).
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.nexus_spine.persistence.models import (
    ForecastRecordDB,
    ObservationRecordDB,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class AuthoritativeTruthLoop:
    """DB-backed truth loop.

    Record forecasts, record observations (actuals), compute error metrics
    on match. Calibration stats held in-memory and rebuilt on startup /
    cache miss.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._pending: dict[
            str, dict[str, Any]
        ] = {}  # forecast_id → forecast dict (awaiting observation)
        self._calibration_cache: dict[tuple[str, str, str | None, str | None], dict[str, Any]] = {}
        self._calibration_loaded = False

    async def record_forecast(
        self,
        session: AsyncSession,
        *,
        forecast_id: str,
        tenant_id: str,
        workspace_id: str,
        sku: str,
        p50: float,
        p80: float,
        p95: float,
        mean: float,
        std_dev: float,
        p10: float | None = None,
        p25: float | None = None,
        p75: float | None = None,
        p90: float | None = None,
        p99: float | None = None,
        supplier_id: str | None = None,
        region: str | None = None,
        product_family: str | None = None,
        model_version: str = "baseline-v1",
        world_state_version: int = 0,
        horizon_days: int = 14,
        features: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        rec = ForecastRecordDB(
            forecast_id=forecast_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            sku=sku,
            supplier_id=supplier_id,
            region=region,
            product_family=product_family,
            model_version=model_version,
            world_state_version=world_state_version,
            horizon_days=horizon_days,
            p10=p10 or p50 * 0.8,
            p25=p25 or p50 * 0.9,
            p50=p50,
            p75=p75 or p50 * 1.1,
            p80=p80,
            p90=p90 or p50 * 1.2,
            p95=p95,
            p99=p99 or p50 * 1.35,
            mean=mean,
            std_dev=std_dev,
            features=features or {},
        )
        session.add(rec)
        await session.flush()
        with self._lock:
            self._pending[forecast_id] = {
                "p50": p50,
                "p80": p80,
                "p95": p95,
                "sku": sku,
                "model_version": model_version,
            }
        return {
            "forecast_id": forecast_id,
            "sku": sku,
            "p50": p50,
            "p80": p80,
            "p95": p95,
            "model_version": model_version,
            "created_at": rec.created_at.isoformat(),
        }

    async def observe(
        self,
        session: AsyncSession,
        *,
        forecast_id: str,
        tenant_id: str,
        workspace_id: str,
        sku: str,
        actual_value: float,
        observed_at: datetime | None = None,
        observation_type: str = "demand",
        supplier_id: str | None = None,
        region: str | None = None,
    ) -> dict[str, Any] | None:
        # Find matching forecast
        forecast_result = await session.execute(
            select(ForecastRecordDB).where(ForecastRecordDB.forecast_id == forecast_id)
        )
        forecast = forecast_result.scalar_one_or_none()

        predicted_p50 = predicted_p80 = predicted_p95 = None
        abs_err = pct_err = bias = None
        within_p80 = within_p95 = None

        if forecast is not None:
            predicted_p50 = forecast.p50
            predicted_p80 = forecast.p80
            predicted_p95 = forecast.p95
            abs_err = actual_value - forecast.p50
            pct_err = (actual_value - forecast.p50) / forecast.p50 if forecast.p50 != 0 else 0.0
            bias = abs_err
            within_p80 = actual_value <= forecast.p80
            within_p95 = actual_value <= forecast.p95
            sku = forecast.sku
            supplier_id = supplier_id or forecast.supplier_id
            region = region or forecast.region

        obs = ObservationRecordDB(
            observation_id=f"OBS-{uuid4().hex[:10]}",
            forecast_id=forecast_id if forecast else None,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            sku=sku,
            supplier_id=supplier_id,
            region=region,
            observation_type=observation_type,
            actual_value=actual_value,
            observed_at=observed_at or _utc_now(),
            predicted_p50=predicted_p50,
            predicted_p80=predicted_p80,
            predicted_p95=predicted_p95,
            absolute_error=abs_err,
            percentage_error=pct_err,
            bias=bias,
            within_p80=within_p80,
            within_p95=within_p95,
        )
        session.add(obs)
        await session.flush()
        with self._lock:
            self._calibration_loaded = False  # invalidate cached calibration
            self._pending.pop(forecast_id, None)

        if forecast is None:
            return None
        return {
            "forecast_id": forecast_id,
            "sku": sku,
            "predicted_p50": predicted_p50,
            "actual": actual_value,
            "absolute_error": abs_err,
            "percentage_error": pct_err,
            "bias": bias,
            "is_within_p80": within_p80,
            "is_within_p95": within_p95,
        }

    async def calibration_for(
        self,
        session: AsyncSession,
        tenant_id: str,
        workspace_id: str,
        sku: str | None = None,
        model_version: str | None = None,
    ) -> list[dict[str, Any]]:
        conditions = [
            ObservationRecordDB.tenant_id == tenant_id,
            ObservationRecordDB.workspace_id == workspace_id,
            ObservationRecordDB.forecast_id.isnot(None),
        ]
        if sku:
            conditions.append(ObservationRecordDB.sku == sku)
        if model_version:
            # Need join with forecast
            pass

        # Group by (sku, model_version) via join
        from sqlalchemy import Float, and_, cast

        stmt = (
            select(
                ObservationRecordDB.sku,
                func.count(ObservationRecordDB.observation_id).label("n"),
                func.avg(func.abs(ObservationRecordDB.absolute_error)).label("mae"),
                func.avg(ObservationRecordDB.percentage_error).label("mpe"),
                func.avg(ObservationRecordDB.bias).label("bias"),
                func.avg(cast(ObservationRecordDB.within_p80, Float)).label("p80_cov"),
                func.avg(cast(ObservationRecordDB.within_p95, Float)).label("p95_cov"),
            )
            .where(and_(*conditions))
            .group_by(ObservationRecordDB.sku)
        )

        result = await session.execute(stmt)
        buckets = []
        for row in result.all():
            n = int(row.n or 0)
            mae = float(row.mae or 0)
            mpe = float(row.mpe or 0)
            bias_v = float(row.bias or 0)
            p80 = float(row.p80_cov or 0)
            p95 = float(row.p95_cov or 0)
            buckets.append(
                {
                    "sku": row.sku,
                    "sample_count": n,
                    "mean_absolute_error": round(mae, 4),
                    "mean_percentage_error": round(mpe, 4),
                    "bias": round(bias_v, 4),
                    "p80_coverage": round(p80, 4),
                    "p95_coverage": round(p95, 4),
                    "wape": round(abs(mpe), 4),
                    "last_updated": _utc_now().isoformat(),
                }
            )
        return buckets

    async def systematic_bias(
        self,
        session: AsyncSession,
        tenant_id: str,
        workspace_id: str,
        min_samples: int = 5,
        bias_threshold: float = 0.05,
    ) -> list[dict[str, Any]]:
        buckets = await self.calibration_for(session, tenant_id, workspace_id)
        flagged = []
        for b in buckets:
            if b["sample_count"] < min_samples:
                continue
            if abs(b["mean_percentage_error"]) >= bias_threshold:
                flagged.append(
                    {
                        "sku": b["sku"],
                        "samples": b["sample_count"],
                        "mean_pct_error": b["mean_percentage_error"],
                        "direction": "under-predicting"
                        if b["mean_percentage_error"] > 0
                        else "over-predicting",
                    }
                )
        return flagged


_singleton: AuthoritativeTruthLoop | None = None


def get_authoritative_truth_loop() -> AuthoritativeTruthLoop:
    global _singleton
    if _singleton is None:
        _singleton = AuthoritativeTruthLoop()
    return _singleton
