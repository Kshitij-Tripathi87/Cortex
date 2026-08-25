"""Customer KPI Calculator — Decision-Grade Customer Service & SLA Metrics.

Program J.4 (Simulation Quality & Evaluation Bridge) — Milestone J.4 Phase 2.

Metrics calculated:
- SLA Breaches: Count of service level agreement breaches caused by delays / stockouts
- Orders Delayed: Estimated number of customer shipments delayed past promised date
- Fill Rate: Percentage of customer demand fulfilled on time from available inventory
- Critical Customer Exposure: Count of tier-1 / key accounts impacted by disruption
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.modules.simulation.metrics.financial import KPIMetric
from app.modules.world.state_diff import StateDiff
from app.modules.world.state_projection import WorldState
from app.modules.world.world_models import StateVariableType

CUSTOMER_FORMULA_VERSION = "customer-kpi-v2.0"


@dataclass(frozen=True)
class CustomerMetricsBundle:
    """Bundle of customer service and SLA impact metrics."""

    sla_breaches: KPIMetric
    orders_delayed: KPIMetric
    order_fill_rate_pct: KPIMetric
    critical_customers_exposed: KPIMetric

    def to_dict(self) -> dict[str, Any]:
        return {
            "sla_breaches": self.sla_breaches.to_dict(),
            "orders_delayed": self.orders_delayed.to_dict(),
            "order_fill_rate_pct": self.order_fill_rate_pct.to_dict(),
            "critical_customers_exposed": self.critical_customers_exposed.to_dict(),
        }


class CustomerKPICalculator:
    """Canonical calculator for customer experience and SLA commitments."""

    def __init__(self, target_fill_rate: float = 98.0):
        self.target_fill_rate = target_fill_rate

    def calculate(
        self,
        baseline_state: WorldState,
        final_state: WorldState,
        diff: StateDiff,
        duration_days: int = 1,
    ) -> CustomerMetricsBundle:
        """Calculate customer and SLA metrics."""
        # Check stockout impact on customers
        stockout_items = 0
        total_items = 0

        for var in final_state.variables.values():
            if var.variable_type == StateVariableType.INVENTORY:
                total_items += 1
                val = float(var.raw_value) if isinstance(var.raw_value, (int, float)) else 0.0
                if val <= 0:
                    stockout_items += 1

        # Fill rate estimation
        fill_rate = (
            max(0.0, 100.0 - (stockout_items / max(1, total_items) * 100.0))
            if total_items > 0
            else 100.0
        )

        # Orders delayed from transit or stockouts
        transit_delays = 0.0
        for var in final_state.variables.values():
            if var.variable_type == StateVariableType.TRANSIT_DELAY:
                val = float(var.raw_value) if isinstance(var.raw_value, (int, float)) else 0.0
                transit_delays += max(0.0, val)

        orders_delayed_count = int(stockout_items * 15 + transit_delays * 5)

        # SLA breaches (triggered when delay > 2 days or stockout > 0)
        sla_breach_count = int(stockout_items * 2 + (transit_delays // 2))

        # Critical customer count
        critical_customers = 0
        for var in final_state.variables.values():
            if var.variable_type == StateVariableType.CUSTOMER_PRIORITY and str(
                var.raw_value
            ).lower() in (
                "tier_1",
                "critical",
                "high",
                "platinum",
            ):
                critical_customers += 1

        exposed_critical = min(critical_customers, stockout_items + int(transit_delays > 0))

        return CustomerMetricsBundle(
            sla_breaches=KPIMetric(
                name="sla_breaches",
                value=float(sla_breach_count),
                unit="count",
                formula_version=CUSTOMER_FORMULA_VERSION,
                provenance="computed:stockout_items * 2 + int(transit_delays / 2)",
                assumptions={
                    "stockout_items": stockout_items,
                    "transit_delays_days": transit_delays,
                },
            ),
            orders_delayed=KPIMetric(
                name="orders_delayed",
                value=float(orders_delayed_count),
                unit="orders",
                formula_version=CUSTOMER_FORMULA_VERSION,
                provenance="computed:stockout_items * 15 + transit_delays * 5",
                assumptions={
                    "estimated_orders_per_item": 15,
                    "orders_delayed": orders_delayed_count,
                },
            ),
            order_fill_rate_pct=KPIMetric(
                name="order_fill_rate_pct",
                value=round(fill_rate, 2),
                unit="percent",
                formula_version=CUSTOMER_FORMULA_VERSION,
                provenance="computed:100.0 - (stockout_items / total_items * 100)",
                assumptions={
                    "total_items": total_items,
                    "stockout_items": stockout_items,
                },
            ),
            critical_customers_exposed=KPIMetric(
                name="critical_customers_exposed",
                value=float(exposed_critical),
                unit="accounts",
                formula_version=CUSTOMER_FORMULA_VERSION,
                provenance="computed:min(tier1_customers, stockout_count + delay_flags)",
                assumptions={
                    "total_tier1_customers": critical_customers,
                },
            ),
        )
