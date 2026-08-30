"""V2 World State Persistence Tests — prove the real WorldStateService path.

These tests validate that the spine's persistent world state path works
end-to-end with a real SQLite-backed WorldStateService:

1. Genesis initialization creates version 1
2. Entity ingestion persists events to the database
3. Version progression is monotonic (1, 2, 3, ...)
4. Idempotency keys prevent duplicate ingestion
5. Full spine run with WorldStateService persists events
6. ExecutionOutcome events are persisted
7. Workspace isolation — events in workspace A not visible in workspace B
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.events.event_models import EntityIngested, ExecutionOutcome
from app.modules.nexus_spine.canonical_schema import (
    CanonicalDataset,
    CanonicalTable,
    EntityType,
)
from app.modules.nexus_spine.spine_orchestrator import RealDataSpine
from app.modules.world.state_repository import StateRepository, WorldStateEventDB
from app.modules.world.world_service import WorldStateService

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_service(session: AsyncSession) -> WorldStateService:
    """Create a WorldStateService from a test session."""
    repo = StateRepository(db=session)
    return WorldStateService(repository=repo, snapshot_interval=100)


def _make_entity_ingested(
    world_id: str,
    workspace_id: str,
    entity_type: str = "SUPPLIER",
    entity_id: str = "S1",
) -> EntityIngested:
    return EntityIngested(
        event_id=f"evt_test_{workspace_id}_{entity_id.lower()}",
        world_id=world_id,
        workspace_id=workspace_id,
        entity_type=entity_type,
        entity_id=entity_id,
        attributes={"name": "Test Supplier", "state": "SP"},
        source_file="suppliers.csv",
    )


def _make_execution_outcome(
    world_id: str,
    workspace_id: str,
    plan_id: str = "PLAN_001",
) -> ExecutionOutcome:
    return ExecutionOutcome(
        event_id=f"evt_outcome_{plan_id.lower()}",
        world_id=world_id,
        workspace_id=workspace_id,
        entity_type="EXECUTION",
        entity_id=plan_id,
        plan_id=plan_id,
        action="DUAL_SOURCE",
        result_status="EXECUTED",
    )


def _build_small_dataset() -> CanonicalDataset:
    """Minimal dataset for spine integration test."""
    ds = CanonicalDataset(workspace_id="ws_persist", organization_id="org_persist")
    ds.tables[EntityType.SUPPLIER] = CanonicalTable(
        entity_type=EntityType.SUPPLIER,
        rows=[
            {"supplier_id": "S1", "state": "SP", "_source_file": "suppliers.csv", "_source_row": 1},
            {"supplier_id": "S2", "state": "RJ", "_source_file": "suppliers.csv", "_source_row": 2},
        ],
        column_types={"supplier_id": "str", "state": "str"},
        source_file="suppliers.csv",
    )
    ds.tables[EntityType.CUSTOMER] = CanonicalTable(
        entity_type=EntityType.CUSTOMER,
        rows=[
            {"customer_id": "C1", "state": "SP", "_source_file": "customers.csv", "_source_row": 1},
        ],
        column_types={"customer_id": "str", "state": "str"},
        source_file="customers.csv",
    )
    ds.tables[EntityType.ORDER] = CanonicalTable(
        entity_type=EntityType.ORDER,
        rows=[
            {"order_id": "O1", "customer_id": "C1", "price": 100.0, "_source_file": "orders.csv", "_source_row": 1},
        ],
        column_types={"order_id": "str", "customer_id": "str", "price": "float"},
        source_file="orders.csv",
    )
    ds.tables[EntityType.ORDER_ITEM] = CanonicalTable(
        entity_type=EntityType.ORDER_ITEM,
        rows=[
            {"item_id": "I1", "order_id": "O1", "supplier_id": "S1", "price": 100.0, "_source_file": "items.csv", "_source_row": 1},
        ],
        column_types={"item_id": "str", "order_id": "str", "supplier_id": "str", "price": "float"},
        source_file="items.csv",
    )
    return ds


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: Genesis initialization
# ─────────────────────────────────────────────────────────────────────────────


class TestGenesisInitialization:
    """initialize_world() creates a genesis state at version 1."""

    async def test_initialize_world_creates_genesis(self, db_session: AsyncSession):
        service = _make_service(db_session)
        state = await service.initialize_world(
            workspace_id="ws_genesis",
            world_id="world_genesis",
        )
        assert state.version == 1
        assert state.workspace_id == "ws_genesis"
        assert state.world_id == "world_genesis"

    async def test_double_initialization_raises(self, db_session: AsyncSession):
        service = _make_service(db_session)
        await service.initialize_world(
            workspace_id="ws_double",
            world_id="world_double",
        )
        with pytest.raises(ValueError, match="already initialized"):
            await service.initialize_world(
                workspace_id="ws_double",
                world_id="world_double",
            )


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: Entity ingestion persists events
# ─────────────────────────────────────────────────────────────────────────────


class TestEntityIngestionPersistence:
    """Submit EntityIngested events and verify they persist."""

    async def test_entity_ingestion_persists_events(self, db_session: AsyncSession):
        service = _make_service(db_session)
        await service.initialize_world(workspace_id="ws_ingest", world_id="world_ingest")

        event = _make_entity_ingested("world_ingest", "ws_ingest")
        result = await service.submit_event(
            event, idempotency_key="ws_ingest.SUPPLIER.S1",
        )

        assert result.version == 2  # genesis=1, first event=2
        assert result.is_duplicate is False
        assert result.event_id == event.event_id

        # Verify event is in the database
        stmt = select(WorldStateEventDB).where(
            WorldStateEventDB.world_id == "world_ingest",
            WorldStateEventDB.workspace_id == "ws_ingest",
        )
        rows = (await db_session.execute(stmt)).scalars().all()
        assert len(rows) == 1
        assert rows[0].event_type == "entity_ingested"
        assert rows[0].entity_type == "SUPPLIER"
        assert rows[0].entity_id == "S1"


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: Version monotonic progression
# ─────────────────────────────────────────────────────────────────────────────


class TestVersionMonotonicProgression:
    """N events produce strictly increasing versions 2, 3, ..., N+1."""

    async def test_version_monotonic_progression(self, db_session: AsyncSession):
        service = _make_service(db_session)
        await service.initialize_world(workspace_id="ws_mono", world_id="world_mono")

        versions: list[int] = []
        for i in range(1, 6):
            event = _make_entity_ingested(
                "world_mono", "ws_mono",
                entity_id=f"S{i}",
            )
            result = await service.submit_event(
                event, idempotency_key=f"ws_mono.SUPPLIER.S{i}",
            )
            versions.append(result.version)

        # Genesis is version 1, events produce 2, 3, 4, 5, 6
        assert versions == [2, 3, 4, 5, 6]

    async def test_current_state_reflects_latest_version(self, db_session: AsyncSession):
        service = _make_service(db_session)
        await service.initialize_world(workspace_id="ws_latest", world_id="world_latest")

        for i in range(1, 4):
            event = _make_entity_ingested(
                "world_latest", "ws_latest",
                entity_id=f"S{i}",
            )
            await service.submit_event(
                event, idempotency_key=f"ws_latest.SUPPLIER.S{i}",
            )

        state = await service.get_current_state(
            workspace_id="ws_latest", world_id="world_latest",
        )
        assert state is not None
        assert state.version == 4  # genesis(1) + 3 events


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: Idempotency
# ─────────────────────────────────────────────────────────────────────────────


class TestIdempotency:
    """Duplicate idempotency key returns is_duplicate=True, version unchanged."""

    async def test_idempotency_duplicate_rejected(self, db_session: AsyncSession):
        service = _make_service(db_session)
        await service.initialize_world(workspace_id="ws_idem", world_id="world_idem")

        event = _make_entity_ingested("world_idem", "ws_idem")
        idem_key = "ws_idem.SUPPLIER.S1"

        result1 = await service.submit_event(event, idempotency_key=idem_key)
        assert result1.version == 2
        assert result1.is_duplicate is False

        # Submit same key again
        result2 = await service.submit_event(event, idempotency_key=idem_key)
        assert result2.is_duplicate is True
        assert result2.version == result1.version  # version unchanged

    async def test_different_keys_produce_different_versions(self, db_session: AsyncSession):
        service = _make_service(db_session)
        await service.initialize_world(workspace_id="ws_diff", world_id="world_diff")

        e1 = _make_entity_ingested("world_diff", "ws_diff", entity_id="S1")
        e2 = _make_entity_ingested("world_diff", "ws_diff", entity_id="S2")

        r1 = await service.submit_event(e1, idempotency_key="ws_diff.SUPPLIER.S1")
        r2 = await service.submit_event(e2, idempotency_key="ws_diff.SUPPLIER.S2")

        assert r1.version == 2
        assert r2.version == 3
        assert r1.is_duplicate is False
        assert r2.is_duplicate is False


# ─────────────────────────────────────────────────────────────────────────────
# Test 5: Spine with real WorldStateService
# ─────────────────────────────────────────────────────────────────────────────


class TestSpineWithRealWorldService:
    """Full spine run with WorldStateService — events persist to DB."""

    async def test_spine_with_real_world_service(self, db_session: AsyncSession):
        service = _make_service(db_session)
        dataset = _build_small_dataset()

        spine = RealDataSpine()
        result = await spine.run(
            dataset,
            organization_id="org_persist",
            workspace_id="ws_persist",
            world_service=service,
        )

        # World state version should be > 0 (genesis + entity events + outcome)
        assert result.world_state_version > 1
        assert result.status.value == "COMPLETED"

        # Verify events were persisted to DB
        stmt = select(WorldStateEventDB).where(
            WorldStateEventDB.workspace_id == "ws_persist",
        )
        rows = (await db_session.execute(stmt)).scalars().all()
        assert len(rows) > 0

        # At least some events should be entity_ingested type
        event_types = {r.event_type for r in rows}
        assert "entity_ingested" in event_types

    async def test_spine_world_version_matches_tracker(self, db_session: AsyncSession):
        service = _make_service(db_session)
        dataset = _build_small_dataset()

        spine = RealDataSpine()
        result = await spine.run(
            dataset,
            organization_id="org_persist",
            workspace_id="ws_version_check",
            world_service=service,
        )

        # The version in the result should match what the service reports
        state = await service.get_current_state(
            workspace_id="ws_version_check",
            world_id=result.world_id,
        )
        assert state is not None
        assert state.version == result.world_state_version


# ─────────────────────────────────────────────────────────────────────────────
# Test 6: ExecutionOutcome event
# ─────────────────────────────────────────────────────────────────────────────


class TestExecutionOutcomeEvent:
    """Submit ExecutionOutcome events and verify persistence."""

    async def test_execution_outcome_event(self, db_session: AsyncSession):
        service = _make_service(db_session)
        await service.initialize_world(workspace_id="ws_outcome", world_id="world_outcome")

        event = _make_execution_outcome("world_outcome", "ws_outcome")
        result = await service.submit_event(event)

        assert result.version == 2
        assert result.is_duplicate is False

        # Verify event in DB
        stmt = select(WorldStateEventDB).where(
            WorldStateEventDB.world_id == "world_outcome",
            WorldStateEventDB.event_type == "execution_outcome",
        )
        rows = (await db_session.execute(stmt)).scalars().all()
        assert len(rows) == 1
        assert rows[0].payload["plan_id"] == "PLAN_001"
        assert rows[0].payload["result_status"] == "EXECUTED"


# ─────────────────────────────────────────────────────────────────────────────
# Test 7: Workspace isolation
# ─────────────────────────────────────────────────────────────────────────────


class TestWorkspaceIsolation:
    """Events in workspace A are not visible in workspace B."""

    async def test_workspace_isolation(self, db_session: AsyncSession):
        service = _make_service(db_session)

        # Initialize two separate workspaces
        await service.initialize_world(workspace_id="ws_A", world_id="world_A")
        await service.initialize_world(workspace_id="ws_B", world_id="world_B")

        # Submit events to workspace A
        for i in range(1, 4):
            event = _make_entity_ingested("world_A", "ws_A", entity_id=f"S{i}")
            await service.submit_event(
                event, idempotency_key=f"ws_A.SUPPLIER.S{i}",
            )

        # Submit one event to workspace B
        event_b = _make_entity_ingested("world_B", "ws_B", entity_id="S1")
        await service.submit_event(event_b, idempotency_key="ws_B.SUPPLIER.S1")

        # Verify workspace A events
        stmt_a = select(WorldStateEventDB).where(
            WorldStateEventDB.workspace_id == "ws_A",
        )
        rows_a = (await db_session.execute(stmt_a)).scalars().all()
        assert len(rows_a) == 3

        # Verify workspace B events
        stmt_b = select(WorldStateEventDB).where(
            WorldStateEventDB.workspace_id == "ws_B",
        )
        rows_b = (await db_session.execute(stmt_b)).scalars().all()
        assert len(rows_b) == 1

        # State versions are independent
        state_a = await service.get_current_state(workspace_id="ws_A", world_id="world_A")
        state_b = await service.get_current_state(workspace_id="ws_B", world_id="world_B")
        assert state_a is not None
        assert state_b is not None
        assert state_a.version == 4  # genesis + 3 events
        assert state_b.version == 2  # genesis + 1 event
