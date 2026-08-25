"""Deterministic backtest runner — replay engine predictions against historical outcomes.

The backtest runner is a pure-functional module (ADR-0003) that compares what the
Morning Brief engines *would have predicted* against what *actually happened* for
a set of historical disruption events. It produces classification metrics —
accuracy, precision, recall, F1 — aligned with the ``analytics.backtest_results``
ORM model (ADR-0013).

Protocol (ADR-0013):
  1. The caller loads historical ``DisruptionEvent`` rows from the DB.
  2. For each event, the caller assembles the ``SupplyChainSnapshot`` as it
     existed *at the time of the event* (point-in-time).
  3. The caller feeds events and snapshots into ``run_backtest()``.
  4. ``run_backtest()`` replays each event through the engines, compares the
     predictions against the actual ground-truth labels, and returns a
     ``BacktestReport`` with aggregate metrics and per-event breakdowns.

Feature gate (ADR-008):
  The caller MUST verify ``is_feature_enabled("FEATURE_BACKTEST")`` before
  invoking the runner. The runner itself is pure computation — it does NOT
  check feature flags or access any infrastructure.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.disruption.engines.brief import run_morning_brief
from app.modules.disruption.engines.types import (
    DisruptionScenario,
    SupplyChainSnapshot,
)


@dataclass(frozen=True)
class BacktestEvent:
    """A single historical event for replay.

    ``snapshot`` is the point-in-time ``SupplyChainSnapshot`` at the moment the
    event was created (what the engines *would have known*).
    ``scenario`` is the ``DisruptionScenario`` record that triggered the
    morning brief.
    ``actual_labels`` contains the ground-truth outcome — which components,
    products, orders, and warehouses were ultimately affected.
    """

    event_id: UUID
    workspace_id: UUID
    snapshot: SupplyChainSnapshot
    scenario: DisruptionScenario
    actual_labels: BacktestLabels


@dataclass(frozen=True)
class BacktestLabels:
    """Ground-truth labels for a single backtest event.

    Each tuple is a set of UUIDs that were **actually** affected by the
    disruption (sourced from logistics events, manual operator resolution,
    or post-mortem analysis). Empty tuples mean none of that type were
    affected.
    """

    affected_component_ids: tuple[UUID, ...] = ()
    affected_product_ids: tuple[UUID, ...] = ()
    affected_order_ids: tuple[UUID, ...] = ()
    affected_warehouse_ids: tuple[UUID, ...] = ()


@dataclass(frozen=True)
class EventBacktestResult:
    """Per-event breakdown produced for every event in a backtest run."""

    event_id: UUID
    workspace_id: UUID
    predicted_component_ids: tuple[UUID, ...]
    predicted_product_ids: tuple[UUID, ...]
    predicted_order_ids: tuple[UUID, ...]
    predicted_warehouse_ids: tuple[UUID, ...]
    true_positives: int
    false_positives: int
    false_negatives: int
    total_predictions: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": str(self.event_id),
            "workspace_id": str(self.workspace_id),
            "predicted_component_ids": [str(c) for c in self.predicted_component_ids],
            "predicted_product_ids": [str(p) for p in self.predicted_product_ids],
            "predicted_order_ids": [str(o) for o in self.predicted_order_ids],
            "predicted_warehouse_ids": [str(w) for w in self.predicted_warehouse_ids],
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "total_predictions": self.total_predictions,
        }


@dataclass
class BacktestReport:
    """Aggregate backtest metrics across all events in a run.

    This is the API-visible shape returned to the caller; the caller is
    responsible for persisting it to ``analytics.backtest_results`` per
    ADR-0013.
    """

    workspace_id: UUID
    started_at: datetime
    ended_at: datetime
    event_count: int
    total_predictions: int
    true_positives: int
    false_positives: int
    false_negatives: int
    accuracy: float
    precision: float
    recall: float
    f1: float
    events: tuple[EventBacktestResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": str(self.workspace_id),
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat(),
            "event_count": self.event_count,
            "total_predictions": self.total_predictions,
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "accuracy": round(self.accuracy, 4),
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "events": [e.to_dict() for e in self.events],
        }


def _evaluate_single(
    event: BacktestEvent,
) -> EventBacktestResult:
    """Replay one historical event through the brief and compute TP/FP/FN."""

    brief = run_morning_brief(event.snapshot, event.scenario)

    predicted_comp = {p.component_id for p in brief.propagation.affected_components}
    predicted_prod = {p.product_id for p in brief.propagation.affected_products}
    predicted_ord = {o.order_id for o in brief.propagation.open_orders_at_risk}
    predicted_wh = {w.warehouse_id for w in brief.propagation.affected_warehouses}

    actual_comp = set(event.actual_labels.affected_component_ids)
    actual_prod = set(event.actual_labels.affected_product_ids)
    actual_ord = set(event.actual_labels.affected_order_ids)
    actual_wh = set(event.actual_labels.affected_warehouse_ids)

    all_predicted = predicted_comp | predicted_prod | predicted_ord | predicted_wh
    all_actual = actual_comp | actual_prod | actual_ord | actual_wh

    tp = len(all_predicted & all_actual)
    fp = len(all_predicted - all_actual)
    fn = len(all_actual - all_predicted)

    return EventBacktestResult(
        event_id=event.event_id,
        workspace_id=event.workspace_id,
        predicted_component_ids=tuple(sorted(predicted_comp)),
        predicted_product_ids=tuple(sorted(predicted_prod)),
        predicted_order_ids=tuple(sorted(predicted_ord)),
        predicted_warehouse_ids=tuple(sorted(predicted_wh)),
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        total_predictions=len(all_predicted),
    )


def run_backtest(
    workspace_id: UUID,
    events: list[BacktestEvent],
    *,
    started_at: datetime,
    ended_at: datetime,
) -> BacktestReport:
    """Replay a set of historical events through the Morning Brief engines.

    For every event the runner:
      1. Invokes ``run_morning_brief(snapshot, scenario)`` to produce predictions.
      2. Compares predicted affected IDs against ``actual_labels``.
      3. Accumulates per-type confusion counts.

    Aggregate accuracy, precision, recall, and F1 are computed from the sum
    of TP, FP, and FN across all events. The empty input returns a report
    where all metrics are 0.0 (not NaN).

    The caller MUST ensure ``FEATURE_BACKTEST`` is enabled before calling
    this function in production code paths.
    """
    event_results: list[EventBacktestResult] = []

    agg_tp = 0
    agg_fp = 0
    agg_fn = 0
    agg_total = 0

    for event in events:
        er = _evaluate_single(event)
        event_results.append(er)
        agg_tp += er.true_positives
        agg_fp += er.false_positives
        agg_fn += er.false_negatives
        agg_total += er.total_predictions

    if agg_total == 0 and agg_tp == 0 and (agg_fp + agg_fn) == 0:
        accuracy = 0.0
        precision = 0.0
        recall = 0.0
        f1 = 0.0
    else:
        total_denom = agg_tp + agg_fp + agg_fn
        accuracy = agg_tp / total_denom if total_denom > 0 else 0.0
        prec_denom = agg_tp + agg_fp
        precision = agg_tp / prec_denom if prec_denom > 0 else 0.0
        rec_denom = agg_tp + agg_fn
        recall = agg_tp / rec_denom if rec_denom > 0 else 0.0
        denom = precision + recall
        f1 = (2 * precision * recall) / denom if denom > 0 else 0.0

    return BacktestReport(
        workspace_id=workspace_id,
        started_at=started_at,
        ended_at=ended_at,
        event_count=len(events),
        total_predictions=agg_total,
        true_positives=agg_tp,
        false_positives=agg_fp,
        false_negatives=agg_fn,
        accuracy=accuracy,
        precision=precision,
        recall=recall,
        f1=f1,
        events=tuple(sorted(event_results, key=lambda e: str(e.event_id))),
    )


__all__ = [
    "BacktestEvent",
    "BacktestLabels",
    "BacktestReport",
    "EventBacktestResult",
    "run_backtest",
]
