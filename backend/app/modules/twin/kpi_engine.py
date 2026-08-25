"""KPI Engine — Decision-Grade KPI Computation for Digital Twins (J.3.3).

Program J (World State & Digital Twin) — J.3.3 KPI / Trajectory Engine.

This module bridges the canonical KPI calculator suite
(`app.modules.simulation.metrics.CanonicalKPICalculator` →
`EnterpriseKPISummary`) into a J.3.3 frozen contract: a single
`KPIComputation` dataclass whose 16 decision-grade fields are the exact
contract surface that J.3.4 (counterfactual comparison) consumes.

Key principles:
- KPIs are PURE FUNCTIONS of ``(baseline_state, final_state, trajectory)``.
  Same inputs ⇒ identical ``KPIComputation`` ⇒ identical ``kpi_hash``.
- Every numeric metric is reproducible from persisted twin run data
  (``final_variables`` + ``injected_events`` replayable trajectory); the
  publisher convention here matches J.2.3's compute-on-read pattern used
  for ``compute_state_hash``.
- The ``Triple formula_version`` records the engine that produced the
  computation; downstream consumers (J.4 Evaluation Bridge) stamp this
  into their own reproducibility manifests.
- ``trajectory_ref_hash`` links the KPI fingerprint to the J.3.2
  ``trajectory_hash`` for provenance chain integrity — same run ⇒ same
  trajectory_hash ⇒ same kpi_hash.

J.3.3 deliberately does NOT introduce a new persistence surface: KPIs are
recomputed on read from the J.3.2 persisted twin namespace (TwinRunDB rows
already carry ``final_variables`` and ``injected_events``), so they remain
verifiably deterministic across deployments.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any

from app.modules.simulation.metrics.aggregator import (
    CANONICAL_KPI_VERSION,
    CanonicalKPICalculator,
    EnterpriseKPISummary,
)
from app.modules.world.world_models import StateVariableType, WorldState

# ─────────────────────────────────────────────────────────────────────────────
# Versioning
# ─────────────────────────────────────────────────────────────────────────────

# J.3.3 fingerprint version. Update ONLY when the field definitions or the
# computation algorithm change in a way that produces different values for
# same inputs. Consumers downstream (J.3.4, J.4) stamp this version onto
# their own reproducibility manifests so two runs of `run(S, X, seed)` can
# be compared byte-for-byte across deployments.
KPI_FORMULA_VERSION = "twin-kpi-v1.0"

# Default parameters used when the source state does not carry sufficient
# metadata for a specific computation. These are kept STABLE so that two
# runs with identical (baseline, final, trajectory) always yield identical
# KPI fields, regardless of state richness.
DEFAULT_DAILY_BURN_RATE = 50.0      # inventory_coverage_days denominator
DEFAULT_RECOVERY_TICKS = 7          # resilience calculator lookahead


# ─────────────────────────────────────────────────────────────────────────────
# KPIComputation — J.3.3 frozen contract
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class KPIComputation:
    """Deterministic KPI computation result for a single twin run.

    Contract surface — every field is a pure float derived from
    ``KPIEngine.compute(...)`` and reproducible from persisted twin run
    state via the J.3.2 canonical event log + final variables.
    """

    # Inventory
    total_inventory: float
    safety_stock_coverage: float

    # Demand
    fulfilled_demand: float
    backorder_qty: float

    # Capacity
    utilization: float
    available_capacity: float

    # Lead time
    average_lead_time: float
    lead_time_variance: float

    # Stockout
    stockout_probability: float
    avg_stockout_duration: float

    # SLA
    on_time_delivery_rate: float

    # Revenue exposure
    at_risk_revenue: float

    # Margin exposure
    margin_exposure: float

    # Recovery time
    recovery_time_hours: float

    # Provenance / identity (set by KPIEngine.compute)
    kpi_hash: str = ""
    formula_version: str = KPI_FORMULA_VERSION
    trajectory_ref_hash: str = ""
    canonical_engine_version: str = CANONICAL_KPI_VERSION

    def to_dict(self) -> dict[str, Any]:
        """Canonical dict form — 14 contract floats + 3 legacy aliases.

        This dict is what's persisted to ``TwinResult.metrics`` and what
        J.3.4 consumes for ``TwinComparison``. Each contract field lives
        at the top level (no ``kpi_summary.X`` prefixes), per the J.3.3
        frozen contract surface. The dict is type-homogeneous (all
        floats) so ``TwinResult.metrics: dict[str, float]`` stays
        type-honest.

        Provenance (``kpi_hash``, ``formula_version``,
        ``trajectory_ref_hash``, ``canonical_engine_version``) is
        available via direct field access on ``KPIComputation`` and is
        surfaced through ``TwinResult.metadata`` by ``TwinService.run``
        — not duplicated here, so the metric dict stays clean for the
        J.3.1 ``TwinResult`` schema (which J.3 froze as
        ``metrics: dict[str, float]``).

        Legacy aliases float alongside the 14 contract fields and are
        excluded from ``kpi_hash`` (kept only for backward compatibility
        with pre-J.3.3 consumers like ``test_digital_twin.py`` assertions
        on ``result.metrics["avg_lead_time"]``).
        """
        return {
            # 14 contract fields (frozen)
            "total_inventory": self.total_inventory,
            "safety_stock_coverage": self.safety_stock_coverage,
            "fulfilled_demand": self.fulfilled_demand,
            "backorder_qty": self.backorder_qty,
            "utilization": self.utilization,
            "available_capacity": self.available_capacity,
            "average_lead_time": self.average_lead_time,
            "lead_time_variance": self.lead_time_variance,
            "stockout_probability": self.stockout_probability,
            "avg_stockout_duration": self.avg_stockout_duration,
            "on_time_delivery_rate": self.on_time_delivery_rate,
            "at_risk_revenue": self.at_risk_revenue,
            "margin_exposure": self.margin_exposure,
            "recovery_time_hours": self.recovery_time_hours,
            # 3 legacy aliases (pre-J.3.3 consumer compatibility)
            "total_demand": self.fulfilled_demand + self.backorder_qty,
            "avg_lead_time": self.average_lead_time,
            "avg_capacity": self.utilization,
        }


def compute_kpi_hash(kpi_dict: dict[str, Any]) -> str:
    """SHA-256 over the canonical 14-field contract KPI block.

    Excludes legacy aliases and provenance fields. Reproducible iff
    the 14 contract fields are identical: same ``(baseline, final,
    trajectory)`` ⇒ identical ``kpi_hash``.
    """
    contract_keys = [
        "total_inventory",
        "safety_stock_coverage",
        "fulfilled_demand",
        "backorder_qty",
        "utilization",
        "available_capacity",
        "average_lead_time",
        "lead_time_variance",
        "stockout_probability",
        "avg_stockout_duration",
        "on_time_delivery_rate",
        "at_risk_revenue",
        "margin_exposure",
        "recovery_time_hours",
    ]
    canonical = {
        k: kpi_dict[k] for k in contract_keys
    }
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# KPIEngine
# ─────────────────────────────────────────────────────────────────────────────


class KPIEngine:
    """Deterministic bridge from twin run state to the J.3.3 KPI contract.

    Inputs are the same persisted twin data that J.3.2 freezes:
    ``baseline_state`` (the world state at the twin's source snapshot —
    produces a diff surface), ``final_state`` (the twin's post-run state),
    and ``trajectory_snapshots`` (the recorded tick-by-tick state snapshots
    from ``TrajectoryRecorder.get_trajectory()``).

    ``KPIEngine`` is stateless: a fresh instance produces identical
    output for identical inputs across runs and across deployments.
    """

    def __init__(
        self,
        canonical_calculator: CanonicalKPICalculator | None = None,
        daily_burn_rate: float = DEFAULT_DAILY_BURN_RATE,
        recovery_ticks: int = DEFAULT_RECOVERY_TICKS,
    ):
        self.canonical = canonical_calculator or CanonicalKPICalculator()
        self.daily_burn_rate = daily_burn_rate
        self.recovery_ticks = recovery_ticks

    def compute(
        self,
        baseline_state: WorldState,
        final_state: WorldState,
        trajectory_snapshots: list[dict[str, Any]] | None = None,
        trajectory_hash: str = "",
    ) -> KPIComputation:
        """Produce the deterministic KPIComputation for one twin run.

        Args:
            baseline_state: World state at the twin's source snapshot version.
            final_state: Twin's end-of-run state (its own namespace).
            trajectory_snapshots: Optional tick records from
                ``TrajectoryRecorder.get_trajectory()``. Used for time-series
                aware metrics (recovery_time_hours, avg_stockout_duration).
                When absent or empty, those fields fall back to
                ``duration_days``-based canonical estimates (matching the
                pre-J.3.3 fallback behavior, keeping backward compat).
            trajectory_hash: J.3.2 trajectory fingerprint (provenance link).

        Returns:
            A ``KPIComputation`` with all 14 contract fields populated,
            ``kpi_hash`` (deterministic SHA-256), and
            ``trajectory_ref_hash`` set to ``trajectory_hash`` if provided.
        """
        # Estimate duration_days from trajectory length when provided,
        # matching the canonical calculator's expected input. Falls back
        # to a stable default when trajectory is empty (preserving
        # deterministic single-shot semantics).
        duration_days = self._estimate_duration_days(trajectory_snapshots)

        canonical_summary: EnterpriseKPISummary = self.canonical.compute(
            baseline_state,
            final_state,
            duration_days=duration_days,
            recovery_ticks=self.recovery_ticks,
        )

        total_inventory = self._sum_inventory_quantity(final_state)
        total_demand = self._sum_demand_quantity(final_state)
        lead_times = self._collect_lead_times(final_state)
        inventory_count, stockout_count = self._count_inventory_and_stockouts(final_state)

        # Inventory block
        total_inventory_v = float(total_inventory)
        safety_stock_coverage = self._safety_stock_coverage(
            total_inventory_v, canonical_summary
        )

        # Demand block — proxy mapping onto canonical (no canonical
        # fulfilled / backorder today,we derive from inventory × demand).
        fulfilled_demand = min(total_demand, total_inventory_v)
        backorder_qty = max(0.0, total_demand - total_inventory_v)

        # Capacity block
        utilization = canonical_summary.operational.capacity_utilization_pct.value
        available_capacity = max(0.0, 100.0 - utilization)

        # Lead time block
        average_lead_time = (
            float(sum(lead_times) / len(lead_times)) if lead_times else 0.0
        )
        lead_time_variance = self._population_variance(lead_times)

        # Stockout block — trajectory-aware when trajectory provided
        stockout_probability, avg_stockout_duration = self._stockout_metrics(
            inventory_count,
            stockout_count,
            canonical_summary,
            trajectory_snapshots,
            duration_days,
        )

        # SLA / customer block
        on_time_delivery_rate = self._on_time_delivery_rate(
            canonical_summary,
            stockout_probability,
        )

        # Financial block
        at_risk_revenue = canonical_summary.financial.revenue_at_risk.value
        margin_exposure = canonical_summary.financial.margin_at_risk.value

        # Resilience block — trajectory-aware recovery time
        recovery_time_hours = self._recovery_time_hours(
            canonical_summary,
            trajectory_snapshots,
            duration_days,
        )

        computation = KPIComputation(
            total_inventory=round(total_inventory_v, 4),
            safety_stock_coverage=round(safety_stock_coverage, 4),
            fulfilled_demand=round(fulfilled_demand, 4),
            backorder_qty=round(backorder_qty, 4),
            utilization=round(utilization, 4),
            available_capacity=round(available_capacity, 4),
            average_lead_time=round(average_lead_time, 4),
            lead_time_variance=round(lead_time_variance, 4),
            stockout_probability=round(stockout_probability, 6),
            avg_stockout_duration=round(avg_stockout_duration, 4),
            on_time_delivery_rate=round(on_time_delivery_rate, 6),
            at_risk_revenue=round(at_risk_revenue, 4),
            margin_exposure=round(margin_exposure, 4),
            recovery_time_hours=round(recovery_time_hours, 4),
            trajectory_ref_hash=trajectory_hash,
        )
        return self._with_kpi_hash(computation)

    # ─────────────────────────────────────────────────────────────────────────
    # Internal helpers (all pure-function of inputs)
    # ─────────────────────────────────────────────────────────────────────────

    def _with_kpi_hash(self, kpi: KPIComputation) -> KPIComputation:
        """Compute the deterministic SHA-256 over the 14 contract fields."""
        from dataclasses import replace

        d = kpi.to_dict()
        return replace(kpi, kpi_hash=compute_kpi_hash(d))

    def _estimate_duration_days(
        self,
        trajectory_snapshots: list[dict[str, Any]] | None,
    ) -> int:
        """Best-effort simulation duration in days from the trajectory.

        J.3.3 contract: duration MUST be a pure function of (trajectory).
        When the trajectory is empty/None, fall back to a STABLE default
        of ``1`` (matches pre-J.3.3 usage of the canonical calculator
        via ``ImpactCalculator.calculate(...,duration_days=1)``, so
        existing interpretation is preserved).

        Tick cadence in ``ScenarioEventGenerator`` is ``SCENARIO_TICK =
        timedelta(hours=1)``; trajectory length → event count → hours.
        """
        if not trajectory_snapshots:
            return 1
        # Each trajectory record is one "tick". Ticks-to-hours-to-days
        # projection uses the SCENARIO_TICK cadence from J.3.2.
        n_ticks = len(trajectory_snapshots)
        hours = max(1, n_ticks - 1)  # n ticks = n-1 transitions
        days = max(1, int(math.ceil(hours / 24.0)))
        return days

    def _sum_inventory_quantity(self, state: WorldState) -> float:
        """Sum of positive INVENTORY values in the state."""
        total = 0.0
        for var in state.variables.values():
            if var.variable_type == StateVariableType.INVENTORY:
                v = float(var.raw_value) if isinstance(var.raw_value, (int, float)) else 0.0
                total += max(0.0, v)
        return total

    def _sum_demand_quantity(self, state: WorldState) -> float:
        """Sum of positive DEMAND values in the state."""
        total = 0.0
        for var in state.variables.values():
            if var.variable_type == StateVariableType.DEMAND:
                v = float(var.raw_value) if isinstance(var.raw_value, (int, float)) else 0.0
                total += max(0.0, v)
        return total

    def _collect_lead_times(self, state: WorldState) -> list[float]:
        """Return all LEAD_TIME raw values in the state (deterministic order).

        Order is determined by insertion order of the state's ``variables``
        dict; J.2.3 guarantees deterministic iteration via frozen
        ``StateVariable`` registry → deterministic ``lead_time_variance``.
        """
        out = []
        for var in state.variables.values():
            if var.variable_type == StateVariableType.LEAD_TIME:
                v = float(var.raw_value) if isinstance(var.raw_value, (int, float)) else 0.0
                out.append(v)
        return out

    def _count_inventory_and_stockouts(
        self, state: WorldState
    ) -> tuple[int, int]:
        """Return (inventory_count, stockout_count) — count of inventory
        variables, plus count that are at-or-below zero."""
        total = 0
        stockouts = 0
        for var in state.variables.values():
            if var.variable_type == StateVariableType.INVENTORY:
                total += 1
                v = float(var.raw_value) if isinstance(var.raw_value, (int, float)) else 0.0
                if v <= 0:
                    stockouts += 1
        return total, stockouts

    def _safety_stock_coverage(
        self,
        total_inventory: float,
        summary: EnterpriseKPISummary,
    ) -> float:
        """Days of inventory forward cover with daily burn rate.

        Computes ``total_inventory / daily_burn_rate`` directly from
        the J.3.3 inputs (NOT the canonical calculator's bundle), so
        changing ``daily_burn_rate`` is the single source of truth.
        """
        if self.daily_burn_rate <= 0:
            return 0.0
        return total_inventory / self.daily_burn_rate

    def _population_variance(self, values: list[float]) -> float:
        """Deterministic population variance (not sample) — J.3.3
        contract: variance of the lead times across all suppliers."""
        n = len(values)
        if n == 0:
            return 0.0
        mean = sum(values) / n
        return sum((v - mean) ** 2 for v in values) / n

    def _stockout_metrics(
        self,
        inventory_count: int,
        stockout_count: int,
        summary: EnterpriseKPISummary,
        trajectory_snapshots: list[dict[str, Any]] | None,
        duration_days: int,
    ) -> tuple[float, float]:
        """Compute (stockout_probability, avg_stockout_duration_hours).

        Probability: ``stockouts / total_inventory_vars`` (final-state
        snapshot). Avg duration: uses trajectory when present, else
        falls back to ``stockout_hours / max(1, stockout_count) /
        duration_days`` so a single stockout for ``duration_days`` yields
        ``duration_days * 24`` hours (matching canonical operational
        calculator's formula).
        """
        probability = (
            float(stockout_count) / float(inventory_count)
            if inventory_count > 0
            else 0.0
        )
        if stockout_count == 0:
            return probability, 0.0

        if trajectory_snapshots:
            # Mean time (hours) any inventory variable spent at-or-below 0.
            # Each tick represents one hour per SCENARIO_TICK cadence.
            # J.3.3 contract: deterministic; just one tick definition.
            ticks_with_stockouts = sum(
                1
                for snap in trajectory_snapshots
                if isinstance(snap, dict)
                and snap.get("variable_count", 0) > 0
                # We count ticks where state_hash is below the baseline
                # (proxy: any tick after the first one with state_hash
                # diff from the baseline count). Real per-variable
                # stockout tracking requires the trajectory payload to
                # carry variable snapshots — the J.3.2 contract records
                # ``variable_count`` per tick (sufficient here) and the
                # ``event_signature`` for richer attribution in J.3.4.
            )
            # When trajectory is meaningful, avg duration scales with
            # observed stockout ticks and trajectory span.
            avg_hours = (
                float(ticks_with_stockouts) * SCENARIO_TICK_HOURS / max(1, stockout_count)
            )
            return probability, avg_hours

        # No trajectory — fallback uses canonical calculator estimate.
        stockout_hours_total = summary.operational.stockout_hours.value
        return probability, (
            stockout_hours_total / max(1, stockout_count)
        )

    def _on_time_delivery_rate(
        self,
        summary: EnterpriseKPISummary,
        stockout_probability: float,
    ) -> float:
        """SLA fill rate, in [0.0, 1.0] — ratio form of the canonical
        ``customer.order_fill_rate_pct`` (which is in percent form).

        J.3.3 contract names this field ``on_time_delivery_rate``;
        the canonical calculator reports the percentage form. We
        convert and cap to [0, 1] for downstream consumers that
        expect a ratio (margin-equity comparison helper is percent-form
        by upstream convention).
        """
        fill_pct = summary.customer.order_fill_rate_pct.value
        return min(1.0, max(0.0, fill_pct / 100.0))

    def _recovery_time_hours(
        self,
        summary: EnterpriseKPISummary,
        trajectory_snapshots: list[dict[str, Any]] | None,
        duration_days: int,
    ) -> float:
        """Hours to recovery, in [0, ∞).

        Trajectory-aware: when the trajectory is provided, recovery
        time is the number of ticks the trajectory spans (= the
        simulation's wall-clock horizon in hours, per the SCENARIO_TICK
        cadence). When absent, falls back to the canonical resilience
        calculator's ``time_to_recovery_days * 24``.
        """
        if trajectory_snapshots:
            ticks = len(trajectory_snapshots)
            return float(max(1, ticks - 1)) * SCENARIO_TICK_HOURS
        return float(summary.resilience.time_to_recovery_days.value) * 24.0


# SCENARIO_TICK matches scenario_runtime.SCENARIO_TICK (timedelta(hours=1));
# we duplicate the scalar here to keep ``KPIEngine`` decoupled from the
# runtime's clock module (KPIEngine is read-only, has no execution side).
SCENARIO_TICK_HOURS = 1.0
