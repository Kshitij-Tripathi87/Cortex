"""Fixed-bucket timeline engine — 0/12/24/48/72 hour buckets.

Projects inventory depletion forward from the disruption start time using
the affected-warehouse snapshot produced by the propagation engine.

Design:
  * Pure-function: no DB, no wall-clock beyond scenario ``started_at``.
  * Deterministic: sorted iteration over affected warehouses guarantees the
    same output for identical input.
  * Only 5 buckets: H0/H12/H24/H48/H72 — executives understand time better.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from app.modules.disruption.engines.types import (
    DisruptionScenario,
    PropagationResult,
    StockoutStatus,
    Timeline,
    TimelineBucket,
    TimelineEvent,
)


def build_timeline(
    propagation: PropagationResult,
    scenario: DisruptionScenario,
) -> Timeline:
    """Compute the fixed-bucket inventory-depletion timeline."""

    warehouses = propagation.affected_warehouses
    products = propagation.affected_products

    t0 = scenario.started_at

    earliest_deadline: datetime | None = None
    comp_deadlines: dict[UUID, datetime | None] = {}

    for w in warehouses:
        if w.daily_usage <= 0:
            continue
        hours_left = (w.quantity / w.daily_usage) * 24.0
        comp_dd = t0 + timedelta(hours=hours_left)
        comp_deadlines[w.component_id] = comp_dd
        if earliest_deadline is None or comp_dd < earliest_deadline:
            earliest_deadline = comp_dd

    events: list[TimelineEvent] = []
    for bucket in TimelineBucket.ordered():
        hours = bucket.hour()
        instant = t0 + timedelta(hours=hours)

        status = StockoutStatus.OK
        at_risk_comp: set[UUID] = set()
        at_risk_prod: set[UUID] = set()

        for w in warehouses:
            q = _qty_after_hours(w.quantity, w.daily_usage, hours)

            if q <= 0:
                if status not in (StockoutStatus.STOCKED_OUT,):
                    status = StockoutStatus.STOCKED_OUT
                at_risk_comp.add(w.component_id)
            elif q <= w.safety_stock:
                if status == StockoutStatus.OK:
                    status = StockoutStatus.AT_SAFETY
                at_risk_comp.add(w.component_id)
            elif q <= w.safety_stock * 1.2:
                if status == StockoutStatus.OK:
                    status = StockoutStatus.BELOW_SAFETY

        for p in products:
            if p.component_id in at_risk_comp:
                at_risk_prod.add(p.product_id)

        events.append(
            TimelineEvent(
                bucket=bucket,
                hours_from_start=hours,
                title=_title(bucket, status),
                description=_description(bucket, status, earliest_deadline, instant),
                stockout_status=status,
                affected_component_ids=tuple(sorted(at_risk_comp, key=str)),
                affected_product_ids=tuple(sorted(at_risk_prod, key=str)),
            )
        )

    return Timeline(
        bucket_zero=t0,
        events=tuple(events),
        stockout_deadline_at=earliest_deadline,
    )


def _qty_after_hours(quantity: int, daily_usage: int, hours: float) -> float:
    consumed = (daily_usage / 24.0) * hours
    return max(0.0, float(quantity) - consumed)


def _title(bucket: TimelineBucket, status: StockoutStatus) -> str:
    labels = {
        StockoutStatus.OK: "Normal operations",
        StockoutStatus.AT_SAFETY: "At safety stock threshold",
        StockoutStatus.BELOW_SAFETY: "Below safety stock",
        StockoutStatus.STOCKED_OUT: "Component stockout",
    }
    return f"Hour {bucket.hour()}: {labels.get(status, status.value)}"


def _description(
    bucket: TimelineBucket,
    status: StockoutStatus,
    deadline: datetime | None,
    instant: datetime,
) -> str:
    if deadline is None:
        return "No projected stockout under current usage rates."
    remaining_h = (deadline - instant).total_seconds() / 3600.0
    if remaining_h > 0:
        return f"Stockout projected in ~{remaining_h:.0f} hours"
    return "Already stocked out"


__all__ = ["build_timeline"]
