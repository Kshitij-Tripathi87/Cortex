"""Twin Service — High-Level Operations for Digital Twins (J.3.1).

Program J (World State & Digital Twin) — J.3.1 Twin Lifecycle.

Public API:
- create() / clone(): create an isolated twin from a production snapshot
- fork(): branch an existing twin (carries the source twin's CURRENT state)
- run(): execute a scenario against a twin in isolated memory (deterministic)
- get() / get_twin(): retrieve a twin by ID (from the database)
- list_twins(): query twins for a workspace (from the database)
- archive(): soft lifecycle transition (twin remains queryable)
- destroy(): permanently remove the twin and its runs (twin namespace only)

J.3.1 invariants enforced here:
1. IMMUTABLE LINEAGE — parent_world_id, parent_version, snapshot_id,
   fork_of_twin_id, fork_from_run_id, created_at are frozen at creation and
   fingerprinted into `lineage_hash`. The repository exposes no update path
   for any of them; only `status` transitions are permitted.
2. PRODUCTION ISOLATION — this service READS production World State via
   StateRepository (the single authoritative read path) and WRITES only to
   the twin namespace (twins, twin_runs). It never appends to
   world_state_events, never stores world_versions, never stores
   world_snapshots, and never mutates production entities.
3. FORK INDEPENDENCE — each twin (and fork) evolves from its own starting
   state; two twins from the same snapshot can diverge independently.

Determinism (foundation for J.3.3): given the same (snapshot, scenario,
seed), the run produces the same final_state_hash. Event timestamps are a
pure function of (snapshot.created_at, seed, event_index) — never wall clock.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.ids import uuid7
from app.modules.twin.kpi_engine import KPIComputation, KPIEngine
from app.modules.twin.scenario_runtime import ScenarioRuntime
from app.modules.twin.twin_isolation import IsolationError, TwinIsolationEnforcer
from app.modules.twin.twin_models import (
    TWIN_ENGINE_VERSION,
    TWIN_RNG_VERSION,
    TWIN_SIMULATION_VERSION,
    DigitalTwin,
    Scenario,
    ScenarioType,
    TwinResult,
    TwinScenario,
    TwinStatus,
    compute_twin_lineage_hash,
    create_currency_shock_scenario,
    create_cyber_attack_scenario,
    create_demand_spike_twin_scenario,
    create_factory_fire_scenario,
    create_labor_strike_scenario,
    create_pandemic_scenario,
    create_port_closure_scenario,
    create_pricing_shock_scenario,
    create_supplier_failure_twin_scenario,
    create_weather_scenario,
)
from app.modules.twin.twin_repository import TwinRepository, TwinRunDB
from app.modules.world.state_repository import StateRepository
from app.modules.world.world_models import (
    StateVariable,
    StateVariableType,
    WorldSnapshot,
    WorldState,
)

# ─────────────────────────────────────────────────────────────────────────────
# Deterministic Twin Clock
# ─────────────────────────────────────────────────────────────────────────────

# Step between successive scenario events. Fixed so that the same
# (scenario, seed) always produces the same occurred_at sequence.
TWIN_EVENT_STEP = timedelta(hours=1)


def _as_utc(dt: datetime) -> datetime:
    """Normalize a stored timestamp to an aware-UTC datetime.

    SQLite round-trips naive datetimes; everything else (J.2.3 convention) is
    aware-UTC. Projections compare occurred_at against provenance timestamps,
    so mixing naive/aware raises TypeError.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def deterministic_event_time(snapshot: WorldSnapshot, seed: int, index: int) -> datetime:
    """Pure-function clock for twin scenario events.

    occurred_at(i) = snapshot.created_at(UTC) + seed days + i hours

    A pure function of (snapshot, seed, index) — no wall clock — so the same
    (snapshot, scenario, seed) always yields the same event timestamps and
    therefore the same projected state.
    """
    return _as_utc(snapshot.created_at) + timedelta(days=seed) + TWIN_EVENT_STEP * index


