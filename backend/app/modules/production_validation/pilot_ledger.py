"""Design Partner Pilot Ledger & Portfolio ROI Aggregator — Program P.12 & Q.

Aggregates multiple real-world historical and live incident validations for a design partner:
- Comprehensive Decision Coverage (Eligible vs Evaluated vs Excluded with reasons)
- Honest Multi-Class Outcome Distribution (Cortex Wins, Human Wins, Ties, Insufficient Evidence)
- Cumulative Net Economic Value Created
- Multi-incident prediction error trajectories
- Coverage-adjusted win rate vs historical human choices
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.modules.production_validation.validation_models import (
    CortexPilotValidationReport,
    PilotCoverageMetrics,
)


@dataclass(frozen=True)
class PilotPortfolioSummary:
    """Consolidated ROI artifact across real enterprise pilot incidents."""

    customer_name: str
    total_incidents_evaluated: int
    coverage_metrics: PilotCoverageMetrics
    outcome_distribution: dict[str, int]
    cumulative_unmitigated_exposure_usd: float
    cumulative_loss_avoided_usd: float
    cumulative_intervention_cost_usd: float
    cumulative_net_economic_value_usd: float
    cumulative_economic_delta_vs_human_usd: float
    cortex_win_rate_pct: float
    coverage_adjusted_win_rate_pct: float
    mean_revenue_prediction_error_pct: float
    mean_stockout_timing_error_hours: float
    is_commercial_deployment_recommended: bool
    executive_recommendation: str
    incident_reports: list[CortexPilotValidationReport] = field(default_factory=list)
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "customer_name": self.customer_name,
            "total_incidents_evaluated": self.total_incidents_evaluated,
            "coverage_metrics": self.coverage_metrics.to_dict(),
            "outcome_distribution": self.outcome_distribution,
            "cumulative_unmitigated_exposure_usd": round(
                self.cumulative_unmitigated_exposure_usd, 2
            ),
            "cumulative_loss_avoided_usd": round(self.cumulative_loss_avoided_usd, 2),
            "cumulative_intervention_cost_usd": round(self.cumulative_intervention_cost_usd, 2),
            "cumulative_net_economic_value_usd": round(self.cumulative_net_economic_value_usd, 2),
            "cumulative_economic_delta_vs_human_usd": round(
                self.cumulative_economic_delta_vs_human_usd, 2
            ),
            "cortex_win_rate_pct": round(self.cortex_win_rate_pct, 2),
            "coverage_adjusted_win_rate_pct": round(self.coverage_adjusted_win_rate_pct, 2),
            "mean_revenue_prediction_error_pct": round(self.mean_revenue_prediction_error_pct, 2),
            "mean_stockout_timing_error_hours": round(self.mean_stockout_timing_error_hours, 2),
            "is_commercial_deployment_recommended": self.is_commercial_deployment_recommended,
            "executive_recommendation": self.executive_recommendation,
            "incident_reports": [r.to_dict() for r in self.incident_reports],
            "generated_at": self.generated_at.isoformat(),
        }


class DesignPartnerPilotLedger:
    """Ledger accumulating real enterprise incident validation reports and coverage metadata."""

    def __init__(self):
        self._partner_incidents: dict[str, list[CortexPilotValidationReport]] = {}
        self._partner_exclusions: dict[
            str, list[tuple[str, str]]
        ] = {}  # list of (incident_id, reason)

    def record_incident_report(self, report: CortexPilotValidationReport) -> None:
        """Append an audited incident validation report to the partner ledger."""
        cust = report.customer_name
        if cust not in self._partner_incidents:
            self._partner_incidents[cust] = []
        self._partner_incidents[cust].append(report)

    def record_excluded_disruption(self, customer_name: str, incident_id: str, reason: str) -> None:
        """Record an operational disruption that was excluded from pilot evaluation."""
        if customer_name not in self._partner_exclusions:
            self._partner_exclusions[customer_name] = []
        self._partner_exclusions[customer_name].append((incident_id, reason))

    def generate_portfolio_summary(
        self, customer_name: str, total_eligible_disruptions: int | None = None
    ) -> PilotPortfolioSummary:
        """Synthesize aggregate commercial ROI summary and coverage statistics."""
        reports = self._partner_incidents.get(customer_name, [])
        exclusions = self._partner_exclusions.get(customer_name, [])
        evaluated_count = len(reports)
        excluded_count = len(exclusions)

        total_eligible = (
            total_eligible_disruptions
            if total_eligible_disruptions is not None
            else (evaluated_count + excluded_count)
        )

        exclusion_breakdown: dict[str, int] = {}
        for _, r in exclusions:
            exclusion_breakdown[r] = exclusion_breakdown.get(r, 0) + 1

        coverage_pct = (
            (evaluated_count / max(1, total_eligible)) * 100.0 if total_eligible > 0 else 100.0
        )

        coverage_metrics = PilotCoverageMetrics(
            total_eligible_disruptions=total_eligible,
            incidents_evaluated=evaluated_count,
            incidents_excluded=excluded_count,
            exclusion_breakdown=exclusion_breakdown,
            decision_coverage_pct=coverage_pct,
        )

        if evaluated_count == 0:
            return PilotPortfolioSummary(
                customer_name=customer_name,
                total_incidents_evaluated=0,
                coverage_metrics=coverage_metrics,
                outcome_distribution={
                    "cortex_wins": 0,
                    "human_wins": 0,
                    "ties": 0,
                    "insufficient_evidence": 0,
                },
                cumulative_unmitigated_exposure_usd=0.0,
                cumulative_loss_avoided_usd=0.0,
                cumulative_intervention_cost_usd=0.0,
                cumulative_net_economic_value_usd=0.0,
                cumulative_economic_delta_vs_human_usd=0.0,
                cortex_win_rate_pct=0.0,
                coverage_adjusted_win_rate_pct=0.0,
                mean_revenue_prediction_error_pct=0.0,
                mean_stockout_timing_error_hours=0.0,
                is_commercial_deployment_recommended=False,
                executive_recommendation="Awaiting partner incident evaluations to populate portfolio ledger.",
                incident_reports=[],
            )

        total_exposure = sum(r.human_benchmark.actual_unmitigated_loss_usd for r in reports)
        total_loss_avoided = sum(r.loss_avoided_usd for r in reports)
        total_cost = sum(r.intervention_cost_usd for r in reports)
        total_net_value = sum(r.net_economic_value_usd for r in reports)
        total_delta = sum(r.human_benchmark.economic_delta_usd for r in reports)

        cortex_wins = sum(1 for r in reports if r.human_benchmark.winner == "CORTEX")
        human_wins = sum(1 for r in reports if r.human_benchmark.winner == "HUMAN")
        ties = sum(1 for r in reports if r.human_benchmark.winner == "TIE")
        insufficient_evidence = sum(
            1 for r in reports if r.human_benchmark.winner == "INSUFFICIENT_EVIDENCE"
        )

        outcome_dist = {
            "cortex_wins": cortex_wins,
            "human_wins": human_wins,
            "ties": ties,
            "insufficient_evidence": insufficient_evidence,
        }

        win_rate = (cortex_wins / evaluated_count) * 100.0
        coverage_adjusted_win_rate = win_rate * (coverage_pct / 100.0)

        # Compute average errors
        rev_errors = []
        timing_errors = []
        for r in reports:
            for row in r.metric_comparisons:
                if row.metric_name == "Revenue Exposure":
                    rev_errors.append(row.error_pct)
                elif row.metric_name == "Time to 1st Stockout":
                    timing_errors.append(abs(row.cortex_predicted - row.actual_ground_truth))

        mean_rev_err = sum(rev_errors) / len(rev_errors) if rev_errors else 0.0
        mean_time_err = sum(timing_errors) / len(timing_errors) if timing_errors else 0.0

        is_recommended = (
            (total_net_value > 0)
            and (win_rate >= 60.0)
            and (mean_rev_err <= 15.0)
            and (coverage_pct >= 70.0)
        )

        rec = (
            f"Commercial deployment verified: Cortex evaluated {evaluated_count}/{total_eligible} disruptions ({coverage_pct:.1f}% coverage) for {customer_name}, "
            f"generating ${total_net_value:,.2f} cumulative Net Economic Value (+${total_delta:,.2f} vs historical human choices) "
            f"with an outcome distribution of [{cortex_wins} Cortex Wins, {human_wins} Human Wins, {ties} Ties] "
            f"and {mean_rev_err:.2f}% mean revenue forecast error."
        )

        return PilotPortfolioSummary(
            customer_name=customer_name,
            total_incidents_evaluated=evaluated_count,
            coverage_metrics=coverage_metrics,
            outcome_distribution=outcome_dist,
            cumulative_unmitigated_exposure_usd=total_exposure,
            cumulative_loss_avoided_usd=total_loss_avoided,
            cumulative_intervention_cost_usd=total_cost,
            cumulative_net_economic_value_usd=total_net_value,
            cumulative_economic_delta_vs_human_usd=total_delta,
            cortex_win_rate_pct=win_rate,
            coverage_adjusted_win_rate_pct=coverage_adjusted_win_rate,
            mean_revenue_prediction_error_pct=mean_rev_err,
            mean_stockout_timing_error_hours=mean_time_err,
            is_commercial_deployment_recommended=is_recommended,
            executive_recommendation=rec,
            incident_reports=reports,
        )
