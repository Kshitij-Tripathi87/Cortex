from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import ClaimState
from app.modules.compiler.models import EvidenceClaim
from app.modules.graph.compiler import (
    _canonicalize_source_row,
    _detect_entity_type,
    _detect_pk_column,
    _resolve_fk_columns,
    compile_evidence_to_graph,
)
from app.modules.graph.entity_keys import canonical_column_name
from app.modules.graph.models import (
    GraphEdge,
    GraphNode,
    GraphSnapshot,
    GraphWriteEvent,
    ProvenanceLink,
)
from app.modules.sources.models import SourceBatch, SourceColumnProfile, SourceFile


async def _seed_supplier_batch(
    db: AsyncSession,
    *,
    workspace_id: str,
    supplier_name: str,
) -> str:
    batch_id = str(uuid4())
    file_id = str(uuid4())
    db.add(
        SourceBatch(
            batch_id=batch_id,
            workspace_id=workspace_id,
            checksum=(uuid4().hex * 2)[:64],
            source_system_hint="erp",
            file_count=1,
        )
    )
    db.add(
        SourceFile(
            file_id=file_id,
            batch_id=batch_id,
            workspace_id=workspace_id,
            storage_key=f"test/{batch_id}/suppliers.csv",
            original_name="suppliers.csv",
            mime_type="text/csv",
            size=256,
            checksum=(uuid4().hex * 2)[:64],
            profiled=True,
            encoding="utf-8",
            row_count=1,
            column_count=3,
        )
    )

    profile_data = [
        ("supplier_id", "SUP-001", "supplier_id", 0, 0.99),
        ("supplier_name", supplier_name, "supplier_name", 1, 0.95),
        ("parent_supplier_id", "SUP-ROOT", "parent_supplier_id", 2, 0.99),
    ]
    for column_name, sample_value, mapping, column_index, confidence in profile_data:
        profile_id = str(uuid4())
        db.add(
            SourceColumnProfile(
                profile_id=profile_id,
                file_id=file_id,
                workspace_id=workspace_id,
                column_name=column_name,
                column_index=column_index,
                inferred_type="string",
                null_ratio=0.0,
                distinct_count=1,
                sample_values=[sample_value],
                recommended_mapping=mapping,
                mapping_confidence=confidence,
                requires_review=False,
            )
        )
        db.add(
            EvidenceClaim(
                claim_id=str(uuid4()),
                workspace_id=workspace_id,
                source_file_id=file_id,
                batch_id=batch_id,
                row_number=0,
                source_column=column_name,
                canonical_entity="Supplier",
                canonical_field=mapping,
                raw_value=sample_value,
                normalized_value=sample_value,
                confidence=confidence,
                claim_state=ClaimState.ACCEPTED.value,
                provenance={"profile_id": profile_id},
                requires_review=False,
            )
        )
    await db.flush()
    return batch_id


@pytest.mark.asyncio
async def test_second_batch_reuses_canonical_supplier_nodes_and_relationships(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.modules.graph.compiler.get_settings",
        lambda: type("Settings", (), {"env": "test"})(),
    )
    workspace_id = str(uuid4())

    first_batch_id = await _seed_supplier_batch(
        db_session,
        workspace_id=workspace_id,
        supplier_name="Acme Ltd",
    )
    first = await compile_evidence_to_graph(db_session, workspace_id, first_batch_id)
    assert first.integrity_passed is True
    assert first.node_count == 2
    assert first.edge_count == 1

    first_nodes = list(
        (
            await db_session.scalars(
                select(GraphNode)
                .where(GraphNode.workspace_id == workspace_id)
                .where(GraphNode.valid_to.is_(None))
            )
        ).all()
    )
    first_edges = list(
        (
            await db_session.scalars(
                select(GraphEdge)
                .where(GraphEdge.workspace_id == workspace_id)
                .where(GraphEdge.valid_to.is_(None))
            )
        ).all()
    )
    supplier_node = next(node for node in first_nodes if node.entity_id == "SUP-001")
    parent_node = next(node for node in first_nodes if node.entity_id == "SUP-ROOT")
    first_edge = first_edges[0]

    second_batch_id = await _seed_supplier_batch(
        db_session,
        workspace_id=workspace_id,
        supplier_name="Acme International",
    )
    second = await compile_evidence_to_graph(db_session, workspace_id, second_batch_id)
    assert second.integrity_passed is True
    assert second.version > first.version
    assert second.node_count == 2
    assert second.edge_count == 1

    active_nodes = list(
        (
            await db_session.scalars(
                select(GraphNode)
                .where(GraphNode.workspace_id == workspace_id)
                .where(GraphNode.valid_to.is_(None))
            )
        ).all()
    )
    active_edges = list(
        (
            await db_session.scalars(
                select(GraphEdge)
                .where(GraphEdge.workspace_id == workspace_id)
                .where(GraphEdge.valid_to.is_(None))
            )
        ).all()
    )
    assert len(active_nodes) == 2
    assert len(active_edges) == 1

    updated_supplier = next(node for node in active_nodes if node.entity_id == "SUP-001")
    reused_parent = next(node for node in active_nodes if node.entity_id == "SUP-ROOT")
    assert updated_supplier.node_id == supplier_node.node_id
    assert updated_supplier.attributes["supplier_name"] == "Acme International"
    assert reused_parent.node_id == parent_node.node_id
    assert active_edges[0].edge_id == first_edge.edge_id
    assert active_edges[0].relationship_type == "PARENT_OF"

    snapshot_count = await db_session.scalar(
        select(func.count(GraphSnapshot.snapshot_id)).where(
            GraphSnapshot.workspace_id == workspace_id
        )
    )
    event_count = await db_session.scalar(
        select(func.count(GraphWriteEvent.event_id)).where(
            GraphWriteEvent.workspace_id == workspace_id
        )
    )
    provenance_count = await db_session.scalar(
        select(func.count(ProvenanceLink.link_id)).where(
            ProvenanceLink.workspace_id == workspace_id
        )
    )
    assert snapshot_count == 2
    assert event_count == 6
    assert provenance_count >= 6

    # A retry of a published batch returns its original snapshot and does not
    # add another node, edge, snapshot, event, or provenance record.
    retry = await compile_evidence_to_graph(db_session, workspace_id, second_batch_id)
    assert retry.snapshot_id == second.snapshot_id
    assert retry.snapshot_hash == second.snapshot_hash

    assert (
        await db_session.scalar(
            select(func.count(GraphSnapshot.snapshot_id)).where(
                GraphSnapshot.workspace_id == workspace_id
            )
        )
        == 2
    )
    assert (
        await db_session.scalar(
            select(func.count(GraphWriteEvent.event_id)).where(
                GraphWriteEvent.workspace_id == workspace_id
            )
        )
        == 6
    )

