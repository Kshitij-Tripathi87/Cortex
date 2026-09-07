"""Tests for the PostgreSQL-backed ontology persistence layer.

Validates the write-through architecture: Postgres is authoritative,
the in-memory projection is a rebuildable cache, and consistency checks
detect drift between the two.

Tests use the in-memory SQLite fixture from conftest.py. The same code
path runs against PostgreSQL in production via the same SQLAlchemy engine
(the JSON/ARRAY variants are PG-compatible via JSONB dialect mutation).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.nexus_spine.ontology import (
    EntityKind,
    EntityQuery,
    RelationshipEdge,
    RelationshipKind,
    SupplierEntity,
    SalesOrderEntity,
    PurchaseOrderEntity,
    get_world_model,
    reset_world_model,
)
from app.modules.nexus_spine.ontology.persistence import (
    NexusEntityDB,
    NexusRelationshipDB,
    OntologyStore,
    entity_to_row,
    row_to_entity,
)
from app.modules.nexus_spine.ontology.write_through import (
    PersistenceMode,
    WriteThroughWorldModelRepository,
)


TENANT = UUID("11111111-1111-1111-1111-111111111111")
WORKSPACE = UUID("22222222-2222-2222-2222-222222222222")


@pytest.fixture
def fresh_model() -> None:
    reset_world_model()
    yield
    reset_world_model()


@pytest.fixture
def make_supplier_sync():
    def _make(natural_key: str = "S-1") -> SupplierEntity:
        return SupplierEntity.create(
            tenant_id=TENANT,
            workspace_id=WORKSPACE,
            natural_key=natural_key,
            name=f"Supplier {natural_key}",
            source="test",
            capacity_pct=80.0,
            risk_score=0.35,
        )
    return _make


# ──────────────────────────────────────────────────────────────────────────────
# Entity serialization round-trip
# ──────────────────────────────────────────────────────────────────────────────


def test_entity_to_row_and_back_round_trip():
    s = SupplierEntity.create(
        tenant_id=TENANT, workspace_id=WORKSPACE,
        natural_key="SUP-X", name="Acme", source="test",
        capacity_pct=72.5, risk_score=0.42,
    )
    row = entity_to_row(s)
    restored = row_to_entity(NexusEntityDB(**row))
    assert restored.entity_id == s.entity_id
    assert restored.kind == EntityKind.SUPPLIER
    assert restored.natural_key == "SUP-X"
    assert restored.state["capacity_pct"] == 72.5


def test_row_preserves_entity_state_history():
    s = SupplierEntity.create(
        tenant_id=TENANT, workspace_id=WORKSPACE,
        natural_key="H-1", name="Historic", source="test",
        capacity_pct=100.0,
    )
    s.append_state_snapshot(
        new_state={"capacity_pct": 50.0},
        world_state_version=3,
        state_hash="abc123",
        actor="test",
        reason="capacity drop",
    )
    row = entity_to_row(s)
    assert len(row["state_history"]) == 1  # first snapshot is the initial state
    restored = row_to_entity(NexusEntityDB(**row))
    assert len(restored.state_history) == 1
    assert restored.state_history[0].version == 1
    assert restored.state_history[0].state["capacity_pct"] == 50.0


def test_row_preserves_provenance_chain():
    s = SupplierEntity.create(
        tenant_id=TENANT, workspace_id=WORKSPACE,
        natural_key="P-1", name="Prov", source="test",
    )
    s.append_state_snapshot(
        new_state=s.state,
        world_state_version=1,
        state_hash="hash1",
        actor="alice",
        action="import",
        reason="initial import",
    )
    row = entity_to_row(s)
    restored = row_to_entity(NexusEntityDB(**row))
    assert len(restored.provenance) == 1  # the manual appends
    assert restored.provenance[0].action == "import"
    assert restored.provenance[0].reason == "initial import"


# ──────────────────────────────────────────────────────────────────────────────
# In-memory projection still works in write-through mode without store
# ──────────────────────────────────────────────────────────────────────────────


def test_write_through_memory_only_mode(fresh_model):
    repo = WriteThroughWorldModelRepository()
    s = SupplierEntity.create(
        tenant_id=TENANT, workspace_id=WORKSPACE,
        natural_key="S", name="S", source="t",
    )
    saved, version = repo.upsert_sync(s, actor="alice")
    assert version >= 1
    assert repo.get(TENANT, WORKSPACE, saved.entity_id) is not None
    assert repo.get_by_natural_key(TENANT, WORKSPACE, "S") is not None


@pytest.mark.asyncio
async def test_write_through_upsert_falls_back_without_store(fresh_model):
    repo = WriteThroughWorldModelRepository()
    s = SupplierEntity.create(
        tenant_id=TENANT, workspace_id=WORKSPACE,
        natural_key="S", name="S", source="t",
    )
    saved, version = await repo.upsert(s, actor="alice")
    assert version >= 1
    assert repo.get(TENANT, WORKSPACE, saved.entity_id) is not None
    events = repo.events
    assert any(e["kind"] == "WORLD_STATE_CHANGED" for e in events)


@pytest.mark.asyncio
async def test_write_through_query_passes_through(fresh_model):
    repo = WriteThroughWorldModelRepository()
    s1 = SupplierEntity.create(
        tenant_id=TENANT, workspace_id=WORKSPACE,
        natural_key="S1", name="One", source="t",
    )
    s2 = SupplierEntity.create(
        tenant_id=TENANT, workspace_id=WORKSPACE,
        natural_key="S2", name="Two", source="t",
    )
    await repo.upsert(s1, actor="t")
    await repo.upsert(s2, actor="t")
    page = repo.query(EntityQuery(tenant_id=TENANT, workspace_id=WORKSPACE, limit=10))
    assert page.total == 2


def test_write_through_consistency_check_no_store(fresh_model):
    import asyncio

    repo = WriteThroughWorldModelRepository()
    report = asyncio.run(repo.consistency_check(TENANT, WORKSPACE))
    assert report.in_sync is True
    assert report.workspace_id == str(WORKSPACE)


# ──────────────────────────────────────────────────────────────────────────────
# DB-backed store (SQLite via same engine fixtures)
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ontology_store_upsert_and_get(db_session: AsyncSession):
    store = OntologyStore(db_session)
    s = SupplierEntity.create(
        tenant_id=TENANT, workspace_id=WORKSPACE,
        natural_key="DB-S1", name="DB Supplier", source="test",
        capacity_pct=64.0,
    )
    saved = await store.upsert_entity(s)
    fetched = await store.get_entity(TENANT, WORKSPACE, saved.entity_id)
    assert fetched is not None
    assert fetched.natural_key == "DB-S1"
    assert fetched.state["capacity_pct"] == 64.0


@pytest.mark.asyncio
async def test_ontology_store_queries_by_kind(db_session: AsyncSession):
    store = OntologyStore(db_session)
    s = SupplierEntity.create(
        tenant_id=TENANT, workspace_id=WORKSPACE,
        natural_key="DB-S2", name="S2", source="t",
    )
    wk = SalesOrderEntity.create(
        tenant_id=TENANT, workspace_id=WORKSPACE,
        natural_key="DB-SO1", name="SO1", source="t",
        quantity=10, customer_id=uuid4(),
        promised_delivery=datetime.now(UTC),
        revenue=1000.0,
    )
    await store.upsert_entity(s)
    await store.upsert_entity(wk)
    results = await store.query_entities(
        EntityQuery(tenant_id=TENANT, workspace_id=WORKSPACE, kinds=[EntityKind.SUPPLIER], limit=10)
    )
    assert len(results) == 1
    assert results[0].kind == EntityKind.SUPPLIER


@pytest.mark.asyncio
async def test_relationship_store_write_and_read(db_session: AsyncSession):
    store = OntologyStore(db_session)
    s = SupplierEntity.create(
        tenant_id=TENANT, workspace_id=WORKSPACE,
        natural_key="R-S", name="From", source="t",
    )
    t = SalesOrderEntity.create(
        tenant_id=TENANT, workspace_id=WORKSPACE,
        natural_key="R-T", name="To", source="t",
        quantity=10, customer_id=uuid4(),
        promised_delivery=datetime.now(UTC),
        revenue=1.0,
    )
    await store.upsert_entity(s)
    await store.upsert_entity(t)
    edge = RelationshipEdge(
        from_entity_id=s.entity_id,
        to_entity_id=t.entity_id,
        kind=RelationshipKind.SUPPLIES,
        confidence=0.9,
    )
    await store.add_relationship(edge, TENANT, WORKSPACE)
    out_edges = await store.list_out_edges(TENANT, WORKSPACE, s.entity_id)
    in_edges = await store.list_in_edges(TENANT, WORKSPACE, t.entity_id)
    assert len(out_edges) == 1
    assert len(in_edges) == 1
    assert out_edges[0].kind == RelationshipKind.SUPPLIES


@pytest.mark.asyncio
async def test_hydrate_workspace_rebuilds_projection(fresh_model, db_session: AsyncSession):
    store = OntologyStore(db_session)
    s = SupplierEntity.create(
        tenant_id=TENANT, workspace_id=WORKSPACE,
        natural_key="HYD-1", name="Hyd", source="t",
    )
    await store.upsert_entity(s)

    projection = get_world_model()
    repo = WriteThroughWorldModelRepository(
        projection=projection,
        store=store,
        mode=PersistenceMode.PERSIST_FIRST,
    )
    loaded = await repo.hydrate_workspace(TENANT, WORKSPACE)
    assert loaded >= 1
    assert repo.get_by_natural_key(TENANT, WORKSPACE, "HYD-1") is not None


@pytest.mark.asyncio
async def test_consistency_check_detects_sync(fresh_model, db_session: AsyncSession):
    from app.modules.nexus_spine.ontology import get_world_model
    store = OntologyStore(db_session)
    s = SupplierEntity.create(
        tenant_id=TENANT, workspace_id=WORKSPACE,
        natural_key="CHK-1", name="Check", source="t",
    )
    await store.upsert_entity(s)
    projection = get_world_model()
    repo = WriteThroughWorldModelRepository(
        projection=projection, store=store, mode=PersistenceMode.PERSIST_FIRST,
    )
    await repo.upsert(s, actor="test")
    report = await repo.consistency_check(TENANT, WORKSPACE)
    assert report.in_sync is True
    assert report.projection_only == 0
    assert report.store_only == 0
