"""J.3.1 Twin Lifecycle — Immutable Lineage + Production Isolation.

These tests verify the two J.3.1 exit-gate invariants and the full lifecycle:

IN-1  IMMUTABLE LINEAGE
      parent_world_id, parent_version, snapshot_id, fork_of_twin_id,
      fork_from_run_id, created_at, twin_id are frozen at creation and
      fingerprinted into `lineage_hash`. No repository mutation path exists
      for them, and any tampering (even via raw SQL) is detectable.

IN-2  PRODUCTION ISOLATION
      No twin lifecycle operation writes to world_states, world_state_events,
      world_snapshots, world_versions, or world_metadata. Proven with a
      before/after `production_fingerprint` comparison.

IN-3  FORK INDEPENDENCE
      Two twins from the same snapshot diverge independently; a fork carries
      the source twin's CURRENT state.

IN-4  DETERMINISM
      Same (snapshot, scenario, seed) → same final_state_hash.

Run (SQLite, always):
    pytest tests/test_j31_twin_lifecycle.py -v

Run (PostgreSQL, integration):
    pytest tests/test_j31_twin_lifecycle.py -v \
        --postgres-url="postgresql+asyncpg://postgres:postgres@localhost:5433/cortex_test"
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from app.common.ids import uuid7
from app.modules.twin.twin_isolation import (
    IsolationError,
    production_fingerprint,
)
from app.modules.twin.twin_models import (
    ScenarioType,
    TwinScenario,
    TwinStatus,
    compute_twin_lineage_hash,
    lineage_intact,
)
from app.modules.twin.twin_repository import TwinDB, TwinRepository
from app.modules.twin.twin_service import TwinService
from app.modules.twin.twin_validation_helpers import make_fake_event
from app.modules.world.state_projection import (
    apply_transition,
    compute_state_hash,
    create_initial_state,
    create_state_snapshot,
    demand_var_id,
    inventory_var_id,
    lead_time_var_id,
    project_event_to_transition,
)
from app.modules.world.state_repository import StateRepository
from app.modules.world.world_models import StateVariable, StateVariableType


async def _seed_production_world(
    session: Any, workspace_id: str, world_id: str
) -> tuple[Any, Any]:
    """Create a production world (v1) + snapshot with inventory/lead/demand vars."""
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
    state = create_initial_state(
        workspace_id=workspace_id,
        world_id=world_id,
        graph_version=1,
        initial_variables={
            inv.variable_id: inv,
            lt.variable_id: lt,
        },
    )
    snapshot = create_state_snapshot(state, created_by="j31_test")
    await repo.create(state)
    await repo.store_snapshot(snapshot)
    return state, snapshot


def _strip_time(fp: dict[str, Any]) -> dict[str, Any]:
    """Remove the wall-clock stamp so fingerprints are comparable."""
    out = {k: v for k, v in fp.items() if k != "taken_at"}
    return out


def _raw_var_hash(state: Any, vid: str) -> Any:
    return state.variables[vid].raw_value


def _demand_scenario(scenario_id: str) -> TwinScenario:
    return TwinScenario(
        scenario_id=scenario_id,
        name="Demand Spike",
        scenario_type=ScenarioType.DEMAND_SPIKE,
        events=[
            {
                "entity_type": "component",
                "entity_id": "comp_a",
                "event_type": "demand_changed",
                "payload": {"demand_change": 150, "confidence": 0.9},
            }
        ],
    )


def _supplier_failure(scenario_id: str) -> TwinScenario:
    return TwinScenario(
        scenario_id=scenario_id,
        name="Supplier Failure",
        scenario_type=ScenarioType.SUPPLIER_FAILURE,
        events=[
            {
                "entity_type": "supplier",
                "entity_id": "sup_1",
                "event_type": "supplier_delayed",
                "payload": {"delay_days": 21, "disruption_type": "port_strike"},
            }
        ],
    )


# ─────────────────────────────────────────────────────────────────────────────
# J.3.1 — Lifecycle, lineage, isolation (SQLite + shared logic)
# ─────────────────────────────────────────────────────────────────────────────


class TestTwinLifecycleSQL:
    async def test_create_persists_immutable_lineage(self, db_session) -> None:
        ws = f"ws_{uuid7()}"
        world = f"world_{uuid7()}"
        _, snapshot = await _seed_production_world(db_session, ws, world)

        service = TwinService(db_session)
        twin = await service.create(
            workspace_id=ws, world_id=world, snapshot_id=snapshot.snapshot_id, name="T1"
        )

        # Lineage fields are populated and consistent with the source.
        assert twin.parent_world_id == world
        assert twin.parent_version == 1
        assert twin.snapshot_id == snapshot.snapshot_id
        assert twin.workspace_id == ws
        assert twin.fork_of_twin_id is None
        assert twin.fork_from_run_id is None
        assert twin.status == TwinStatus.READY

        # Lineage fingerprint is stamped and self-consistent.
        assert twin.lineage_hash == compute_twin_lineage_hash(twin)
        assert lineage_intact(twin)

        # Re-read from the database: lineage intact after round-trip.
        repo = TwinRepository(db_session)
        reloaded = await repo.get_twin(twin.twin_id, ws)
        assert reloaded is not None
        assert reloaded.parent_world_id == world
        assert reloaded.lineage_hash == twin.lineage_hash
        assert lineage_intact(reloaded)

    async def test_lineage_has_no_mutation_path(self, db_session) -> None:
        """The repository exposes NO update path for lineage fields."""
        repo = TwinRepository(db_session)
        for forbidden in (
            "update_lineage",
            "update_twin",
            "set_parent",
            "update_snapshot",
            "update_created_at",
        ):
            assert not hasattr(repo, forbidden), f"TwinRepository must not expose {forbidden}()"
        # The ONLY permitted mutation is a status transition.
        assert hasattr(repo, "transition_status")
        assert hasattr(repo, "create_twin")

    async def test_lineage_tamper_detection_sqlite(self, db_session) -> None:
        """Even a raw SQL tamper with a lineage field breaks the fingerprint."""
        ws = f"ws_{uuid7()}"
        world = f"world_{uuid7()}"
        _, snapshot = await _seed_production_world(db_session, ws, world)

        service = TwinService(db_session)
        twin = await service.create(
            workspace_id=ws, world_id=world, snapshot_id=snapshot.snapshot_id, name="T"
        )
        assert lineage_intact(twin)

        # Simulate unauthorized tampering by rewriting a lineage column directly.
        from sqlalchemy import update as sa_update

        await db_session.execute(
            sa_update(TwinDB).where(TwinDB.twin_id == twin.twin_id).values(parent_world_id="world_TAMPERED")
        )
        await db_session.commit()

        repo = TwinRepository(db_session)
        reloaded = await repo.get_twin(twin.twin_id, ws)
        assert reloaded is not None
        assert reloaded.parent_world_id == "world_TAMPERED"
        assert not lineage_intact(reloaded), "tampered lineage must fail the fingerprint"

        report = await service.verify_lineage(twin.twin_id, ws)
        assert report["lineage_intact"] is False

    async def test_clone_validation_rejects_bad_provenance(self, db_session) -> None:
        ws = f"ws_{uuid7()}"
        world = f"world_{uuid7()}"
        other_world = f"world_{uuid7()}"
        _, snapshot = await _seed_production_world(db_session, ws, world)
        await _seed_production_world(db_session, ws, other_world)

        service = TwinService(db_session)
        # Missing snapshot.
        with pytest.raises(IsolationError):
            await service.create(
                workspace_id=ws, world_id=world, snapshot_id="nope", name="T"
            )
        # Snapshot belonging to a different world.
        _, other_snap = await _seed_production_world(db_session, ws, other_world)
        with pytest.raises(IsolationError):
            await service.create(
                workspace_id=ws, world_id=world, snapshot_id=other_snap.snapshot_id, name="T"
            )
        # Snapshot in a different workspace (workspace-scoped read → not found).
        ws2 = f"ws_{uuid7()}"
        await _seed_production_world(db_session, ws2, world)
        with pytest.raises(IsolationError):
            await service.create(
                workspace_id=ws2, world_id=world, snapshot_id=snapshot.snapshot_id, name="T"
            )

    async def test_clone_rejects_hash_mismatch(self, db_session) -> None:
        """A snapshot whose hash disagrees with the materialized state is refused."""
        ws = f"ws_{uuid7()}"
        world = f"world_{uuid7()}"
        state, _ = await _seed_production_world(db_session, ws, world)

        # Store a forged snapshot referencing version 1 but with a wrong hash.
        from datetime import UTC, datetime

        from app.modules.world.world_models import WorldSnapshot

        forged = WorldSnapshot(
            snapshot_id=str(uuid7()),
            world_id=world,
            workspace_id=ws,
            version=1,
            graph_version=1,
            state_hash="0" * 64,
            variable_count=2,
            created_at=datetime.now(UTC),
        )
        await StateRepository(db_session).store_snapshot(forged)

        service = TwinService(db_session)
        real_hash = state.metadata.get("state_hash", "")
        assert real_hash != "0" * 64
        with pytest.raises(IsolationError):
            await service.create(
                workspace_id=ws, world_id=world, snapshot_id=forged.snapshot_id, name="T"
            )

    async def test_fork_carries_current_state_and_provenance(self, db_session) -> None:
        ws = f"ws_{uuid7()}"
        world = f"world_{uuid7()}"
        _, snapshot = await _seed_production_world(db_session, ws, world)

        service = TwinService(db_session)
        twin = await service.create(
            workspace_id=ws, world_id=world, snapshot_id=snapshot.snapshot_id, name="Source"
        )

        # Run a disruption on the source so it has a CURRENT (moved) state.
        await service.run(twin, _supplier_failure(f"scn_{uuid7()}"), seed=1)
        lt_after_run = _raw_var_hash(
            await service.get_current_state(twin), lead_time_var_id("sup_1")
        )
        assert lt_after_run == 31

        # Fork must carry the source's CURRENT state (not the snapshot's).
        fork = await service.fork(source_twin_id=twin.twin_id, fork_name="Branch")
        assert fork.fork_of_twin_id == twin.twin_id
        assert fork.fork_from_run_id is not None
        assert fork.parent_world_id == world
        assert "fork" in fork.tags
        assert fork.lineage_hash != twin.lineage_hash  # different identity → different hash
        assert lineage_intact(fork)

        fork_state = await service.get_current_state(fork)
        assert _raw_var_hash(fork_state, lead_time_var_id("sup_1")) == 31

    async def test_fork_from_unrun_twin_starts_at_snapshot(self, db_session) -> None:
        ws = f"ws_{uuid7()}"
        world = f"world_{uuid7()}"
        _, snapshot = await _seed_production_world(db_session, ws, world)

        service = TwinService(db_session)
        twin = await service.create(
            workspace_id=ws, world_id=world, snapshot_id=snapshot.snapshot_id, name="Source"
        )
        fork = await service.fork(source_twin_id=twin.twin_id, fork_name="Branch")
        assert fork.fork_from_run_id is None  # source never ran

        fork_state = await service.get_current_state(fork)
        # Un-run fork starts at the snapshot state (lead time = 10, inventory = 500).
        assert _raw_var_hash(fork_state, lead_time_var_id("sup_1")) == 10
        assert (
            _raw_var_hash(fork_state, inventory_var_id("wh_1", "comp_a")) == 500
        )

    async def test_forks_are_independent_divergence(self, db_session) -> None:
        """IN-3: Twin A and Twin B diverge independently from the same snapshot."""
        ws = f"ws_{uuid7()}"
        world = f"world_{uuid7()}"
        _, snapshot = await _seed_production_world(db_session, ws, world)

        service = TwinService(db_session)
        before = _strip_time(await production_fingerprint(db_session, ws))

        twin_a = await service.create(
            workspace_id=ws, world_id=world, snapshot_id=snapshot.snapshot_id, name="A"
        )
        twin_b = await service.create(
            workspace_id=ws, world_id=world, snapshot_id=snapshot.snapshot_id, name="B"
        )

        result_a = await service.run(twin_a, _supplier_failure(f"scn_{uuid7()}"), seed=0)
        result_b = await service.run(twin_b, _demand_scenario(f"scn_{uuid7()}"), seed=0)

        # Divergent final states.
        assert result_a.final_state_hash != result_b.final_state_hash

        state_a = await service.get_current_state(twin_a)
        state_b = await service.get_current_state(twin_b)
        # A suffered the supplier delay; B did not.
        assert _raw_var_hash(state_a, lead_time_var_id("sup_1")) == 31
        assert _raw_var_hash(state_b, lead_time_var_id("sup_1")) == 10
        # B absorbed the demand spike (a brand-new variable); A did not.
        assert demand_var_id("comp_a") in state_b.variables
        assert demand_var_id("comp_a") not in state_a.variables

        # Production is untouched by either twin.
        after = _strip_time(await production_fingerprint(db_session, ws))
        assert before == after, "twin execution must not leak into production tables"

    async def test_production_isolation_full_lifecycle(self, db_session) -> None:
        """IN-2: zero leakage across the entire lifecycle."""
        ws = f"ws_{uuid7()}"
        world = f"world_{uuid7()}"
        _, snapshot = await _seed_production_world(db_session, ws, world)

        service = TwinService(db_session)
        before = _strip_time(await production_fingerprint(db_session, ws))

        twin = await service.create(
            workspace_id=ws, world_id=world, snapshot_id=snapshot.snapshot_id, name="Iso"
        )
        fork = await service.fork(source_twin_id=twin.twin_id, fork_name="IsoFork")
        await service.run(twin, _supplier_failure(f"scn_{uuid7()}"), seed=0)
        await service.run(fork, _demand_scenario(f"scn_{uuid7()}"), seed=0)
        await service.archive(twin.twin_id)
        assert await service.destroy(fork.twin_id) is True

        after = _strip_time(await production_fingerprint(db_session, ws))
        assert before == after, (
            f"production fingerprint changed: before={before['tables']} after={after['tables']}"
        )

        # Point-in-time per-twin leakage check is clean too.
        enforcer_check = await service.enforcer.verify_isolation(twin.twin_id)
        assert enforcer_check["isolated"] is True

    async def test_run_is_deterministic(self, db_session) -> None:
        """IN-4: same (snapshot, scenario, seed) → same final hash."""
        ws = f"ws_{uuid7()}"
        world = f"world_{uuid7()}"
        _, snapshot = await _seed_production_world(db_session, ws, world)

        service = TwinService(db_session)
        twin_1 = await service.create(
            workspace_id=ws, world_id=world, snapshot_id=snapshot.snapshot_id, name="D1"
        )
        twin_2 = await service.create(
            workspace_id=ws, world_id=world, snapshot_id=snapshot.snapshot_id, name="D2"
        )

        scenario = _supplier_failure(f"scn_{uuid7()}")
        r1 = await service.run(twin_1, scenario, seed=42)
        r2 = await service.run(twin_2, scenario, seed=42)

        assert r1.final_state_hash == r2.final_state_hash
        assert r1.final_version == r2.final_version
        assert r1.final_state_hash != ""  # non-vacuous: a real fingerprint


class TestTwinLifecycleStatusTransitions:
    async def test_status_machine(self, db_session) -> None:
        ws = f"ws_{uuid7()}"
        world = f"world_{uuid7()}"
        _, snapshot = await _seed_production_world(db_session, ws, world)
        service = TwinService(db_session)
        twin = await service.create(
            workspace_id=ws, world_id=world, snapshot_id=snapshot.snapshot_id, name="SM"
        )
        assert (await service.get_twin(twin.twin_id, ws)).status == TwinStatus.READY

        await service.run(twin, _supplier_failure(f"scn_{uuid7()}"), seed=0)
        assert (await service.get_twin(twin.twin_id, ws)).status == TwinStatus.COMPLETED

        archived = await service.archive(twin.twin_id)
        assert archived.status == TwinStatus.ARCHIVED
        # Archived twin cannot run or be forked.
        with pytest.raises(IsolationError):
            await service.run(twin.twin_id, _demand_scenario(f"scn_{uuid7()}"), seed=0)
        with pytest.raises(IsolationError):
            await service.fork(source_twin_id=twin.twin_id, fork_name="Nope")
        # Double archive is rejected.
        with pytest.raises(IsolationError):
            await service.archive(twin.twin_id)

    async def test_destroy_removes_twin_and_runs(self, db_session) -> None:
        ws = f"ws_{uuid7()}"
        world = f"world_{uuid7()}"
        _, snapshot = await _seed_production_world(db_session, ws, world)
        service = TwinService(db_session)
        twin = await service.create(
            workspace_id=ws, world_id=world, snapshot_id=snapshot.snapshot_id, name="Del"
        )
        await service.run(twin, _supplier_failure(f"scn_{uuid7()}"), seed=0)

        repo = TwinRepository(db_session)
        assert await repo.count_runs(twin.twin_id, ws) == 1

        assert await service.destroy(twin.twin_id) is True
        assert await service.get_twin(twin.twin_id, ws) is None
        assert await repo.count_runs(twin.twin_id, ws) == 0
        # Second destroy is a no-op (idempotent).
        assert await service.destroy(twin.twin_id) is False

    async def test_workspace_isolation(self, db_session) -> None:
        ws_a = f"ws_{uuid7()}"
        ws_b = f"ws_{uuid7()}"
        world_a = f"world_{uuid7()}"
        world_b = f"world_{uuid7()}"
        await _seed_production_world(db_session, ws_a, world_a)
        _, snap_b = await _seed_production_world(db_session, ws_b, world_b)

        service = TwinService(db_session)
        snap_a = await StateRepository(db_session).get_latest_snapshot(world_a, ws_a)
        assert snap_a is not None
        twin_a = await service.create(
            workspace_id=ws_a, world_id=world_a, snapshot_id=snap_a.snapshot_id, name="Iso"
        )
        await service.create(
            workspace_id=ws_b, world_id=world_b, snapshot_id=snap_b.snapshot_id, name="IsoB"
        )

        # ws_b does not see ws_a's twin.
        listed_b = await service.list_twins(ws_b)
        assert all(t.twin_id != twin_a.twin_id for t in listed_b)
        assert await service.get_twin(twin_a.twin_id, workspace_id=ws_b) is None
        # But ws_a sees it.
        assert await service.get_twin(twin_a.twin_id, workspace_id=ws_a) is not None


class TestTwinRunReplay:
    async def test_replay_run_events_reconstructs_state(self, db_session) -> None:
        """Replaying the persisted run event log reproduces the run's final hash."""
        ws = f"ws_{uuid7()}"
        world = f"world_{uuid7()}"
        _, snapshot = await _seed_production_world(db_session, ws, world)

        service = TwinService(db_session)
        twin = await service.create(
            workspace_id=ws, world_id=world, snapshot_id=snapshot.snapshot_id, name="RLP"
        )
        scenario = _supplier_failure(f"scn_{uuid7()}")
        result = await service.run(twin, scenario, seed=7)

        # Load the persisted run + the snapshot's base state.
        repo = TwinRepository(db_session)
        run_row = await repo.get_latest_run(twin.twin_id, ws)
        assert run_row is not None
        base_state = await service._validated_parent_state(ws, world, snapshot)

        # Replay the run's own event log from the base state.
        state = base_state
        for ev in run_row.injected_events:
            fake = make_fake_event(
                event_id=ev["event_id"],
                world_id=world,
                workspace_id=ws,
                entity_type=ev["entity_type"],
                entity_id=ev["entity_id"],
                event_type=ev["event_type"],
                payload=ev["payload"],
                occurred_at=datetime.fromisoformat(ev["occurred_at"]),
            )
            transition = project_event_to_transition(state, fake)
            if transition is not None:
                state = apply_transition(state, transition)

        assert compute_state_hash(state) == run_row.final_state_hash
        assert compute_state_hash(state) == result.final_state_hash
        assert state.version == run_row.final_version