# ─────────────────────────────────────────────────────────────────────────────
# Twin Service
# ─────────────────────────────────────────────────────────────────────────────


class TwinService:
    """Service for managing digital twin lifecycle and isolated scenario execution."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = TwinRepository(db)
        self.world_repo = StateRepository(db)
        self.enforcer = TwinIsolationEnforcer(db)

    @asynccontextmanager
    async def _transaction(self) -> AsyncGenerator[None]:
        """Transaction boundary for write operations (mirrors WorldStateService)."""
        if self.db.in_transaction():
            async with self.db.begin_nested():
                yield
        else:
            async with self.db.begin():
                yield

    # ─────────────────────────────────────────────────────────────────────────
    # Twin Lifecycle: create / clone
    # ─────────────────────────────────────────────────────────────────────────

    async def create(
        self,
        workspace_id: str,
        world_id: str,
        snapshot_id: str,
        name: str,
        description: str = "",
        created_by: str | None = None,
        tags: list[str] | None = None,
        organization_id: str | None = None,
    ) -> DigitalTwin:
        """Create an isolated digital twin from a production world snapshot.

        Lineage (organization_id, parent_world_id, parent_version, snapshot_id, created_at) is
        validated against production, fingerprinted, and IMMUTABLE thereafter.
        """
        snapshot = await self._validated_snapshot(workspace_id, world_id, snapshot_id)
        await self._validated_parent_state(workspace_id, world_id, snapshot)

        created_at = datetime.now(UTC)
        twin = DigitalTwin(
            twin_id=str(uuid7()),
            organization_id=organization_id or workspace_id,
            workspace_id=workspace_id,
            parent_world_id=world_id,
            parent_version=snapshot.version,
            snapshot_id=snapshot_id,
            name=name,
            status=TwinStatus.READY,
            description=description,
            tags=list(tags or []),
            created_at=created_at,
            created_by=created_by,
            metadata={
                "state_source": "snapshot",
                "source_state_hash": snapshot.state_hash,
            },
        )
        twin = replace(twin, lineage_hash=compute_twin_lineage_hash(twin))

        async with self._transaction():
            await self.repo.create_twin(twin)
        return twin

    # `clone` is the J.3.1 canonical name; `create` is an alias kept so both
    # lifecycle verbs in the spec map to the same operation.
    clone = create

    async def _validated_snapshot(
        self, workspace_id: str, world_id: str, snapshot_id: str
    ) -> WorldSnapshot:
        """Load and validate the production snapshot a twin will clone from."""
        snapshot = await self.world_repo.get_snapshot(snapshot_id, workspace_id)
        if not snapshot:
            raise IsolationError(f"Snapshot {snapshot_id} not found in workspace {workspace_id}")
        if snapshot.world_id != world_id:
            raise IsolationError(
                f"Snapshot {snapshot_id} belongs to world {snapshot.world_id}, not {world_id}"
            )
        return snapshot

    async def _validated_parent_state(
        self, workspace_id: str, world_id: str, snapshot: WorldSnapshot
    ) -> WorldState:
        """Load the production state at the snapshot version and verify its hash.

        A twin may only be seeded from a production state that is provably the
        one the snapshot certified. This is the J.3 boundary: the twin
        CONSUMES World State — it does not recreate or bypass it.
        """
        state = await self.world_repo.get(world_id, workspace_id, snapshot.version)
        if not state:
            raise IsolationError(
                f"Parent world state version {snapshot.version} not found for world {world_id}"
            )
        state_hash = state.metadata.get("state_hash", "")
        if snapshot.state_hash and state_hash and state_hash != snapshot.state_hash:
            raise IsolationError(
                f"Snapshot {snapshot.snapshot_id} state hash does not match the "
                f"materialized state at version {snapshot.version}; refusing to clone"
            )
        return state

    # ─────────────────────────────────────────────────────────────────────────
    # Twin Lifecycle: fork
    # ─────────────────────────────────────────────────────────────────────────

    async def fork(
        self,
        source_twin_id: str,
        fork_name: str,
        description: str = "",
        created_by: str | None = None,
        workspace_id: str | None = None,
    ) -> DigitalTwin:
        """Fork an existing twin into a new independent branch.

        The fork inherits the source twin's production lineage
        (parent_world_id / parent_version / snapshot_id) plus counterfactual
        provenance (fork_of_twin_id / fork_from_run_id). Its starting state is
        the source twin's CURRENT state — the final state of its latest run,
        or the parent snapshot state if the source has never run.

        Fork lineage is immutable once created, exactly like clone lineage.
        """
        source = await self.repo.get_twin(source_twin_id, workspace_id)
        if source is None:
            raise IsolationError(f"Source twin {source_twin_id} not found")

        source_status = (
            TwinStatus(source.status) if isinstance(source.status, str) else source.status
        )
        if source_status not in (TwinStatus.READY, TwinStatus.COMPLETED, TwinStatus.FAILED):
            raise IsolationError(
                f"Cannot fork twin in status: {source.status!r} (must be ready, completed, or failed)"
            )

        ws = source.workspace_id

        # Resolve the source twin's CURRENT state (its own namespace).
        latest_run = await self.repo.get_latest_run(source_twin_id, ws)
        fork_from_run_id: str | None = None
        if latest_run is not None:
            state_source = f"run:{latest_run.run_id}"
            fork_from_run_id = latest_run.run_id
            snapshot = await self._validated_snapshot(
                ws, source.parent_world_id, source.snapshot_id
            )
            inherited_state = self._state_from_run(source, snapshot, latest_run)
        else:
            state_source = "snapshot"
            snapshot = await self._validated_snapshot(
                ws, source.parent_world_id, source.snapshot_id
            )
            inherited_state = await self._validated_parent_state(
                ws, source.parent_world_id, snapshot
            )

        # Stamp the canonical hash of the inherited state (deterministic).
        from app.modules.world.state_projection import compute_state_hash

        inherited_hash = inherited_state.metadata.get("state_hash") or compute_state_hash(
            inherited_state
        )

        created_at = datetime.now(UTC)
        fork = DigitalTwin(
            twin_id=str(uuid7()),
            organization_id=source.organization_id,
            workspace_id=ws,
            parent_world_id=source.parent_world_id,
            parent_version=source.parent_version,
            snapshot_id=source.snapshot_id,
            name=fork_name,
            status=TwinStatus.READY,
            description=description,
            tags=list(source.tags) + ["fork"],
            fork_of_twin_id=source_twin_id,
            fork_from_run_id=fork_from_run_id,
            created_at=created_at,
            created_by=created_by,
            metadata={
                "state_source": state_source,
                "source_state_hash": inherited_hash,
            },
        )
        fork = replace(fork, lineage_hash=compute_twin_lineage_hash(fork))

        # Materialize the inherited state as the fork's FIRST (seed) run, so the
        # fork's own current-state resolution (get_latest_run) returns it. This
        # keeps the fork's state fully in the twin namespace and replayable.
        finished_at = datetime.now(UTC)
        seed_run = TwinRunDB.from_values(
            twin_id=fork.twin_id,
            workspace_id=ws,
            scenario=TwinScenario(
                scenario_id=f"fork_seed:{source_twin_id}",
                name="Fork seed (inherited state)",
                scenario_type=ScenarioType.CUSTOM,
                events=[],
            ),
            seed=0,
            injected_events=[],
            final_variables={vid: v.to_dict() for vid, v in inherited_state.variables.items()},
            final_state_hash=inherited_hash,
            final_version=inherited_state.version,
            metrics=self._compute_metrics(inherited_state),
            comparison=None,
            created_at=created_at,
            finished_at=finished_at,
        )
        seed_run.extra_metadata = {
            "fork_seed": True,
            "source_twin_id": source_twin_id,
            "source_run_id": fork_from_run_id,
        }

        async with self._transaction():
            await self.repo.create_twin(fork)
            await self.repo.append_run(seed_run)
        return fork

    # ─────────────────────────────────────────────────────────────────────────
    # Twin Lifecycle: run (deterministic scenario execution)
    # ─────────────────────────────────────────────────────────────────────────

    async def run(
        self,
        twin: DigitalTwin | str,
        scenario: TwinScenario | Scenario,
        seed: int = 0,
        inject_events: list[dict[str, Any]] | None = None,
    ) -> TwinResult:
        """Execute a scenario against a twin in an isolated sandbox.

        Deterministic: the same (twin starting state, scenario, seed) always
        produces the same final_state_hash — event IDs and timestamps are
        pure functions of the inputs, never wall clock or randomness.

        Isolation: all projection happens on in-memory WorldState clones; the
        only writes are to the twin namespace. Zero writes to production world_* tables.

        Uses J.3.2 ScenarioRuntime for deterministic execution with full provenance.
        """
        twin = await self._resolve_twin(twin)

        status = TwinStatus(twin.status) if isinstance(twin.status, str) else twin.status
        if status not in (TwinStatus.READY, TwinStatus.COMPLETED, TwinStatus.FAILED):
            raise IsolationError(f"Cannot run scenario on twin in status: {twin.status!r}")

        # Convert legacy TwinScenario to new Scenario format if needed
        if isinstance(scenario, TwinScenario):
            js2_scenario = self._convert_legacy_scenario(scenario, seed)
        else:
            js2_scenario = scenario

        # Inject pre-events if provided
        if inject_events:
            js2_scenario = replace(
                js2_scenario,
                parameters={**js2_scenario.parameters, "inject_events": inject_events},
            )

        # Execute via J.3.2 ScenarioRuntime
        runtime = ScenarioRuntime(self.db)
        scenario_run = await runtime.execute(twin, js2_scenario)

        # Transition twin status
        ws = twin.workspace_id
        async with self._transaction():
            await self.repo.transition_status(twin.twin_id, ws, TwinStatus.RUNNING)
            await self.repo.transition_status(twin.twin_id, ws, TwinStatus.COMPLETED)

        # Get final state for result
        final_state = await self.get_current_state(twin)

        # Compute metrics and comparison (J.3.3 — KPIEngine, time-series aware)
        baseline_snapshot = await self.world_repo.get_snapshot(twin.snapshot_id, ws)
        if baseline_snapshot is None:
            raise IsolationError(f"Snapshot {twin.snapshot_id} not found for baseline state")
        base_state = await self._validated_parent_state(
            ws, twin.parent_world_id, baseline_snapshot
        )
        kpi = self._compute_kpi(
            base_state,
            final_state,
            trajectory_snapshots=scenario_run.trajectory_snapshots,
            trajectory_hash=scenario_run.trajectory_hash,
        )
        metrics = kpi.to_dict()
        comparison = self._compute_comparison(base_state, final_state)

        # ScenarioRuntime already persisted the run; use its run_id and data
        run_id = scenario_run.run_id
        created_at = scenario_run.started_at
        finished_at = scenario_run.completed_at or scenario_run.started_at

        return TwinResult(
            run_id=run_id,
            twin_id=twin.twin_id,
            scenario_id=js2_scenario.scenario_id,
            final_state_hash=scenario_run.final_state_hash,
            final_version=final_state.version,
            events_processed=scenario_run.event_count,
            metrics=metrics,
            timeline=self._build_timeline(final_state),
            comparison=comparison,
            created_at=created_at,
            metadata={
                "seed": seed,
                "duration_ms": (finished_at - created_at).total_seconds() * 1000,
                "rng_version": TWIN_RNG_VERSION,
                "engine_version": TWIN_ENGINE_VERSION,
                "simulation_version": TWIN_SIMULATION_VERSION,
                "trajectory_hash": scenario_run.trajectory_hash,
                "trajectory_ref_hash": scenario_run.trajectory_hash,
                # J.3.3 KPI provenance — links this result's metric block to
                # the deterministic KPI computation that produced it.
                "kpi_hash": kpi.kpi_hash,
                "kpi_formula_version": kpi.formula_version,
                "kpi_canonical_engine_version": kpi.canonical_engine_version,
            },
        )

    def _convert_legacy_scenario(self, legacy: TwinScenario, seed: int) -> Scenario:
        """Convert legacy TwinScenario to J.3.2 Scenario format."""
        # Extract target entities and parameters from events
        target_entities: dict[str, list[str]] = {}
        parameters = dict(legacy.parameters)

        for event in legacy.events:
            etype = event.get("entity_type")
            eid = event.get("entity_id")
            if etype and eid:
                target_entities.setdefault(etype, []).append(eid)

            # Extract payload as parameters
            payload = event.get("payload", {})
            for k, v in payload.items():
                if k not in parameters:  # Don't override explicit parameters
                    parameters[k] = v

        # Preserve original events for CUSTOM scenario execution
        metadata = {}
        if legacy.scenario_type == ScenarioType.CUSTOM and legacy.events:
            metadata["custom_events"] = legacy.events

        return Scenario(
            scenario_id=legacy.scenario_id,
            scenario_type=legacy.scenario_type,
            target_entities=target_entities,
            parameters=parameters,
            seed=seed,
            engine_version=TWIN_ENGINE_VERSION,
            simulation_version=TWIN_SIMULATION_VERSION,
            metadata=metadata,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Twin State Access (twin namespace)
    # ─────────────────────────────────────────────────────────────────────────

    async def get_current_state(self, twin: DigitalTwin | str) -> WorldState:
        """Return the twin's CURRENT state (latest run, or snapshot state if never run).

        This is the twin's own mutable domain state: it exists in the twin
        namespace and never in production world_* tables.
        """
        twin = await self._resolve_twin(twin)

        ws = twin.workspace_id
        snapshot = await self.world_repo.get_snapshot(twin.snapshot_id, ws)
        if not snapshot:
            raise IsolationError(f"Snapshot {twin.snapshot_id} not found")

        latest_run = await self.repo.get_latest_run(twin.twin_id, ws)
        if latest_run is not None:
            return self._state_from_run(twin, snapshot, latest_run)
        return await self._validated_parent_state(ws, twin.parent_world_id, snapshot)

    def _state_from_run(
        self, twin: DigitalTwin, snapshot: WorldSnapshot, run: TwinRunDB
    ) -> WorldState:
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

    # ─────────────────────────────────────────────────────────────────────────
    # Queries
    # ─────────────────────────────────────────────────────────────────────────

    async def get_twin(self, twin_id: str, workspace_id: str | None = None) -> DigitalTwin | None:
        """Get a twin by ID (from the database, workspace-isolated)."""
        return await self.repo.get_twin(twin_id, workspace_id)

    # Alias for the J.3.1 spec verb.
    get = get_twin

    async def list_twins(
        self,
        workspace_id: str,
        status: TwinStatus | str | None = None,
        include_archived: bool = True,
    ) -> list[DigitalTwin]:
        """List all twins in a workspace (from the database)."""
        return await self.repo.list_twins(
            workspace_id, status=status, include_archived=include_archived
        )

    async def get_results(self, twin_id: str) -> list[TwinResult]:
        """Get all run results for a twin (from the database, oldest first)."""
        workspace_id = await self._workspace_for(twin_id)
        runs = await self.repo.get_runs(twin_id, workspace_id)
        return [self._run_to_result(run) for run in runs]

    async def _workspace_for(self, twin_id: str) -> str:
        """Resolve a twin's workspace from any cached row, or an empty scope.

        get_results is called without a workspace (historical API); the run
        rows are themselves scoped by workspace, so we look up the twin first.
        """
        twin = await self.repo.get_twin(twin_id)
        return twin.workspace_id if twin else ""

    def _run_to_result(self, run: TwinRunDB) -> TwinResult:
        return TwinResult(
            run_id=run.run_id,
            twin_id=run.twin_id,
            scenario_id=run.scenario_id,
            final_state_hash=run.final_state_hash,
            final_version=run.final_version,
            events_processed=len(run.injected_events or []),
            metrics=dict(run.metrics or {}),
            timeline=[],
            comparison=dict(run.comparison) if run.comparison else None,
            created_at=run.created_at,
            metadata={"seed": run.seed},
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Twin Lifecycle: archive / destroy (with strict state machine)
    # ─────────────────────────────────────────────────────────────────────────

    # Allowed status transitions (from -> list of allowed next states)
    _ALLOWED_TRANSITIONS: dict[TwinStatus, list[TwinStatus]] = {
        TwinStatus.CREATED: [TwinStatus.READY],
        TwinStatus.READY: [
            TwinStatus.RUNNING,
            TwinStatus.COMPLETED,
            TwinStatus.FAILED,
            TwinStatus.ARCHIVED,
        ],
        TwinStatus.RUNNING: [TwinStatus.COMPLETED, TwinStatus.FAILED],
        TwinStatus.COMPLETED: [TwinStatus.ARCHIVED],
        TwinStatus.FAILED: [TwinStatus.ARCHIVED],
        TwinStatus.ARCHIVED: [],  # Terminal - no further transitions allowed
        TwinStatus.DESTROYED: [],  # Terminal - no further transitions allowed
    }

    def _validate_transition(self, current: TwinStatus, target: TwinStatus) -> None:
        """Validate that a status transition is allowed.

        Raises IsolationError if the transition is not permitted.
        """
        allowed = self._ALLOWED_TRANSITIONS.get(current, [])
        if target not in allowed:
            raise IsolationError(
                f"Invalid twin status transition: {current.value} -> {target.value}. "
                f"Allowed: {[s.value for s in allowed]}"
            )

    async def _transition_status(
        self, twin_id: str, workspace_id: str, new_status: TwinStatus
    ) -> DigitalTwin:
        """Transition twin status with strict validation."""
        twin = await self.repo.get_twin(twin_id, workspace_id)
        if twin is None:
            raise IsolationError(f"Twin {twin_id} not found")
        current = TwinStatus(twin.status) if isinstance(twin.status, str) else twin.status
        self._validate_transition(current, new_status)

        async with self._transaction():
            await self.repo.transition_status(twin_id, workspace_id, new_status)
        updated = await self.repo.get_twin(twin_id, workspace_id)
        if updated is None:
            raise IsolationError(f"Twin {twin_id} disappeared during status transition")
        return updated

    async def archive(self, twin_id: str | DigitalTwin) -> DigitalTwin:
        """Archive a twin (soft lifecycle transition; remains queryable)."""
        twin: DigitalTwin | None
        if isinstance(twin_id, DigitalTwin):
            twin = twin_id
            target_id = twin.twin_id
        else:
            target_id = twin_id
            twin = await self.repo.get_twin(target_id)
        if twin is None:
            raise IsolationError(f"Twin {target_id} not found")

        return await self._transition_status(target_id, twin.workspace_id, TwinStatus.ARCHIVED)

    async def destroy(self, twin_id: str | DigitalTwin) -> bool:
        """Permanently destroy a twin and all its execution artifacts.

        Twin namespace only — production World State is never touched.
        Sets status to DESTROYED before deletion.
        """
        if isinstance(twin_id, DigitalTwin):
            target_id = twin_id.twin_id
            ws = twin_id.workspace_id
        else:
            target_id = twin_id
            twin = await self.repo.get_twin(target_id)
            if twin is None:
                return False
            ws = twin.workspace_id

        # Transition to DESTROYED first (strict state machine)
        with suppress(IsolationError):
            await self._transition_status(target_id, ws, TwinStatus.DESTROYED)

        async with self._transaction():
            return await self.repo.delete_twin(target_id, ws)

    # ─────────────────────────────────────────────────────────────────────────
    # Lineage Verification
    # ─────────────────────────────────────────────────────────────────────────

    async def verify_lineage(self, twin_id: str, workspace_id: str | None = None) -> dict[str, Any]:
        """Verify a twin's immutable lineage has not been tampered with.

        Re-reads the twin from the database and recomputes the lineage
        fingerprint. Returns a report:

            {"twin_id", "lineage_intact", "stored_hash", "computed_hash"}
        """
        from app.modules.twin.twin_models import lineage_intact

        twin = await self.repo.get_twin(twin_id, workspace_id)
        if twin is None:
            return {
                "twin_id": twin_id,
                "lineage_intact": False,
                "stored_hash": None,
                "computed_hash": None,
                "reason": "twin not found",
            }
        computed = compute_twin_lineage_hash(twin)
        return {
            "twin_id": twin_id,
            "lineage_intact": lineage_intact(twin),
            "stored_hash": twin.lineage_hash,
            "computed_hash": computed,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Scenario Factory Helpers (unchanged public surface)
    # ─────────────────────────────────────────────────────────────────────────

    def create_supplier_failure_scenario(
        self,
        supplier_id: str,
        delay_days: int,
        disruption_type: str = "factory_fire",
    ) -> TwinScenario:
        return create_supplier_failure_twin_scenario(
            scenario_id=str(uuid7()),
            supplier_id=supplier_id,
            delay_days=delay_days,
            disruption_type=disruption_type,
        )

    def create_demand_spike_scenario(
        self,
        component_id: str,
        demand_change: int,
        confidence: float = 0.8,
    ) -> TwinScenario:
        return create_demand_spike_twin_scenario(
            scenario_id=str(uuid7()),
            component_id=component_id,
            demand_change=demand_change,
            confidence=confidence,
        )

    def create_port_closure_scenario(
        self,
        route_id: str,
        delay_days: int,
    ) -> TwinScenario:
        return create_port_closure_scenario(
            scenario_id=str(uuid7()),
            route_id=route_id,
            delay_days=delay_days,
        )

    def create_factory_fire_scenario(
        self,
        factory_id: str,
        capacity_pct: float = 0.0,
        estimated_recovery_days: int = 30,
    ) -> TwinScenario:
        return create_factory_fire_scenario(
            scenario_id=str(uuid7()),
            factory_id=factory_id,
            capacity_pct=capacity_pct,
            estimated_recovery_days=estimated_recovery_days,
        )

    def create_labor_strike_scenario(
        self,
        factory_id: str,
        capacity_pct: float = 50.0,
        estimated_recovery_days: int = 14,
    ) -> TwinScenario:
        return create_labor_strike_scenario(
            scenario_id=str(uuid7()),
            factory_id=factory_id,
            capacity_pct=capacity_pct,
            estimated_recovery_days=estimated_recovery_days,
        )

    def create_cyber_attack_scenario(
        self,
        factory_id: str,
        capacity_pct: float = 0.0,
        estimated_recovery_days: int = 21,
    ) -> TwinScenario:
        return create_cyber_attack_scenario(
            scenario_id=str(uuid7()),
            factory_id=factory_id,
            capacity_pct=capacity_pct,
            estimated_recovery_days=estimated_recovery_days,
        )

    def create_weather_scenario(
        self,
        affected_routes: list[str],
        delay_days: int,
    ) -> TwinScenario:
        return create_weather_scenario(
            scenario_id=str(uuid7()),
            affected_routes=affected_routes,
            delay_days=delay_days,
        )

    def create_pricing_shock_scenario(
        self,
        component_id: str,
        price_multiplier: float,
    ) -> TwinScenario:
        return create_pricing_shock_scenario(
            scenario_id=str(uuid7()),
            component_id=component_id,
            price_multiplier=price_multiplier,
        )

    def create_currency_shock_scenario(
        self,
        affected_components: list[str],
        exchange_rate_change: float,
    ) -> TwinScenario:
        return create_currency_shock_scenario(
            scenario_id=str(uuid7()),
            affected_components=affected_components,
            exchange_rate_change=exchange_rate_change,
        )

    def create_pandemic_scenario(
        self,
        affected_factories: list[str],
        capacity_reduction_pct: float = 30.0,
        duration_days: int = 90,
    ) -> TwinScenario:
        return create_pandemic_scenario(
            scenario_id=str(uuid7()),
            affected_factories=affected_factories,
            capacity_reduction_pct=capacity_reduction_pct,
            duration_days=duration_days,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Internal Helpers
    # ─────────────────────────────────────────────────────────────────────────

    async def _resolve_twin(self, twin: DigitalTwin | str) -> DigitalTwin:
        """Resolve a twin identifier (id or object) to a persisted DigitalTwin."""
        if isinstance(twin, DigitalTwin):
            return twin
        resolved = await self.repo.get_twin(twin)
        if resolved is None:
            raise IsolationError(f"Twin {twin} not found")
        return resolved

    def _compute_kpi(
        self,
        baseline_state: WorldState,
        final_state: WorldState,
        *,
        trajectory_snapshots: list[dict[str, Any]] | None = None,
        trajectory_hash: str = "",
    ) -> KPIComputation:
        """J.3.3 KPI / Trajectory Engine entry point.

        Returns a deterministic ``KPIComputation`` — the frozen 16-field
        contract surface for downstream consumers (J.3.4 counterfactual
        comparison, J.4 evaluation bridge). The resulting ``kpi_hash``
        is reproducible across runs of identical ``(baseline, final,
        trajectory)``.
        """
        engine = KPIEngine()
        return engine.compute(
            baseline_state,
            final_state,
            trajectory_snapshots=trajectory_snapshots,
            trajectory_hash=trajectory_hash,
        )

    def _compute_metrics(self, state: WorldState) -> dict[str, float]:
        """Flat legacy metric dict used by J.3.1 ``fork()``'s seed run record.

        The fork's seed run has no scenario and no trajectory — it is just
        the inherited starting state. J.3.3 doesn't apply (there is no
        baseline-vs-final diff). We compute the simple flat keys from a
        single state, mirroring the pre-J.3.3 implementation, so the seed
        ``TwinRunDB.metrics`` field stays consistent with the fork's
        ``DigitalTwin.metadata["source_state_hash"]``.
        """
        metrics: dict[str, float] = {
            "total_inventory": self._sum_state_quantity(state, StateVariableType.INVENTORY),
            "total_demand": self._sum_state_quantity(state, StateVariableType.DEMAND),
        }
        metrics["avg_capacity"] = self._avg_state_quantity(state, StateVariableType.CAPACITY, 100.0)
        metrics["avg_supplier_health"] = self._avg_state_quantity(state, "supplier_health", 1.0)
        metrics["avg_lead_time"] = self._avg_state_quantity(state, StateVariableType.LEAD_TIME, 0.0)
        return metrics

    @staticmethod
    def _sum_state_quantity(state: WorldState, vtype: Any) -> float:
        """Sum of positive raw_values for a given variable type."""
        total = 0.0
        for var in state.variables.values():
            if (var.variable_type == vtype or var.variable_type.value == vtype) and isinstance(
                var.raw_value, (int, float)
            ):
                total += max(0.0, float(var.raw_value))
        return total

    @staticmethod
    def _avg_state_quantity(state: WorldState, vtype: Any, default: float) -> float:
        values: list[float] = []
        for var in state.variables.values():
            if (var.variable_type == vtype or var.variable_type.value == vtype) and isinstance(
                var.raw_value, (int, float)
            ):
                values.append(float(var.raw_value))
        return sum(values) / len(values) if values else default

    def _compute_comparison(
        self, baseline_state: WorldState, final_state: WorldState
    ) -> dict[str, Any]:
        """Compare a twin's final state against the production baseline state."""
        from app.modules.world.state_diff import DiffEngine

        diff = DiffEngine().diff(baseline_state, final_state)
        return {
            "variables_added": len(diff.added_variables),
            "variables_removed": len(diff.removed_variables),
            "variables_changed": len(diff.variable_diffs),
            "total_delta": diff.summary.total_variables_after - diff.summary.total_variables_before,
        }

    def _build_timeline(self, state: WorldState) -> list[dict[str, Any]]:
        """Build a minimal timeline entry for the final state."""
        return [
            {
                "version": state.version,
                "description": "Final state after scenario execution",
                "variable_count": len(state.variables),
            }
        ]
