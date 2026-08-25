"""Test Concurrency & Sequencing — J.2.3 Repository Hardening.

Tests that monotonic sequencing via sequence_number prevents concurrent write conflicts.

Invariants verified:
1. Duplicate sequence numbers are rejected
2. Concurrent writers are serialized
3. Version numbers remain monotonic (1, 2, 3, ...) regardless of concurrency
4. No race conditions or out-of-order versions
"""

from __future__ import annotations

import asyncio
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


class TestConcurrencyAndSequencing:
    """Verify monotonic sequencing prevents concurrent write conflicts.

    The concurrent tests require PostgreSQL: the shared SQLite test session
    cannot run concurrent transactions, and the advisory world write lock
    (which serializes writers) is a no-op on SQLite. They skip automatically
    when PostgreSQL is unavailable; the SQLite suite retains the sequential
    invariants (duplicate-sequence rejection, per-world isolation).
    """

    async def test_concurrent_appends_remain_serialized(
        self,
        postgres_service: WorldStateService,
        postgres_sessionmaker: async_sessionmaker[AsyncSession],
        submit_in_own_session: Any,
    ) -> None:
        """Verify dual concurrent submissions to same world are serialized."""
        workspace_id = f"ws_{uuid7()}"
        world_id = f"world_{uuid7()}"

        await postgres_service.initialize_world(workspace_id, world_id)

        # Create two events
        event1 = InventoryChanged(
            event_id=str(uuid7()),
            world_id=world_id,
            workspace_id=workspace_id,
            entity_type="warehouse",
            entity_id="wh_001",
            warehouse_id="wh_001",
            component_id="comp_a",
            quantity_change=100,
            reason="receipt",
        )

        event2 = InventoryChanged(
            event_id=str(uuid7()),
            world_id=world_id,
            workspace_id=workspace_id,
            entity_type="warehouse",
            entity_id="wh_001",
            warehouse_id="wh_001",
            component_id="comp_b",
            quantity_change=200,
            reason="receipt",
        )

        # Submit both concurrently, each in its own session (like production)
        result1, result2 = await asyncio.gather(
            submit_in_own_session(postgres_sessionmaker, event1, "k1"),
            submit_in_own_session(postgres_sessionmaker, event2, "k2"),
        )

        # Verify versions are sequential (no duplicates, no gaps)
        assert result1.version in (2, 3)
        assert result2.version in (2, 3)
        assert result1.version != result2.version  # Different versions
        assert abs(result1.version - result2.version) == 1  # Sequential

        # Verify final state is version 3
        final_state = await postgres_service.get_current_state(workspace_id, world_id)
        assert final_state is not None
        assert final_state.version == 3

    async def test_high_contention_ordering(
        self,
        postgres_service: WorldStateService,
        postgres_sessionmaker: async_sessionmaker[AsyncSession],
        submit_in_own_session: Any,
    ) -> None:
        """Verify 10 concurrent workers produce perfectly ordered versions."""
        workspace_id = f"ws_{uuid7()}"
        world_id = f"world_{uuid7()}"

        await postgres_service.initialize_world(workspace_id, world_id)

        # Create 10 events
        events = [
            InventoryChanged(
                event_id=str(uuid7()),
                world_id=world_id,
                workspace_id=workspace_id,
                entity_type="warehouse",
                entity_id=f"wh_{i:03d}",
                warehouse_id=f"wh_{i:03d}",
                component_id="comp_001",
                quantity_change=10 * (i + 1),
                reason="receipt",
            )
            for i in range(10)
        ]

        # Submit all concurrently, each in its own session
        results = await asyncio.gather(
            *[
                submit_in_own_session(postgres_sessionmaker, event, f"key_{i}")
                for i, event in enumerate(events)
            ],
            return_exceptions=False,
        )

        # Collect versions
        versions = sorted([r.version for r in results])

        # Verify they are 2..11 (sequential after genesis version 1)
        expected = list(range(2, 12))
        assert versions == expected, f"Expected {expected}, got {versions}"

        # Verify final state is version 11
        final_state = await postgres_service.get_current_state(workspace_id, world_id)
        assert final_state is not None
        assert final_state.version == 11

    async def test_duplicate_sequence_rejected_by_database(
        self,
        postgres_service: WorldStateService,
        postgres_sessionmaker: async_sessionmaker[AsyncSession],
    ) -> None:
        """Verify database constraint prevents duplicate sequence numbers.

        The unique (world_id, workspace_id, sequence_number) constraint is a
        PostgreSQL partial index (migration 010) — it does not exist on the
        SQLite test schema, so this test runs against PostgreSQL and skips
        when it is unavailable. Note: genesis carries sequence_number=None,
        so the constraint only governs non-null event sequences.
        """
        from datetime import UTC, datetime

        from sqlalchemy.exc import IntegrityError

        from app.modules.world.state_repository import WorldVersionDB

        workspace_id = f"ws_{uuid7()}"
        world_id = f"world_{uuid7()}"

        # Initialize
        await postgres_service.initialize_world(workspace_id, world_id)

        def _record(version: int) -> WorldVersionDB:
            return WorldVersionDB(
                version_id=str(uuid7()),
                world_id=world_id,
                workspace_id=workspace_id,
                version=version,
                sequence_number=1,
                graph_version=0,
                state_hash="fakehash",
                event_id=None,
                parent_version_id=None,
                source="test",
                created_at=datetime.now(UTC),
                extra_metadata={},
            )

        # Insert the first record with sequence_number=1 and commit
        async with postgres_sessionmaker() as session:
            session.add(_record(99))
            await session.flush()
            await session.commit()

        # Second record with the same sequence_number must violate the constraint
        async with postgres_sessionmaker() as session:
            session.add(_record(100))
            with pytest.raises(IntegrityError):
                await session.flush()
            await session.rollback()

    async def test_isolation_between_worlds(
        self,
        postgres_service: WorldStateService,
        postgres_repo: StateRepository,
        postgres_sessionmaker: async_sessionmaker[AsyncSession],
        submit_in_own_session: Any,
    ) -> None:
        """Verify sequencing is per-world, not global."""
        workspace_id = f"ws_{uuid7()}"
        world_a = f"world_a_{uuid7()}"
        world_b = f"world_b_{uuid7()}"

        # Initialize both worlds
        await postgres_service.initialize_world(workspace_id, world_a)
        await postgres_service.initialize_world(workspace_id, world_b)

        # Create events for both worlds
        events_a = [
            InventoryChanged(
                event_id=str(uuid7()),
                world_id=world_a,
                workspace_id=workspace_id,
                entity_type="warehouse",
                entity_id=f"wh_{i:03d}",
                warehouse_id=f"wh_{i:03d}",
                component_id="comp_001",
                quantity_change=10,
                reason="receipt",
            )
            for i in range(3)
        ]

        events_b = [
            InventoryChanged(
                event_id=str(uuid7()),
                world_id=world_b,
                workspace_id=workspace_id,
                entity_type="warehouse",
                entity_id=f"wh_{i:03d}",
                warehouse_id=f"wh_{i:03d}",
                component_id="comp_001",
                quantity_change=20,
                reason="receipt",
            )
            for i in range(2)
        ]

        # Submit all concurrently (mixed), each in its own session
        all_events = [(world_a, e) for e in events_a] + [(world_b, e) for e in events_b]
        results = await asyncio.gather(
            *[
                submit_in_own_session(
                    postgres_sessionmaker, event, idempotency_key=f"key_{idx}"
                )
                for idx, (world, event) in enumerate(all_events)
            ],
            return_exceptions=False,
        )

        # Collect versions by world
        versions_a = sorted([r.version for r in results[:3]])
        versions_b = sorted([r.version for r in results[3:]])

        # World A should have versions 2, 3, 4 (genesis is 1)
        # World B should have versions 2, 3 (genesis is 1)
        assert versions_a == [2, 3, 4]
        assert versions_b == [2, 3]

        # Verify final states
        final_a = await postgres_repo.get_latest(workspace_id, world_a)
        final_b = await postgres_repo.get_latest(workspace_id, world_b)

        assert final_a is not None and final_a.version == 4
        assert final_b is not None and final_b.version == 3