# ─────────────────────────────────────────────────────────────────────────────
# J.3.1 — Strict State Machine (invalid transitions rejected)
# ─────────────────────────────────────────────────────────────────────────────


class TestTwinStateMachine:
    async def test_invalid_transition_archived_to_running(self, db_session) -> None:
        """ARCHIVED → RUNNING must be rejected."""
        ws = f"ws_{uuid7()}"
        world = f"world_{uuid7()}"
        _, snapshot = await _seed_production_world(db_session, ws, world)
        service = TwinService(db_session)
        twin = await service.create(
            workspace_id=ws, world_id=world, snapshot_id=snapshot.snapshot_id, name="SM"
        )
        await service.run(twin, _supplier_failure(f"scn_{uuid7()}"), seed=0)
        await service.archive(twin.twin_id)

        # Archived twin cannot transition to RUNNING directly.
        with pytest.raises(IsolationError, match="Invalid twin status transition"):
            await service._transition_status(twin.twin_id, ws, TwinStatus.RUNNING)

    async def test_invalid_transition_destroyed_to_ready(self, db_session) -> None:
        """DESTROYED → READY must be rejected (after destroy, twin is gone)."""
        ws = f"ws_{uuid7()}"
        world = f"world_{uuid7()}"
        _, snapshot = await _seed_production_world(db_session, ws, world)
        service = TwinService(db_session)
        twin = await service.create(
            workspace_id=ws, world_id=world, snapshot_id=snapshot.snapshot_id, name="DST"
        )
        await service.destroy(twin.twin_id)
        # Twin no longer exists, so the transition raises IsolationError.
        with pytest.raises(IsolationError, match="not found"):
            await service._transition_status(twin.twin_id, ws, TwinStatus.READY)

    async def test_cannot_fork_archived_twin(self, db_session) -> None:
        """Cannot fork a twin in ARCHIVED status."""
        ws = f"ws_{uuid7()}"
        world = f"world_{uuid7()}"
        _, snapshot = await _seed_production_world(db_session, ws, world)
        service = TwinService(db_session)
        twin = await service.create(
            workspace_id=ws, world_id=world, snapshot_id=snapshot.snapshot_id, name="ARC"
        )
        await service.run(twin, _supplier_failure(f"scn_{uuid7()}"), seed=0)
        await service.archive(twin.twin_id)

        with pytest.raises(IsolationError):
            await service.fork(source_twin_id=twin.twin_id, fork_name="Nope")

    async def test_cannot_run_archived_twin(self, db_session) -> None:
        """Cannot run a scenario on an ARCHIVED twin."""
        ws = f"ws_{uuid7()}"
        world = f"world_{uuid7()}"
        _, snapshot = await _seed_production_world(db_session, ws, world)
        service = TwinService(db_session)
        twin = await service.create(
            workspace_id=ws, world_id=world, snapshot_id=snapshot.snapshot_id, name="ARC"
        )
        await service.archive(twin.twin_id)

        with pytest.raises(IsolationError):
            await service.run(twin.twin_id, _demand_scenario(f"scn_{uuid7()}"), seed=0)


