"""Test Risk Propagation Forecasting — Program K.6.

Verifies:
- Multi-hop disruption cascade simulation
- Time-to-impact tick estimation
- Critical path generation and loss estimation
"""

from __future__ import annotations

from app.modules.gnn.graph_representation import GraphExtractor
from app.modules.gnn.models import SupplyChainGNN
from app.modules.gnn.tasks.risk_propagation import RiskPropagationForecaster
from app.modules.world.state_projection import (
    capacity_var_id,
    create_initial_state,
    demand_var_id,
    inventory_var_id,
    lead_time_var_id,
)
from app.modules.world.world_models import StateVariable, StateVariableType


class TestRiskPropagation:
    def test_forecast_disruption_cascade_across_time_horizon(self) -> None:
        """Disruption at upstream supplier cascades to factories, warehouses, and customers."""
        s1 = StateVariable(
            variable_id=lead_time_var_id("sup_origin"),
            variable_type=StateVariableType.LEAD_TIME,
            entity_id="sup_origin",
            entity_type="supplier",
            value=7,
        )
        f1 = StateVariable(
            variable_id=capacity_var_id("fac_1"),
            variable_type=StateVariableType.CAPACITY,
            entity_id="fac_1",
            entity_type="factory",
            value=100.0,
        )
        w1 = StateVariable(
            variable_id=inventory_var_id("wh_1", "comp_a"),
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_1",
            entity_type="warehouse",
            value=600,
        )
        c1 = StateVariable(
            variable_id=demand_var_id("cust_1"),
            variable_type=StateVariableType.DEMAND,
            entity_id="cust_1",
            entity_type="customer",
            value=300,
        )

        state = create_initial_state(
            workspace_id="ws_prop",
            world_id="world_prop",
            graph_version=1,
            initial_variables={
                s1.variable_id: s1,
                f1.variable_id: f1,
                w1.variable_id: w1,
                c1.variable_id: c1,
            },
        )

        extractor = GraphExtractor()
        graph_data = extractor.extract_from_world_state(state)
        gnn = SupplyChainGNN(in_features=graph_data.feature_dim)
        embeddings = gnn.encode(graph_data)

        forecaster = RiskPropagationForecaster()
        forecast = forecaster.forecast_propagation(
            epicenter_entity_id="sup_origin",
            graph_data=graph_data,
            embeddings=embeddings,
            horizon_ticks=5,
            initial_severity_pct=100.0,
        )

        assert forecast.epicenter_node_id == "sup_origin"
        assert forecast.horizon_ticks == 5
        assert len(forecast.predicted_impacts) >= 4
        assert forecast.total_expected_revenue_loss > 0.0
        assert len(forecast.critical_path) >= 2

        # Epicenter impact at tick 0
        epicenter_impact = forecast.predicted_impacts[0]
        assert epicenter_impact.node_id == "sup_origin"
        assert epicenter_impact.time_to_impact_ticks == 0
        assert epicenter_impact.expected_capacity_loss_pct == 100.0
