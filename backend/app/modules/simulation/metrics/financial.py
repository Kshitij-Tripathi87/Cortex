"""Financial KPI Calculator — Decision-Grade Financial Impact Metrics.

Program J.4 (Simulation Quality & Evaluation Bridge) — Milestone J.4 Phase 2.

Metrics calculated:
- Revenue at Risk: Total potential gross revenue lost due to unfulfilled demand / stockouts
- Margin at Risk: Profit margin lost based on component product margins
- Recovery Cost: Estimated financial cost to restore disrupted facilities / suppliers
- Expedite Cost: Premium shipping and rush fees incurred during disruption
- Working Capital Impact: Capital tied up in excess inventory or freed by stock depletion

Every metric includes:
- value: float
- unit: str (USD, etc.)
- formula_version: str
- provenance: str
- assumptions: dict[str, Any]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.modules.world.state_diff import StateDiff
from app.modules.world.state_projection import WorldState
from app.modules.world.world_models import StateVariableType

FINANCIAL_FORMULA_VERSION = "financial-kpi-v2.0"


@dataclass(frozen=True)
class KPIMetric:
    """Individual decision-grade KPI with explicit provenance and assumptions."""

    name: str
    value: float
    unit: str
    formula_version: str
    provenance: str
    assumptions: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "formula_version": self.formula_version,
            "provenance": self.provenance,
            "assumptions": dict(self.assumptions),
        }


@dataclass(frozen=True)
class FinancialMetricsBundle:
    """Bundle of all calculated financial metrics."""

    revenue_at_risk: KPIMetric
    margin_at_risk: KPIMetric
    recovery_cost: KPIMetric
    expedite_cost: KPIMetric
    working_capital_impact: KPIMetric

    def to_dict(self) -> dict[str, Any]:
        return {
            "revenue_at_risk": self.revenue_at_risk.to_dict(),
            "margin_at_risk": self.margin_at_risk.to_dict(),
            "recovery_cost": self.recovery_cost.to_dict(),
            "expedite_cost": self.expedite_cost.to_dict(),
            "working_capital_impact": self.working_capital_impact.to_dict(),
            "total_financial_exposure": (
                self.revenue_at_risk.value + self.recovery_cost.value + self.expedite_cost.value
            ),
        }


class FinancialKPICalculator:
    """Canonical engine for computing decision-grade financial impact."""

    def __init__(
        self,
        default_unit_revenue: float = 100.0,
        default_unit_margin_pct: float = 0.25,
        default_expedite_fee_per_unit: float = 15.0,
        default_unit_cost: float = 60.0,
    ):
        self.default_unit_revenue = default_unit_revenue
        self.default_unit_margin_pct = default_unit_margin_pct
        self.default_expedite_fee_per_unit = default_expedite_fee_per_unit
        self.default_unit_cost = default_unit_cost

    def calculate(
        self,
        baseline_state: WorldState,
        final_state: WorldState,
        diff: StateDiff,
        duration_days: int = 1,
    ) -> FinancialMetricsBundle:
        """Calculate decision-grade financial KPIs across states."""
        # 1. Unfulfilled demand / stockout units
        unfulfilled_units = 0.0
        expedited_units = 0.0

        for var_diff in diff.variable_diffs:
            v_id = var_diff.variable_id
            var = final_state.variables.get(v_id)
            if not var:
                continue

            if var.variable_type == StateVariableType.INVENTORY:
                # If inventory dropped below 0 or decreased drastically
                if float(var.raw_value) < 0:
                    unfulfilled_units += abs(float(var.raw_value))
            elif var.variable_type == StateVariableType.TRANSIT_DELAY and float(var.raw_value) > 0:
                # Delays cause expedite actions
                expedited_units += float(var.raw_value) * 10.0

        # Also account for direct revenue/margin variables if present
        direct_rev_loss = 0.0
        direct_margin_loss = 0.0
        for var_diff in diff.variable_diffs:
            var = final_state.variables.get(var_diff.variable_id)
            if var and var.variable_type == StateVariableType.REVENUE:
                old_val = float(var_diff.old_value) if var_diff.old_value is not None else 0.0
                direct_rev_loss += max(0.0, old_val - float(var.raw_value))
            elif var and var.variable_type == StateVariableType.MARGIN:
                old_val = float(var_diff.old_value) if var_diff.old_value is not None else 0.0
                direct_margin_loss += max(0.0, old_val - float(var.raw_value))

        rev_loss = (
            direct_rev_loss
            if direct_rev_loss > 0
            else (unfulfilled_units * self.default_unit_revenue)
        )
        margin_loss = (
            direct_margin_loss
            if direct_margin_loss > 0
            else (rev_loss * self.default_unit_margin_pct)
        )

        # 2. Recovery Cost (factories/suppliers offline)
        disrupted_facilities = 0
        for var_diff in diff.variable_diffs:
            var = final_state.variables.get(var_diff.variable_id)
            if (
                var
                and var.variable_type == StateVariableType.CAPACITY
                and float(var.raw_value) < 100.0
            ):
                disrupted_facilities += 1

        recovery_cost_val = disrupted_facilities * 25000.0 * max(1, duration_days // 7)

        # 3. Expedite cost
        expedite_cost_val = expedited_units * self.default_expedite_fee_per_unit

        # 4. Working capital impact
        inv_delta_units = 0.0
        for var_diff in diff.variable_diffs:
            var = final_state.variables.get(var_diff.variable_id)
            if var and var.variable_type == StateVariableType.INVENTORY:
                old_val = float(var_diff.old_value) if var_diff.old_value is not None else 0.0
                inv_delta_units += float(var.raw_value) - old_val

        working_cap_val = inv_delta_units * self.default_unit_cost

        return FinancialMetricsBundle(
            revenue_at_risk=KPIMetric(
                name="revenue_at_risk",
                value=round(rev_loss, 2),
                unit="USD",
                formula_version=FINANCIAL_FORMULA_VERSION,
                provenance="computed:unfulfilled_units * unit_revenue + direct_revenue_delta",
                assumptions={
                    "default_unit_revenue": self.default_unit_revenue,
                    "unfulfilled_units": unfulfilled_units,
                },
            ),
            margin_at_risk=KPIMetric(
                name="margin_at_risk",
                value=round(margin_loss, 2),
                unit="USD",
                formula_version=FINANCIAL_FORMULA_VERSION,
                provenance="computed:revenue_at_risk * margin_pct",
                assumptions={
                    "margin_pct": self.default_unit_margin_pct,
                },
            ),
            recovery_cost=KPIMetric(
                name="recovery_cost",
                value=round(recovery_cost_val, 2),
                unit="USD",
                formula_version=FINANCIAL_FORMULA_VERSION,
                provenance="computed:disrupted_facilities * cost_per_facility_week",
                assumptions={
                    "disrupted_facilities": disrupted_facilities,
                    "duration_days": duration_days,
                },
            ),
            expedite_cost=KPIMetric(
                name="expedite_cost",
                value=round(expedite_cost_val, 2),
                unit="USD",
                formula_version=FINANCIAL_FORMULA_VERSION,
                provenance="computed:delayed_transit_units * expedite_rate",
                assumptions={
                    "expedited_units": expedited_units,
                    "fee_per_unit": self.default_expedite_fee_per_unit,
                },
            ),
            working_capital_impact=KPIMetric(
                name="working_capital_impact",
                value=round(working_cap_val, 2),
                unit="USD",
                formula_version=FINANCIAL_FORMULA_VERSION,
                provenance="computed:net_inventory_delta_units * unit_cost",
                assumptions={
                    "inventory_delta_units": inv_delta_units,
                    "unit_cost": self.default_unit_cost,
                },
            ),
        )