# ─────────────────────────────────────────────────────────────────────────────
# J.3.1 — Organization ID and Lineage
# ─────────────────────────────────────────────────────────────────────────────


class TestTwinOrganizationLineage:
    async def test_organization_id_preserved(self, db_session) -> None:
        """organization_id is set on creation and preserved on reload."""
        ws = f"ws_{uuid7()}"
        org = f"org_{uuid7()}"
        world = f"world_{uuid7()}"
        _, snapshot = await _seed_production_world(db_session, ws, world)

        service = TwinService(db_session)
        twin = await service.create(
            workspace_id=ws,
            world_id=world,
            snapshot_id=snapshot.snapshot_id,
            name="OrgTwin",
            organization_id=org,
        )
        assert twin.organization_id == org

        # Reload from DB: organization_id preserved.
        reloaded = await service.get_twin(twin.twin_id, ws)
        assert reloaded is not None
        assert reloaded.organization_id == org

    async def test_organization_id_defaults_to_workspace(self, db_session) -> None:
        """If organization_id not provided, it defaults to workspace_id."""
        ws = f"ws_{uuid7()}"
        world = f"world_{uuid7()}"
        _, snapshot = await _seed_production_world(db_session, ws, world)

        service = TwinService(db_session)
        twin = await service.create(
            workspace_id=ws,
            world_id=world,
            snapshot_id=snapshot.snapshot_id,
            name="DefaultOrg",
        )
        assert twin.organization_id == ws

    async def test_fork_inherits_organization_id(self, db_session) -> None:
        """Forked twin inherits organization_id from source."""
        ws = f"ws_{uuid7()}"
        org = f"org_{uuid7()}"
        world = f"world_{uuid7()}"
        _, snapshot = await _seed_production_world(db_session, ws, world)

        service = TwinService(db_session)
        twin = await service.create(
            workspace_id=ws,
            world_id=world,
            snapshot_id=snapshot.snapshot_id,
            name="Parent",
            organization_id=org,
        )
        fork = await service.fork(source_twin_id=twin.twin_id, fork_name="Child")
        assert fork.organization_id == org

    async def test_lineage_hash_includes_organization_id(self, db_session) -> None:
        """Lineage hash changes when organization_id differs."""
        ws = f"ws_{uuid7()}"
        world = f"world_{uuid7()}"
        _, snapshot = await _seed_production_world(db_session, ws, world)

        service = TwinService(db_session)
        twin_a = await service.create(
            workspace_id=ws,
            world_id=world,
            snapshot_id=snapshot.snapshot_id,
            name="A",
            organization_id="org_a",
        )
        twin_b = await service.create(
            workspace_id=ws,
            world_id=world,
            snapshot_id=snapshot.snapshot_id,
            name="B",
            organization_id="org_b",
        )
        # Same snapshot, same workspace, but different organization_id → different hash.
        assert twin_a.lineage_hash != twin_b.lineage_hash


