"""Impact Calculator — Computes Business Impact of Simulations.

Program J (World State & Digital Twin) impact analysis:

The ImpactCalculator takes a baseline state and a final state
(typically from a simulation), and computes the financial and
operational impact.

Computes:
- Revenue impact (dollar change)
- Margin impact (dollar change)
- Inventory impact (units affected)
- Customer impact (number affected)
- Factory impact (number affected)
- Route impact (number affected)
- Supplier impact (number affected)
- Severity classification (low, medium, high, critical)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.modules.simulation.simulation_models import ImpactSummary
from app.modules.world.state_diff import DiffEngine
from app.modules.world.state_projection import WorldState
from app.modules.world.world_models import StateVariableType


@dataclass(frozen=True)
class ImpactThresholds:
    """Thresholds for severity classification."""

    # Revenue impact thresholds (USD)
    revenue_low: float = 10_000
    revenue_medium: float = 100_000
    revenue_high: float = 1_000_000
    revenue_critical: float = 10_000_000

    # Margin impact thresholds (USD)
    margin_low: float = 1_000
    margin_medium: float = 10_000
    margin_high: float = 100_000
    margin_critical: float = 1_000_000

    # Inventory impact thresholds (units)
    inventory_low: int = 100
    inventory_medium: int = 1_000
    inventory_high: int = 10_000
    inventory_critical: int = 100_000


class ImpactCalculator:
    """Calculates business impact of state changes from a simulation."""

    def __init__(self, thresholds: ImpactThresholds | None = None):
        self.thresholds = thresholds or ImpactThresholds()

    def calculate(
        self,
        baseline: WorldState,
        final: WorldState,
        duration_days: int = 0,
    ) -> ImpactSummary:
        """Calculate the impact of state changes from baseline to final.

        Args:
            baseline: Starting world state (pre-simulation)
            final: Ending world state (post-simulation)
            duration_days: Duration of the simulation in days

        Returns:
            ImpactSummary with all computed metrics
        """
        # Compute diff between baseline and final
        diff = DiffEngine().diff(baseline, final)

        # Revenue and margin deltas
        revenue_delta = self._sum_variable_delta(diff, StateVariableType.REVENUE, baseline, final)
        margin_delta = self._sum_variable_delta(diff, StateVariableType.MARGIN, baseline, final)

        # Inventory delta
        inventory_delta = self._sum_variable_delta(
            diff, StateVariableType.INVENTORY, baseline, final
        )

        # Count affected entities by type
        customers_impacted = self._count_affected_entities(
            diff, StateVariableType.CUSTOMER_PRIORITY, baseline, final
        )
        factories_affected = self._count_affected_entities(
            diff, StateVariableType.CAPACITY, baseline, final
        )
        routes_affected = self._count_affected_entities(
            diff, StateVariableType.TRANSIT_DELAY, baseline, final
        )
        suppliers_affected = self._count_affected_entities(
            diff, StateVariableType.LEAD_TIME, baseline, final
        )

        # Classify severity
        severity = self._classify_severity(
            abs(revenue_delta),
            abs(margin_delta),
            abs(inventory_delta),
        )

        # Compute canonical decision-grade metrics
        from app.modules.simulation.metrics.aggregator import CanonicalKPICalculator

        canonical_kpis = CanonicalKPICalculator().compute(
            baseline_state=baseline,
            final_state=final,
            duration_days=max(1, duration_days),
        )

        return ImpactSummary(
            revenue_impact=revenue_delta,
            margin_impact=margin_delta,
            inventory_impact=inventory_delta,
            customers_impacted=customers_impacted,
            factories_affected=factories_affected,
            routes_affected=routes_affected,
            suppliers_affected=suppliers_affected,
            duration_days=duration_days,
            severity=severity,
            kpi_summary=canonical_kpis.to_dict(),
        )

    def _sum_variable_delta(
        self,
        diff: Any,
        variable_type: StateVariableType,
        baseline: WorldState,
        final: WorldState,
    ) -> float:
        """Sum the change in variables of a given type."""
        total_delta = 0.0
        for var_diff in diff.variable_diffs:
            var = final.variables.get(var_diff.variable_id)
            if (
                var
                and var.variable_type == variable_type
                and isinstance(var.raw_value, (int, float))
            ):
                # Get old value from baseline
                old_var = baseline.variables.get(var_diff.variable_id)
                if old_var and isinstance(old_var.raw_value, (int, float)):
                    total_delta += var.raw_value - old_var.raw_value
                else:
                    total_delta += var.raw_value
        return total_delta

    def _count_affected_entities(
        self,
        diff: Any,
        variable_type: StateVariableType,
        baseline: WorldState,
        final: WorldState,
    ) -> int:
        """Count distinct entities affected for a given variable type."""
        affected_entities = set()
        for var_diff in diff.variable_diffs:
            var = final.variables.get(var_diff.variable_id)
            if var and var.variable_type == variable_type:
                affected_entities.add(var.entity_id)
        return len(affected_entities)

    def _classify_severity(
        self,
        revenue_impact: float,
        margin_impact: float,
        inventory_impact: float,
    ) -> str:
        """Classify severity based on impact magnitudes."""
        t = self.thresholds

        # Use the highest-impact metric for classification
        revenue_level = self._level_for_value(
            revenue_impact,
            [t.revenue_low, t.revenue_medium, t.revenue_high, t.revenue_critical],
        )
        margin_level = self._level_for_value(
            margin_impact,
            [t.margin_low, t.margin_medium, t.margin_high, t.margin_critical],
        )
        inventory_level = self._level_for_value(
            inventory_impact,
            [t.inventory_low, t.inventory_medium, t.inventory_high, t.inventory_critical],
        )

        max_level = max(revenue_level, margin_level, inventory_level)
        levels = ["low", "medium", "high", "critical"]
        return levels[min(max_level, len(levels) - 1)]

    def _level_for_value(self, value: float, thresholds: list[float]) -> int:
        """Return level (0-3) based on which threshold the value exceeds."""
        for i, threshold in enumerate(thresholds):
            if value < threshold:
                return i
        return len(thresholds)
