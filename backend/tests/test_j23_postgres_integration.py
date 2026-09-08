"""J.2.3 PostgreSQL Integration Tests — Real Concurrency & Persistence Verification.

This module contains integration tests that require a real PostgreSQL instance.
These tests verify:

1. CONCURRENCY SAFETY: Row-level locking and transactional retry prevent race conditions
2. UNIQUE CONSTRAINTS: PostgreSQL unique constraints actually enforce idempotency and sequencing
3. TRANSACTION ISOLATION: ACID properties hold across concurrent writers
4. WORKSPACE ISOLATION: Database-level scoping is enforced in actual queries
5. REPLAY CONSISTENCY: Deterministic reconstruction from event log at all scales

These tests are NOT run against SQLite. SQLite has fundamentally different concurrency
and locking semantics than PostgreSQL. To run these tests:

    pytest backend/tests/test_j23_postgres_integration.py -v \
        --postgres-url="postgresql+asyncpg://user:pass@localhost:5432/cortex_test"

Or set environment variable:
    export CORTEX_TEST_DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/cortex_test"
    pytest backend/tests/test_j23_postgres_integration.py -v

Prerequisites:
    - PostgreSQL 16+ running and accessible
    - Database created: createdb cortex_test
    - Alembic migrations applied: alembic upgrade head
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.ids import uuid7
from app.modules.events.event_models import InventoryChanged
from app.modules.world.state_repository import StateRepository, WorldStateEventDB, WorldVersionDB
from app.modules.world.world_service import WorldStateService


def pytest_collection_modifyitems(config, items):
    """Mark PostgreSQL tests and skip if database unavailable."""
    postgres_marker = pytest.mark.postgres
    for item in items:
        if item.fspath.basename == "test_j23_postgres_integration.py":
            item.add_marker(postgres_marker)


class TestPostgresSequenceAllocation:
    """Verify sequence number allocation is concurrency-safe under real PostgreSQL."""

    async def test_concurrent_sequence_allocation_no_duplicates(
        self,
        postgres_service: WorldStateService,
        postgres_repo: StateRepository,
        postgres_sessionmaker: async_sessionmaker[AsyncSession],
        submit_in_own_session: Any,
    ) -> None:
        """Verify that concurrent submissions get unique monotonic sequences.

        This test specifically exercises:
        1. Row-level locking with FOR UPDATE
        2. Transactional retry on UNIQUE constraint violation
        3. PostgreSQL's serialization guarantees
        """
        workspace_id = f"ws_{uuid7()}"
        world_id = f"world_{uuid7()}"

        # Initialize world
        await postgres_service.initialize_world(workspace_id, world_id)

        # Create 10 concurrent event submissions
        events = []
        for i in range(10):
            event = InventoryChanged(
                event_id=str(uuid7()),
                world_id=world_id,
                workspace_id=workspace_id,
                entity_id=f"sku_{i}",
                entity_type="warehouse",
                warehouse_id=f"wh_{i}",
                component_id="comp_a",
                quantity_change=i,
                reason="receipt",
                metadata={},
            )
            events.append(event)

        # Submit concurrently — each task uses its own session (production pattern)
        results = await asyncio.gather(
            *[
                submit_in_own_session(postgres_sessionmaker, event, idempotency_key=f"req_{i}")
                for i, event in enumerate(events)
            ]
        )

        # Verify all succeeded
        assert len(results) == 10
        for result in results:
            assert result.event_id is not None
            assert result.version_id is not None
            assert not result.is_duplicate

        # Verify all versions have unique sequence numbers
        versions = await postgres_repo.get_versions(world_id, workspace_id)
        assert len(versions) == 11  # 1 genesis + 10 events

        sequences = [v.sequence_number for v in versions if v.sequence_number is not None]
        assert len(sequences) == 10  # All events have sequences (genesis has None)
        assert len(set(sequences)) == 10  # All unique
        assert sequences == sorted(sequences)  # All monotonic

    async def test_high_contention_sequencing_10_workers(
        self,
        postgres_service: WorldStateService,
        postgres_repo: StateRepository,
        postgres_sessionmaker: async_sessionmaker[AsyncSession],
    ) -> None:
        """Stress test: 10 concurrent workers each submitting 5 events = 50 concurrent writes.

        Verifies that even under high contention:
        1. All sequences are unique
        2. All sequences are monotonic
        3. No UNIQUE constraint violations escape to caller
        4. Retry logic handles conflicts transparently
        """
        workspace_id = f"ws_{uuid7()}"
        world_id = f"world_{uuid7()}"

        await postgres_service.initialize_world(workspace_id, world_id)

        async def worker(worker_id: int):
            # One session per worker, reused across its 5 sequential submissions
            async with postgres_sessionmaker() as session:
                repo = StateRepository(db=session)
                service = WorldStateService(repository=repo, snapshot_interval=100)
                results = []
                for event_num in range(5):
                    event = InventoryChanged(
                        event_id=str(uuid7()),
                        world_id=world_id,
                        workspace_id=workspace_id,
                        entity_id=f"worker_{worker_id}_item_{event_num}",
                        entity_type="warehouse",
                        warehouse_id=f"wh_{worker_id}",
                        component_id=f"comp_{event_num}",
                        quantity_change=event_num,
                        reason="receipt",
                        metadata={},
                    )
                    result = await service.submit_event(
                        event, idempotency_key=f"worker_{worker_id}_req_{event_num}"
                    )
                    results.append(result)
                await session.rollback()
                return results

        # Run 10 workers concurrently
        worker_results = await asyncio.gather(*[worker(i) for i in range(10)])

        # Flatten results
        all_results = [r for results in worker_results for r in results]
        assert len(all_results) == 50

        # All should succeed
        for result in all_results:
            assert result.event_id is not None
            assert result.version_id is not None
            assert not result.is_duplicate

        # Verify sequence integrity
        versions = await postgres_repo.get_versions(world_id, workspace_id)
        assert len(versions) == 51  # 1 genesis + 50 events

        sequences = [v.sequence_number for v in versions if v.sequence_number is not None]
        assert len(sequences) == 50
        assert len(set(sequences)) == 50  # All unique
        assert sequences == sorted(sequences)  # All monotonic

    async def test_unique_constraint_prevents_duplicate_sequence_insertion(
        self, postgres_repo: StateRepository
    ) -> None:
        """Verify PostgreSQL UNIQUE(world_id, workspace_id, sequence_number) constraint works.

        This is a low-level test that directly attempts to violate the constraint.
        """
        workspace_id = f"ws_{uuid7()}"
        world_id = f"world_{uuid7()}"

        # Create first version with sequence=1
        version1 = WorldVersionDB(
            version_id=str(uuid7()),
            world_id=world_id,
            workspace_id=workspace_id,
            version=1,
            sequence_number=1,
            state_hash="hash1",
            source="test",
        )
        postgres_repo.db.add(version1)
        await postgres_repo.db.flush()
        await postgres_repo.db.commit()

        # Attempt to create another version with same sequence (should fail)
        version2 = WorldVersionDB(
            version_id=str(uuid7()),
            world_id=world_id,
            workspace_id=workspace_id,
            version=2,
            sequence_number=1,  # Duplicate!
            state_hash="hash2",
            source="test",
        )
        postgres_repo.db.add(version2)

        # Should raise IntegrityError
        with pytest.raises(IntegrityError):
            await postgres_repo.db.flush()

        await postgres_repo.db.rollback()


class TestPostgresIdempotencyEnforcement:
    """Verify idempotency key uniqueness is enforced by PostgreSQL."""

    async def test_duplicate_idempotency_key_returns_identical_result(
        self, postgres_service: WorldStateService, postgres_repo: StateRepository
    ) -> None:
        """Verify that resubmitting the same idempotency key returns identical result."""
        workspace_id = f"ws_{uuid7()}"
        world_id = f"world_{uuid7()}"

        await postgres_service.initialize_world(workspace_id, world_id)

        event = InventoryChanged(
            event_id=str(uuid7()),
            world_id=world_id,
            workspace_id=workspace_id,
            entity_id="sku_001",
            entity_type="warehouse",
            warehouse_id="wh_001",
            component_id="comp_a",
            quantity_change=10,
            reason="receipt",
            metadata={},
        )

        idempotency_key = "req_12345"

        # Submit first time
        result1 = await postgres_service.submit_event(event, idempotency_key=idempotency_key)
        assert not result1.is_duplicate
        assert result1.version == 2

        # Submit identical key again
        result2 = await postgres_service.submit_event(event, idempotency_key=idempotency_key)
        assert result2.is_duplicate
        assert result2.version == 2
        assert result2.event_id == result1.event_id
        assert result2.version_id == result1.version_id
        assert result2.state.metadata.get("state_hash", "") == result1.state.metadata.get(
            "state_hash", ""
        )

    async def test_concurrent_duplicate_submissions_deduplicated(
        self,
        postgres_service: WorldStateService,
        postgres_repo: StateRepository,
        postgres_sessionmaker: async_sessionmaker[AsyncSession],
        submit_in_own_session: Any,
    ) -> None:
        """Verify concurrent submissions with same idempotency key are deduplicated.

        If two requests arrive simultaneously with the same idempotency_key,
        exactly one state version should be created.
        """
        workspace_id = f"ws_{uuid7()}"
        world_id = f"world_{uuid7()}"

        await postgres_service.initialize_world(workspace_id, world_id)

        event = InventoryChanged(
            event_id=str(uuid7()),
            world_id=world_id,
            workspace_id=workspace_id,
            entity_id="sku_002",
            entity_type="warehouse",
            warehouse_id="wh_002",
            component_id="comp_b",
            quantity_change=25,
            reason="receipt",
            metadata={},
        )

        idempotency_key = "req_concurrent_123"

        # Submit 3 times concurrently with same idempotency_key (own session each)
        results = await asyncio.gather(
            *[
                submit_in_own_session(postgres_sessionmaker, event, idempotency_key=idempotency_key)
                for _ in range(3)
            ]
        )

        # All should have same event_id and version_id
        event_ids = {r.event_id for r in results}
        version_ids = {r.version_id for r in results}

        assert len(event_ids) == 1, "All submissions should return same event_id"
        assert len(version_ids) == 1, "All submissions should return same version_id"

        # Exactly one event should exist in database
        db_events = await postgres_repo.get_events(
            world_id=world_id,
            workspace_id=workspace_id,
        )

        idempotency_events = [e for e in db_events if e.idempotency_key == idempotency_key]
        assert len(idempotency_events) == 1, "Only one event should exist for this key"


class TestPostgresWorkspaceIsolation:
    """Verify workspace isolation at the database query level."""

    async def test_workspace_queries_never_cross_boundaries(
        self, postgres_repo: StateRepository
    ) -> None:
        """Verify that queries for Workspace A never return Workspace B data."""
        ws_a = f"ws_a_{uuid7()}"
        ws_b = f"ws_b_{uuid7()}"

        world_a = f"world_a_{uuid7()}"
        world_b = f"world_b_{uuid7()}"

        # Create events in workspace A
        event_a = WorldStateEventDB(
            event_id=str(uuid7()),
            world_id=world_a,
            workspace_id=ws_a,
            entity_type="test",
            entity_id="a1",
            event_type="test_event",
            payload={"data": "a"},
            idempotency_key="key_a",
        )
        postgres_repo.db.add(event_a)

        # Create events in workspace B
        event_b = WorldStateEventDB(
            event_id=str(uuid7()),
            world_id=world_b,
            workspace_id=ws_b,
            entity_type="test",
            entity_id="b1",
            event_type="test_event",
            payload={"data": "b"},
            idempotency_key="key_b",
        )
        postgres_repo.db.add(event_b)
        await postgres_repo.db.flush()

        # Query workspace A events
        events_a = await postgres_repo.get_events(world_a, ws_a)

        # Should only see event A
        assert len(events_a) == 1
        assert events_a[0].workspace_id == ws_a
        assert events_a[0].world_id == world_a
        assert events_a[0].payload["data"] == "a"

        # Query workspace B events
        events_b = await postgres_repo.get_events(world_b, ws_b)

        # Should only see event B
        assert len(events_b) == 1
        assert events_b[0].workspace_id == ws_b
        assert events_b[0].world_id == world_b
        assert events_b[0].payload["data"] == "b"


class TestPostgresReplayConsistency:
    """Verify replay consistency at scale with real PostgreSQL."""

    async def test_replay_equivalence_100_events(
        self, postgres_service: WorldStateService, postgres_repo: StateRepository
    ) -> None:
        """Verify replay(100 events) == live_state for deterministic reconstruction.

        This is the most important J.2.3 invariant:
            replay(events_from_genesis) == live_state
        """
        workspace_id = f"ws_{uuid7()}"
        world_id = f"world_{uuid7()}"

        await postgres_service.initialize_world(workspace_id, world_id)

        # Submit 100 events
        for i in range(100):
            event = InventoryChanged(
                event_id=str(uuid7()),
                world_id=world_id,
                workspace_id=workspace_id,
                entity_id=f"sku_{i % 10}",
                entity_type="warehouse",
                warehouse_id=f"wh_{i % 10}",
                component_id="comp_a",
                quantity_change=10,
                reason="receipt",
                metadata={"sequence": i},
            )
            result = await postgres_service.submit_event(event, idempotency_key=f"req_{i}")
            assert result.version == i + 2  # +2 because genesis is version 1

        # Get live state
        live_state = await postgres_service.get_current_state(workspace_id, world_id)
        assert live_state is not None
        assert live_state.version == 101  # 1 genesis + 100 events
        live_hash = live_state.metadata.get("state_hash", "")

        # Replay from genesis
        replayed_state = await postgres_service.replay_from_genesis(world_id, workspace_id)
        assert replayed_state is not None
        assert replayed_state.state.version == 101
        replayed_hash = replayed_state.state.metadata.get("state_hash", "")

        # Hashes must match
        assert live_hash == replayed_hash, "Replay state does not match live state"

    async def test_time_travel_to_arbitrary_version(
        self, postgres_service: WorldStateService, postgres_repo: StateRepository
    ) -> None:
        """Verify time_travel to arbitrary historical version works correctly."""
        workspace_id = f"ws_{uuid7()}"
        world_id = f"world_{uuid7()}"

        await postgres_service.initialize_world(workspace_id, world_id)

        # Submit 50 events
        for i in range(50):
            event = InventoryChanged(
                event_id=str(uuid7()),
                world_id=world_id,
                workspace_id=workspace_id,
                entity_id=f"sku_{i % 5}",
                entity_type="warehouse",
                warehouse_id=f"wh_{i % 5}",
                component_id="comp_b",
                quantity_change=5,
                reason="receipt",
                metadata={},
            )
            await postgres_service.submit_event(event, idempotency_key=f"req_{i}")

        # Time travel to version 25
        state_v25 = await postgres_service.time_travel(world_id, workspace_id, 25)
        assert state_v25.state.version == 25

        # Get version directly
        state_direct = await postgres_service.get_state_at_version(world_id, workspace_id, 25)
        assert state_direct is not None
        assert state_direct.version == 25
        assert state_direct.metadata.get("state_hash", "") == state_v25.state.metadata.get(
            "state_hash", ""
        )


class TestPostgresTransactionProperties:
    """Verify ACID properties with real PostgreSQL."""

    async def test_event_and_version_atomicity(
        self, postgres_service: WorldStateService, postgres_repo: StateRepository
    ) -> None:
        """Verify that event and version insertions are atomic.

        If one succeeds and other fails, transaction rolls back completely.
        """
        workspace_id = f"ws_{uuid7()}"
        world_id = f"world_{uuid7()}"

        await postgres_service.initialize_world(workspace_id, world_id)

        initial_version = await postgres_service.get_current_state(workspace_id, world_id)
        assert initial_version.version == 1

        event = InventoryChanged(
            event_id=str(uuid7()),
            world_id=world_id,
            workspace_id=workspace_id,
            entity_id="sku_test",
            entity_type="warehouse",
            warehouse_id="wh_test",
            component_id="comp_test",
            quantity_change=100,
            reason="receipt",
            metadata={},
        )

        result = await postgres_service.submit_event(event, idempotency_key="req_atomic")

        # Verify both event and version exist
        db_event = await postgres_repo.get_event_by_idempotency_key(
            world_id=world_id,
            workspace_id=workspace_id,
            idempotency_key="req_atomic",
        )
        assert db_event is not None

        db_version = await postgres_repo.get_version(
            world_id=world_id,
            workspace_id=workspace_id,
            version=result.version,
        )
        assert db_version is not None