# ─────────────────────────────────────────────────────────────────────────────
# J.3.1 — Run Provenance (determinism version stamps)
# ─────────────────────────────────────────────────────────────────────────────


class TestTwinRunProvenance:
    async def test_run_records_engine_version(self, db_session) -> None:
        """A run's result metadata includes engine_version for reproducibility."""
        ws = f"ws_{uuid7()}"
        world = f"world_{uuid7()}"
        _, snapshot = await _seed_production_world(db_session, ws, world)
        service = TwinService(db_session)
        twin = await service.create(
            workspace_id=ws, world_id=world, snapshot_id=snapshot.snapshot_id, name="PV"
        )
        result = await service.run(twin, _supplier_failure(f"scn_{uuid7()}"), seed=0)

        assert "engine_version" in result.metadata
        assert "rng_version" in result.metadata
        assert "simulation_version" in result.metadata
        assert result.metadata["engine_version"] != ""

    async def test_run_provenance_persisted(self, db_session) -> None:
        """Run provenance is persisted in the twin_runs metadata."""
        ws = f"ws_{uuid7()}"
        world = f"world_{uuid7()}"
        _, snapshot = await _seed_production_world(db_session, ws, world)
        service = TwinService(db_session)
        twin = await service.create(
            workspace_id=ws, world_id=world, snapshot_id=snapshot.snapshot_id, name="PVP"
        )
        await service.run(twin, _supplier_failure(f"scn_{uuid7()}"), seed=0)

        repo = TwinRepository(db_session)
        run_row = await repo.get_latest_run(twin.twin_id, ws)
        assert run_row is not None
        meta = run_row.extra_metadata
        assert "rng_version" in meta
        assert "engine_version" in meta
        assert "simulation_version" in meta


