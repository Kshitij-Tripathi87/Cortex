"""Simulation Models — Immutable Contracts for Scenario Runtime.

Program J (World State & Digital Twin) simulation layer:

The Simulation Runtime executes scenarios against digital twins,
stepping through time and tracking impact on key business metrics.

Key concepts:
- Simulation: A configured run with a scenario, twin, and time horizon
- SimulationTick: A single step in time (one day's worth of events)
- SimulationResult: Final outcome with metrics, timeline, and impact
- SimulationConfig: Configuration (tick interval, max ticks, etc.)

The engine flow is:
    Clone → Inject → Tick → Tick → Tick → Result

All models are immutable (frozen dataclasses).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class SimulationStatus(StrEnum):
    """Lifecycle status of a simulation."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TickGranularity(StrEnum):
    """Time granularity for simulation ticks."""

    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


# ─────────────────────────────────────────────────────────────────────────────
# Simulation Configuration
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SimulationConfig:
    """Configuration for a simulation run."""

    config_id: str
    tick_granularity: TickGranularity = TickGranularity.DAY
    max_ticks: int = 30  # Default: 30 days
    start_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    include_recovery: bool = True  # Simulate recovery after disruption
    recovery_ticks: int = 7  # Days of recovery simulation
    random_seed: int | None = None  # For deterministic simulations
    capture_metrics_every_n_ticks: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_id": self.config_id,
            "tick_granularity": self.tick_granularity.value,
            "max_ticks": self.max_ticks,
            "start_at": self.start_at.isoformat(),
            "include_recovery": self.include_recovery,
            "recovery_ticks": self.recovery_ticks,
            "random_seed": self.random_seed,
            "capture_metrics_every_n_ticks": self.capture_metrics_every_n_ticks,
            "metadata": dict(self.metadata),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Simulation Tick
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SimulationTick:
    """A single step in a simulation.

    Each tick represents one time interval (e.g., one day) and captures:
    - The simulated time
    - Events that occurred during this tick
    - State changes (variable diffs)
    - Metrics snapshot at this point
    """

    tick_id: str
    simulation_id: str
    tick_number: int  # 0, 1, 2, ...
    simulated_time: datetime
    events: list[dict[str, Any]] = field(default_factory=list)
    state_hash: str = ""
    metrics: dict[str, float] = field(default_factory=dict)
    variable_changes: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tick_id": self.tick_id,
            "simulation_id": self.simulation_id,
            "tick_number": self.tick_number,
            "simulated_time": self.simulated_time.isoformat(),
            "events": self.events,
            "state_hash": self.state_hash,
            "metrics": dict(self.metrics),
            "variable_changes": dict(self.variable_changes),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Simulation
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Simulation:
    """A configured simulation run."""

    simulation_id: str
    workspace_id: str
    twin_id: str
    scenario_id: str
    config: SimulationConfig
    status: SimulationStatus = SimulationStatus.PENDING
    name: str = ""
    description: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "simulation_id": self.simulation_id,
            "workspace_id": self.workspace_id,
            "twin_id": self.twin_id,
            "scenario_id": self.scenario_id,
            "config": self.config.to_dict(),
            "status": self.status.value,
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "tags": list(self.tags),
            "metadata": dict(self.metadata),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Simulation Result
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ImpactSummary:
    """Summary of financial/operational impact."""

    revenue_impact: float = 0.0  # Dollar impact on revenue
    margin_impact: float = 0.0  # Dollar impact on margin
    inventory_impact: float = 0.0  # Units affected
    customers_impacted: int = 0
    factories_affected: int = 0
    routes_affected: int = 0
    suppliers_affected: int = 0
    duration_days: int = 0
    severity: str = "low"  # low, medium, high, critical
    kpi_summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "revenue_impact": self.revenue_impact,
            "margin_impact": self.margin_impact,
            "inventory_impact": self.inventory_impact,
            "customers_impacted": self.customers_impacted,
            "factories_affected": self.factories_affected,
            "routes_affected": self.routes_affected,
            "suppliers_affected": self.suppliers_affected,
            "duration_days": self.duration_days,
            "severity": self.severity,
            "kpi_summary": dict(self.kpi_summary),
        }


@dataclass(frozen=True)
class SimulationResult:
    """Final outcome of a simulation."""

    simulation_id: str
    twin_id: str
    scenario_id: str
    status: SimulationStatus
    ticks_executed: int
    final_state_hash: str
    final_version: int
    timeline: list[SimulationTick] = field(default_factory=list)
    final_metrics: dict[str, float] = field(default_factory=dict)
    baseline_metrics: dict[str, float] = field(default_factory=dict)
    impact: ImpactSummary | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: float | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "simulation_id": self.simulation_id,
            "twin_id": self.twin_id,
            "scenario_id": self.scenario_id,
            "status": self.status.value,
            "ticks_executed": self.ticks_executed,
            "final_state_hash": self.final_state_hash,
            "final_version": self.final_version,
            "timeline": [t.to_dict() for t in self.timeline],
            "final_metrics": dict(self.final_metrics),
            "baseline_metrics": dict(self.baseline_metrics),
            "impact": self.impact.to_dict() if self.impact else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_ms": self.duration_ms,
            "error_message": self.error_message,
            "metadata": dict(self.metadata),
        }
