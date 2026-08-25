"""Test Idempotency — J.2.3 Repository Hardening.

Tests that idempotency keys prevent duplicate state mutations on resubmission.

Invariants verified:
1. Same event + same idempotency key → identical result, no duplicate state
2. Different idempotency key + same event → new version
3. Network retries are correctly deduplicated
4. Idempotency works across concurrent submissions
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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


class TestIdempotency:
    """Verify idempotency prevents duplicate state mutations."""

    async def test_resubmit_same_key_same_result(
        self, service: WorldStateService, repo: StateRepository
    ) -> None:
        """Verify resubmitting with same key produces identical result."""
        workspace_id = f"ws_{uuid7()}"
        world_id = f"world_{uuid7()}"
        idempotency_key = "test-key-001"

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

        # Submit first time
        result1 = await service.submit_event(event, idempotency_key=idempotency_key)
        assert result1.is_duplicate is False
        assert result1.version == 2

        # Submit again with same key
        result2 = await service.submit_event(event, idempotency_key=idempotency_key)
        assert result2.is_duplicate is True
        assert result2.version == 2  # Same version as first
        assert result2.event_id == result1.event_id  # Same event
        assert result2.state.metadata.get("state_hash") == result1.state.metadata.get("state_hash")  # Same state

        # Verify no new version was created
        final_state = await repo.get_latest(workspace_id, world_id)
        assert final_state is not None
        assert final_state.version == 2  # Still version 2, not 3

        # Verify the event appears only once in the log
        events = await repo.get_events(world_id, workspace_id)
        matching_events = [e for e in events if e.event_id == event.event_id]
        assert len(matching_events) == 1, "Event appears more than once in log"

    async def test_different_key_same_event_creates_new_version(
        self, service: WorldStateService, repo: StateRepository
    ) -> None:
        """Verify different idempotency keys create separate versions."""
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

        # Submit with key A
        result_a = await service.submit_event(event, idempotency_key="key-a")
        assert result_a.version == 2
        assert result_a.is_duplicate is False

        # Submit with key B (same event payload, fresh event_id — event log is append-only)
        event_b = replace(event, event_id=f"evt_{uuid7()}")
        result_b = await service.submit_event(event_b, idempotency_key="key-b")
        assert result_b.version == 3  # New version
        assert result_b.is_duplicate is False
        assert result_b.event_id == event_b.event_id

        # Verify final state is version 3
        final_state = await repo.get_latest(workspace_id, world_id)
        assert final_state is not None
        assert final_state.version == 3

    async def test_idempotency_key_from_event_metadata(
        self, service: WorldStateService, repo: StateRepository
    ) -> None:
        """Verify idempotency key can be extracted from event metadata."""
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
            metadata={"idempotency_key": "metadata-key-001"},
        )

        # Submit first time (idempotency key from event metadata)
        result1 = await service.submit_event(event)
        assert result1.version == 2
        assert result1.is_duplicate is False

        # Create new event object with same metadata key
        event2 = InventoryChanged(
            event_id=f"evt_{uuid7()}",
            world_id=world_id,
            workspace_id=workspace_id,
            entity_type="warehouse",
            entity_id="wh_001",
            warehouse_id="wh_001",
            component_id="comp_001",
            quantity_change=100,
            reason="receipt",
            metadata={"idempotency_key": "metadata-key-001"},
        )

        # Submit again with same metadata key
        result2 = await service.submit_event(event2)
        assert result2.is_duplicate is True
        assert result2.version == 2  # Same version

    async def test_network_retry_simulation(
        self, service: WorldStateService, repo: StateRepository
    ) -> None:
        """Simulate network timeout and retry with same idempotency key."""
        workspace_id = f"ws_{uuid7()}"
        world_id = f"world_{uuid7()}"
        idempotency_key = "network-retry-test"

        await service.initialize_world(workspace_id, world_id)

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

        # First attempt
        result1 = await service.submit_event(event, idempotency_key=idempotency_key)
        version_after_first = result1.version

        # Simulate network timeout and retry
        # (in real code, the client would timeout and retry with same key)
        result2 = await service.submit_event(event, idempotency_key=idempotency_key)

        # Verify retry returns same result as first attempt
        assert result2.version == version_after_first
        assert result2.is_duplicate is True
        assert result2.event_id == result1.event_id

        # Verify only one event in the log
        events = await repo.get_events(world_id, workspace_id)
        assert len(events) == 1  # Only the initial event, no duplicate

    async def test_idempotency_concurrent_submission(
        self,
        postgres_service: WorldStateService,
        postgres_sessionmaker: async_sessionmaker[AsyncSession],
        submit_in_own_session: Any,
    ) -> None:
        """Verify idempotency works with concurrent submissions (same key).

        Requires PostgreSQL: each concurrent task needs its own session, and
        the advisory world write lock (no-op on SQLite) serializes writers.
        Skips automatically when PostgreSQL is unavailable.
        """
        workspace_id = f"ws_{uuid7()}"
        world_id = f"world_{uuid7()}"
        idempotency_key = "concurrent-key"

        await postgres_service.initialize_world(workspace_id, world_id)

        event = InventoryChanged(
            event_id=str(uuid7()),
            world_id=world_id,
            workspace_id=workspace_id,
            entity_type="warehouse",
            entity_id="wh_001",
            warehouse_id="wh_001",
            component_id="comp_001",
            quantity_change=75,
            reason="receipt",
        )

        # Submit the same event with same key, concurrently (own session each)
        results = await asyncio.gather(
            *[
                submit_in_own_session(postgres_sessionmaker, event, idempotency_key)
                for _ in range(3)
            ],
            return_exceptions=False,
        )

        # All three should get the same result
        versions = [r.version for r in results]
        assert all(v == versions[0] for v in versions), f"Versions differ: {versions}"
        assert versions[0] == 2  # Should be version 2

        duplicates = [r.is_duplicate for r in results]
        # First one is not a duplicate, others are
        assert duplicates.count(False) == 1
        assert duplicates.count(True) == 2

        # Final state should be version 2
        final_state = await postgres_service.get_current_state(workspace_id, world_id)
        assert final_state is not None
        assert final_state.version == 2

    async def test_idempotency_key_persisted_in_event(
        self, service: WorldStateService, repo: StateRepository
    ) -> None:
        """Verify idempotency key is stored in event metadata for audit."""
        workspace_id = f"ws_{uuid7()}"
        world_id = f"world_{uuid7()}"
        idempotency_key = "audit-test-key"

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

        await service.submit_event(event, idempotency_key=idempotency_key)

        # Fetch the event from repository
        persisted = await repo.get_event(event.event_id, workspace_id)
        assert persisted is not None

        # Verify idempotency key is in metadata
        assert "idempotency_key" in persisted.extra_metadata
        assert persisted.extra_metadata["idempotency_key"] == idempotency_key