def test_vendor_export_headers_resolve_to_supplier_primary_and_parent_keys() -> None:
    headers = ["Vendor Code", "Vendor Name", "Parent Vendor Code"]

    entity_type = _detect_entity_type(headers)
    assert entity_type == "Supplier"
    assert _detect_pk_column(headers, entity_type) == "supplier_id"
    assert _resolve_fk_columns(headers, entity_type) == [
        ("parent_supplier_id", "Supplier", "PARENT_OF", "parent_supplier_id")
    ]

    row = _canonicalize_source_row(
        {
            "Vendor Code": "V-001",
            "Vendor Name": "Northwind Components",
            "Parent Vendor Code": "V-ROOT",
        },
        entity_type,
    )
    assert row == {
        "supplier_id": "V-001",
        "vendor_name": "Northwind Components",
        "parent_supplier_id": "V-ROOT",
    }


def test_purchase_order_export_resolves_vendor_and_destination_facility_edges():
    headers = ["PO Number", "Vendor ID", "Ship To Warehouse Code"]

    entity_type = _detect_entity_type(headers)
    assert entity_type == "PurchaseOrder"
    assert _detect_pk_column(headers, entity_type) == "po_number"
    assert _resolve_fk_columns(headers, entity_type) == [
        ("supplier_id", "Supplier", "ORDERS_FROM", "supplier_id"),
        ("ship_to_facility_id", "Facility", "SHIPS_TO", "ship_to_facility_id"),
    ]

    row = _canonicalize_source_row(
        {
            "PO Number": "PO-1008",
            "Vendor ID": "V-001",
            "Ship To Warehouse Code": "WH-09",
        },
        entity_type,
    )
    assert row["po_number"] == "PO-1008"
    assert row["supplier_id"] == "V-001"
    assert row["ship_to_facility_id"] == "WH-09"


def test_lot_number_alias_is_a_valid_inventory_lot_primary_key():
    headers = ["Lot Number", "SKU", "Quantity"]
    entity_type = _detect_entity_type(headers)

    assert entity_type == "InventoryLot"
    assert _detect_pk_column(headers, entity_type) == "lot_id"
    assert canonical_column_name("Lot Number") == "lot_id"


def test_conflicting_duplicate_aliases_fail_closed():
    with pytest.raises(ValueError, match="conflicting columns"):
        _canonicalize_source_row(
            {
                "Vendor ID": "V-001",
                "Supplier ID": "V-002",
            },
            "Supplier",
        )


def test_sales_order_customer_foreign_key_does_not_override_row_primary_key() -> None:
    headers = ["SO Number", "Customer ID", "Ship From Warehouse ID"]
    assert _detect_entity_type(headers) == "SalesOrder"


def test_shipment_carrier_and_route_foreign_keys_do_not_override_row_entity() -> None:
    headers = [
        "Shipment Number",
        "Carrier Code",
        "Route Code",
        "Origin Warehouse ID",
        "Destination Port ID",
    ]
    assert _detect_entity_type(headers) == "Shipment"


def test_inventory_identifier_wins_over_product_and_facility_foreign_keys() -> None:
    headers = ["Inventory ID", "SKU", "Warehouse ID"]
    assert _detect_entity_type(headers) == "InventoryItem"


def test_reviewed_canonical_field_override_is_used_by_graph_row_normalizer() -> None:
    row = _canonicalize_source_row(
        {"Vendor Code": "V-007", "Vendor Name": "Northwind"},
        "Supplier",
        {"Vendor Code": "supplier_id", "Vendor Name": "legal_name"},
    )
    assert row == {"supplier_id": "V-007", "legal_name": "Northwind"}