# ─────────────────────────────────────────────────────────────────────────────
# J.3.1 — Persistence / Reload
# ─────────────────────────────────────────────────────────────────────────────


class TestTwinPersistence:
    async def test_twin_survives_reload(self, db_session) -> None:
        """A twin reloaded from the DB has identical lineage fields."""
        ws = f"ws_{uuid7()}"
        world = f"world_{uuid7()}"
        _, snapshot = await _seed_production_world(db_session, ws, world)
        service = TwinService(db_session)
        twin = await service.create(
            workspace_id=ws, world_id=world, snapshot_id=snapshot.snapshot_id, name="Persist"
        )

        reloaded = await service.get_twin(twin.twin_id, ws)
        assert reloaded is not None
        assert reloaded.twin_id == twin.twin_id
        assert reloaded.organization_id == twin.organization_id
        assert reloaded.parent_world_id == twin.parent_world_id
        assert reloaded.parent_version == twin.parent_version
        assert reloaded.snapshot_id == twin.snapshot_id
        assert reloaded.lineage_hash == twin.lineage_hash
        assert lineage_intact(reloaded)

    async def test_run_result_reloaded(self, db_session) -> None:
        """Run results survive reload and can be queried."""
        ws = f"ws_{uuid7()}"
        world = f"world_{uuid7()}"
        _, snapshot = await _seed_production_world(db_session, ws, world)
        service = TwinService(db_session)
        twin = await service.create(
            workspace_id=ws, world_id=world, snapshot_id=snapshot.snapshot_id, name="RR"
        )
        result = await service.run(twin, _supplier_failure(f"scn_{uuid7()}"), seed=0)

        # Query results after "reload"
        results = await service.get_results(twin.twin_id)
        assert len(results) >= 1
        assert results[0].run_id == result.run_id
        assert results[0].final_state_hash == result.final_state_hash

    async def test_destroy_is_idempotent(self, db_session) -> None:
        """Destroying a non-existent twin returns False (idempotent)."""
        ws = f"ws_{uuid7()}"
        service = TwinService(db_session)
        assert await service.destroy("nonexistent_twin_id_xyz") is False


