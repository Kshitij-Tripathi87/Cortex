"""Scenario Runtime — Deterministic Scenario Execution Engine (J.3.2).

Program J (World State & Digital Twin) — J.3.2 Scenario Runtime.

This module implements the deterministic runtime that executes declarative
Scenarios against Digital Twins, generating events and projecting them
through the Twin projection engine.

Key principles:
- Scenario is DECLARATIVE data; runtime INTERPRETS it
- All execution is deterministic: same (twin, scenario, seed) → identical result
- Events are generated, then projected (no direct state mutation)
- Trajectory is recorded at each step for replay/analysis
- Production World State is NEVER touched (read-only via StateRepository)
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.ids import uuid7
from app.modules.twin.twin_isolation import IsolationError, TwinIsolationEnforcer
from app.modules.twin.twin_models import (
    TWIN_ENGINE_VERSION,
    TWIN_RNG_VERSION,
    TWIN_SIMULATION_VERSION,
    DigitalTwin,
    Scenario,
    ScenarioEvent,
    ScenarioRun,
    ScenarioType,
    TwinRunStatus,
)
from app.modules.twin.twin_repository import TwinRepository
from app.modules.world.state_projection import apply_transition, project_event_to_transition
from app.modules.world.state_repository import StateRepository
from app.modules.world.world_models import (
    StateVariable,
    StateVariableType,
    WorldSnapshot,
    WorldState,
)

# ─────────────────────────────────────────────────────────────────────────────
# Deterministic Scenario Clock
# ─────────────────────────────────────────────────────────────────────────────

SCENARIO_TICK = timedelta(hours=1)  # Fixed tick for event sequencing


def _as_utc(dt: datetime) -> datetime:
    """Normalize a stored timestamp to an aware-UTC datetime."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def deterministic_event_time(
    snapshot: WorldSnapshot,
    seed: int,
    tick: int,
) -> datetime:
    """Pure-function clock for scenario events.

    occurred_at = snapshot.created_at + seed hours + tick hours

    Pure function of (snapshot, seed, tick) — no wall clock.
    """
    return _as_utc(snapshot.created_at) + timedelta(hours=seed) + SCENARIO_TICK * tick


# ─────────────────────────────────────────────────────────────────────────────
# Scenario Event Generators
# ─────────────────────────────────────────────────────────────────────────────


