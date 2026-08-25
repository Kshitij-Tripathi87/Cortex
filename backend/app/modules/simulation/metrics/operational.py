"""Operational KPI Calculator — Decision-Grade Operational Performance Metrics.

Program J.4 (Simulation Quality & Evaluation Bridge) — Milestone J.4 Phase 2.

Metrics calculated:
- Stockout Hours: Cumulative hours of stockout across all warehouse inventory variables
- Production Downtime: Cumulative operational hours lost due to facility / factory shutdowns
- Inventory Coverage: Estimated days of inventory forward coverage based on daily burn rate
- Capacity Utilization: Aggregate operational capacity percentage across all facilities
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.modules.simulation.metrics.financial import KPIMetric
from app.modules.world.state_diff import StateDiff
from app.modules.world.state_projection import WorldState
from app.modules.world.world_models import StateVariableType

OPERATIONAL_FORMULA_VERSION = "operational-kpi-v2.0"


@dataclass(frozen=True)
class OperationalMetricsBundle:
    """Bundle of decision-grade operational performance metrics."""

    stockout_hours: KPIMetric
    production_downtime_hours: KPIMetric
    inventory_coverage_days: KPIMetric
    capacity_utilization_pct: KPIMetric

    def to_dict(self) -> dict[str, Any]:
        return {
            "stockout_hours": self.stockout_hours.to_dict(),
            "production_downtime_hours": self.production_downtime_hours.to_dict(),
            "inventory_coverage_days": self.inventory_coverage_days.to_dict(),
            "capacity_utilization_pct": self.capacity_utilization_pct.to_dict(),
        }


class OperationalKPICalculator:
    """Canonical calculator for operational efficiency and disruption metrics."""

    def __init__(self, default_daily_burn_rate: float = 50.0):
        self.default_daily_burn_rate = default_daily_burn_rate

    def calculate(
        self,
        baseline_state: WorldState,
        final_state: WorldState,
        diff: StateDiff,
        duration_days: int = 1,
    ) -> OperationalMetricsBundle:
        """Calculate operational metrics across states."""
        # 1. Stockout hours
        stockout_occurrences = 0
        total_inventory = 0.0

        for var in final_state.variables.values():
            if var.variable_type == StateVariableType.INVENTORY:
                val = float(var.raw_value) if isinstance(var.raw_value, (int, float)) else 0.0
                total_inventory += max(0.0, val)
                if val <= 0:
                    stockout_occurrences += 1

        stockout_hrs = stockout_occurrences * duration_days * 24.0

        # 2. Production downtime hours
        downtime_hrs = 0.0
        capacities = []
        for var in final_state.variables.values():
            if var.variable_type == StateVariableType.CAPACITY:
                cap = float(var.raw_value) if isinstance(var.raw_value, (int, float)) else 100.0
                capacities.append(cap)
                lost_cap = max(0.0, 100.0 - cap)
                downtime_hrs += (lost_cap / 100.0) * duration_days * 24.0

        avg_cap = sum(capacities) / len(capacities) if capacities else 100.0

        # 3. Inventory coverage days
        coverage_days = (
            total_inventory / self.default_daily_burn_rate
            if self.default_daily_burn_rate > 0
            else 0.0
        )

        return OperationalMetricsBundle(
            stockout_hours=KPIMetric(
                name="stockout_hours",
                value=round(stockout_hrs, 1),
                unit="hours",
                formula_version=OPERATIONAL_FORMULA_VERSION,
                provenance="computed:stockout_occurrences * duration_days * 24h",
                assumptions={
                    "stockout_occurrences": stockout_occurrences,
                    "duration_days": duration_days,
                },
            ),
            production_downtime_hours=KPIMetric(
                name="production_downtime_hours",
                value=round(downtime_hrs, 1),
                unit="hours",
                formula_version=OPERATIONAL_FORMULA_VERSION,
                provenance="computed:lost_capacity_fraction * duration_days * 24h",
                assumptions={
                    "duration_days": duration_days,
                    "facility_count": len(capacities),
                },
            ),
            inventory_coverage_days=KPIMetric(
                name="inventory_coverage_days",
                value=round(coverage_days, 1),
                unit="days",
                formula_version=OPERATIONAL_FORMULA_VERSION,
                provenance="computed:total_positive_inventory / daily_burn_rate",
                assumptions={
                    "daily_burn_rate": self.default_daily_burn_rate,
                    "total_inventory": total_inventory,
                },
            ),
            capacity_utilization_pct=KPIMetric(
                name="capacity_utilization_pct",
                value=round(avg_cap, 2),
                unit="percent",
                formula_version=OPERATIONAL_FORMULA_VERSION,
                provenance="computed:mean(active_facility_capacities)",
                assumptions={
                    "facilities_tracked": len(capacities),
                },
            ),
        )
