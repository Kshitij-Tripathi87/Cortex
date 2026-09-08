"""Test Repository Contract — J.2.3 Repository Hardening.

Tests that the StateRepository is a boring persistence boundary with no forbidden mutations.

Invariants verified:
1. Events are append-only (never updated/deleted)
2. Versions are sequential and immutable
3. Snapshots are sealed (never mutated)
4. Lineage forms a DAG (parent chains are acyclic)
5. Workspace isolation (one workspace cannot mutate another's state)
6. Read operations have no side effects
7. No forbidden mutation methods exposed
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


class TestRepositoryContract:
    """Verify boring persistence contract: queries only, no hidden mutations."""

    async def test_repository_exposes_only_intended_methods(self, repo: StateRepository) -> None:
        """Verify no forbidden mutation methods exist."""
        forbidden_methods = [
            "update_state",
            "delete_event",
            "archive_snapshot",
            "mutate_version",
            "hard_reset",
            "edit_state",
            "modify_version",
        ]
        for method_name in forbidden_methods:
            assert not hasattr(repo, method_name), (
                f"Forbidden method {method_name} found on repository"
            )

    async def test_repository_get_methods_no_side_effects(
        self, service: WorldStateService, repo: StateRepository
    ) -> None:
        """Verify read operations never mutate state."""
        workspace_id = f"ws_{uuid7()}"
        world_id = f"world_{uuid7()}"

        # Initialize
        await service.initialize_world(workspace_id, world_id)

        # Get state multiple times
        state1 = await repo.get_latest(workspace_id, world_id)
        state2 = await repo.get_latest(workspace_id, world_id)
        state3 = await repo.get_latest(workspace_id, world_id)

        # All reads should be identical
        assert state1 is not None and state2 is not None and state3 is not None
        assert state1.version == state2.version == state3.version == 1
        assert (
            state1.metadata.get("state_hash")
            == state2.metadata.get("state_hash")
            == state3.metadata.get("state_hash")
        )

    async def test_events_never_updated_or_deleted(
        self, service: WorldStateService, repo: StateRepository
    ) -> None:
        """Verify events table is append-only (no UPDATE/DELETE)."""
        workspace_id = f"ws_{uuid7()}"
        world_id = f"world_{uuid7()}"

        await service.initialize_world(workspace_id, world_id)

        event = InventoryChanged(
            event_id=f"evt_{uuid7()}",
            world_id=world_id,
            workspace_id=workspace_id,
            entity_type="warehouse",
            entity_id="wh_001",
            warehouse_id="wh_001",
            component_id="comp_001",
            quantity_change=100,
            reason="receipt",
        )

        await service.submit_event(event)

        # Fetch the event
        persisted = await repo.get_event(event.event_id, workspace_id)
        assert persisted is not None
        original_payload = dict(persisted.payload)

        # Verify we cannot mutate the event (no update method exposed)
        assert not hasattr(repo, "update_event"), "Repository exposes update_event"
        assert not hasattr(repo, "delete_event"), "Repository exposes delete_event"

        # Verify the event is still the same
        persisted_again = await repo.get_event(event.event_id, workspace_id)
        assert persisted_again is not None
        assert persisted_again.payload == original_payload

    async def test_versions_immutable_after_creation(
        self, service: WorldStateService, repo: StateRepository
    ) -> None:
        """Verify version records are never mutated."""
        workspace_id = f"ws_{uuid7()}"
        world_id = f"world_{uuid7()}"

        await service.initialize_world(workspace_id, world_id)

        # Get version 1
        version1 = await repo.get_version(world_id, workspace_id, 1)
        assert version1 is not None
        original_source = version1.source
        original_hash = version1.state_hash

        # Submit an event to create version 2
        event = InventoryChanged(
            event_id=f"evt_{uuid7()}",
            world_id=world_id,
            workspace_id=workspace_id,
            entity_type="warehouse",
            entity_id="wh_001",
            warehouse_id="wh_001",
            component_id="comp_001",
            quantity_change=50,
            reason="receipt",
        )
        await service.submit_event(event)

        # Fetch version 1 again, verify it's unchanged
        version1_again = await repo.get_version(world_id, workspace_id, 1)
        assert version1_again is not None
        assert version1_again.source == original_source
        assert version1_again.state_hash == original_hash

        # Verify no mutation methods exist
        assert not hasattr(repo, "update_version"), "Repository exposes update_version"
        assert not hasattr(repo, "mutate_version"), "Repository exposes mutate_version"

    async def test_snapshots_sealed_and_immutable(
        self, service: WorldStateService, repo: StateRepository
    ) -> None:
        """Verify snapshots, once created, are never mutated."""
        workspace_id = f"ws_{uuid7()}"
        world_id = f"world_{uuid7()}"

        await service.initialize_world(workspace_id, world_id)

        # Get genesis snapshot
        snapshot = await repo.get_latest_snapshot(world_id, workspace_id)
        assert snapshot is not None
        original_hash = snapshot.state_hash
        original_version = snapshot.version

        # Verify we cannot mutate snapshots
        assert not hasattr(repo, "update_snapshot"), "Repository exposes update_snapshot"
        assert not hasattr(repo, "mutate_snapshot"), "Repository exposes mutate_snapshot"
        assert not hasattr(repo, "delete_snapshot"), "Repository exposes delete_snapshot"

        # Fetch snapshot again, verify it's unchanged
        snapshot_again = await repo.get_latest_snapshot(world_id, workspace_id)
        assert snapshot_again is not None
        assert snapshot_again.state_hash == original_hash
        assert snapshot_again.version == original_version

    async def test_workspace_isolation_in_repository_queries(
        self, service: WorldStateService, repo: StateRepository
    ) -> None:
        """Verify repository queries are workspace-scoped."""
        ws_a = f"ws_a_{uuid7()}"
        ws_b = f"ws_b_{uuid7()}"
        world_a = f"world_a_{uuid7()}"
        world_b = f"world_b_{uuid7()}"

        # Initialize states in different workspaces
        await service.initialize_world(ws_a, world_a)
        await service.initialize_world(ws_b, world_b)

        # Fetch states, verify they remain isolated
        state_a = await repo.get_latest(ws_a, world_a)
        state_b = await repo.get_latest(ws_b, world_b)

        assert state_a is not None and state_b is not None
        assert state_a.workspace_id == ws_a
        assert state_b.workspace_id == ws_b
        assert state_a.world_id == world_a
        assert state_b.world_id == world_b
        assert state_a.metadata.get("state_hash") != state_b.metadata.get("state_hash")

    async def test_lineage_forms_dag_no_cycles(
        self, service: WorldStateService, repo: StateRepository
    ) -> None:
        """Verify version lineage is acyclic (no circular parent references)."""
        workspace_id = f"ws_{uuid7()}"
        world_id = f"world_{uuid7()}"

        await service.initialize_world(workspace_id, world_id)

        # Submit events to create a chain
        for i in range(3):
            event = InventoryChanged(
                event_id=f"evt_{uuid7()}",
                world_id=world_id,
                workspace_id=workspace_id,
                entity_type="warehouse",
                entity_id=f"wh_{i:03d}",
                warehouse_id=f"wh_{i:03d}",
                component_id="comp_001",
                quantity_change=10 * (i + 1),
                reason="receipt",
            )
            await service.submit_event(event)

        # Walk the lineage chain and verify no cycles
        all_versions = await repo.get_versions(world_id, workspace_id)
        assert len(all_versions) == 4  # genesis + 3 events

        # Build lineage map
        by_id = {v.version_id: v for v in all_versions}
        visited = set()

        def check_lineage(version_id: str | None) -> int:
            """Recursively check lineage and count hops."""
            if version_id is None:
                return 0
            if version_id in visited:
                raise AssertionError(f"Cycle detected at {version_id}")
            if version_id not in by_id:
                return 0

            visited.add(version_id)
            parent_id = by_id[version_id].parent_version_id
            depth = 1 + check_lineage(parent_id)
            return depth

        # Check each version
        for version in all_versions:
            visited.clear()
            depth = check_lineage(version.version_id)
            assert depth >= 1, f"Version {version.version_id} has no hops"
