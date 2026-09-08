"""Tests for the Nexus ontology — entity model, repository, graph traversal.

Covers the Phase A foundation: WorldModelRepository, Entity, specialized
entity types, query, relationship edges, blast-radius traversal, and
content-hash state snapshots.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.modules.nexus_spine.ontology import (
    Entity,
    EntityKind,
    EntityQuery,
    ForecastEntity,
    ProductEntity,
    PurchaseOrderEntity,
    SalesOrderEntity,
    SupplierEntity,
    WarehouseEntity,
    canonical_state_hash,
    get_world_model,
    reset_world_model,
)
from app.modules.nexus_spine.ontology.core_types import (
    EntityDomain,
    RelationshipKind,
    domain_of,
)
from app.modules.nexus_spine.ontology.entities import (
    PermissionGrant,
    RelationshipEdge,
)
from app.modules.nexus_spine.ontology.repository import WorldModelRepository


@pytest.fixture
def repo() -> WorldModelRepository:
    reset_world_model()
    return get_world_model()


TENANT = UUID("11111111-1111-1111-1111-111111111111")
WORKSPACE = UUID("22222222-2222-2222-2222-222222222222")


# ──────────────────────────────────────────────────────────────────────────────
# Core types
# ──────────────────────────────────────────────────────────────────────────────


def test_entity_kind_to_domain_mapping_is_complete():
    for kind in EntityKind:
        assert domain_of(kind) in EntityDomain
    assert domain_of(EntityKind.SUPPLIER) == EntityDomain.SUPPLY
    assert domain_of(EntityKind.PRODUCT) == EntityDomain.PRODUCT
    assert domain_of(EntityKind.DECISION) == EntityDomain.OPS


def test_closed_vocabulary_covers_supply_chain_kinds():
    expected = {
        "organization",
        "workspace",
        "supplier",
        "manufacturer",
        "plant",
        "warehouse",
        "port",
        "product",
        "sku",
        "component",
        "material",
        "purchase_order",
        "sales_order",
        "shipment",
        "route",
        "carrier",
        "inventory_position",
        "customer",
        "contract",
        "capacity",
        "demand",
        "forecast",
        "lead_time",
        "disruption",
        "signal",
        "scenario",
        "simulation",
        "decision",
        "recommendation",
        "execution",
        "outcome",
        "evidence",
        "agent",
        "tool",
        "policy",
        "approval",
    }
    actual = {k.value for k in EntityKind}
    assert expected.issubset(actual)


def test_relationship_kind_is_directional_and_closed():
    assert RelationshipKind.SUPPLIES.value == "supplies"
    assert RelationshipKind.DERIVED_FROM.value == "derived_from"
    assert len(list(RelationshipKind)) > 15


# ──────────────────────────────────────────────────────────────────────────────
# Entity basics
# ──────────────────────────────────────────────────────────────────────────────


def test_entity_requires_non_empty_natural_key():
    with pytest.raises(ValueError):
        Entity(
            tenant_id=TENANT,
            workspace_id=WORKSPACE,
            kind=EntityKind.SUPPLIER,
            natural_key="",
            name="",
            source="test",
        )


def test_entity_has_provenance_and_permissions_envelope():
    e = SupplierEntity.create(
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        natural_key="SUP-001",
        name="Acme Components",
        source="manual",
        capacity_pct=82.0,
    )
    assert e.entity_id is not None
    assert e.domain == EntityDomain.SUPPLY
    assert e.state["capacity_pct"] == 82.0
    assert isinstance(e.provenance, list)
    assert isinstance(e.permissions, list)


def test_specialized_entity_factory_creates_correct_kind():
    s = SupplierEntity.create(
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        natural_key="S1",
        name="S",
        source="t",
    )
    assert s.kind == EntityKind.SUPPLIER
    w = WarehouseEntity.create(
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        natural_key="W1",
        name="W",
        source="t",
    )
    assert w.kind == EntityKind.WAREHOUSE
    p = PurchaseOrderEntity.create(
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        natural_key="PO1",
        name="PO1",
        source="t",
        quantity=100,
        supplier_id=uuid4(),
        expected_delivery=__import__("datetime").datetime.now(__import__("datetime").UTC),
    )
    assert p.kind == EntityKind.PURCHASE_ORDER
    fo = ForecastEntity.create(
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        natural_key="F1",
        name="F1",
        source="t",
        horizon_days=14,
        forecast_timestamp=__import__("datetime").datetime.now(__import__("datetime").UTC),
        p50=100,
        p80=120,
        p95=140,
        confidence=0.8,
        primary_drivers=["seasonality"],
        model_version="Demand-v0.1",
    )
    assert fo.kind == EntityKind.FORECAST
    assert fo.state["p50"] == 100


# ──────────────────────────────────────────────────────────────────────────────
# State history + content hash
# ──────────────────────────────────────────────────────────────────────────────


def test_canonical_state_hash_is_deterministic():
    s1 = {"a": 1, "b": 2, "c": [1, 2, 3]}
    s2 = {"c": [1, 2, 3], "b": 2, "a": 1}
    assert canonical_state_hash(s1) == canonical_state_hash(s2)


def test_entity_state_snapshot_appends_history():
    e = SupplierEntity.create(
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        natural_key="S",
        name="S",
        source="t",
        capacity_pct=80.0,
    )
    assert e.state_history == []
    e.append_state_snapshot(
        new_state={"capacity_pct": 70.0},
        world_state_version=1,
        state_hash=canonical_state_hash({"capacity_pct": 70.0}),
        actor="test",
        action="update",
        reason="capacity drop",
    )
    assert len(e.state_history) == 1
    assert e.state["capacity_pct"] == 70.0
    assert e.provenance[-1].action == "update"
    assert e.provenance[-1].reason == "capacity drop"


# ──────────────────────────────────────────────────────────────────────────────
# Repository — CRUD + query
# ──────────────────────────────────────────────────────────────────────────────


def test_repository_upsert_and_get(repo):
    supplier = SupplierEntity.create(
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        natural_key="S1",
        name="S1",
        source="t",
        capacity_pct=80.0,
    )
    saved, wsv = repo.upsert(supplier, actor="alice")
    assert wsv >= 1
    assert saved.provenance[-1].action == "create"
    fetched = repo.get(TENANT, WORKSPACE, saved.entity_id)
    assert fetched is not None
    assert fetched.natural_key == "S1"


def test_repository_get_by_natural_key(repo):
    s = SupplierEntity.create(
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        natural_key="S42",
        name="S42",
        source="t",
    )
    repo.upsert(s)
    fetched = repo.get_by_natural_key(TENANT, WORKSPACE, "S42")
    assert fetched is not None
    assert fetched.entity_id == s.entity_id


def test_repository_query_by_kind_and_text(repo):
    for i in range(3):
        s = SupplierEntity.create(
            tenant_id=TENANT,
            workspace_id=WORKSPACE,
            natural_key=f"S{i}",
            name=f"Supplier {i}",
            source="t",
        )
        repo.upsert(s)
    for i in range(2):
        w = WarehouseEntity.create(
            tenant_id=TENANT,
            workspace_id=WORKSPACE,
            natural_key=f"W{i}",
            name=f"Warehouse {i}",
            source="t",
        )
        repo.upsert(w)
    page = repo.query(
        EntityQuery(
            tenant_id=TENANT,
            workspace_id=WORKSPACE,
            kinds=[EntityKind.SUPPLIER],
            limit=10,
            offset=0,
        )
    )
    assert page.total == 3
    page = repo.query(
        EntityQuery(
            tenant_id=TENANT,
            workspace_id=WORKSPACE,
            kinds=[EntityKind.WAREHOUSE],
            limit=10,
            offset=0,
        )
    )
    assert page.total == 2
    page = repo.query(
        EntityQuery(
            tenant_id=TENANT,
            workspace_id=WORKSPACE,
            text_search="Supplier 0",
            limit=10,
            offset=0,
        )
    )
    assert page.total == 1


def test_repository_query_by_domain(repo):
    s = SupplierEntity.create(
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        natural_key="S",
        name="S",
        source="t",
    )
    repo.upsert(s)
    fo = ForecastEntity.create(
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        natural_key="F",
        name="F",
        source="t",
        horizon_days=7,
        forecast_timestamp=__import__("datetime").datetime.now(__import__("datetime").UTC),
        p50=10,
        p80=12,
        p95=14,
        confidence=0.5,
        primary_drivers=[],
        model_version="v0",
    )
    repo.upsert(fo)
    # FORECAST is in COMMERCIAL domain
    page = repo.query(
        EntityQuery(
            tenant_id=TENANT,
            workspace_id=WORKSPACE,
            domain=EntityDomain.COMMERCIAL,
            limit=10,
            offset=0,
        )
    )
    assert any(e.kind == EntityKind.FORECAST for e in page.items)
    # SUPPLIER is in SUPPLY domain
    page = repo.query(
        EntityQuery(
            tenant_id=TENANT,
            workspace_id=WORKSPACE,
            domain=EntityDomain.SUPPLY,
            limit=10,
            offset=0,
        )
    )
    assert any(e.kind == EntityKind.SUPPLIER for e in page.items)


def test_repository_query_isolated_by_tenant(repo):
    other_tenant = UUID("99999999-9999-9999-9999-999999999999")
    s1 = SupplierEntity.create(
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        natural_key="S1",
        name="S1",
        source="t",
    )
    s2 = SupplierEntity.create(
        tenant_id=other_tenant,
        workspace_id=WORKSPACE,
        natural_key="S2",
        name="S2",
        source="t",
    )
    repo.upsert(s1)
    repo.upsert(s2)
    page = repo.query(EntityQuery(tenant_id=TENANT, workspace_id=WORKSPACE, limit=10, offset=0))
    assert page.total == 1
    assert page.items[0].tenant_id == TENANT


def test_repository_delete_removes_entity(repo):
    s = SupplierEntity.create(
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        natural_key="S",
        name="S",
        source="t",
    )
    saved, _ = repo.upsert(s)
    assert repo.delete(TENANT, WORKSPACE, saved.entity_id, actor="alice") is True
    assert repo.get(TENANT, WORKSPACE, saved.entity_id) is None
    # Deleting again is idempotent
    assert repo.delete(TENANT, WORKSPACE, saved.entity_id) is False


# ──────────────────────────────────────────────────────────────────────────────
# Repository — graph traversal + blast radius
# ──────────────────────────────────────────────────────────────────────────────


def test_repository_traverse_supply_chain(repo):
    # Build a small chain: supplier -> PO -> product -> SO
    supplier = SupplierEntity.create(
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        natural_key="S",
        name="S",
        source="t",
    )
    repo.upsert(supplier)
    product = ProductEntity.create(
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        natural_key="P",
        name="P",
        source="t",
    )
    repo.upsert(product)
    customer_id = uuid4()
    po = PurchaseOrderEntity.create(
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        natural_key="PO",
        name="PO",
        source="t",
        quantity=10,
        supplier_id=supplier.entity_id,
        expected_delivery=__import__("datetime").datetime.now(__import__("datetime").UTC),
    )
    so = SalesOrderEntity.create(
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        natural_key="SO",
        name="SO",
        source="t",
        quantity=10,
        customer_id=customer_id,
        promised_delivery=__import__("datetime").datetime.now(__import__("datetime").UTC),
        revenue=50000.0,
        sla_risk_pct=0.5,
    )
    repo.upsert(po)
    repo.upsert(so)

    repo.add_relationship(
        RelationshipEdge(
            from_entity_id=supplier.entity_id,
            to_entity_id=po.entity_id,
            kind=RelationshipKind.SUPPLIES,
        )
    )
    repo.add_relationship(
        RelationshipEdge(
            from_entity_id=po.entity_id,
            to_entity_id=so.entity_id,
            kind=RelationshipKind.PRODUCES,
        )
    )

    paths = repo.traverse_supply_chain(TENANT, WORKSPACE, supplier.entity_id, max_depth=3)
    assert po.entity_id in paths
    assert so.entity_id in paths
    # so is reached via po → so, so there's 1 edge in the path
    assert len(paths[so.entity_id]) == 1
    # po is reached via supplier → po
    assert len(paths[po.entity_id]) == 1


def test_repository_publishes_change_events(repo):
    received: list[dict] = []
    repo.subscribe(lambda evt: received.append(evt))
    s = SupplierEntity.create(
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        natural_key="S",
        name="S",
        source="t",
    )
    repo.upsert(s, actor="alice")
    assert any(e.get("kind") == "WORLD_STATE_CHANGED" for e in received)


# ──────────────────────────────────────────────────────────────────────────────
# Permissions
# ──────────────────────────────────────────────────────────────────────────────


def test_permission_grant_can_be_attached_to_entity(repo):
    s = SupplierEntity.create(
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        natural_key="S",
        name="S",
        source="t",
    )
    s.grant_permission(PermissionGrant(role="analyst", can_read=True, granted_by="admin"))
    assert len(s.permissions) == 1
    assert s.permissions[0].role == "analyst"
