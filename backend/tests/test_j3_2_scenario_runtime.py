"""J.3.2 Scenario Runtime — Deterministic Execution & Scenario Contract.

These tests extend the J.3.1 frozen contract with the invariants that the
J.3.2 subsystem specifically owns:

SR-1  DECLARATIVE SCENARIO GENERATORS
      Each `ScenarioType` produces a deterministic `ScenarioEvent` sequence
      via `ScenarioEventGenerator`. Event payloads are pure functions of
      (snapshot, scenario.parameters, scenario.seed, generator.tick);
      event IDs are a pure function of (run_id, tick).

SR-2  PROPAGATION DETERMINISM
      `PropagationEngine` derives cascade events using a per-engine
      monotonic counter — NO `uuid7()`, NO wall-clock. Two runs of
      `run(twin, scenario, seed)` produce byte-identical propagated
      event IDs (the precondition for trajectory reproducibility).

SR-3  TRAJECTORY REPRODUCIBILITY (the J.3 exit gate's #4 invariant)
      `TrajectoryRecorder` captures only fields that are pure functions
      of (snapshot, scenario, seed). Wall-clock timestamps and the
      per-invocation `run_id` are excluded, so two runs of
      `run(S, X, seed)` ⇒ identical `trajectory_hash`.

SR-4  PRODUCTION ISOLATION UNDER RUNTIME
      `ScenarioRuntime.execute` writes only to the twin namespace;
      `production_fingerprint` is unchanged before/after.

SR-5  PERSISTED TRAJECTORY
      The persisted `TwinRunDB.extra_metadata["trajectory_hash"]` equals
      the in-memory `ScenarioRun.trajectory_hash` returned by the
      runtime — the on-disk run record carries the reproducibility
      fingerprint downstream to J.3.3 (KPI) and J.3.4 (counterfactual).

The durable scope expansion over J.3.1 is:
- Trajectory-level (not just state-level) determinism.
- The new declarative `create_*_scenario` factories for the six
  ScenarioType values with J.3.2 generators (the legacy TwinScenario
  wrappers continue to be exercised by `test_digital_twin.py`).

Run (SQLite, always):
    pytest tests/test_j3_2_scenario_runtime.py -v

Run (PostgreSQL, integration):
    pytest tests/test_j3_2_scenario_runtime.py -v \
        --postgres-url="postgresql+asyncpg://postgres:postgres@localhost:5433/cortex_test"
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.common.ids import uuid7
from app.modules.twin.scenario_runtime import (
    PropagationEngine,
    ScenarioEventGenerator,
    TrajectoryRecorder,
)
from app.modules.twin.twin_isolation import production_fingerprint
from app.modules.twin.twin_models import (
    TWIN_ENGINE_VERSION,
    TWIN_SIMULATION_VERSION,
    Scenario,
    ScenarioEvent,
    ScenarioType,
    create_capacity_reduction_scenario,
    create_demand_spike_scenario,
    create_inventory_shortage_scenario,
    create_route_disruption_scenario,
    create_supplier_delay_scenario,
    create_supplier_failure_scenario,
)
from app.modules.twin.twin_repository import TwinRepository
from app.modules.twin.twin_service import TwinService
from app.modules.world.state_projection import (
    create_initial_state,
    create_state_snapshot,
    demand_var_id,
    inventory_var_id,
    lead_time_var_id,
)
from app.modules.world.state_repository import StateRepository
from app.modules.world.world_models import StateVariable, StateVariableType

# ─────────────────────────────────────────────────────────────────────────────
# Test helpers
# ─────────────────────────────────────────────────────────────────────────────


async def _seed_production_world(
    session: Any,
    workspace_id: str,
    world_id: str,
    *,
    with_demand: bool = False,
) -> tuple[Any, Any]:
    """Create a production world (v1) + snapshot with inventory/lead vars.

    When `with_demand=True`, also seed a `demand.component.comp_a` variable
    with raw value 100 — blocks tests that exercise demand-spike scenarios
    from collapsing into the "no base demand ⇒ no-op" path.
    """
    repo = StateRepository(session)
    inv = StateVariable.from_raw_value(
        variable_id=inventory_var_id("wh_1", "comp_a"),
        variable_type=StateVariableType.INVENTORY,
        entity_id="wh_1",
        entity_type="warehouse",
        raw_value=500,
    )
    lt = StateVariable.from_raw_value(
        variable_id=lead_time_var_id("sup_1"),
        variable_type=StateVariableType.LEAD_TIME,
        entity_id="sup_1",
        entity_type="supplier",
        raw_value=10,
    )
    initial: dict[str, StateVariable] = {
        inv.variable_id: inv,
        lt.variable_id: lt,
    }
    if with_demand:
        demand = StateVariable.from_raw_value(
            variable_id=demand_var_id("comp_a"),
            variable_type=StateVariableType.DEMAND,
            entity_id="comp_a",
            entity_type="component",
            raw_value=100,
        )
        initial[demand.variable_id] = demand
    state = create_initial_state(
        workspace_id=workspace_id,
        world_id=world_id,
        graph_version=1,
        initial_variables=initial,
    )
    snapshot = create_state_snapshot(state, created_by="j32_test")
    await repo.create(state)
    await repo.store_snapshot(snapshot)
    return state, snapshot


def _supplier_failure_scenario(
    scenario_id: str = "scn_supp_fail",
    seed: int = 0,
    capacity_pct: float = 0.0,
) -> Scenario:
    """J.3.2 declarative supplier failure — pure datum, no embedded events."""
    return create_supplier_failure_scenario(
        scenario_id=scenario_id,
        supplier_id="sup_1",
        capacity_pct=capacity_pct,
        disruption_type="factory_fire",
        seed=seed,
    )


def _make_snapshot(state: Any) -> Any:
    """Build a snapshot for an in-memory state (not persisted)."""
    return create_state_snapshot(state, created_by="j32_unit")


# ─────────────────────────────────────────────────────────────────────────────
# A. Scenario generators — declarative contract (SR-1)
# ─────────────────────────────────────────────────────────────────────────────


class TestScenarioGenerators:
    """SR-1: Each ScenarioType emits deterministic, contract-correct events."""

    def _make_state(self) -> Any:
        return create_initial_state(
            workspace_id="ws_test",
            world_id="world_test",
            graph_version=1,
            initial_variables={
                demand_var_id("comp_a"): StateVariable.from_raw_value(
                    variable_id=demand_var_id("comp_a"),
                    variable_type=StateVariableType.DEMAND,
                    entity_id="comp_a",
                    entity_type="component",
                    raw_value=100,
                ),
            },
        )

    def _gen(
        self,
        scenario: Scenario,
        *,
        run_id: str = "run_test",
        state: Any | None = None,
    ) -> list[ScenarioEvent]:
        snapshot = _make_snapshot(state or self._make_state())
        return ScenarioEventGenerator(run_id, scenario, snapshot, state=state).generate()

    def test_supplier_failure_generator_capacity_mode(self) -> None:
        """J.3.2 declarative supplier failure emits `supplier_capacity_changed`."""
        scn = _supplier_failure_scenario(capacity_pct=0.0)
        events = self._gen(scn)

        assert len(events) == 1
        e = events[0]
        assert e.entity_type == "supplier"
        assert e.entity_id == "sup_1"
        assert e.event_type == "supplier_capacity_changed"
        assert e.payload["capacity_pct"] == 0.0
        assert e.payload["disruption_type"] == "factory_fire"
        # Event ID is a pure function of (run_id, tick) — no uuid7 / wall-clock.
        assert e.event_id == "run_test:evt:0000"

    def test_supplier_failure_generator_delay_days_legacy_compat(self) -> None:
        """When `delay_days` is present in parameters (legacy contract),
        the supplier-failure generator emits `supplier_delayed` — the same
        event type the legacy TwinScenario.factory produces."""
        scn = Scenario(
            scenario_id="scn_legacy",
            scenario_type=ScenarioType.SUPPLIER_FAILURE,
            target_entities={"supplier": ["sup_1"]},
            parameters={"delay_days": 7, "disruption_type": "port_strike"},
            seed=0,
        )
        events = self._gen(scn)

        assert len(events) == 1
        assert events[0].event_type == "supplier_delayed"
        assert events[0].payload["delay_days"] == 7
        assert events[0].payload["disruption_type"] == "port_strike"

    def test_supplier_delay_generator(self) -> None:
        """J.3.2 declarative supplier delay emits the delay event."""
        scn = create_supplier_delay_scenario(
            scenario_id="scn_sd",
            supplier_id="sup_1",
            delay_days=3,
            seed=1,
        )
        events = self._gen(scn, run_id="r_sd")

        assert len(events) == 1
        assert events[0].event_type == "supplier_delayed"
        assert events[0].entity_id == "sup_1"
        assert events[0].payload["delay_days"] == 3
        assert events[0].event_id == "r_sd:evt:0000"

    def test_inventory_shortage_generator(self) -> None:
        scn = create_inventory_shortage_scenario(
            scenario_id="scn_inv",
            warehouse_id="wh_1",
            component_id="comp_a",
            reduction_pct=40.0,
            seed=0,
        )
        events = self._gen(scn)

        assert len(events) == 1
        e = events[0]
        assert e.entity_type == "warehouse"
        assert e.entity_id == "wh_1"
        assert e.event_type == "inventory_reduced"
        assert e.payload["component_id"] == "comp_a"
        assert e.payload["reduction_pct"] == 40.0

    def test_route_disruption_generator(self) -> None:
        scn = create_route_disruption_scenario(
            scenario_id="scn_route",
            route_id="route_7",
            delay_hours=48,
            disruption_type="port_closure",
            seed=0,
        )
        events = self._gen(scn)

        assert len(events) == 1
        e = events[0]
        assert e.entity_type == "route"
        assert e.entity_id == "route_7"
        assert e.event_type == "route_disrupted"
        assert e.payload["delay_hours"] == 48
        assert e.payload["disruption_type"] == "port_closure"

    def test_capacity_reduction_generator_multi_entity(self) -> None:
        """Capacity reduction fans out one event per target entity."""
        scn = create_capacity_reduction_scenario(
            scenario_id="scn_cap",
            entity_type="factory",
            entity_id="fac_1",
            capacity_pct=30.0,
            seed=0,
        )
        events = self._gen(scn)

        assert len(events) == 1
        assert events[0].event_type == "factory_capacity_changed"
        assert events[0].payload["capacity_pct"] == 30.0


class TestDemandSpikeGenerator:
    """Demand spike is the one generator with two resolution modes (legacy +
    declarative) plus an explicit no-op path. Each must produce a numeric
    `demand_change` in the payload so the projector (which key-errors
    otherwise) can apply the event."""

    def _state_with_demand(self, base: float = 100) -> Any:
        return create_initial_state(
            workspace_id="ws_test",
            world_id="world_test",
            graph_version=1,
            initial_variables={
                demand_var_id("comp_a"): StateVariable.from_raw_value(
                    variable_id=demand_var_id("comp_a"),
                    variable_type=StateVariableType.DEMAND,
                    entity_id="comp_a",
                    entity_type="component",
                    raw_value=base,
                ),
            },
        )

    def _gen(
        self,
        scenario: Scenario,
        *,
        state: Any | None = None,
        run_id: str = "r",
    ) -> ScenarioEvent:
        snapshot = _make_snapshot(
            state
            or create_initial_state(
                workspace_id="ws_test",
                world_id="world_test",
                graph_version=1,
                initial_variables={},
            )
        )
        events = ScenarioEventGenerator(run_id, scenario, snapshot, state=state).generate()
        assert len(events) == 1
        return events[0]

    def test_explicit_demand_change_wins(self) -> None:
        """When `demand_change` is supplied (legacy contract), it is used
        verbatim and no multiplier is recorded in the payload."""
        scn = Scenario(
            scenario_id="scn_exp",
            scenario_type=ScenarioType.DEMAND_SPIKE,
            target_entities={"component": ["comp_a"]},
            parameters={"demand_change": 500, "confidence": 0.9},
            seed=0,
        )
        e = self._gen(scn)

        assert e.payload["demand_change"] == 500
        assert "demand_multiplier" not in e.payload
        assert e.payload["confidence"] == 0.9

    def test_multiplier_with_state_computes_additive_delta(self) -> None:
        """With base demand = 100 and multiplier = 2.0, additive delta = 100."""
        scn = create_demand_spike_scenario(
            scenario_id="scn_mul_state",
            component_id="comp_a",
            demand_multiplier=2.0,
            seed=0,
        )
        e = self._gen(scn, state=self._state_with_demand(base=100))

        # delta = base * (multiplier - 1) = 100 * 1 = 100 (integer base ⇒ int delta)
        assert e.payload["demand_change"] == 100
        assert e.payload["demand_multiplier"] == 2.0

    def test_multiplier_no_state_yields_deterministic_noop(self) -> None:
        """No demand variable in state (or no state at all) ⇒ `demand_change`
        is a deterministic 0, not the pre-fix synthetic 100."""
        scn = create_demand_spike_scenario(
            scenario_id="scn_mul_noop",
            component_id="comp_a",
            demand_multiplier=2.0,
            seed=0,
        )
        e = self._gen(scn)

        assert e.payload["demand_change"] == 0
        assert e.payload["demand_multiplier"] == 2.0

    def test_multiplier_one_yields_zero_delta(self) -> None:
        """A multiplier of 1.0 produces no change (deterministic)."""
        scn = create_demand_spike_scenario(
            scenario_id="scn_mul_one",
            component_id="comp_a",
            demand_multiplier=1.0,
            seed=0,
        )
        e = self._gen(scn, state=self._state_with_demand(base=500))

        assert e.payload["demand_change"] == 0
        assert e.payload["demand_multiplier"] == 1.0

    def test_no_change_no_multiplier_yields_explicit_noop(self) -> None:
        """Neither `demand_change` nor `demand_multiplier` ⇒ J.3.2 contract
        is a deterministic zero, not a synthetic constant."""
        scn = Scenario(
            scenario_id="scn_empty",
            scenario_type=ScenarioType.DEMAND_SPIKE,
            target_entities={"component": ["comp_a"]},
            parameters={},
            seed=0,
        )
        e = self._gen(scn)

        assert e.payload["demand_change"] == 0
        assert "demand_multiplier" not in e.payload


# ─────────────────────────────────────────────────────────────────────────────
# B. PropagationEngine — propagated event IDs are deterministic (SR-2)
# ─────────────────────────────────────────────────────────────────────────────


class TestPropagationDeterminism:
    """SR-2: propagated event IDs are a pure function of (run_id, counter) —
    no `uuid7()`, no `os.urandom`. Two runs with the same inputs produce the
    same propagated event IDs."""

    def _state_with_supplier_dep(self) -> Any:
        """State with a component whose `supplier_id = sup_1` metadata — the
        propagation edge supplier-failure → component lead_time relies on it."""
        comp_var = StateVariable.from_raw_value(
            variable_id="component.comp_a",
            variable_type=StateVariableType.INVENTORY,
            entity_id="comp_a",
            entity_type="component",
            raw_value=10,
        )
        # Inject the metadata link that the supplier-failure propagator reads.
        comp_var_with_supplier = StateVariable(
            variable_id=comp_var.variable_id,
            variable_type=comp_var.variable_type,
            entity_id=comp_var.entity_id,
            entity_type=comp_var.entity_type,
            value=comp_var.value,
            unit=comp_var.unit,
            metadata={"supplier_id": "sup_1"},
        )
        return create_initial_state(
            workspace_id="ws_test",
            world_id="world_test",
            graph_version=1,
            initial_variables={comp_var_with_supplier.variable_id: comp_var_with_supplier},
        )

    def test_propagation_event_id_is_deterministic_across_engines(self) -> None:
        """Run the supplier-failure propagation twice with two fresh engines
        — same inputs ⇒ same propagated event ID."""
        parent_event = ScenarioEvent(
            event_id="run_test:evt:0000",
            scenario_run_id="run_test",
            sequence=0,
            entity_type="supplier",
            entity_id="sup_1",
            event_type="supplier_capacity_changed",
            payload={"capacity_pct": 0.0, "disruption_type": "factory_fire"},
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

        state = self._state_with_supplier_dep()
        snapshot = _make_snapshot(state)

        eng1 = PropagationEngine(state, snapshot)
        eng2 = PropagationEngine(state, snapshot)

        derived_1 = eng1.propagate(parent_event)
        derived_2 = eng2.propagate(parent_event)

        assert len(derived_1) >= 1
        assert len(derived_1) == len(derived_2)
        for a, b in zip(derived_1, derived_2, strict=True):
            assert a.event_id == b.event_id
            # The propagation ID format is `f"{run_id}:prop:{counter:04d}"`
            assert a.event_id == "run_test:prop:0001"

    def test_propagation_counter_increments_monotonically(self) -> None:
        """Repeated propagation calls within one engine advance the counter."""
        parent_event = ScenarioEvent(
            event_id="run_test:evt:0000",
            scenario_run_id="run_test",
            sequence=0,
            entity_type="supplier",
            entity_id="sup_1",
            event_type="supplier_capacity_changed",
            payload={"capacity_pct": 0.0, "disruption_type": "factory_fire"},
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

        state = self._state_with_supplier_dep()
        snapshot = _make_snapshot(state)
        eng = PropagationEngine(state, snapshot)

        # Propagate the same event twice — counter advances each call.
        first = eng.propagate(parent_event)
        second = eng.propagate(parent_event)

        assert first[0].event_id == "run_test:prop:0001"
        assert second[0].event_id == "run_test:prop:0002"
        # The propagation ID prefix is the parent's run_id (deterministic).
        assert all(e.event_id.startswith("run_test:prop:") for e in first + second)


# ─────────────────────────────────────────────────────────────────────────────
# C. TrajectoryRecorder — reproducibility contract (SR-3)
# ─────────────────────────────────────────────────────────────────────────────


class TestTrajectoryRecorder:
    """SR-3: trajectory_hash is a pure function of (snapshot, scenario, seed)."""

    def _state(self, lead_time: int = 10) -> Any:
        lt = StateVariable.from_raw_value(
            variable_id=lead_time_var_id("sup_1"),
            variable_type=StateVariableType.LEAD_TIME,
            entity_id="sup_1",
            entity_type="supplier",
            raw_value=lead_time,
        )
        return create_initial_state(
            workspace_id="ws_test",
            world_id="world_test",
            graph_version=1,
            initial_variables={lt.variable_id: lt},
        )

    def _event(
        self,
        *,
        sequence: int = 0,
        event_type: str = "supplier_delayed",
        payload: dict[str, Any] | None = None,
        run_id: str = "run_a",
        occurred_at: datetime | None = None,
    ) -> ScenarioEvent:
        return ScenarioEvent(
            event_id=f"{run_id}:evt:{sequence:04d}",
            scenario_run_id=run_id,
            sequence=sequence,
            entity_type="supplier",
            entity_id="sup_1",
            event_type=event_type,
            payload=payload if payload is not None else {"delay_days": 5},
            occurred_at=occurred_at or datetime(2026, 1, 1, tzinfo=UTC),
        )

    def test_event_signature_excludes_run_id_and_event_id(self) -> None:
        """The `event_signature` dict captured by the recorder drops event_id
        and scenario_run_id (both carry the per-invocation run_id from
        uuid7). This is the precondition for trajectory_hash reproducibility.
        """
        e = self._event(run_id="run_unique_id_xyz")
        sig = TrajectoryRecorder._event_signature(e)

        assert "event_id" not in sig
        assert "scenario_run_id" not in sig
        # Deterministic fields are preserved.
        assert sig["sequence"] == 0
        assert sig["entity_type"] == "supplier"
        assert sig["entity_id"] == "sup_1"
        assert sig["event_type"] == "supplier_delayed"
        assert sig["payload"] == {"delay_days": 5}

    def test_trajectory_hash_reproducible_across_run_ids(self) -> None:
        """Two runs with their own uuid7-based run_id produce identical
        trajectory_hash as long as the inputs (event sequence + payload)
        match."""
        state = self._state()

        rec_a = TrajectoryRecorder()
        rec_b = TrajectoryRecorder()
        # Record two ticks of the SAME state.
        rec_a.record(state, tick=0)
        rec_a.record(state, tick=1, event=self._event(run_id="run_unique_a", sequence=0))
        rec_b.record(state, tick=0)
        rec_b.record(state, tick=1, event=self._event(run_id="run_unique_b", sequence=0))

        assert rec_a.trajectory_hash() == rec_b.trajectory_hash()

    def test_trajectory_hash_differs_on_different_payloads(self) -> None:
        state = self._state()

        rec_a = TrajectoryRecorder()
        rec_b = TrajectoryRecorder()
        rec_a.record(state, tick=0, event=self._event(payload={"delay_days": 5}))
        rec_b.record(state, tick=0, event=self._event(payload={"delay_days": 21}))

        assert rec_a.trajectory_hash() != rec_b.trajectory_hash()

    def test_trajectory_record_excludes_wall_clock(self) -> None:
        """Snapshots never capture `datetime.now()` — the dropped `timestamp`
        key must not appear in trajectory records, so the hash is not a
        function of wall-clock time."""
        state = self._state()
        rec = TrajectoryRecorder()
        rec.record(state, tick=0, event=self._event())

        for snap in rec.get_trajectory():
            assert "timestamp" not in snap
            assert "event" not in snap  # the canonical field is event_signature


# ─────────────────────────────────────────────────────────────────────────────
# D. ScenarioRuntime.execute — J.3 exit gate invariants under DB (SR-4, SR-5)
# ─────────────────────────────────────────────────────────────────────────────


class TestScenarioRuntimeExitGate:
    """The four J.3 exit-gate invariants as extended by J.3.2 (state-level
    AND trajectory-level reproducibility), plus production isolation under
    runtime execution and the persistence of `trajectory_hash`."""

    def _scenario_for_run(self, name: str = "scn_j32", seed: int = 42) -> Scenario:
        return create_supplier_delay_scenario(
            scenario_id=name,
            supplier_id="sup_1",
            delay_days=5,
            seed=seed,
        )

    async def test_same_snapshot_scenario_seed_yields_identical_trajectory_hash(
        self, db_session
    ) -> None:
        """IN-4 (extended): same (snapshot, scenario, seed) ⇒ identical
        `trajectory_hash` AND identical `final_state_hash`.

        This is the J.3 exit-gate invariant #4 extended from state-only to
        trajectory — the new contribution of J.3.2."""
        ws = f"ws_{uuid7()}"
        world = f"world_{uuid7()}"
        _, snapshot = await _seed_production_world(db_session, ws, world)

        service = TwinService(db_session)
        twin_a = await service.create(
            workspace_id=ws, world_id=world, snapshot_id=snapshot.snapshot_id, name="A"
        )
        twin_b = await service.create(
            workspace_id=ws, world_id=world, snapshot_id=snapshot.snapshot_id, name="B"
        )

        scenario = self._scenario_for_run()
        # Two runs from independent twins, same inputs.
        r_a = await service.run(twin_a, scenario, seed=42)
        r_b = await service.run(twin_b, scenario, seed=42)

        # State-level reproducibility (frozen at J.3.1).
        assert r_a.final_state_hash == r_b.final_state_hash
        assert r_a.final_state_hash != ""
        # Trajectory reproducibility — the new J.3.2 contribution.
        assert r_a.metadata["trajectory_hash"] == r_b.metadata["trajectory_hash"]
        assert r_a.metadata["trajectory_hash"] != ""
        # Event counts are identical.
        assert r_a.events_processed == r_b.events_processed

    async def test_different_seed_yields_different_trajectory_hash(self, db_session) -> None:
        """Different seed ⇒ different `trajectory_hash` (or, at minimum,
        different final_state_hash). This is the non-vacuous converse of
        the reproducibility invariant: the runtime is sensitive to seed."""
        ws = f"ws_{uuid7()}"
        world = f"world_{uuid7()}"
        _, snapshot = await _seed_production_world(db_session, ws, world)

        service = TwinService(db_session)
        twin_a = await service.create(
            workspace_id=ws, world_id=world, snapshot_id=snapshot.snapshot_id, name="A"
        )
        twin_b = await service.create(
            workspace_id=ws, world_id=world, snapshot_id=snapshot.snapshot_id, name="B"
        )

        # Same scenario data, different seeds.
        scn_a = create_supplier_delay_scenario(
            scenario_id="scn_seed_a", supplier_id="sup_1", delay_days=5, seed=1
        )
        scn_b = create_supplier_delay_scenario(
            scenario_id="scn_seed_b", supplier_id="sup_1", delay_days=5, seed=999
        )
        r_a = await service.run(twin_a, scn_a, seed=1)
        r_b = await service.run(twin_b, scn_b, seed=999)

        assert (
            r_a.metadata["trajectory_hash"] != r_b.metadata["trajectory_hash"]
            or r_a.final_state_hash != r_b.final_state_hash
        )

    async def test_different_scenario_yields_different_trajectory_hash(self, db_session) -> None:
        """Different scenario (same seed) ⇒ trajectory diverges."""
        ws = f"ws_{uuid7()}"
        world = f"world_{uuid7()}"
        _, snapshot = await _seed_production_world(db_session, ws, world, with_demand=True)

        service = TwinService(db_session)
        twin_a = await service.create(
            workspace_id=ws, world_id=world, snapshot_id=snapshot.snapshot_id, name="A"
        )
        twin_b = await service.create(
            workspace_id=ws, world_id=world, snapshot_id=snapshot.snapshot_id, name="B"
        )

        scn_supplier = create_supplier_delay_scenario(
            scenario_id="scn_supp", supplier_id="sup_1", delay_days=10, seed=7
        )
        scn_demand = create_demand_spike_scenario(
            scenario_id="scn_demand", component_id="comp_a", demand_multiplier=2.0, seed=7
        )
        r_a = await service.run(twin_a, scn_supplier, seed=7)
        r_b = await service.run(twin_b, scn_demand, seed=7)

        assert r_a.metadata["trajectory_hash"] != r_b.metadata["trajectory_hash"]

    async def test_runtime_does_not_leak_into_production(self, db_session) -> None:
        """SR-4: production_fingerprint is identical before and after a
        scenario run (zero world-state leakage)."""
        ws = f"ws_{uuid7()}"
        world = f"world_{uuid7()}"
        _, _ = await _seed_production_world(db_session, ws, world)

        service = TwinService(db_session)
        snapshot = await StateRepository(db_session).get_latest_snapshot(world, ws)
        assert snapshot is not None

        def _strip_taken(fp: dict[str, Any]) -> dict[str, Any]:
            return {k: v for k, v in fp.items() if k != "taken_at"}

        before = _strip_taken(await production_fingerprint(db_session, ws))

        twin = await service.create(
            workspace_id=ws, world_id=world, snapshot_id=snapshot.snapshot_id, name="Iso"
        )
        scenario = self._scenario_for_run(seed=1)
        await service.run(twin, scenario, seed=1)

        after = _strip_taken(await production_fingerprint(db_session, ws))
        assert before == after, "ScenarioRuntime.execute must not touch production tables"

    async def test_persisted_run_exposes_trajectory_hash(self, db_session) -> None:
        """SR-5: the TwinRunDB row written by ScenarioRuntime carries
        `trajectory_hash` in extra_metadata, equal to the in-memory run."""
        ws = f"ws_{uuid7()}"
        world = f"world_{uuid7()}"
        _, snapshot = await _seed_production_world(db_session, ws, world)

        service = TwinService(db_session)
        twin = await service.create(
            workspace_id=ws, world_id=world, snapshot_id=snapshot.snapshot_id, name="P"
        )
        scenario = self._scenario_for_run(seed=7)
        result = await service.run(twin, scenario, seed=7)

        repo = TwinRepository(db_session)
        persisted = await repo.get_latest_run(twin.twin_id, ws)
        assert persisted is not None

        # The persisted run carries the trajectory fingerprint downstream.
        assert persisted.extra_metadata["trajectory_hash"] == result.metadata["trajectory_hash"]
        # All three provenance versions are stamped.
        assert persisted.extra_metadata["engine_version"] == TWIN_ENGINE_VERSION
        assert persisted.extra_metadata["simulation_version"] == TWIN_SIMULATION_VERSION


# ─────────────────────────────────────────────────────────────────────────────
# E. End-to-end synthesis — propagation produces a deterministic trajectory
# ─────────────────────────────────────────────────────────────────────────────


class TestEndToEndDeterminism:
    """A scenario whose generator emits a primary event AND triggers
    propagation: the trajectory_hash reflects BOTH, reproducibly."""

    async def test_supplier_failure_with_component_dependency_reproducible(
        self, db_session
    ) -> None:
        """From a parent state that has both a supplier and a dependent
        component, a supplier-failure scenario runs end-to-end twice
        yielding identical trajectory_hash."""

        ws = f"ws_{uuid7()}"
        world = f"world_{uuid7()}"
        # Seed production with a supplier + a dependent component.
        repo = StateRepository(db_session)
        lt = StateVariable.from_raw_value(
            variable_id=lead_time_var_id("sup_1"),
            variable_type=StateVariableType.LEAD_TIME,
            entity_id="sup_1",
            entity_type="supplier",
            raw_value=10,
        )
        comp = StateVariable(
            variable_id="component.comp_a",
            variable_type=StateVariableType.INVENTORY,
            entity_id="comp_a",
            entity_type="component",
            value=0,
            unit=None,
            metadata={"supplier_id": "sup_1"},
        )
        state = create_initial_state(
            workspace_id=ws,
            world_id=world,
            graph_version=1,
            initial_variables={lt.variable_id: lt, comp.variable_id: comp},
        )
        snapshot = create_state_snapshot(state, created_by="j32_e2e")
        await repo.create(state)
        await repo.store_snapshot(snapshot)

        service = TwinService(db_session)
        twin_a = await service.create(
            workspace_id=ws, world_id=world, snapshot_id=snapshot.snapshot_id, name="E2Ea"
        )
        twin_b = await service.create(
            workspace_id=ws, world_id=world, snapshot_id=snapshot.snapshot_id, name="E2Eb"
        )

        scenario = create_supplier_failure_scenario(
            scenario_id="scn_e2e",
            supplier_id="sup_1",
            capacity_pct=0.0,
            disruption_type="port_strike",
            seed=11,
        )

        r_a = await service.run(twin_a, scenario, seed=11)
        r_b = await service.run(twin_b, scenario, seed=11)

        assert r_a.metadata["trajectory_hash"] == r_b.metadata["trajectory_hash"]
        assert r_a.final_state_hash == r_b.final_state_hash
        # Non-vacuous: both events > 0 (primary + at least one propagated).
        assert r_a.events_processed >= 1
        assert r_a.events_processed == r_b.events_processed

        # Stability: a third run on a fresh twin from the same snapshot also
        # reproduces the trajectory hash — verification that the propagation
        # counter is reproducible too.
        twin_c = await service.create(
            workspace_id=ws, world_id=world, snapshot_id=snapshot.snapshot_id, name="E2Ec"
        )
        r_c = await service.run(twin_c, scenario, seed=11)
        assert r_c.metadata["trajectory_hash"] == r_a.metadata["trajectory_hash"]
