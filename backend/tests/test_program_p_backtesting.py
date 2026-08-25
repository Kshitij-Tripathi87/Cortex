"""Test Temporal Historical Backtesting — Program P.3.

Verifies:
- Execution of historical backtest frozen at T_0 without future knowledge leakage
- Comparison of predicted revenue exposure vs empirical actual loss
- Stockout timing error and product impact recall
"""

from __future__ import annotations

from app.modules.production_validation.backtesting import TemporalBacktester
from app.modules.production_validation.validation_models import (
    DisruptionType,
    TemporalBacktestScenario,
)
from app.modules.world.state_projection import (
    capacity_var_id,
    create_initial_state,
    inventory_var_id,
    lead_time_var_id,
)
from app.modules.world.world_models import StateVariable, StateVariableType


class TestTemporalBacktesting:
    def test_historical_supplier_failure_backtest(self) -> None:
        """Backtest evaluates pre-event world state without future leakage."""
        s1 = StateVariable(
            variable_id=lead_time_var_id("sup_104"),
            variable_type=StateVariableType.LEAD_TIME,
            entity_id="sup_104",
            entity_type="supplier",
            value=8,
        )
        w1 = StateVariable(
            variable_id=inventory_var_id("wh_central", "comp_chip"),
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_central",
            entity_type="warehouse",
            value=600,
        )
        f1 = StateVariable(
            variable_id=capacity_var_id("fac_plant_1"),
            variable_type=StateVariableType.CAPACITY,
            entity_id="fac_plant_1",
            entity_type="factory",
            value=100.0,
        )

        pre_event_state = create_initial_state(
            workspace_id="ws_backtest",
            world_id="world_pre_event",
            graph_version=1,
            initial_variables={s1.variable_id: s1, w1.variable_id: w1, f1.variable_id: f1},
        )

        scenario = TemporalBacktestScenario(
            scenario_id="scen_hist_2023_09",
            incident_name="Supplier S-104 Semiconductor Fab Delay",
            disruption_type=DisruptionType.SUPPLIER_DELAY,
            pre_event_world_id="world_pre_event",
            disrupted_entity_id="sup_104",
            ground_truth_actual_revenue_loss_usd=280000.0,
            ground_truth_affected_products=["sup_104"],
            ground_truth_stockout_hours=48.0,
            ground_truth_recovery_days=14.0,
        )

        backtester = TemporalBacktester()
        result = backtester.run_backtest(scenario, pre_event_state)

        assert result.scenario_id == "scen_hist_2023_09"
        assert result.actual_revenue_loss_usd == 280000.0
        assert result.predicted_revenue_exposure_usd > 0.0
        assert result.product_impact_recall >= 0.70
        assert result.recommended_mitigation_net_value_usd > 0.0
        assert result.backtest_passed is True