# ─────────────────────────────────────────────────────────────────────────────
# J.3.1 — PostgreSQL integration (real DB; skips if unavailable)
# ─────────────────────────────────────────────────────────────────────────────


class TestTwinLifecyclePostgres:
    async def test_pg_full_lifecycle_and_isolation(self, postgres_session) -> None:
        ws = f"ws_{uuid7()}"
        world = f"world_{uuid7()}"
        _, snapshot = await _seed_production_world(postgres_session, ws, world)

        service = TwinService(postgres_session)
        before = _strip_time(await production_fingerprint(postgres_session, ws))

        twin = await service.create(
            workspace_id=ws, world_id=world, snapshot_id=snapshot.snapshot_id, name="PG"
        )
        await service.run(twin, _supplier_failure(f"scn_{uuid7()}"), seed=3)
        fork = await service.fork(source_twin_id=twin.twin_id, fork_name="PGFork")
        await service.run(fork, _demand_scenario(f"scn_{uuid7()}"), seed=3)
        await service.archive(twin.twin_id)

        after = _strip_time(await production_fingerprint(postgres_session, ws))
        assert before == after

        report = await service.verify_lineage(twin.twin_id, ws)
        assert report["lineage_intact"] is True

    async def test_pg_lineage_tamper_detection(self, postgres_session) -> None:
        ws = f"ws_{uuid7()}"
        world = f"world_{uuid7()}"
        _, snapshot = await _seed_production_world(postgres_session, ws, world)

        service = TwinService(postgres_session)
        twin = await service.create(
            workspace_id=ws, world_id=world, snapshot_id=snapshot.snapshot_id, name="PG"
        )
        assert lineage_intact(twin)

        from sqlalchemy import text

        await postgres_session.execute(
            text("UPDATE twins SET parent_version = 999 WHERE twin_id = :tid"),
            {"tid": twin.twin_id},
        )
        await postgres_session.commit()

        repo = TwinRepository(postgres_session)
        reloaded = await repo.get_twin(twin.twin_id, ws)
        assert reloaded is not None
        assert reloaded.parent_version == 999
        assert not lineage_intact(reloaded)
        report = await service.verify_lineage(twin.twin_id, ws)
        assert report["lineage_intact"] is False

    async def test_pg_run_is_deterministic(self, postgres_session) -> None:
        ws = f"ws_{uuid7()}"
        world = f"world_{uuid7()}"
        _, snapshot = await _seed_production_world(postgres_session, ws, world)

        service = TwinService(postgres_session)
        t1 = await service.create(
            workspace_id=ws, world_id=world, snapshot_id=snapshot.snapshot_id, name="P1"
        )
        t2 = await service.create(
            workspace_id=ws, world_id=world, snapshot_id=snapshot.snapshot_id, name="P2"
        )
        scenario = _supplier_failure(f"scn_{uuid7()}")
        r1 = await service.run(t1, scenario, seed=99)
        r2 = await service.run(t2, scenario, seed=99)
        assert r1.final_state_hash == r2.final_state_hash
        assert r1.final_state_hash != ""
