"""Test Decision-Grade KPIs — Provenance, Units, and Mathematical Formulas.

Program J.4 (Simulation Quality & Evaluation Bridge) — Milestone J.4 Phase 2.

Validates:
- All 4 KPI dimensions: Financial, Operational, Customer, Resilience
- Provenance & Assumptions contract on every metric
- Canonical aggregation without metric drift
"""

from __future__ import annotations

from app.modules.simulation.metrics import (
    CANONICAL_KPI_VERSION,
    CanonicalKPICalculator,
    FinancialKPICalculator,
    OperationalKPICalculator,
)
from app.modules.world.state_diff import DiffEngine
from app.modules.world.state_projection import (
    capacity_var_id,
    create_initial_state,
    customer_priority_var_id,
    inventory_var_id,
    lead_time_var_id,
)
from app.modules.world.world_models import StateVariable, StateVariableType


class TestDecisionGradeKPIs:
    def test_financial_kpi_calculation_and_provenance(self) -> None:
        """Financial metrics calculate with typed units, formula versions, and explicit assumptions."""
        # Baseline
        inv_base = StateVariable(
            variable_id=inventory_var_id("wh_1", "comp_x"),
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_1",
            entity_type="warehouse",
            value=200,
        )
        base_state = create_initial_state(
            workspace_id="ws_kpi",
            world_id="world_kpi",
            graph_version=1,
            initial_variables={inv_base.variable_id: inv_base},
        )

        # Final state with stockout (-100 units)
        inv_final = StateVariable(
            variable_id=inventory_var_id("wh_1", "comp_x"),
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_1",
            entity_type="warehouse",
            value=-100,
        )
        final_state = create_initial_state(
            workspace_id="ws_kpi",
            world_id="world_kpi",
            graph_version=1,
            initial_variables={inv_final.variable_id: inv_final},
        )

        diff = DiffEngine().diff(base_state, final_state)
        calc = FinancialKPICalculator(default_unit_revenue=150.0, default_unit_margin_pct=0.30)
        bundle = calc.calculate(base_state, final_state, diff, duration_days=7)

        # Revenue at risk = 100 * 150 = $15,000
        assert bundle.revenue_at_risk.value == 15000.0
        assert bundle.revenue_at_risk.unit == "USD"
        assert bundle.revenue_at_risk.formula_version == "financial-kpi-v2.0"
        assert "unfulfilled_units" in bundle.revenue_at_risk.assumptions

        # Margin at risk = 15000 * 0.30 = $4,500
        assert bundle.margin_at_risk.value == 4500.0
        assert bundle.margin_at_risk.unit == "USD"

    def test_operational_kpi_calculation(self) -> None:
        """Operational metrics track stockout hours, downtime, coverage, and utilization."""
        inv_var = StateVariable(
            variable_id=inventory_var_id("wh_1", "comp_x"),
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_1",
            entity_type="warehouse",
            value=0,
        )
        cap_var = StateVariable(
            variable_id=capacity_var_id("fac_1"),
            variable_type=StateVariableType.CAPACITY,
            entity_id="fac_1",
            entity_type="factory",
            value=60.0,
        )
        state = create_initial_state(
            workspace_id="ws_kpi",
            world_id="world_kpi",
            graph_version=1,
            initial_variables={inv_var.variable_id: inv_var, cap_var.variable_id: cap_var},
        )

        diff = DiffEngine().diff(state, state)
        calc = OperationalKPICalculator(default_daily_burn_rate=20.0)
        bundle = calc.calculate(state, state, diff, duration_days=5)

        # Stockout hours = 1 occurrence * 5 days * 24h = 120h
        assert bundle.stockout_hours.value == 120.0
        assert bundle.stockout_hours.unit == "hours"

        # Lost capacity = 40% of 5 days * 24h = 48.0h
        assert bundle.production_downtime_hours.value == 48.0
        assert bundle.capacity_utilization_pct.value == 60.0

    def test_customer_and_resilience_canonical_summary(self) -> None:
        """Canonical aggregator consolidates all 4 bundles seamlessly."""
        inv_var = StateVariable(
            variable_id=inventory_var_id("wh_1", "comp_a"),
            variable_type=StateVariableType.INVENTORY,
            entity_id="wh_1",
            entity_type="warehouse",
            value=100,
        )
        lt_var = StateVariable(
            variable_id=lead_time_var_id("sup_1"),
            variable_type=StateVariableType.LEAD_TIME,
            entity_id="sup_1",
            entity_type="supplier",
            value=21,
        )
        cust_var = StateVariable(
            variable_id=customer_priority_var_id("cust_1"),
            variable_type=StateVariableType.CUSTOMER_PRIORITY,
            entity_id="cust_1",
            entity_type="customer",
            value="tier_1",
        )

        state = create_initial_state(
            workspace_id="ws_kpi",
            world_id="world_kpi",
            graph_version=1,
            initial_variables={
                inv_var.variable_id: inv_var,
                lt_var.variable_id: lt_var,
                cust_var.variable_id: cust_var,
            },
        )

        calc = CanonicalKPICalculator()
        summary = calc.compute(state, state, duration_days=10)

        assert summary.engine_version == CANONICAL_KPI_VERSION
        dict_rep = summary.to_dict()

        assert "kpi_summary" in dict_rep
        assert dict_rep["kpi_summary"]["time_to_recovery_days"] >= 21.0
        assert dict_rep["kpi_summary"]["order_fill_rate_pct"] == 100.0

        # Query specific metric
        ttr_metric = summary.get_metric("time_to_recovery_days")
        assert ttr_metric is not None
        assert ttr_metric.unit == "days"
        assert ttr_metric.formula_version == "resilience-kpi-v2.0"