class ScenarioEventGenerator:
    """Generates ScenarioEvents from a declarative Scenario.

    Each scenario type has a dedicated generator that emits the sequence
    of events needed to simulate that disruption.
    """

    def __init__(
        self,
        run_id: str,
        scenario: Scenario,
        snapshot: WorldSnapshot,
        state: WorldState | None = None,
    ):
        self.run_id = run_id
        self.scenario = scenario
        self.snapshot = snapshot
        # Optional base state — lets scenario generators look up seeded
        # quantities (e.g. base demand) deterministically. J.3.2 does NOT
        # use state for sequencing/timing; only for parameter derivation.
        self.state = state
        self.tick = 0

    def _next_time(self) -> datetime:
        t = deterministic_event_time(self.snapshot, self.scenario.seed, self.tick)
        self.tick += 1
        return t

    def _event(
        self,
        entity_type: str,
        entity_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> ScenarioEvent:
        return ScenarioEvent(
            event_id=f"{self.run_id}:evt:{self.tick:04d}",
            scenario_run_id=self.run_id,
            sequence=self.tick,
            entity_type=entity_type,
            entity_id=entity_id,
            event_type=event_type,
            payload=payload,
            occurred_at=self._next_time(),
        )

    def generate(self) -> list[ScenarioEvent]:
        """Generate the full event sequence for this scenario."""
        generators = {
            ScenarioType.SUPPLIER_FAILURE: self._gen_supplier_failure,
            ScenarioType.SUPPLIER_DELAY: self._gen_supplier_delay,
            ScenarioType.INVENTORY_SHORTAGE: self._gen_inventory_shortage,
            ScenarioType.DEMAND_SPIKE: self._gen_demand_spike,
            ScenarioType.ROUTE_DISRUPTION: self._gen_route_disruption,
            ScenarioType.CAPACITY_REDUCTION: self._gen_capacity_reduction,
        }
        gen = generators.get(self.scenario.scenario_type, self._gen_custom)
        return gen()

    def _gen_supplier_failure(self) -> list[ScenarioEvent]:
        events = []
        supplier_id = self.scenario.target_entities.get("supplier", [""])[0]
        # Use delay_days if provided (legacy SUPPLIER_FAILURE with delay_days)
        # otherwise use capacity_pct for true capacity reduction
        delay_days = self.scenario.parameters.get("delay_days")
        if delay_days is not None:
            events.append(
                self._event(
                    entity_type="supplier",
                    entity_id=supplier_id,
                    event_type="supplier_delayed",
                    payload={
                        "delay_days": delay_days,
                        "disruption_type": self.scenario.parameters.get(
                            "disruption_type", "factory_fire"
                        ),
                    },
                )
            )
        else:
            capacity_pct = self.scenario.parameters.get("capacity_pct", 0.0)
            events.append(
                self._event(
                    entity_type="supplier",
                    entity_id=supplier_id,
                    event_type="supplier_capacity_changed",
                    payload={
                        "capacity_pct": capacity_pct,
                        "disruption_type": self.scenario.parameters.get(
                            "disruption_type", "factory_fire"
                        ),
                    },
                )
            )
        return events

    def _gen_supplier_delay(self) -> list[ScenarioEvent]:
        events = []
        supplier_id = self.scenario.target_entities.get("supplier", [""])[0]
        delay_days = self.scenario.parameters.get("delay_days", 3)
        events.append(
            self._event(
                entity_type="supplier",
                entity_id=supplier_id,
                event_type="supplier_delayed",
                payload={
                    "delay_days": delay_days,
                },
            )
        )
        return events

    def _gen_inventory_shortage(self) -> list[ScenarioEvent]:
        events = []
        warehouse_id = self.scenario.target_entities.get("warehouse", [""])[0]
        component_id = self.scenario.target_entities.get("component", [""])[0]
        reduction_pct = self.scenario.parameters.get("reduction_pct", 50.0)
        events.append(
            self._event(
                entity_type="warehouse",
                entity_id=warehouse_id,
                event_type="inventory_reduced",
                payload={
                    "component_id": component_id,
                    "reduction_pct": reduction_pct,
                },
            )
        )
        return events

    def _gen_demand_spike(self) -> list[ScenarioEvent]:
        """Demand-spike event — deterministic payload in both contract modes.

        Resolution priority (J.3.2 contract):

        1. ``demand_change`` is an explicit numeric additive delta (legacy
           ``create_demand_spike_twin_scenario`` contract). Use it as-is.
        2. ``demand_multiplier`` is a multiplicative factor against the
           twin state's CURRENT base demand for ``component_id``
           (``demand.component.<id>``). The additive delta is computed as
           ``base_demand * (multiplier - 1)`` so the downstream
           ``_project_demand_changed`` projector (which is strictly
           additive) reproduces the multiplicative intent exactly.
        3. Neither — deterministic no-op. Records ``demand_change = 0``
           with no multiplier so the payload speaks for itself.

        All branches yield ``demand_change`` as a number, satisfying the
        projector's payload-key requirement (it would KeyError otherwise).
        """
        events: list[ScenarioEvent] = []
        component_id = self.scenario.target_entities.get("component", [""])[0]
        params = self.scenario.parameters
        payload: dict[str, Any] = {
            "confidence": params.get("confidence", 1.0),
            "source": params.get("source", "actual"),
        }

        explicit_change = params.get("demand_change")
        if explicit_change is not None:
            payload["demand_change"] = explicit_change
        elif "demand_multiplier" in params:
            multiplier = float(params["demand_multiplier"])
            payload["demand_multiplier"] = multiplier
            payload["demand_change"] = self._multiplier_to_delta(
                self._lookup_base_demand(component_id), multiplier
            )
        else:
            # J.3.2 contract: missing both ⇒ explicit no-op (no demand change).
            payload["demand_change"] = 0

        events.append(
            self._event(
                entity_type="component",
                entity_id=component_id,
                event_type="demand_changed",
                payload=payload,
            )
        )
        return events

    def _lookup_base_demand(self, component_id: str) -> float:
        """Read the current base demand for ``component_id`` from state.

        J.3.2 contract: demand vars follow the world-engine convention
        ``demand_var_id(component_id)``. When the state carries no demand
        variable for this component (or no state was supplied to the
        generator), the base is 0.0 — a deterministic, honest result
        that yields a zero-no-op payload rather than a synthetic constant.
        """
        if self.state is None:
            return 0.0
        from app.modules.world.state_projection import demand_var_id

        var = self.state.variables.get(demand_var_id(component_id))
        return float(var.raw_value) if var is not None else 0.0

    @staticmethod
    def _multiplier_to_delta(base_demand: float, multiplier: float) -> int | float:
        """Convert ``(base_demand, multiplier)`` to the additive delta the
        projector consumes. Preserves integer typing when the input is
        integer so the payload hash is reproducible across runs.
        """
        delta = base_demand * (multiplier - 1)
        if isinstance(base_demand, int):
            return int(round(delta))
        if float(base_demand).is_integer():
            return int(round(delta))
        return delta

    def _gen_route_disruption(self) -> list[ScenarioEvent]:
        events = []
        route_id = self.scenario.target_entities.get("route", [""])[0]
        delay_hours = self.scenario.parameters.get("delay_hours", 24)
        disruption_type = self.scenario.parameters.get("disruption_type", "port_closure")
        events.append(
            self._event(
                entity_type="route",
                entity_id=route_id,
                event_type="route_disrupted",
                payload={
                    "delay_hours": delay_hours,
                    "disruption_type": disruption_type,
                },
            )
        )
        return events

    def _gen_capacity_reduction(self) -> list[ScenarioEvent]:
        events = []
        for entity_type, entity_ids in self.scenario.target_entities.items():
            capacity_pct = self.scenario.parameters.get("capacity_pct", 50.0)
            for entity_id in entity_ids:
                events.append(
                    self._event(
                        entity_type=entity_type,
                        entity_id=entity_id,
                        event_type=f"{entity_type}_capacity_changed",
                        payload={"capacity_pct": capacity_pct},
                    )
                )
        return events

    def _gen_custom(self) -> list[ScenarioEvent]:
        """Generate events for custom scenarios from preserved legacy events."""
        events = []

        # Use custom events from metadata if available (from legacy TwinScenario conversion)
        custom_events = self.scenario.metadata.get("custom_events", [])
        if custom_events:
            for i, event in enumerate(custom_events):
                events.append(
                    self._event(
                        entity_type=event.get("entity_type", "custom"),
                        entity_id=event.get("entity_id", f"custom_{i}"),
                        event_type=event.get("event_type", "parameter_changed"),
                        payload=event.get("payload", {}),
                    )
                )
            return events

        # Fallback: generate from parameters
        for key, value in self.scenario.parameters.items():
            events.append(
                self._event(
                    entity_type="custom",
                    entity_id=key,
                    event_type="parameter_changed",
                    payload={"key": key, "value": value},
                )
            )
        return events


# ─────────────────────────────────────────────────────────────────────────────
# Propagation Engine (Graph-based State Change Propagation)
# ─────────────────────────────────────────────────────────────────────────────


class PropagationEngine:
    """Propagates state changes through the operational graph.

    A disruption at one node (e.g., supplier failure) cascades through
    the supply chain graph: supplier → warehouse → orders → customers.

    Determinism (J.3.2): propagated event IDs and sequence numbers are
    generated from a per-engine monotonic counter — NO wall-clock, NO
    urandom. Two runs of `run(twin, scenario, seed)` therefore yield
    byte-identical propagated event IDs, which is the precondition for
    the `trajectory_hash` reproducibility invariant at the J.3 exit gate.
    """

    def __init__(self, state: WorldState, snapshot: WorldSnapshot):
        self.state = state
        self.snapshot = snapshot
        self._propagation_counter = 0
        self._build_adjacency()

    def _next_propagation_id(self, run_id: str) -> str:
        """Deterministic event ID for a propagated event.

        Format: ``f"{run_id}:prop:{counter:04d}"`` where ``counter`` is a
        per-PropagationEngine monotonic integer that increments for every
        event emitted. Same (state, snapshot) + same primary event sequence
        ⇒ same counter progression ⇒ same IDs across runs.
        """
        self._propagation_counter += 1
        return f"{run_id}:prop:{self._propagation_counter:04d}"

    def _build_adjacency(self) -> None:
        """Build adjacency graph from the snapshot's graph structure.

        J.3.2 contract — metadata-scan propagation: cascade edges are read
        from each state variable's ``metadata`` map (e.g. ``supplier_id``,
        ``warehouse_id``, ``factory_id``, ``route_id``) rather than from a
        separate graph store. This is deterministic, guarantees projection
        isolation, and consumes the single authoritative World State —
        satisfying the "every other subsystem consumes that state rather
        than re-creating it" principle.

        The ``adjacency`` dict is reserved for the J.3.4 ground-truth
        upgrade, where it will be built from ``snapshot.graph_version``
        against the operational graph snapshot. J.3.2 deliberately defers
        that graph-backed propagation; the current implementation is
        strictly metadata-scan based.
        """
        self.adjacency: dict[str, list[tuple[str, str]]] = {}

    def propagate(self, initial_event: ScenarioEvent) -> list[ScenarioEvent]:
        """Propagate an initial event through the operational graph.

        Returns the cascade of derived events.
        """
        # For J.3.2 MVP, implement basic propagation rules:
        # supplier_failure → lead_time increases for dependent components
        # inventory_shortage → order fulfillment impacted
        # route_disruption → transit_time increases
        # capacity_reduction → throughput decreases

        derived = []

        if initial_event.event_type == "supplier_capacity_changed":
            derived.extend(self._propagate_supplier_failure(initial_event))
        elif initial_event.event_type == "supplier_delayed":
            derived.extend(self._propagate_supplier_delay(initial_event))
        elif initial_event.event_type == "inventory_reduced":
            derived.extend(self._propagate_inventory_shortage(initial_event))
        elif initial_event.event_type == "demand_changed":
            derived.extend(self._propagate_demand_spike(initial_event))
        elif initial_event.event_type == "route_disrupted":
            derived.extend(self._propagate_route_disruption(initial_event))
        elif initial_event.event_type.endswith("_capacity_changed"):
            derived.extend(self._propagate_capacity_reduction(initial_event))

        return derived

    def _propagate_supplier_failure(self, event: ScenarioEvent) -> list[ScenarioEvent]:
        """Supplier failure propagates to lead times of dependent components."""
        derived = []
        supplier_id = event.entity_id
        # Find components that depend on this supplier
        for _var_id, var in self.state.variables.items():
            if var.entity_type == "component" and var.metadata.get("supplier_id") == supplier_id:
                derived.append(
                    ScenarioEvent(
                        event_id=self._next_propagation_id(event.scenario_run_id),
                        scenario_run_id=event.scenario_run_id,
                        sequence=0,  # Will be renumbered
                        entity_type="component",
                        entity_id=var.entity_id,
                        event_type="lead_time_changed",
                        payload={"delta_days": 7, "reason": f"supplier_{supplier_id}_failure"},
                        occurred_at=event.occurred_at + timedelta(hours=1),
                    )
                )
        return derived

    def _propagate_supplier_delay(self, event: ScenarioEvent) -> list[ScenarioEvent]:
        return self._propagate_supplier_failure(event)

    def _propagate_inventory_shortage(self, event: ScenarioEvent) -> list[ScenarioEvent]:
        """Inventory shortage affects order fulfillment."""
        derived = []
        warehouse_id = event.entity_id
        component_id = event.payload.get("component_id")
        reduction_pct = event.payload.get("reduction_pct", 50.0)

        for _var_id, var in self.state.variables.items():
            if (
                var.entity_type == "order"
                and var.metadata.get("warehouse_id") == warehouse_id
                and (component_id is None or var.metadata.get("component_id") == component_id)
            ):
                derived.append(
                    ScenarioEvent(
                        event_id=self._next_propagation_id(event.scenario_run_id),
                        scenario_run_id=event.scenario_run_id,
                        sequence=0,
                        entity_type="order",
                        entity_id=var.entity_id,
                        event_type="order_fulfillment_risk",
                        payload={
                            "risk_increase_pct": reduction_pct,
                            "reason": f"inventory_shortage_at_{warehouse_id}",
                        },
                        occurred_at=event.occurred_at + timedelta(hours=1),
                    )
                )
        return derived

    def _propagate_demand_spike(self, event: ScenarioEvent) -> list[ScenarioEvent]:
        """Demand spike depletes inventory faster."""
        derived = []
        component_id = event.entity_id
        multiplier = event.payload.get("demand_multiplier", 2.0)

        for _var_id, var in self.state.variables.items():
            if var.entity_type == "inventory" and var.entity_id == component_id:
                derived.append(
                    ScenarioEvent(
                        event_id=self._next_propagation_id(event.scenario_run_id),
                        scenario_run_id=event.scenario_run_id,
                        sequence=0,
                        entity_type="inventory",
                        entity_id=component_id,
                        event_type="demand_fulfillment_rate_changed",
                        payload={"multiplier": multiplier},
                        occurred_at=event.occurred_at + timedelta(hours=1),
                    )
                )
        return derived

    def _propagate_route_disruption(self, event: ScenarioEvent) -> list[ScenarioEvent]:
        """Route disruption increases transit times for affected shipments."""
        derived = []
        route_id = event.entity_id
        delay_hours = event.payload.get("delay_hours", 24)

        for _var_id, var in self.state.variables.items():
            if var.entity_type == "shipment" and var.metadata.get("route_id") == route_id:
                derived.append(
                    ScenarioEvent(
                        event_id=self._next_propagation_id(event.scenario_run_id),
                        scenario_run_id=event.scenario_run_id,
                        sequence=0,
                        entity_type="shipment",
                        entity_id=var.entity_id,
                        event_type="transit_time_changed",
                        payload={
                            "delay_hours": delay_hours,
                            "reason": f"route_{route_id}_disruption",
                        },
                        occurred_at=event.occurred_at + timedelta(hours=1),
                    )
                )
        return derived

    def _propagate_capacity_reduction(self, event: ScenarioEvent) -> list[ScenarioEvent]:
        """Capacity reduction at warehouse/factory reduces throughput."""
        derived = []
        entity_type = event.entity_type
        entity_id = event.entity_id
        capacity_pct = event.payload.get("capacity_pct", 50.0)

        # Find dependent entities and reduce their throughput
        if entity_type == "factory":
            for _var_id, var in self.state.variables.items():
                if var.entity_type == "component" and var.metadata.get("factory_id") == entity_id:
                    derived.append(
                        ScenarioEvent(
                            event_id=self._next_propagation_id(event.scenario_run_id),
                            scenario_run_id=event.scenario_run_id,
                            sequence=0,
                            entity_type="component",
                            entity_id=var.entity_id,
                            event_type="production_rate_changed",
                            payload={"capacity_multiplier": capacity_pct / 100.0},
                            occurred_at=event.occurred_at + timedelta(hours=1),
                        )
                    )
        elif entity_type == "warehouse":
            for _var_id, var in self.state.variables.items():
                if var.entity_type == "inventory" and var.metadata.get("warehouse_id") == entity_id:
                    derived.append(
                        ScenarioEvent(
                            event_id=self._next_propagation_id(event.scenario_run_id),
                            scenario_run_id=event.scenario_run_id,
                            sequence=0,
                            entity_type="inventory",
                            entity_id=var.entity_id,
                            event_type="throughput_changed",
                            payload={"capacity_multiplier": capacity_pct / 100.0},
                            occurred_at=event.occurred_at + timedelta(hours=1),
                        )
                    )
        return derived


# ─────────────────────────────────────────────────────────────────────────────
# Trajectory Recorder
# ─────────────────────────────────────────────────────────────────────────────


class TrajectoryRecorder:
    """Records the state trajectory during scenario execution.

    Captures state snapshots at each tick for replay and analysis.

    Determinism (J.3.2): every field captured by ``record()`` must be a
    pure function of ``(snapshot, scenario, seed, tick)``. We deliberately
    exclude:

    - **``timestamp``** — wall-clock, would differ between two identical runs.
    - **``event.event_id``** — embeds the per-invocation ``run_id``, which
      is a fresh ``uuid7()`` per call (persistence uniqueness). The run_id
      is NOT reproducible, so it must not enter ``trajectory_hash``.
    - **``event.scenario_run_id``** — same reason.

    What remains is the event SIGNATURE: ``sequence``, ``entity_type``,
    ``entity_id``, ``event_type``, ``payload``, ``occurred_at``. All of
    these are pure functions of ``(snapshot, scenario, seed, tick)`` via
    ``ScenarioEventGenerator`` and the deterministic propagation counter,
    so ``trajectory_hash`` is reproducible across runs.
    """

    def __init__(self) -> None:
        self.snapshots: list[dict[str, Any]] = []

    def record(self, state: WorldState, tick: int, event: ScenarioEvent | None = None) -> None:
        """Record a trajectory point — deterministic only."""
        from app.modules.world.state_projection import compute_state_hash

        snapshot = {
            "tick": tick,
            "version": state.version,
            "state_hash": state.metadata.get("state_hash") or compute_state_hash(state),
            "variable_count": len(state.variables),
            "event_signature": self._event_signature(event) if event else None,
        }
        self.snapshots.append(snapshot)

    @staticmethod
    def _event_signature(event: ScenarioEvent) -> dict[str, Any]:
        """Deterministic subset of a ScenarioEvent — excludes event_id and
        scenario_run_id (both carry the per-invocation run_id)."""
        return {
            "sequence": event.sequence,
            "entity_type": event.entity_type,
            "entity_id": event.entity_id,
            "event_type": event.event_type,
            "payload": dict(event.payload),
            "occurred_at": event.occurred_at.isoformat(),
        }

    def get_trajectory(self) -> list[dict[str, Any]]:
        return self.snapshots

    def trajectory_hash(self) -> str:
        """SHA-256 of the canonical trajectory.

        Reproducible iff (snapshot, scenario, seed) are identical:
        ``run(S, X, seed)`` ⇒ identical ``trajectory_hash`` across calls.
        """
        import hashlib
        import json

        canonical = json.dumps(self.snapshots, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        return hashlib.sha256(canonical).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# Scenario Runtime
# ─────────────────────────────────────────────────────────────────────────────


class ScenarioRuntime:
    """Deterministic scenario execution engine (J.3.2).

    Orchestrates the full scenario execution:
    1. Load twin's current state
    2. Generate events from scenario
    3. Propagate events through graph
    4. Project all events to compute final state
    5. Record trajectory
    6. Return ScenarioRun with full provenance
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = TwinRepository(db)
        self.world_repo = StateRepository(db)
        self.enforcer = TwinIsolationEnforcer(db)

    async def execute(
        self,
        twin: DigitalTwin,
        scenario: Scenario,
    ) -> ScenarioRun:
        """Execute a scenario against a twin deterministically.

        Returns a ScenarioRun with full provenance.
        """
        run_id = str(uuid7())
        started_at = datetime.now(UTC)

        # Create initial ScenarioRun record
        run = ScenarioRun(
            run_id=run_id,
            twin_id=twin.twin_id,
            scenario_id=scenario.scenario_id,
            source_snapshot_id=twin.snapshot_id,
            source_state_hash="",
            seed=scenario.seed,
            engine_version=TWIN_ENGINE_VERSION,
            simulation_version=TWIN_SIMULATION_VERSION,
            started_at=started_at,
            status=TwinRunStatus.RUNNING,
        )

        try:
            # Load snapshot and twin's current state
            snapshot = await self.world_repo.get_snapshot(twin.snapshot_id, twin.workspace_id)
            if not snapshot:
                raise IsolationError(f"Snapshot {twin.snapshot_id} not found")

            current_state = await self._get_twin_current_state(twin, snapshot)
            run = replace(run, initial_state_hash=current_state.metadata.get("state_hash", ""))

            # Generate events from scenario (state supplied for deterministic
            # parameter derivation — e.g. demand spike multiplier lookup).
            generator = ScenarioEventGenerator(run_id, scenario, snapshot, state=current_state)
            primary_events = generator.generate()

            # Propagate and project all events
            all_events = list(primary_events)

            # Add propagated events
            propagation_engine = PropagationEngine(current_state, snapshot)
            for event in primary_events:
                propagated = propagation_engine.propagate(event)
                all_events.extend(propagated)

            # Record trajectory
            trajectory = TrajectoryRecorder()
            trajectory.record(current_state, tick=0)

            # Project all events in sequence
            state = current_state
            for i, event in enumerate(all_events):
                fake_event = self._to_fake_event(event, twin.parent_world_id, twin.workspace_id)
                transition = project_event_to_transition(state, fake_event)
                if transition is not None:
                    state = apply_transition(state, transition)

                # Record trajectory at each step
                trajectory.record(state, tick=i + 1, event=event)

            # Compute final hashes
            from app.modules.world.state_projection import compute_state_hash

            final_state_hash = state.metadata.get("state_hash") or compute_state_hash(state)
            trajectory_hash = trajectory.trajectory_hash()

            completed_at = datetime.now(UTC)

            # Snapshot the trajectory in-memory; consumers (TwinService.run →
            # KPIEngine.compute) read it from the ScenarioRun without
            # needing to reproject events. Persisted TwinRunDB rows already
            # freeze trajectory via the injected_events log + trajectory_hash.
            trajectory_snapshots = trajectory.get_trajectory()

            run = replace(
                run,
                completed_at=completed_at,
                event_count=len(all_events),
                final_state_hash=final_state_hash,
                trajectory_hash=trajectory_hash,
                status=TwinRunStatus.SUCCEEDED,
                result_hash=final_state_hash,  # For J.3.2, result_hash == final_state_hash
                trajectory_snapshots=trajectory_snapshots,
            )

            # Persist events and run
            await self._persist_run(run, all_events, trajectory_snapshots, twin.workspace_id, state)

            return run

        except Exception as e:
            completed_at = datetime.now(UTC)
            run = replace(
                run,
                completed_at=completed_at,
                status=TwinRunStatus.FAILED,
                error_message=str(e),
            )
            raise

    async def _get_twin_current_state(
        self, twin: DigitalTwin, snapshot: WorldSnapshot
    ) -> WorldState:
        """Get the twin's current state (latest run or snapshot)."""
        latest_run = await self.repo.get_latest_run(twin.twin_id, twin.workspace_id)
        if latest_run is not None:
            return self._state_from_run(twin, snapshot, latest_run)
        return await self._validated_parent_state(twin.workspace_id, twin.parent_world_id, snapshot)

    async def _validated_parent_state(
        self, workspace_id: str, world_id: str, snapshot: WorldSnapshot
    ) -> WorldState:
        state = await self.world_repo.get(world_id, workspace_id, snapshot.version)
        if not state:
            raise IsolationError(f"Parent world state version {snapshot.version} not found")
        return state

    def _state_from_run(self, twin: DigitalTwin, snapshot: WorldSnapshot, run: Any) -> WorldState:
        """Reconstruct a WorldState from a persisted twin run's final variables."""
        variables: dict[str, StateVariable] = {}
        for vid, vdata in (run.final_variables or {}).items():
            variables[vid] = StateVariable(
                variable_id=vid,
                variable_type=StateVariableType(vdata["variable_type"]),
                entity_id=vdata["entity_id"],
                entity_type=vdata["entity_type"],
                value=vdata["value"],
                unit=vdata.get("unit"),
                metadata=vdata.get("metadata", {}),
            )
        from app.modules.world.state_projection import compute_state_hash

        state = WorldState(
            world_id=twin.parent_world_id,
            workspace_id=twin.workspace_id,
            version=run.final_version,
            variables=variables,
            graph_version=snapshot.graph_version,
            created_at=run.finished_at or run.created_at,
            metadata={},
        )
        return replace(
            state, metadata={"state_hash": run.final_state_hash or compute_state_hash(state)}
        )

    def _to_fake_event(self, event: ScenarioEvent, world_id: str, workspace_id: str) -> Any:
        """Convert ScenarioEvent to FakeEvent for projection."""
        from app.modules.twin.twin_validation_helpers import make_fake_event

        return make_fake_event(
            event_id=event.event_id,
            world_id=world_id,
            workspace_id=workspace_id,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            event_type=event.event_type,
            payload=event.payload,
            occurred_at=event.occurred_at,
        )

    async def _persist_run(
        self,
        run: ScenarioRun,
        events: list[ScenarioEvent],
        trajectory: list[dict[str, Any]],
        workspace_id: str,
        final_state: WorldState,
    ) -> None:
        """Persist run and events to the database."""
        from app.modules.twin.twin_models import ScenarioType, TwinScenario
        from app.modules.twin.twin_repository import TwinRunDB

        # Convert final state variables to dict for storage
        final_variables = {}
        for vid, var in final_state.variables.items():
            final_variables[vid] = {
                "variable_type": var.variable_type.value,
                "entity_id": var.entity_id,
                "entity_type": var.entity_type,
                "value": var.raw_value,
                "unit": var.unit,
                "metadata": var.metadata,
            }

        # Create a minimal TwinScenario from the J.3.2 Scenario
        minimal_scenario = TwinScenario(
            scenario_id=run.scenario_id,
            name=run.scenario_id,
            scenario_type=ScenarioType.CUSTOM,
            events=[],
        )

        run_row = TwinRunDB.from_values(
            twin_id=run.twin_id,
            workspace_id=workspace_id,
            scenario=minimal_scenario,
            seed=run.seed,
            injected_events=[e.to_dict() for e in events],
            final_variables=final_variables,
            final_state_hash=run.final_state_hash,
            final_version=final_state.version,
            metrics={},
            comparison=None,
            created_at=run.started_at,
            finished_at=run.completed_at or run.started_at,
        )
        run_row.run_id = run.run_id
        run_row.scenario_id = run.scenario_id
        run_row.scenario_type = "scenario"
        run_row.extra_metadata = {
            "trajectory_hash": run.trajectory_hash,
            "initial_state_hash": run.initial_state_hash,
            "event_count": run.event_count,
            "rng_version": TWIN_RNG_VERSION,
            "engine_version": TWIN_ENGINE_VERSION,
            "simulation_version": TWIN_SIMULATION_VERSION,
        }

        self.db.add(run_row)
        await self.db.flush()
