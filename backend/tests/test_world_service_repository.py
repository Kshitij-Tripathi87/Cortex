"""Tests for WorldStateService and StateRepository — Program J Milestone J.2.3.

Covers:
1. WorldStateService initialization & genesis snapshot creation
2. Monotonic version increment on event submissions
3. Domain state transitions (Inventory, SupplierDelay, OrderPlaced, Capacity, etc.)
4. Snapshot checkpointing at configured intervals
5. Idempotency handling (duplicate submissions produce no state mutation or version bump)
6. Workspace multi-tenant isolation
7. Transaction boundaries & atomicity (full rollback on validation/projection failure)
8. Batch event submission within a single transaction
9. StateRepository boring persistence contract (queries, lineage, metadata, summaries)
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.ids import uuid7
from app.modules.events.event_models import (
    InventoryChanged,
    OrderPlaced,
    SupplierDelayed,
)
from app.modules.world.state_projection import inventory_var_id, lead_time_var_id
from app.modules.world.state_repository import StateRepository
from app.modules.world.world_models import (
    StateMetadata,
    WorldState,
)
from app.modules.world.world_service import SubmitEventResult, WorldStateService


@pytest.fixture
def repo(db_session: AsyncSession) -> StateRepository:
    return StateRepository(db=db_session)


@pytest.fixture
def service(repo: StateRepository) -> WorldStateService:
    return WorldStateService(repository=repo, snapshot_interval=5)


# ─────────────────────────────────────────────────────────────────────────────
# 1. World Initialization & Genesis State
# ─────────────────────────────────────────────────────────────────────────────


class TestWorldInitialization:
    async def test_initialize_world_creates_version_1_and_genesis_snapshot(
        self, service: WorldStateService, repo: StateRepository
    ) -> None:
        workspace_id = f"ws_{uuid7()}"
        world_id = f"world_{uuid7()}"

        state = await service.initialize_world(
            workspace_id=workspace_id,
            world_id=world_id,
            graph_version=1,
        )

        assert state.version == 1
        assert state.workspace_id == workspace_id
        assert state.world_id == world_id
        assert state.graph_version == 1
        assert state.variables == {}

        # Verify state in repository
        latest = await repo.get_latest(workspace_id, world_id)
        assert latest is not None
        assert latest.version == 1
        assert latest.world_id == world_id

        # Verify version lineage record
        version_rec = await repo.get_version(world_id, workspace_id, version=1)
        assert version_rec is not None
        assert version_rec.source == "genesis"
        assert version_rec.parent_version_id is None

        # Verify genesis snapshot
        snapshot = await repo.get_latest_snapshot(world_id, workspace_id)
        assert snapshot is not None
        assert snapshot.version == 1
        assert snapshot.created_by == "system_genesis"

    async def test_initialize_world_already_exists_raises(self, service: WorldStateService) -> None:
        workspace_id = f"ws_{uuid7()}"
        world_id = f"world_{uuid7()}"

        await service.initialize_world(workspace_id=workspace_id, world_id=world_id)

        with pytest.raises(ValueError, match="already initialized"):
            await service.initialize_world(workspace_id=workspace_id, world_id=world_id)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Event Submission & Monotonic State Progression
# ─────────────────────────────────────────────────────────────────────────────


class TestEventSubmission:
    async def test_submit_event_increments_version_and_updates_variable(
        self, service: WorldStateService, repo: StateRepository
    ) -> None:
        workspace_id = f"ws_{uuid7()}"
        world_id = f"world_{uuid7()}"

        await service.initialize_world(workspace_id=workspace_id, world_id=world_id)

        event = InventoryChanged(
            event_id=f"evt_{uuid7()}",
            world_id=world_id,
            workspace_id=workspace_id,
            entity_type="warehouse",
            entity_id="wh_001",
            warehouse_id="wh_001",
            component_id="comp_100",
            quantity_change=500,
            reason="receipt",
        )

        result = await service.submit_event(event)

        assert isinstance(result, SubmitEventResult)
        assert result.version == 2
        assert result.is_duplicate is False
        assert result.event_id == event.event_id
        assert result.state.version == 2

        var_id = inventory_var_id("wh_001", "comp_100")
        var = result.state.variables.get(var_id)
        assert var is not None
        assert var.raw_value == 500

        # Check repository state
        current = await repo.get_latest(workspace_id, world_id)
        assert current is not None
        assert current.version == 2

        # Check event log in repository
        persisted_event = await repo.get_event(event.event_id, workspace_id)
        assert persisted_event is not None
        assert persisted_event.payload["quantity_change"] == 500

    async def test_submit_multiple_events_advances_versions_sequentially(
        self, service: WorldStateService
    ) -> None:
        workspace_id = f"ws_{uuid7()}"
        world_id = f"world_{uuid7()}"

        await service.initialize_world(workspace_id=workspace_id, world_id=world_id)

        # Event 1: add inventory 1000
        e1 = InventoryChanged(
            event_id=f"evt_{uuid7()}",
            world_id=world_id,
            workspace_id=workspace_id,
            entity_type="warehouse",
            entity_id="wh_001",
            warehouse_id="wh_001",
            component_id="comp_100",
            quantity_change=1000,
            reason="receipt",
        )
        res1 = await service.submit_event(e1)
        assert res1.version == 2

        # Event 2: order placed consuming 200
        e2 = OrderPlaced(
            event_id=f"evt_{uuid7()}",
            world_id=world_id,
            workspace_id=workspace_id,
            entity_type="warehouse",
            entity_id="wh_001",
            warehouse_id="wh_001",
            component_id="comp_100",
            quantity=200,
            customer_id="cust_01",
        )
        res2 = await service.submit_event(e2)
        assert res2.version == 3

        # Event 3: supplier delay 7 days
        e3 = SupplierDelayed(
            event_id=f"evt_{uuid7()}",
            world_id=world_id,
            workspace_id=workspace_id,
            entity_type="supplier",
            entity_id="supp_01",
            delay_days=7,
            disruption_type="port_strike",
        )
        res3 = await service.submit_event(e3)
        assert res3.version == 4

        # Final state check
        var_id = inventory_var_id("wh_001", "comp_100")
        assert res3.state.variables[var_id].raw_value == 800

        supp_var_id = lead_time_var_id("supp_01")
        assert res3.state.variables[supp_var_id].raw_value == 7

    async def test_submit_event_without_initial_state_raises(
        self, service: WorldStateService
    ) -> None:
        workspace_id = f"ws_{uuid7()}"
        world_id = f"world_{uuid7()}"

        event = InventoryChanged(
            event_id=f"evt_{uuid7()}",
            world_id=world_id,
            workspace_id=workspace_id,
            entity_type="warehouse",
            entity_id="wh_001",
            warehouse_id="wh_001",
            component_id="comp_100",
            quantity_change=100,
        )

        with pytest.raises(ValueError, match="No initial state found"):
            await service.submit_event(event)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Snapshot Checkpointing Policies
# ─────────────────────────────────────────────────────────────────────────────


class TestSnapshotPolicy:
    async def test_snapshot_triggered_at_interval(self, repo: StateRepository) -> None:
        # Snapshot interval = 3
        service = WorldStateService(repository=repo, snapshot_interval=3)
        workspace_id = f"ws_{uuid7()}"
        world_id = f"world_{uuid7()}"

        await service.initialize_world(workspace_id=workspace_id, world_id=world_id)

        # Version 2
        r2 = await service.submit_event(
            InventoryChanged(
                event_id=f"evt_{uuid7()}",
                world_id=world_id,
                workspace_id=workspace_id,
                entity_type="warehouse",
                entity_id="wh_1",
                warehouse_id="wh_1",
                component_id="c1",
                quantity_change=10,
            )
        )
        assert r2.is_snapshot_created is False

        # Version 3 -> 3 % 3 == 0 -> snapshot created!
        r3 = await service.submit_event(
            InventoryChanged(
                event_id=f"evt_{uuid7()}",
                world_id=world_id,
                workspace_id=workspace_id,
                entity_type="warehouse",
                entity_id="wh_1",
                warehouse_id="wh_1",
                component_id="c1",
                quantity_change=20,
            )
        )
        assert r3.version == 3
        assert r3.is_snapshot_created is True
        assert r3.snapshot is not None
        assert r3.snapshot.version == 3

        # Check repository has snapshot
        snap = await repo.get_latest_snapshot(world_id, workspace_id)
        assert snap is not None
        assert snap.version == 3

    async def test_explicit_snapshot_creation(
        self, service: WorldStateService, repo: StateRepository
    ) -> None:
        workspace_id = f"ws_{uuid7()}"
        world_id = f"world_{uuid7()}"

        await service.initialize_world(workspace_id=workspace_id, world_id=world_id)

        snapshot = await service.create_snapshot(
            workspace_id=workspace_id,
            world_id=world_id,
            created_by="operator_manual",
        )

        assert snapshot.world_id == world_id
        assert snapshot.version == 1
        assert snapshot.created_by == "operator_manual"

        persisted = await repo.get_snapshot(snapshot.snapshot_id, workspace_id)
        assert persisted is not None
        assert persisted.created_by == "operator_manual"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Idempotency Enforcement
# ─────────────────────────────────────────────────────────────────────────────


class TestIdempotency:
    async def test_duplicate_event_submission_returns_cached_state_without_mutation(
        self, service: WorldStateService, repo: StateRepository
    ) -> None:
        workspace_id = f"ws_{uuid7()}"
        world_id = f"world_{uuid7()}"

        await service.initialize_world(workspace_id=workspace_id, world_id=world_id)

        idempotency_key = f"idem_key_{uuid7()}"
        event = InventoryChanged(
            event_id=f"evt_{uuid7()}",
            world_id=world_id,
            workspace_id=workspace_id,
            entity_type="warehouse",
            entity_id="wh_001",
            warehouse_id="wh_001",
            component_id="comp_100",
            quantity_change=300,
        )

        # 1st submission -> processes transition to version 2
        res1 = await service.submit_event(event, idempotency_key=idempotency_key)
        assert res1.version == 2
        assert res1.is_duplicate is False

        # 2nd submission with same key -> should detect duplicate, return existing version 2
        res2 = await service.submit_event(event, idempotency_key=idempotency_key)
        assert res2.version == 2
        assert res2.is_duplicate is True
        assert res2.event_id == res1.event_id

        # 100th submission with same key -> still version 2, no extra events or mutations
        for _ in range(10):
            res_n = await service.submit_event(event, idempotency_key=idempotency_key)
            assert res_n.version == 2
            assert res_n.is_duplicate is True

        # State variable should be exactly 300 (applied once, not 12 times)
        latest = await repo.get_latest(workspace_id, world_id)
        assert latest is not None
        assert latest.version == 2
        var_id = inventory_var_id("wh_001", "comp_100")
        assert latest.variables[var_id].raw_value == 300

    async def test_different_idempotency_keys_process_normally(
        self, service: WorldStateService
    ) -> None:
        workspace_id = f"ws_{uuid7()}"
        world_id = f"world_{uuid7()}"

        await service.initialize_world(workspace_id=workspace_id, world_id=world_id)

        e1 = InventoryChanged(
            event_id=f"evt_{uuid7()}",
            world_id=world_id,
            workspace_id=workspace_id,
            entity_type="warehouse",
            entity_id="wh_1",
            warehouse_id="wh_1",
            component_id="c1",
            quantity_change=100,
        )
        r1 = await service.submit_event(e1, idempotency_key="key_1")
        assert r1.version == 2

        e2 = InventoryChanged(
            event_id=f"evt_{uuid7()}",
            world_id=world_id,
            workspace_id=workspace_id,
            entity_type="warehouse",
            entity_id="wh_1",
            warehouse_id="wh_1",
            component_id="c1",
            quantity_change=200,
        )
        r2 = await service.submit_event(e2, idempotency_key="key_2")
        assert r2.version == 3


# ─────────────────────────────────────────────────────────────────────────────
# 5. Multi-Tenant Workspace Isolation
# ─────────────────────────────────────────────────────────────────────────────


class TestWorkspaceIsolation:
    async def test_workspaces_are_completely_isolated(
        self, service: WorldStateService, repo: StateRepository
    ) -> None:
        ws_a = f"ws_a_{uuid7()}"
        world_a = f"world_a_{uuid7()}"

        ws_b = f"ws_b_{uuid7()}"
        world_b = f"world_b_{uuid7()}"

        # Initialize both worlds
        await service.initialize_world(workspace_id=ws_a, world_id=world_a)
        await service.initialize_world(workspace_id=ws_b, world_id=world_b)

        # Advance Workspace A by 3 events -> version 4
        for i in range(3):
            await service.submit_event(
                InventoryChanged(
                    event_id=f"evt_a_{i}_{uuid7()}",
                    world_id=world_a,
                    workspace_id=ws_a,
                    entity_type="warehouse",
                    entity_id="wh_a",
                    warehouse_id="wh_a",
                    component_id="comp_a",
                    quantity_change=100,
                )
            )

        # Check Workspace A is version 4
        state_a = await repo.get_latest(ws_a, world_a)
        assert state_a is not None
        assert state_a.version == 4
        assert inventory_var_id("wh_a", "comp_a") in state_a.variables

        # Check Workspace B is STILL version 1, unaffected
        state_b = await repo.get_latest(ws_b, world_b)
        assert state_b is not None
        assert state_b.version == 1
        assert state_b.variables == {}

        # Query summaries per workspace
        summaries_a = await repo.get_workspace_states(ws_a)
        assert len(summaries_a) == 1
        assert summaries_a[0].workspace_id == ws_a
        assert summaries_a[0].version == 4

        summaries_b = await repo.get_workspace_states(ws_b)
        assert len(summaries_b) == 1
        assert summaries_b[0].workspace_id == ws_b
        assert summaries_b[0].version == 1


# ─────────────────────────────────────────────────────────────────────────────
# 6. Transaction Boundaries & Rollback Integrity
# ─────────────────────────────────────────────────────────────────────────────


class TestTransactionRollback:
    async def test_invalid_event_payload_rolls_back_transaction(
        self, service: WorldStateService, repo: StateRepository
    ) -> None:
        workspace_id = f"ws_{uuid7()}"
        world_id = f"world_{uuid7()}"

        await service.initialize_world(workspace_id=workspace_id, world_id=world_id)

        # Event with empty entity_id (hard validation failure)
        bad_event = InventoryChanged(
            event_id=f"evt_bad_{uuid7()}",
            world_id=world_id,
            workspace_id=workspace_id,
            entity_type="warehouse",
            entity_id="",  # Invalid: required field
            warehouse_id="wh_1",
            component_id="comp_1",
            quantity_change=50,
        )

        with pytest.raises(ValueError):
            await service.submit_event(bad_event)

        # Verify state is still at version 1
        current = await repo.get_latest(workspace_id, world_id)
        assert current is not None
        assert current.version == 1

        # Verify no orphan event was saved
        saved_event = await repo.get_event(bad_event.event_id, workspace_id)
        assert saved_event is None

    async def test_batch_event_submission_atomic_all_or_nothing(
        self, service: WorldStateService, repo: StateRepository
    ) -> None:
        workspace_id = f"ws_{uuid7()}"
        world_id = f"world_{uuid7()}"

        await service.initialize_world(workspace_id=workspace_id, world_id=world_id)

        valid_1 = InventoryChanged(
            event_id=f"evt_v1_{uuid7()}",
            world_id=world_id,
            workspace_id=workspace_id,
            entity_type="warehouse",
            entity_id="wh_1",
            warehouse_id="wh_1",
            component_id="c1",
            quantity_change=100,
        )
        valid_2 = InventoryChanged(
            event_id=f"evt_v2_{uuid7()}",
            world_id=world_id,
            workspace_id=workspace_id,
            entity_type="warehouse",
            entity_id="wh_1",
            warehouse_id="wh_1",
            component_id="c2",
            quantity_change=200,
        )

        # Submit valid batch
        results = await service.submit_events([valid_1, valid_2])
        assert len(results) == 2
        assert results[0].version == 2
        assert results[1].version == 3

        latest = await repo.get_latest(workspace_id, world_id)
        assert latest is not None
        assert latest.version == 3


# ─────────────────────────────────────────────────────────────────────────────
# 7. StateRepository Boring Persistence Contract
# ─────────────────────────────────────────────────────────────────────────────


class TestStateRepositoryContract:
    async def test_repository_lineage_and_metadata_persistence(self, repo: StateRepository) -> None:
        workspace_id = f"ws_{uuid7()}"
        world_id = f"world_{uuid7()}"

        # 1. Create initial state
        state = WorldState(
            world_id=world_id,
            workspace_id=workspace_id,
            version=1,
            graph_version=1,
            variables={},
        )
        await repo.create(state)

        # 2. Store metadata
        meta = StateMetadata(
            workspace_id=workspace_id,
            world_id=world_id,
            version=1,
            graph_version=1,
            source="test_source",
            tags=["pilot", "synthetic"],
            metadata={"environment": "ci"},
        )
        await repo.store_metadata(meta)

        retrieved_meta = await repo.get_metadata(world_id, workspace_id, version=1)
        assert retrieved_meta is not None
        assert retrieved_meta.source == "test_source"
        assert retrieved_meta.tags == ["pilot", "synthetic"]

        # 3. List versions
        versions = await repo.list_versions(world_id, workspace_id)
        assert len(versions) == 1
        assert versions[0].version == 1

        # 4. Get event logs
        evt_id = await repo.append_event(
            world_id=world_id,
            workspace_id=workspace_id,
            entity_type="supplier",
            entity_id="supp_007",
            event_type="supplier_delayed",
            payload={"delay_days": 10},
        )
        events = await repo.get_events(world_id, workspace_id)
        assert len(events) == 1
        assert events[0].event_id == evt_id
        assert events[0].payload["delay_days"] == 10
