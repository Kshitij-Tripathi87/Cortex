"""Canonical KPI Aggregator — Single Source of Truth for Simulation & Twin Metrics.

Program J.4 (Simulation Quality & Evaluation Bridge) — Milestone J.4 Phase 2.

Unifies all 4 decision-grade KPI dimensions:
1. Financial Metrics (Revenue at Risk, Margin at Risk, Recovery Cost, Expedite Cost, Working Capital)
2. Operational Metrics (Stockout Hours, Downtime, Coverage Days, Capacity Utilization)
3. Customer Metrics (SLA Breaches, Orders Delayed, Fill Rate, Critical Customer Exposure)
4. Resilience Metrics (Time to Recovery, Impact Duration, Maximum Exposure, Recovery Efficiency)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.modules.simulation.metrics.customer import CustomerKPICalculator, CustomerMetricsBundle
from app.modules.simulation.metrics.financial import (
    FinancialKPICalculator,
    FinancialMetricsBundle,
    KPIMetric,
)
from app.modules.simulation.metrics.operational import (
    OperationalKPICalculator,
    OperationalMetricsBundle,
)
from app.modules.simulation.metrics.resilience import (
    ResilienceKPICalculator,
    ResilienceMetricsBundle,
)
from app.modules.world.state_diff import DiffEngine
from app.modules.world.state_projection import WorldState

CANONICAL_KPI_VERSION = "enterprise-kpi-v2.0"


@dataclass(frozen=True)
class EnterpriseKPISummary:
    """Consolidated enterprise decision-grade metric summary."""

    financial: FinancialMetricsBundle
    operational: OperationalMetricsBundle
    customer: CustomerMetricsBundle
    resilience: ResilienceMetricsBundle
    engine_version: str = CANONICAL_KPI_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine_version": self.engine_version,
            "financial": self.financial.to_dict(),
            "operational": self.operational.to_dict(),
            "customer": self.customer.to_dict(),
            "resilience": self.resilience.to_dict(),
            # Flattened decision-ready summary map:
            "kpi_summary": {
                "revenue_at_risk": self.financial.revenue_at_risk.value,
                "margin_at_risk": self.financial.margin_at_risk.value,
                "recovery_cost": self.financial.recovery_cost.value,
                "expedite_cost": self.financial.expedite_cost.value,
                "working_capital_impact": self.financial.working_capital_impact.value,
                "stockout_hours": self.operational.stockout_hours.value,
                "production_downtime_hours": self.operational.production_downtime_hours.value,
                "inventory_coverage_days": self.operational.inventory_coverage_days.value,
                "capacity_utilization_pct": self.operational.capacity_utilization_pct.value,
                "sla_breaches": self.customer.sla_breaches.value,
                "orders_delayed": self.customer.orders_delayed.value,
                "order_fill_rate_pct": self.customer.order_fill_rate_pct.value,
                "critical_customers_exposed": self.customer.critical_customers_exposed.value,
                "time_to_recovery_days": self.resilience.time_to_recovery_days.value,
                "impact_duration_days": self.resilience.impact_duration_days.value,
                "maximum_exposure_usd": self.resilience.maximum_exposure_usd.value,
                "recovery_efficiency_pct": self.resilience.recovery_efficiency_pct.value,
            },
        }

    def get_metric(self, name: str) -> KPIMetric | None:
        """Retrieve any specific metric by name with its full provenance and assumptions."""
        all_metrics = [
            self.financial.revenue_at_risk,
            self.financial.margin_at_risk,
            self.financial.recovery_cost,
            self.financial.expedite_cost,
            self.financial.working_capital_impact,
            self.operational.stockout_hours,
            self.operational.production_downtime_hours,
            self.operational.inventory_coverage_days,
            self.operational.capacity_utilization_pct,
            self.customer.sla_breaches,
            self.customer.orders_delayed,
            self.customer.order_fill_rate_pct,
            self.customer.critical_customers_exposed,
            self.resilience.time_to_recovery_days,
            self.resilience.impact_duration_days,
            self.resilience.maximum_exposure_usd,
            self.resilience.recovery_efficiency_pct,
        ]
        for m in all_metrics:
            if m.name == name:
                return m
        return None


class CanonicalKPICalculator:
    """Master calculator invoking all 4 specialized domain calculators."""

    def __init__(
        self,
        financial_calculator: FinancialKPICalculator | None = None,
        operational_calculator: OperationalKPICalculator | None = None,
        customer_calculator: CustomerKPICalculator | None = None,
        resilience_calculator: ResilienceKPICalculator | None = None,
    ):
        self.financial_calc = financial_calculator or FinancialKPICalculator()
        self.operational_calc = operational_calculator or OperationalKPICalculator()
        self.customer_calc = customer_calculator or CustomerKPICalculator()
        self.resilience_calc = resilience_calculator or ResilienceKPICalculator()

    def compute(
        self,
        baseline_state: WorldState,
        final_state: WorldState,
        duration_days: int = 1,
        recovery_ticks: int = 7,
    ) -> EnterpriseKPISummary:
        """Compute the full decision-grade metric summary between two states."""
        diff = DiffEngine().diff(baseline_state, final_state)

        fin_bundle = self.financial_calc.calculate(
            baseline_state, final_state, diff, duration_days=duration_days
        )
        ops_bundle = self.operational_calc.calculate(
            baseline_state, final_state, diff, duration_days=duration_days
        )
        cust_bundle = self.customer_calc.calculate(
            baseline_state, final_state, diff, duration_days=duration_days
        )
        res_bundle = self.resilience_calc.calculate(
            baseline_state,
            final_state,
            diff,
            duration_days=duration_days,
            recovery_ticks=recovery_ticks,
        )

        return EnterpriseKPISummary(
            financial=fin_bundle,
            operational=ops_bundle,
            customer=cust_bundle,
            resilience=res_bundle,
        )
