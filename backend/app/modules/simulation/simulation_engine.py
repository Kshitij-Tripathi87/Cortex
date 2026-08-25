"""Simulation Engine — Executes Scenarios Through Time.

Program J (World State & Digital Twin) simulation runtime:

The SimulationEngine is the heart of the scenario runtime. It:
1. Takes a Digital Twin and a Twin Scenario
2. Steps through time, projecting events at each tick
3. Tracks state changes and metrics
4. Computes impact at the end

Engine flow:
    Clone (twin) → Inject (scenario events) → Tick → Tick → Tick → Result

Each tick represents one time interval (day, week, etc.) during which:
- Recovery events may occur (if configured)
- Cascading effects propagate (delays → inventory changes → etc.)
- Metrics are captured

The engine is deterministic when given a fixed scenario + initial state.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.ids import uuid7
from app.modules.simulation.impact_calculator import ImpactCalculator
from app.modules.simulation.simulation_models import (
    Simulation,
    SimulationConfig,
    SimulationResult,
    SimulationStatus,
    TickGranularity,
)
from app.modules.simulation.timeline import Timeline
from app.modules.twin.twin_isolation import (
    IsolationContext,
    IsolationError,
    TwinIsolationEnforcer,
)
from app.modules.twin.twin_models import (
    DigitalTwin,
    TwinScenario,
)
from app.modules.world.state_projection import (
    WorldState,
    apply_transition,
    create_state_snapshot,
    project_event_to_transition,
)

# ─────────────────────────────────────────────────────────────────────────────
# Simulation Engine
# ─────────────────────────────────────────────────────────────────────────────


class SimulationEngine:
    """Executes scenarios against digital twins.

    The engine is designed to be:
    - Deterministic (same inputs → same outputs)
    - Isolated (operates within twin's namespace)
    - Composable (can be chained for complex simulations)
    - Observable (emits events at each tick)
    """

    def __init__(
        self,
        db: AsyncSession,
        impact_calculator: ImpactCalculator | None = None,
    ):
        self.db = db
        self.enforcer = TwinIsolationEnforcer(db)
        self.impact_calculator = impact_calculator or ImpactCalculator()

    async def simulate(
        self,
        twin: DigitalTwin,
        scenario: TwinScenario,
        config: SimulationConfig | None = None,
    ) -> SimulationResult:
        """Run a simulation against a twin.

        Args:
            twin: The digital twin to simulate against
            scenario: The scenario to execute
            config: Simulation configuration (uses default if None)

        Returns:
            SimulationResult with timeline, metrics, and impact
        """
        config = config or SimulationConfig(config_id=str(uuid7()))

        # Create simulation record
        simulation_id = str(uuid7())
        simulation = Simulation(
            simulation_id=simulation_id,
            workspace_id=twin.workspace_id,
            twin_id=twin.twin_id,
            scenario_id=scenario.scenario_id,
            config=config,
            status=SimulationStatus.RUNNING,
            name=f"{scenario.name} on {twin.name}",
            started_at=datetime.now(UTC),
        )

        # Initialize timeline
        timeline = Timeline(
            simulation_id=simulation_id,
            config_id=config.config_id,
            granularity=config.tick_granularity,
            start_time=config.start_at,
            current_time=config.start_at,
        )

        ticks_executed = 0

        try:
            # Build isolation context
            context = await self._build_context(twin)

            # Capture baseline metrics
            baseline_metrics = self._compute_metrics(context.state)

            # Execute scenario
            state = context.state
            all_events = list(scenario.events)  # Copy to mutate

            # Tick 0: Initial state capture
            initial_hash = create_state_snapshot(state).state_hash
            timeline.advance(
                events=[],
                state=state,
                metrics=baseline_metrics,
                state_hash=initial_hash,
            )
            ticks_executed += 1

            # Execute scenario events on tick 1 (immediate impact)
            if all_events:
                state = self._apply_events(state, all_events, context)
                metrics = self._compute_metrics(state)
                snapshot = create_state_snapshot(state)
                timeline.advance(
                    events=all_events,
                    state=state,
                    metrics=metrics,
                    state_hash=snapshot.state_hash,
                )
                ticks_executed += 1
                all_events = []  # Events consumed

            # Continue ticking until max_ticks reached
            max_ticks = config.max_ticks
            while ticks_executed < max_ticks:
                # In a full implementation, this would simulate recovery,
                # cascading effects, and other time-based dynamics.
                # For now, we capture the steady state at each tick.
                metrics = self._compute_metrics(state)
                snapshot = create_state_snapshot(state)
                timeline.advance(
                    events=[],
                    state=state,
                    metrics=metrics,
                    state_hash=snapshot.state_hash,
                )
                ticks_executed += 1

            # Compute final metrics and impact
            final_metrics = self._compute_metrics(state)
            final_snapshot = create_state_snapshot(state)

            impact = self.impact_calculator.calculate(
                baseline=context.state,
                final=state,
                duration_days=ticks_executed * self._days_per_tick(config.tick_granularity),
            )

            # Build result
            completed_at = datetime.now(UTC)
            duration_ms = (completed_at - simulation.started_at).total_seconds() * 1000

            result = SimulationResult(
                simulation_id=simulation_id,
                twin_id=twin.twin_id,
                scenario_id=scenario.scenario_id,
                status=SimulationStatus.COMPLETED,
                ticks_executed=ticks_executed,
                final_state_hash=final_snapshot.state_hash,
                final_version=state.version,
                timeline=timeline.ticks,
                final_metrics=final_metrics,
                baseline_metrics=baseline_metrics,
                impact=impact,
                started_at=simulation.started_at,
                completed_at=completed_at,
                duration_ms=duration_ms,
                metadata={
                    "engine_version": "simulation-v2.0",
                    "timeline_hash": timeline.timeline_hash,
                    "seed": config.random_seed,
                    "kpis": impact.kpi_summary if impact else {},
                },
            )

            return result

        except Exception as exc:
            # Simulation failed
            completed_at = datetime.now(UTC)
            duration_ms = (completed_at - simulation.started_at).total_seconds() * 1000

            return SimulationResult(
                simulation_id=simulation_id,
                twin_id=twin.twin_id,
                scenario_id=scenario.scenario_id,
                status=SimulationStatus.FAILED,
                ticks_executed=ticks_executed,
                final_state_hash="",
                final_version=0,
                timeline=timeline.ticks,
                error_message=str(exc),
                started_at=simulation.started_at,
                completed_at=completed_at,
                duration_ms=duration_ms,
            )

    async def simulate_batch(
        self,
        twin: DigitalTwin,
        scenarios: list[TwinScenario],
        config: SimulationConfig | None = None,
    ) -> list[SimulationResult]:
        """Run multiple scenarios against the same twin.

        Each scenario gets its own simulation result.
        The twin state is reset to baseline between scenarios.
        """
        results = []
        for scenario in scenarios:
            # Reset twin to baseline (clone from snapshot each time)
            result = await self.simulate(twin, scenario, config)
            results.append(result)
        return results

    # ─────────────────────────────────────────────────────────────────────────
    # Internal Helpers
    # ─────────────────────────────────────────────────────────────────────────

    async def _build_context(self, twin: DigitalTwin) -> IsolationContext:
        """Build isolation context from twin."""
        snapshot = await self.enforcer.repo.get_snapshot(twin.snapshot_id, twin.workspace_id)
        if not snapshot:
            raise IsolationError(f"Snapshot {twin.snapshot_id} not found")

        parent_state = await self.enforcer.repo.get(
            twin.parent_world_id, twin.workspace_id, twin.parent_version
        )
        if not parent_state:
            raise IsolationError(f"Parent world version {twin.parent_version} not found")

        return IsolationContext(
            twin_id=twin.twin_id,
            workspace_id=twin.workspace_id,
            parent_world_id=twin.parent_world_id,
            parent_version=twin.parent_version,
            snapshot=snapshot,
            state=parent_state,
        )

    def _apply_events(
        self,
        state: WorldState,
        events: list[dict[str, Any]],
        context: IsolationContext,
    ) -> WorldState:
        """Apply a list of events to the state."""
        from app.modules.twin.twin_validation_helpers import make_fake_event

        current = state
        for event_data in events:
            fake_event = make_fake_event(
                event_id=str(uuid7()),
                world_id=context.twin_id,
                workspace_id=context.workspace_id,
                entity_type=event_data["entity_type"],
                entity_id=event_data["entity_id"],
                event_type=event_data["event_type"],
                payload=event_data["payload"],
            )
            transition = project_event_to_transition(current, fake_event)
            if transition:
                current = apply_transition(current, transition)
        return current

    def _compute_metrics(self, state: WorldState) -> dict[str, float]:
        """Compute key metrics from a world state."""
        metrics = {}

        # Sum inventory
        total_inventory = sum(
            var.raw_value
            for var in state.variables.values()
            if var.variable_type.value == "inventory" and isinstance(var.raw_value, (int, float))
        )
        metrics["total_inventory"] = float(total_inventory)

        # Sum demand
        total_demand = sum(
            var.raw_value
            for var in state.variables.values()
            if var.variable_type.value == "demand" and isinstance(var.raw_value, (int, float))
        )
        metrics["total_demand"] = float(total_demand)

        # Average capacity
        capacity_values = [
            var.raw_value
            for var in state.variables.values()
            if var.variable_type.value == "capacity" and isinstance(var.raw_value, (int, float))
        ]
        metrics["avg_capacity"] = (
            sum(capacity_values) / len(capacity_values) if capacity_values else 100.0
        )

        # Average supplier health
        health_values = [
            var.raw_value
            for var in state.variables.values()
            if var.variable_type.value == "supplier_health"
            and isinstance(var.raw_value, (int, float))
        ]
        metrics["avg_supplier_health"] = (
            sum(health_values) / len(health_values) if health_values else 1.0
        )

        # Average lead time
        lead_times = [
            var.raw_value
            for var in state.variables.values()
            if var.variable_type.value == "lead_time" and isinstance(var.raw_value, (int, float))
        ]
        metrics["avg_lead_time"] = sum(lead_times) / len(lead_times) if lead_times else 0

        # Total revenue (if tracked)
        total_revenue = sum(
            var.raw_value
            for var in state.variables.values()
            if var.variable_type.value == "revenue" and isinstance(var.raw_value, (int, float))
        )
        metrics["total_revenue"] = float(total_revenue)

        # Total margin
        total_margin = sum(
            var.raw_value
            for var in state.variables.values()
            if var.variable_type.value == "margin" and isinstance(var.raw_value, (int, float))
        )
        metrics["total_margin"] = float(total_margin)

        return metrics

    def _days_per_tick(self, granularity: TickGranularity) -> int:
        """Convert granularity to days per tick."""
        if granularity == TickGranularity.HOUR:
            return 0  # Less than a day
        if granularity == TickGranularity.DAY:
            return 1
        if granularity == TickGranularity.WEEK:
            return 7
        if granularity == TickGranularity.MONTH:
            return 30
        return 1
