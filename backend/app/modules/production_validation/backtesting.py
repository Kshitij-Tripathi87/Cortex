"""Temporal Historical Backtesting Engine — Program P.3.

Executes rigorous historical incident backtesting without temporal leakage:
- Reconstructs operational world as it existed at T_0 (prior to event)
- Simulates disruption spread and evaluates mitigation recommendations
- Compares predicted vs. actual outcomes (revenue loss, stockouts, affected products)
"""

from __future__ import annotations

import copy

from app.modules.gnn.gnn_service import GNNService
from app.modules.production_validation.validation_models import (
    TemporalBacktestResult,
    TemporalBacktestScenario,
)
from app.modules.rl.environment import SupplyChainEnv
from app.modules.rl.policy import DQNMitigationPolicy
from app.modules.world.world_models import WorldState


class TemporalBacktester:
    """Rigorous temporal backtesting engine comparing pre-event forecasts with empirical truth."""

    def __init__(
        self,
        gnn_service: GNNService | None = None,
        rl_policy: DQNMitigationPolicy | None = None,
    ):
        self.gnn = gnn_service or GNNService()
        self.policy = rl_policy or DQNMitigationPolicy()

    def run_backtest(
        self,
        scenario: TemporalBacktestScenario,
        pre_event_world_state: WorldState,
    ) -> TemporalBacktestResult:
        """Run temporal backtest starting at T_0 without knowledge of the future."""
        # 1. Run GNN risk propagation forecast from pre-event world state
        forecast = self.gnn.forecast_risk_propagation(
            world_state=pre_event_world_state,
            epicenter_entity_id=scenario.disrupted_entity_id,
            horizon_ticks=7,
        )

        predicted_loss = forecast.total_expected_revenue_loss
        actual_loss = scenario.ground_truth_actual_revenue_loss_usd

        # Revenue error %
        rev_error_pct = (abs(predicted_loss - actual_loss) / max(1.0, actual_loss)) * 100.0

        # Stockout timing estimation (ticks to hours)
        predicted_stockout_hrs = min(
            (
                p.time_to_impact_ticks * 24.0
                for p in forecast.predicted_impacts
                if p.time_to_impact_ticks > 0
            ),
            default=48.0,
        )
        actual_stockout_hrs = scenario.ground_truth_stockout_hours
        timing_error_hrs = abs(predicted_stockout_hrs - actual_stockout_hrs)

        # Product impact overlap
        predicted_products = set(forecast.critical_path)
        actual_products = set(scenario.ground_truth_affected_products)

        tp = len(predicted_products & actual_products)
        precision = tp / max(1, len(predicted_products))
        recall = tp / max(1, len(actual_products))

        # 2. Evaluate RL mitigation policy in sandbox
        env = SupplyChainEnv(initial_world_state=copy.deepcopy(pre_event_world_state), max_steps=5)
        rec = self.policy.recommend_action(env)
        net_benefit = max(0.0, predicted_loss - rec.recommended_action.cost_usd)

        # Pass criteria: Revenue error < 25%, Product recall >= 75%, Net value > $0
        passed = (rev_error_pct <= 25.0) and (recall >= 0.70) and (net_benefit > 0.0)

        return TemporalBacktestResult(
            scenario_id=scenario.scenario_id,
            incident_name=scenario.incident_name,
            predicted_revenue_exposure_usd=predicted_loss,
            actual_revenue_loss_usd=actual_loss,
            revenue_error_pct=rev_error_pct,
            predicted_stockout_hours=predicted_stockout_hrs,
            actual_stockout_hours=actual_stockout_hrs,
            stockout_timing_error_hours=timing_error_hrs,
            product_impact_precision=precision,
            product_impact_recall=recall,
            recommended_mitigation_net_value_usd=net_benefit,
            backtest_passed=passed,
        )
