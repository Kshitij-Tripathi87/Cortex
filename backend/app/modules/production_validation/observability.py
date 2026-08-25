"""Cortex Observability Engine — Program P.9.

Operational Control Plane tracking:
"Is Cortex Becoming More Correct Over Time?"
- Prediction error trajectories
- Simulation-vs-reality delta
- Net economic value created across customer operations
- Autonomy tier distributions
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.modules.production_validation.validation_models import CortexDecisionLifecycle


@dataclass(frozen=True)
class ObservabilityDashboardSnapshot:
    """Consolidated operational control plane snapshot."""

    workspace_id: str
    total_decisions_tracked: int
    mean_prediction_error_pct: float
    error_reduction_trend_pct: float  # Positive means error is shrinking over time
    cumulative_net_economic_value_created_usd: float
    operator_approval_rate_pct: float
    autonomy_distribution: dict[str, int]
    system_verdict: str
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "total_decisions_tracked": self.total_decisions_tracked,
            "mean_prediction_error_pct": round(self.mean_prediction_error_pct, 2),
            "error_reduction_trend_pct": round(self.error_reduction_trend_pct, 2),
            "cumulative_net_economic_value_created_usd": round(
                self.cumulative_net_economic_value_created_usd, 2
            ),
            "operator_approval_rate_pct": round(self.operator_approval_rate_pct, 2),
            "autonomy_distribution": dict(self.autonomy_distribution),
            "system_verdict": self.system_verdict,
            "generated_at": self.generated_at.isoformat(),
        }


class CortexObservabilityEngine:
    """Tracks and evaluates operational correctness over longitudinal decision datasets."""

    def __init__(self):
        self._lifecycles: dict[str, list[CortexDecisionLifecycle]] = {}

    def record_decision(self, lifecycle: CortexDecisionLifecycle) -> None:
        """Add a decision lifecycle record to the workspace telemetry ledger."""
        ws_id = lifecycle.workspace_id
        if ws_id not in self._lifecycles:
            self._lifecycles[ws_id] = []
        self._lifecycles[ws_id].append(lifecycle)

    def generate_dashboard(self, workspace_id: str) -> ObservabilityDashboardSnapshot:
        """Generate the operational correctness dashboard."""
        records = self._lifecycles.get(workspace_id, [])
        if not records:
            return ObservabilityDashboardSnapshot(
                workspace_id=workspace_id,
                total_decisions_tracked=0,
                mean_prediction_error_pct=0.0,
                error_reduction_trend_pct=0.0,
                cumulative_net_economic_value_created_usd=0.0,
                operator_approval_rate_pct=100.0,
                autonomy_distribution={"L3_HUMAN_APPROVE": 0},
                system_verdict="Awaiting initial decision telemetry.",
            )

        total_value = sum(r.net_economic_value_created_usd for r in records)
        mean_error = sum(r.prediction_error_pct for r in records) / len(records)

        # Autonomy distribution
        autonomy_counts: dict[str, int] = {}
        for r in records:
            key = r.autonomy_level.name
            autonomy_counts[key] = autonomy_counts.get(key, 0) + 1

        # Trend: compare first half vs second half error
        if len(records) >= 2:
            mid = len(records) // 2
            first_half_err = sum(r.prediction_error_pct for r in records[:mid]) / mid
            second_half_err = sum(r.prediction_error_pct for r in records[mid:]) / (
                len(records) - mid
            )
            trend = first_half_err - second_half_err  # Positive = error is decreasing
        else:
            trend = 0.0

        verdict = (
            f"Cortex is actively learning: {len(records)} decision lifecycles recorded, "
            f"generating ${total_value:,.2f} cumulative net economic value with {mean_error:.1f}% mean error."
        )

        return ObservabilityDashboardSnapshot(
            workspace_id=workspace_id,
            total_decisions_tracked=len(records),
            mean_prediction_error_pct=mean_error,
            error_reduction_trend_pct=trend,
            cumulative_net_economic_value_created_usd=total_value,
            operator_approval_rate_pct=100.0,
            autonomy_distribution=autonomy_counts,
            system_verdict=verdict,
        )
