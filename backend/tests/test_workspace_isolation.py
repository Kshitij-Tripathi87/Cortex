"""Test Workspace Isolation — J.2.3 Repository Hardening.

Tests that workspaces are hermetically isolated from one another.

Invariants verified:
1. Workspace A events cannot mutate Workspace B state
2. Workspace A events cannot read Workspace B state
3. Query results are always workspace-scoped
4. State history is per-workspace
5. No cross-workspace contamination in any form
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.ids import uuid7
from app.modules.events.event_models import InventoryChanged
from app.modules.world.state_repository import StateRepository
from app.modules.world.world_service import WorldStateService


@pytest.fixture
def repo(db_session: AsyncSession) -> StateRepository:
    return StateRepository(db=db_session)


@pytest.fixture
def service(repo: StateRepository) -> WorldStateService:
    return WorldStateService(repository=repo, snapshot_interval=10)


class TestWorkspaceIsolation:
    """Verify hermetic isolation between workspaces."""

    async def test_workspace_a_event_cannot_mutate_workspace_b_state(
        self, service: WorldStateService, repo: StateRepository
    ) -> None:
        """Verify Workspace A events do not affect Workspace B state."""
        ws_a = f"ws_a_{uuid7()}"
        ws_b = f"ws_b_{uuid7()}"
        world_a = f"world_a_{uuid7()}"
        world_b = f"world_b_{uuid7()}"

        # Initialize states in both workspaces
        state_a_init = await service.initialize_world(ws_a, world_a)
        state_b_init = await service.initialize_world(ws_b, world_b)

        assert state_a_init.workspace_id == ws_a
        assert state_b_init.workspace_id == ws_b
        assert state_a_init.version == 1
        assert state_b_init.version == 1

        # Submit event to workspace A
        event_a = InventoryChanged(
            event_id=f"evt_a_{uuid7()}",
            world_id=world_a,
            workspace_id=ws_a,
            entity_type="warehouse",
            entity_id="wh_001",
            warehouse_id="wh_001",
            component_id="comp_001",
            quantity_change=100,
            reason="receipt",
        )

        result_a = await service.submit_event(event_a)
        assert result_a.version == 2
        assert result_a.state.workspace_id == ws_a

        # Verify Workspace B state is unchanged
        state_b_after = await repo.get_latest(ws_b, world_b)
        assert state_b_after is not None
        assert state_b_after.version == 1  # Still version 1
        assert state_b_after.workspace_id == ws_b

    async def test_workspace_a_cannot_read_workspace_b_state(
        self, service: WorldStateService, repo: StateRepository
    ) -> None:
        """Verify Workspace A queries cannot access Workspace B state."""
        ws_a = f"ws_a_{uuid7()}"
        ws_b = f"ws_b_{uuid7()}"
        world_a = f"world_a_{uuid7()}"
        world_b = f"world_b_{uuid7()}"

        # Initialize states
        await service.initialize_world(ws_a, world_a)
        await service.initialize_world(ws_b, world_b)

        # Submit event to workspace B to mark it distinctly
        event_b = InventoryChanged(
            event_id=f"evt_b_{uuid7()}",
            world_id=world_b,
            workspace_id=ws_b,
            entity_type="warehouse",
            entity_id="wh_002",
            warehouse_id="wh_002",
            component_id="comp_002",
            quantity_change=200,
            reason="receipt",
        )

        result_b = await service.submit_event(event_b)
        state_b = result_b.state

        # Query workspace A state — should NOT see B's state or version
        state_a = await repo.get_latest(ws_a, world_a)
        assert state_a is not None
        assert state_a.workspace_id == ws_a
        assert state_a.world_id == world_a
        assert state_a.version == 1  # Workspace A is still at genesis

        # Verify A's state is different from B's state
        assert state_a.metadata.get("state_hash") != state_b.metadata.get("state_hash")
        assert state_a.version != state_b.version

    async def test_query_results_are_workspace_scoped(
        self, service: WorldStateService, repo: StateRepository
    ) -> None:
        """Verify all repository queries respect workspace boundaries."""
        ws_a = f"ws_a_{uuid7()}"
        ws_b = f"ws_b_{uuid7()}"
        world_a = f"world_a_{uuid7()}"
        world_b = f"world_b_{uuid7()}"

        # Initialize both
        await service.initialize_world(ws_a, world_a)
        await service.initialize_world(ws_b, world_b)

        # Get latest for workspace A
        latest_a = await repo.get_latest(ws_a, world_a)
        assert latest_a is not None
        assert latest_a.workspace_id == ws_a

        # Get latest for workspace B
        latest_b = await repo.get_latest(ws_b, world_b)
        assert latest_b is not None
        assert latest_b.workspace_id == ws_b

        # Verify they are different
        assert latest_a.metadata.get("state_hash") != latest_b.metadata.get("state_hash")

        # Query workspace A's workspace-level states
        ws_a_states = await repo.get_workspace_states(ws_a)
        ws_b_states = await repo.get_workspace_states(ws_b)

        # All A states should have workspace_id = ws_a
        for state in ws_a_states:
            assert state.workspace_id == ws_a, f"Found state with workspace {state.workspace_id} in ws_a"

        # All B states should have workspace_id = ws_b
        for state in ws_b_states:
            assert state.workspace_id == ws_b, f"Found state with workspace {state.workspace_id} in ws_b"

    async def test_events_are_workspace_scoped(
        self, service: WorldStateService, repo: StateRepository
    ) -> None:
        """Verify event log queries are scoped to workspace."""
        ws_a = f"ws_a_{uuid7()}"
        ws_b = f"ws_b_{uuid7()}"
        world_a = f"world_a_{uuid7()}"
        world_b = f"world_b_{uuid7()}"

        await service.initialize_world(ws_a, world_a)
        await service.initialize_world(ws_b, world_b)

        # Submit event to A
        event_a = InventoryChanged(
            event_id=f"evt_a_{uuid7()}",
            world_id=world_a,
            workspace_id=ws_a,
            entity_type="warehouse",
            entity_id="wh_001",
            warehouse_id="wh_001",
            component_id="comp_001",
            quantity_change=100,
            reason="receipt",
        )

        # Submit event to B
        event_b = InventoryChanged(
            event_id=f"evt_b_{uuid7()}",
            world_id=world_b,
            workspace_id=ws_b,
            entity_type="warehouse",
            entity_id="wh_002",
            warehouse_id="wh_002",
            component_id="comp_002",
            quantity_change=200,
            reason="receipt",
        )

        await service.submit_event(event_a)
        await service.submit_event(event_b)

        # Fetch events from world A
        events_a = await repo.get_events(world_a, ws_a)
        assert len(events_a) == 1
        assert events_a[0].workspace_id == ws_a
        assert events_a[0].world_id == world_a

        # Fetch events from world B
        events_b = await repo.get_events(world_b, ws_b)
        assert len(events_b) == 1
        assert events_b[0].workspace_id == ws_b
        assert events_b[0].world_id == world_b

        # Verify the events are different
        assert events_a[0].event_id != events_b[0].event_id

    async def test_versions_are_workspace_scoped(
        self, service: WorldStateService, repo: StateRepository
    ) -> None:
        """Verify version history is per-workspace."""
        ws_a = f"ws_a_{uuid7()}"
        ws_b = f"ws_b_{uuid7()}"
        world_a = f"world_a_{uuid7()}"
        world_b = f"world_b_{uuid7()}"

        await service.initialize_world(ws_a, world_a)
        await service.initialize_world(ws_b, world_b)

        # Submit 2 events to A
        for i in range(2):
            event_a = InventoryChanged(
                event_id=f"evt_a_{i}_{uuid7()}",
                world_id=world_a,
                workspace_id=ws_a,
                entity_type="warehouse",
                entity_id=f"wh_{i:03d}",
                warehouse_id=f"wh_{i:03d}",
                component_id="comp_001",
                quantity_change=10 * (i + 1),
                reason="receipt",
            )
            await service.submit_event(event_a)

        # Submit 1 event to B
        event_b = InventoryChanged(
            event_id=f"evt_b_{uuid7()}",
            world_id=world_b,
            workspace_id=ws_b,
            entity_type="warehouse",
            entity_id="wh_001",
            warehouse_id="wh_001",
            component_id="comp_001",
            quantity_change=50,
            reason="receipt",
        )
        await service.submit_event(event_b)

        # Get version histories
        versions_a = await repo.get_versions(world_a, ws_a)
        versions_b = await repo.get_versions(world_b, ws_b)

        # A should have 3 versions (genesis + 2 events)
        assert len(versions_a) == 3
        for version in versions_a:
            assert version.workspace_id == ws_a

        # B should have 2 versions (genesis + 1 event)
        assert len(versions_b) == 2
        for version in versions_b:
            assert version.workspace_id == ws_b

    async def test_snapshots_are_workspace_scoped(
        self, service: WorldStateService, repo: StateRepository
    ) -> None:
        """Verify snapshots are not leaked across workspaces."""
        ws_a = f"ws_a_{uuid7()}"
        ws_b = f"ws_b_{uuid7()}"
        world_a = f"world_a_{uuid7()}"
        world_b = f"world_b_{uuid7()}"

        # Initialize with different snapshot intervals
        service_short = WorldStateService(repository=repo, snapshot_interval=2)

        await service.initialize_world(ws_a, world_a)
        await service_short.initialize_world(ws_b, world_b)

        # Submit events to B to trigger snapshot creation
        for i in range(3):
            event_b = InventoryChanged(
                event_id=f"evt_b_{i}_{uuid7()}",
                world_id=world_b,
                workspace_id=ws_b,
                entity_type="warehouse",
                entity_id=f"wh_{i:03d}",
                warehouse_id=f"wh_{i:03d}",
                component_id="comp_001",
                quantity_change=10 * (i + 1),
                reason="receipt",
            )
            await service_short.submit_event(event_b)

        # Fetch snapshots
        snapshot_a = await repo.get_latest_snapshot(world_a, ws_a)
        snapshot_b = await repo.get_latest_snapshot(world_b, ws_b)

        assert snapshot_a is not None and snapshot_b is not None
        assert snapshot_a.workspace_id == ws_a
        assert snapshot_b.workspace_id == ws_b
        assert snapshot_a.world_id == world_a
        assert snapshot_b.world_id == world_b
        assert snapshot_a.snapshot_id != snapshot_b.snapshot_id
