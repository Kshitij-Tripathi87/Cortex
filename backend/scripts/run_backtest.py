"""Backtest CLI runner — replay a scenario through the Morning Brief engines.

Usage:
    python scripts/run_backtest.py                     # supplier_delay (default)
    python scripts/run_backtest.py --format markdown   # write report to markdown
    python scripts/run_backtest.py --format json        # dump metrics to stdout

Output: accuracy, precision, recall, F1, and per-event breakdown for a single
supplier-delay scenario with known ground-truth labels.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from uuid import UUID

from app.modules.disruption.engines.backtest import BacktestEvent, run_backtest
from app.modules.disruption.scenarios.supplier_delay import build

WS = UUID("55555555-5555-5555-5555-555555555555")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest the supplier_delay MVP wedge scenario.")
    parser.add_argument("--format", choices=["json", "markdown"],
                        default="markdown", help="Output format")
    parser.add_argument("--tolerance", type=float, default=0.70,
                        help="Minimum acceptable accuracy (default 0.70)")
    args = parser.parse_args()

    snapshot, scenario, labels = build()
    started_at = datetime.now(UTC)
    event = BacktestEvent(
        event_id=UUID("eeeeeee1-0000-0000-0000-000000000001"),
        workspace_id=WS,
        snapshot=snapshot,
        scenario=scenario,
        actual_labels=labels,
    )
    report = run_backtest(
        workspace_id=WS,
        events=[event],
        started_at=started_at,
        ended_at=datetime.now(UTC),
    )

    if args.format == "json":
        json.dump(report.to_dict(), sys.stdout, indent=2)
        print()
        return

    _print_markdown(report, args.tolerance)


def _print_markdown(report, tolerance: float) -> None:
    """Print a human-readable markdown backtest report."""
    events = report.events

    print("# Backtest Report")
    print("**Scenario:** supplier_delay (Acme Electronics - 5-day delay)")
    print(f"**Run at**: {report.started_at.isoformat()}")
    print(f"**Duration**: {(report.ended_at - report.started_at).total_seconds():.2f}s")
    print(f"**Event count**: {report.event_count}")
    print()
    print("## Aggregate Metrics")
    print()
    print("| Metric        | Value    |")
    print("|---------------|----------|")
    print(f"| Accuracy      | {report.accuracy:.4f} |")
    print(f"| Precision     | {report.precision:.4f} |")
    print(f"| Recall        | {report.recall:.4f} |")
    print(f"| F1 Score      | {report.f1:.4f} |")
    print(f"| TP / FP / FN  | {report.true_positives} / {report.false_positives} / {report.false_negatives} |")
    print()

    if report.accuracy >= tolerance:
        print(f"[OK] ACCEPTED (accuracy {report.accuracy:.4f} >= tolerance {tolerance})")
    else:
        print(f"[FAIL] BELOW TOLERANCE (accuracy {report.accuracy:.4f} < {tolerance})")
        sys.exit(1)

    print()
    print("## Per-Event Breakdown")
    for event in events:
        print(f"Event: {event.event_id}")
        print(f"- Predicted components: {len(event.predicted_component_ids)}")
        print(f"- Predicted products: {len(event.predicted_product_ids)}")
        print(f"- Predicted orders: {len(event.predicted_order_ids)}")
        print(f"- Predicted warehouses: {len(event.predicted_warehouse_ids)}")
        print(f"- TP={event.true_positives} FP={event.false_positives} FN={event.false_negatives} Total={event.total_predictions}")
        print()


if __name__ == "__main__":
    main()
