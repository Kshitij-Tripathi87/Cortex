"""Digital Twin Models — Immutable Contracts for Digital Twins.

Program J (World State & Digital Twin) twin layer:

A Digital Twin is an isolated, cloned instance of a world state
that can be modified, simulated, and discarded without affecting
the production world.

Key concepts:
- DigitalTwin: The twin itself — holds a world state snapshot
- TwinScenario: A named scenario (e.g., "supplier_failure", "demand_spike")
- TwinRun: An execution of a scenario against a twin
- TwinResult: The outcome of a twin run (final state, metrics, timeline)

All models are immutable (frozen dataclasses) with:
✓ Versioning
✓ Serializability
✓ Hashability (for verification)
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class TwinStatus(StrEnum):
    """Lifecycle status of a digital twin."""

    CREATED = "created"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ARCHIVED = "archived"
    DESTROYED = "destroyed"


# ─────────────────────────────────────────────────────────────────────────────
# Run Provenance Constants (for determinism verification)
# ─────────────────────────────────────────────────────────────────────────────

# These must be updated together when the simulation engine or RNG changes.
# They become part of the run provenance so that `run(S, X, seed, V)` is
# reproducible across deployments.
TWIN_ENGINE_VERSION = "1.0.0"
TWIN_RNG_VERSION = "1.0.0"  # Deterministic clock version
TWIN_SIMULATION_VERSION = "1.0.0"  # Scenario execution semantics version


class TwinRunStatus(StrEnum):
    """Status of a twin run execution."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ScenarioType(StrEnum):
    """Predefined scenario types for common disruptions."""

    SUPPLIER_FAILURE = "supplier_failure"
    SUPPLIER_DELAY = "supplier_delay"
    INVENTORY_SHORTAGE = "inventory_shortage"
    DEMAND_SPIKE = "demand_spike"
    ROUTE_DISRUPTION = "route_disruption"
    CAPACITY_REDUCTION = "capacity_reduction"
    PORT_CLOSURE = "port_closure"
    FACTORY_FIRE = "factory_fire"
    LABOR_STRIKE = "labor_strike"
    CYBER_ATTACK = "cyber_attack"
    PANDEMIC = "pandemic"
    WEATHER = "weather"
    PRICING_SHOCK = "pricing_shock"
    CURRENCY_SHOCK = "currency_shock"
    CUSTOM = "custom"


# ─────────────────────────────────────────────────────────────────────────────
# Twin Scenario
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TwinScenario:
    """A named scenario defining a sequence of injected events.

    Scenarios can be:
    - Predefined (ScenarioType enum)
    - Custom (arbitrary event sequence)
    - Parameterized (template with variables)
    """

    scenario_id: str
    name: str
    description: str = ""
    scenario_type: ScenarioType = ScenarioType.CUSTOM
    events: list[dict[str, Any]] = field(default_factory=list)  # Event payloads to inject
    parameters: dict[str, Any] = field(default_factory=dict)  # For templated scenarios
    tags: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Coerce plain strings (e.g., from pydantic request models) to the enum,
        # mirroring the status coercion on DigitalTwin and TwinRun.
        if isinstance(self.scenario_type, str):
            object.__setattr__(self, "scenario_type", ScenarioType(self.scenario_type))

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "name": self.name,
            "description": self.description,
            "scenario_type": self.scenario_type.value,
            "events": self.events,
            "parameters": self.parameters,
            "tags": list(self.tags),
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "metadata": dict(self.metadata),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Digital Twin
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DigitalTwin:
    """A digital twin — isolated clone of a world state.

    A twin contains:
    - A snapshot of the world state at creation time
    - Its own event log (separate from production)
    - Metadata linking back to the source world
    - Isolation guarantees (organization, workspace, memory, snapshot)

    Twins are:
    - Immutable (state changes create new twin versions)
    - Traceable (parent_world_id, parent_version tracked)
    - Disposable (can be archived/destroyed safely)
    """

    twin_id: str
    organization_id: str
    workspace_id: str
    parent_world_id: str  # The production world this twin was cloned from
    parent_version: int  # Version of the parent world at clone time
    snapshot_id: str  # The snapshot used as the starting state
    name: str
    # Fork provenance (immutable). None for twins cloned directly from production.
    fork_of_twin_id: str | None = None
    fork_from_run_id: str | None = None
    status: TwinStatus = TwinStatus.CREATED
    description: str = ""
    tags: list[str] = field(default_factory=list)
    # Immutable fingerprint of the lineage above, computed at creation.
    lineage_hash: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.status, str):
            object.__setattr__(self, "status", TwinStatus(self.status))

    def to_dict(self) -> dict[str, Any]:
        return {
            "twin_id": self.twin_id,
            "organization_id": self.organization_id,
            "workspace_id": self.workspace_id,
            "parent_world_id": self.parent_world_id,
            "parent_version": self.parent_version,
            "snapshot_id": self.snapshot_id,
            "fork_of_twin_id": self.fork_of_twin_id,
            "fork_from_run_id": self.fork_from_run_id,
            "name": self.name,
            "status": self.status.value,
            "description": self.description,
            "tags": list(self.tags),
            "lineage_hash": self.lineage_hash,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "metadata": dict(self.metadata),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Immutable Lineage
# ─────────────────────────────────────────────────────────────────────────────


def _utc_iso(dt: datetime) -> str:
    """Canonical UTC ISO rendering, robust to naive datetimes.

    SQLite round-trips store/return naive datetimes; PostgreSQL stores real
    timestamptz. The lineage fingerprint must be identical either way, so the
    canonical form normalizes naive values to UTC before rendering.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC).isoformat()
    return dt.astimezone(UTC).isoformat()


def compute_twin_lineage_hash(twin: DigitalTwin) -> str:
    """Canonical SHA-256 fingerprint of a twin's immutable lineage.

    The lineage is the full provenance chain of where this twin came from:

        parent_world_id + parent_version + snapshot_id   (production provenance)
        fork_of_twin_id + fork_from_run_id               (counterfactual provenance)
        twin_id + organization_id + workspace_id + created_at  (identity)

    ``status`` is deliberately excluded: it is the only mutable twin column
    (lifecycle), and mutating it must not change the lineage fingerprint.

    Determinism: the hash is computed from RAW FIELDS ONLY (canonical JSON,
    sorted keys, compact separators), mirroring ``compute_state_hash`` in the
    World State Engine. Recomputing it after a read and comparing against the
    stored ``lineage_hash`` detects tampering with any lineage field.
    """
    lineage = {
        "twin_id": twin.twin_id,
        "organization_id": twin.organization_id,
        "workspace_id": twin.workspace_id,
        "parent_world_id": twin.parent_world_id,
        "parent_version": twin.parent_version,
        "snapshot_id": twin.snapshot_id,
        "fork_of_twin_id": twin.fork_of_twin_id,
        "fork_from_run_id": twin.fork_from_run_id,
        "created_at": _utc_iso(twin.created_at),
    }
    canonical = json.dumps(lineage, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def lineage_intact(twin: DigitalTwin) -> bool:
    """Verify a twin's stored lineage fingerprint still matches its fields.

    Returns True if the recomputed lineage hash equals the ``lineage_hash``
    stored on the twin. Used to prove the lineage-immutability invariant after
    a twin has been persisted and re-read from the database.
    """
    return bool(twin.lineage_hash) and compute_twin_lineage_hash(twin) == twin.lineage_hash


# ─────────────────────────────────────────────────────────────────────────────
# Twin Run
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TwinRun:
    """A single execution of a scenario against a twin."""

    run_id: str
    twin_id: str
    scenario_id: str
    status: TwinRunStatus = TwinRunStatus.PENDING
    injected_events: list[dict[str, Any]] = field(default_factory=list)
    start_time: datetime | None = None
    end_time: datetime | None = None
    duration_ms: float | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.status, str):
            object.__setattr__(self, "status", TwinRunStatus(self.status))

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "twin_id": self.twin_id,
            "scenario_id": self.scenario_id,
            "status": self.status.value,
            "injected_events": self.injected_events,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_ms": self.duration_ms,
            "error_message": self.error_message,
            "metadata": dict(self.metadata),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Twin Result
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TwinResult:
    """Outcome of a twin run execution."""

    run_id: str
    twin_id: str
    scenario_id: str
    final_state_hash: str
    final_version: int
    events_processed: int
    metrics: dict[str, float] = field(default_factory=dict)  # revenue, margin, inventory, etc.
    timeline: list[dict[str, Any]] = field(default_factory=list)  # state at each step
    comparison: dict[str, Any] | None = None  # vs parent world
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "twin_id": self.twin_id,
            "scenario_id": self.scenario_id,
            "final_state_hash": self.final_state_hash,
            "final_version": self.final_version,
            "events_processed": self.events_processed,
            "metrics": dict(self.metrics),
            "timeline": list(self.timeline),
            "comparison": dict(self.comparison) if self.comparison else None,
            "created_at": self.created_at.isoformat(),
            "metadata": dict(self.metadata),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Scenario (J.3.2 — Declarative Scenario Contract)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Scenario:
    """Declarative scenario definition for J.3.2 Scenario Runtime.

    A scenario is a pure data description of a disruption to be simulated.
    It does NOT contain executable code — the ScenarioRuntime interprets it.
    """

    scenario_id: str
    scenario_type: ScenarioType
    target_entities: dict[str, list[str]]  # e.g., {"supplier": ["sup_1"], "warehouse": ["wh_1"]}
    parameters: dict[str, Any] = field(
        default_factory=dict
    )  # e.g., {"capacity_pct": 0.0, "delay_days": 5}
    start_time: datetime = field(default_factory=lambda: datetime.now(UTC))
    duration_hours: int = 72  # Simulation duration
    seed: int = 0
    engine_version: str = TWIN_ENGINE_VERSION
    simulation_version: str = TWIN_SIMULATION_VERSION
    created_by: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.scenario_type, str):
            object.__setattr__(self, "scenario_type", ScenarioType(self.scenario_type))

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "scenario_type": self.scenario_type.value,
            "target_entities": dict(self.target_entities),
            "parameters": dict(self.parameters),
            "start_time": self.start_time.isoformat(),
            "duration_hours": self.duration_hours,
            "seed": self.seed,
            "engine_version": self.engine_version,
            "simulation_version": self.simulation_version,
            "created_by": self.created_by,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ScenarioEvent:
    """A single event generated by a scenario during execution.

    Events are the primitive operations that the ScenarioRuntime emits.
    They are projected by the TwinProjection engine to produce state changes.
    """

    event_id: str
    scenario_run_id: str
    sequence: int
    entity_type: str
    entity_id: str
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "scenario_run_id": self.scenario_run_id,
            "sequence": self.sequence,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "event_type": self.event_type,
            "payload": dict(self.payload),
            "occurred_at": self.occurred_at.isoformat(),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ScenarioRun:
    """Immutable execution record for a scenario run (J.3.2).

    This provides full provenance so that:
        run(S, X, seed, V) → identical result every time.

    J.3.3 extension — ``trajectory_snapshots`` carries the tick-by-tick
    trajectory records produced by ``TrajectoryRecorder.get_trajectory()``
    for in-memory consumers (e.g. ``KPIEngine.compute`` for the
    time-series-aware KPI computations). It is an OPTIONAL field, defaulted
    empty, and is NOT part of the J.3.2 ``trajectory_hash`` fingerprint
    (that hash is its own self-contained field). Persisted twin runs do NOT
    store ``trajectory_snapshots`` directly — downstream consumers
    recompute them from the persisted ``TwinRunDB.injected_events`` log
    via the same deterministic event projection path (J.2.3 convention).
    """

    run_id: str
    twin_id: str
    scenario_id: str
    source_snapshot_id: str
    source_state_hash: str
    seed: int
    engine_version: str
    simulation_version: str
    started_at: datetime
    completed_at: datetime | None = None
    event_count: int = 0
    initial_state_hash: str = ""
    final_state_hash: str = ""
    status: TwinRunStatus = TwinRunStatus.PENDING
    result_hash: str = ""
    trajectory_hash: str = ""  # Hash of the full trajectory
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    trajectory_snapshots: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if isinstance(self.status, str):
            object.__setattr__(self, "status", TwinRunStatus(self.status))

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "twin_id": self.twin_id,
            "scenario_id": self.scenario_id,
            "source_snapshot_id": self.source_snapshot_id,
            "source_state_hash": self.source_state_hash,
            "seed": self.seed,
            "engine_version": self.engine_version,
            "simulation_version": self.simulation_version,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "event_count": self.event_count,
            "initial_state_hash": self.initial_state_hash,
            "final_state_hash": self.final_state_hash,
            "status": self.status.value,
            "result_hash": self.result_hash,
            "trajectory_hash": self.trajectory_hash,
            "error_message": self.error_message,
            "metadata": dict(self.metadata),
            # NOTE: trajectory_snapshots deliberately NOT serialized by
            # to_dict() to avoid bloating the provenance dict — they
            # are passed in-memory only via the dataclass field.
        }


# ─────────────────────────────────────────────────────────────────────────────
# Predefined Scenario Factories (J.3.2 — Declarative)
# ─────────────────────────────────────────────────────────────────────────────


def create_supplier_failure_scenario(
    scenario_id: str,
    supplier_id: str,
    capacity_pct: float = 0.0,
    disruption_type: str = "factory_fire",
    seed: int = 0,
) -> Scenario:
    """Create a supplier failure scenario (J.3.2 declarative)."""
    return Scenario(
        scenario_id=scenario_id,
        scenario_type=ScenarioType.SUPPLIER_FAILURE,
        target_entities={"supplier": [supplier_id]},
        parameters={
            "capacity_pct": capacity_pct,
            "disruption_type": disruption_type,
        },
        seed=seed,
    )


def create_supplier_delay_scenario(
    scenario_id: str,
    supplier_id: str,
    delay_days: int = 3,
    seed: int = 0,
) -> Scenario:
    """Create a supplier delay scenario (J.3.2 declarative)."""
    return Scenario(
        scenario_id=scenario_id,
        scenario_type=ScenarioType.SUPPLIER_DELAY,
        target_entities={"supplier": [supplier_id]},
        parameters={"delay_days": delay_days},
        seed=seed,
    )


def create_inventory_shortage_scenario(
    scenario_id: str,
    warehouse_id: str,
    component_id: str,
    reduction_pct: float = 50.0,
    seed: int = 0,
) -> Scenario:
    """Create an inventory shortage scenario (J.3.2 declarative)."""
    return Scenario(
        scenario_id=scenario_id,
        scenario_type=ScenarioType.INVENTORY_SHORTAGE,
        target_entities={"warehouse": [warehouse_id], "component": [component_id]},
        parameters={"reduction_pct": reduction_pct},
        seed=seed,
    )


def create_demand_spike_scenario(
    scenario_id: str,
    component_id: str,
    demand_multiplier: float = 2.0,
    seed: int = 0,
) -> Scenario:
    """Create a demand spike scenario (J.3.2 declarative)."""
    return Scenario(
        scenario_id=scenario_id,
        scenario_type=ScenarioType.DEMAND_SPIKE,
        target_entities={"component": [component_id]},
        parameters={"demand_multiplier": demand_multiplier},
        seed=seed,
    )


def create_route_disruption_scenario(
    scenario_id: str,
    route_id: str,
    delay_hours: int = 24,
    disruption_type: str = "port_closure",
    seed: int = 0,
) -> Scenario:
    """Create a route disruption scenario (J.3.2 declarative)."""
    return Scenario(
        scenario_id=scenario_id,
        scenario_type=ScenarioType.ROUTE_DISRUPTION,
        target_entities={"route": [route_id]},
        parameters={"delay_hours": delay_hours, "disruption_type": disruption_type},
        seed=seed,
    )


def create_capacity_reduction_scenario(
    scenario_id: str,
    entity_type: str,  # "warehouse" | "factory"
    entity_id: str,
    capacity_pct: float = 50.0,
    seed: int = 0,
) -> Scenario:
    """Create a capacity reduction scenario (J.3.2 declarative)."""
    return Scenario(
        scenario_id=scenario_id,
        scenario_type=ScenarioType.CAPACITY_REDUCTION,
        target_entities={entity_type: [entity_id]},
        parameters={"capacity_pct": capacity_pct},
        seed=seed,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Predefined TwinScenario Factories (Legacy — return TwinScenario, pre-J.3.2 API)
#
# These factories predate the J.3.2 declarative `Scenario` contract. Each
# returns a `TwinScenario` with a pre-baked `events` list. The J.3.2
# ScenarioRuntime consumes them transparently via
# TwinService._convert_legacy_scenario().
#
# They are distinct from the J.3.2 declarative factories above, which return
# `Scenario` (no event list — the runtime generates events from the parameters
# via ScenarioEventGenerator). The legacy names are suffixed `_twin_scenario`
# so the declarative `create_*_scenario` factories can take their canonical
# public role going forward.
# ─────────────────────────────────────────────────────────────────────────────


def create_supplier_failure_twin_scenario(
    scenario_id: str,
    supplier_id: str,
    delay_days: int,
    disruption_type: str = "factory_fire",
) -> TwinScenario:
    """Create a legacy supplier failure TwinScenario with a pre-baked delay event."""
    return TwinScenario(
        scenario_id=scenario_id,
        name=f"Supplier Failure: {supplier_id}",
        description=f"Supplier {supplier_id} delayed by {delay_days} days due to {disruption_type}",
        scenario_type=ScenarioType.SUPPLIER_FAILURE,
        events=[
            {
                "event_type": "supplier_delayed",
                "entity_type": "supplier",
                "entity_id": supplier_id,
                "payload": {"delay_days": delay_days, "disruption_type": disruption_type},
            }
        ],
        parameters={
            "supplier_id": supplier_id,
            "delay_days": delay_days,
            "disruption_type": disruption_type,
        },
    )


def create_demand_spike_twin_scenario(
    scenario_id: str,
    component_id: str,
    demand_change: int,
    confidence: float = 0.8,
) -> TwinScenario:
    """Create a legacy demand spike TwinScenario with a pre-baked demand change event."""
    return TwinScenario(
        scenario_id=scenario_id,
        name=f"Demand Spike: {component_id}",
        description=f"Demand for {component_id} increased by {demand_change} units",
        scenario_type=ScenarioType.DEMAND_SPIKE,
        events=[
            {
                "event_type": "demand_changed",
                "entity_type": "component",
                "entity_id": component_id,
                "payload": {
                    "demand_change": demand_change,
                    "confidence": confidence,
                    "source": "forecast",
                },
            }
        ],
        parameters={
            "component_id": component_id,
            "demand_change": demand_change,
            "confidence": confidence,
        },
    )


def create_port_closure_scenario(
    scenario_id: str,
    route_id: str,
    delay_days: int,
) -> TwinScenario:
    """Create a port closure scenario."""
    return TwinScenario(
        scenario_id=scenario_id,
        name=f"Port Closure: {route_id}",
        description=f"Route {route_id} disrupted for {delay_days} days",
        scenario_type=ScenarioType.PORT_CLOSURE,
        events=[
            {
                "event_type": "route_disruption",
                "entity_type": "route",
                "entity_id": route_id,
                "payload": {"delay_days": delay_days, "disruption_type": "port_closure"},
            }
        ],
        parameters={"route_id": route_id, "delay_days": delay_days},
    )


def create_factory_fire_scenario(
    scenario_id: str,
    factory_id: str,
    capacity_pct: float = 0.0,
    estimated_recovery_days: int = 30,
) -> TwinScenario:
    """Create a factory fire scenario."""
    return TwinScenario(
        scenario_id=scenario_id,
        name=f"Factory Fire: {factory_id}",
        description=f"Factory {factory_id} capacity reduced to {capacity_pct}%",
        scenario_type=ScenarioType.FACTORY_FIRE,
        events=[
            {
                "event_type": "factory_shutdown",
                "entity_type": "factory",
                "entity_id": factory_id,
                "payload": {
                    "capacity_pct": capacity_pct,
                    "estimated_recovery_days": estimated_recovery_days,
                    "cause": "fire",
                },
            }
        ],
        parameters={
            "factory_id": factory_id,
            "capacity_pct": capacity_pct,
            "estimated_recovery_days": estimated_recovery_days,
        },
    )


def create_labor_strike_scenario(
    scenario_id: str,
    factory_id: str,
    capacity_pct: float = 50.0,
    estimated_recovery_days: int = 14,
) -> TwinScenario:
    """Create a labor strike scenario."""
    return TwinScenario(
        scenario_id=scenario_id,
        name=f"Labor Strike: {factory_id}",
        description=f"Factory {factory_id} operating at {capacity_pct}% due to strike",
        scenario_type=ScenarioType.LABOR_STRIKE,
        events=[
            {
                "event_type": "factory_shutdown",
                "entity_type": "factory",
                "entity_id": factory_id,
                "payload": {
                    "capacity_pct": capacity_pct,
                    "estimated_recovery_days": estimated_recovery_days,
                    "cause": "labor_strike",
                },
            }
        ],
        parameters={
            "factory_id": factory_id,
            "capacity_pct": capacity_pct,
            "estimated_recovery_days": estimated_recovery_days,
        },
    )


def create_cyber_attack_scenario(
    scenario_id: str,
    factory_id: str,
    capacity_pct: float = 0.0,
    estimated_recovery_days: int = 21,
) -> TwinScenario:
    """Create a cyber attack scenario."""
    return TwinScenario(
        scenario_id=scenario_id,
        name=f"Cyber Attack: {factory_id}",
        description=f"Factory {factory_id} offline due to cyber attack",
        scenario_type=ScenarioType.CYBER_ATTACK,
        events=[
            {
                "event_type": "factory_shutdown",
                "entity_type": "factory",
                "entity_id": factory_id,
                "payload": {
                    "capacity_pct": capacity_pct,
                    "estimated_recovery_days": estimated_recovery_days,
                    "cause": "cyber_attack",
                },
            }
        ],
        parameters={
            "factory_id": factory_id,
            "capacity_pct": capacity_pct,
            "estimated_recovery_days": estimated_recovery_days,
        },
    )


def create_weather_scenario(
    scenario_id: str,
    affected_routes: list[str],
    delay_days: int,
) -> TwinScenario:
    """Create a weather disruption scenario."""
    events = []
    for route_id in affected_routes:
        events.append(
            {
                "event_type": "route_disruption",
                "entity_type": "route",
                "entity_id": route_id,
                "payload": {"delay_days": delay_days, "disruption_type": "weather"},
            }
        )
    return TwinScenario(
        scenario_id=scenario_id,
        name=f"Weather Disruption: {len(affected_routes)} routes",
        description=f"Weather disruption affecting {len(affected_routes)} routes for {delay_days} days",
        scenario_type=ScenarioType.WEATHER,
        events=events,
        parameters={"affected_routes": affected_routes, "delay_days": delay_days},
    )


def create_pricing_shock_scenario(
    scenario_id: str,
    component_id: str,
    price_multiplier: float,
) -> TwinScenario:
    """Create a pricing shock scenario."""
    return TwinScenario(
        scenario_id=scenario_id,
        name=f"Pricing Shock: {component_id}",
        description=f"Price of {component_id} changed by {price_multiplier}x",
        scenario_type=ScenarioType.PRICING_SHOCK,
        events=[
            {
                "event_type": "price_changed",
                "entity_type": "component",
                "entity_id": component_id,
                "payload": {"new_price": 0.0, "previous_price": 0.0, "currency": "USD"},
            }
        ],
        parameters={"component_id": component_id, "price_multiplier": price_multiplier},
    )


def create_currency_shock_scenario(
    scenario_id: str,
    affected_components: list[str],
    exchange_rate_change: float,
) -> TwinScenario:
    """Create a currency shock scenario."""
    events = []
    for component_id in affected_components:
        events.append(
            {
                "event_type": "price_changed",
                "entity_type": "component",
                "entity_id": component_id,
                "payload": {"new_price": 0.0, "previous_price": 0.0, "currency": "USD"},
            }
        )
    return TwinScenario(
        scenario_id=scenario_id,
        name=f"Currency Shock: {len(affected_components)} components",
        description=f"Exchange rate change of {exchange_rate_change}% affecting {len(affected_components)} components",
        scenario_type=ScenarioType.CURRENCY_SHOCK,
        events=events,
        parameters={
            "affected_components": affected_components,
            "exchange_rate_change": exchange_rate_change,
        },
    )


def create_pandemic_scenario(
    scenario_id: str,
    affected_factories: list[str],
    capacity_reduction_pct: float = 30.0,
    duration_days: int = 90,
) -> TwinScenario:
    """Create a pandemic scenario — workforce reduction across multiple factories."""
    events = []
    for factory_id in affected_factories:
        events.append(
            {
                "event_type": "factory_shutdown",
                "entity_type": "factory",
                "entity_id": factory_id,
                "payload": {
                    "capacity_pct": 100.0 - capacity_reduction_pct,
                    "estimated_recovery_days": duration_days,
                    "cause": "pandemic",
                },
            }
        )
    return TwinScenario(
        scenario_id=scenario_id,
        name=f"Pandemic: {len(affected_factories)} factories affected",
        description=f"Workforce reduction of {capacity_reduction_pct}% across {len(affected_factories)} factories for {duration_days} days",
        scenario_type=ScenarioType.PANDEMIC,
        events=events,
        parameters={
            "affected_factories": affected_factories,
            "capacity_reduction_pct": capacity_reduction_pct,
            "duration_days": duration_days,
        },
    )
