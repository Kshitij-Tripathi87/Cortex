"""Workspace evidence for the Ask box, read from real PostgreSQL.

The route-level Ask tests run on in-memory SQLite. Production runs on
PostgreSQL through asyncpg, where a query that SQLite accepts can still fail
(typed parameters, JSON columns, grouping). This test stores a small published
history directly in PostgreSQL and runs every kind of evidence query against
it. It skips when PostgreSQL is not available.

The history: suppliers published, then orders that refer to a supplier no file
describes yet, then a supplier update that changes one record, completes the
referenced one, repeats one unchanged and adds one. A fourth upload is still
waiting for review.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import MetaData, delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.compiler.models import EvidenceClaim, EvidenceConflict
from app.modules.graph.models import GraphEdge, GraphNode, GraphSnapshot, GraphWriteEvent
from app.modules.nexus_spine.p0_migration.workspace_evidence import build_workspace_evidence
from app.modules.sources.models import SourceBatch, SourceFile

MODELS = (
    GraphWriteEvent,
    GraphEdge,
    GraphNode,
    GraphSnapshot,
    EvidenceConflict,
    EvidenceClaim,
    SourceFile,
    SourceBatch,
)
TODAY = date(2026, 11, 17)
START = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)


@pytest.fixture
async def sessions(
    request: pytest.FixtureRequest,
) -> AsyncGenerator[async_sessionmaker[AsyncSession]]:
    try:
        engine = create_async_engine(request.config.postgres_url, echo=False)  # type: ignore[attr-defined]
        async with engine.begin() as conn:
            await conn.execute(select(1))
    except Exception as exc:  # any connection failure means "no PostgreSQL here"
        pytest.skip(f"PostgreSQL not available: {exc}")

    # A migrated database (CI) already has these tables; create_all is then a no-op.
    metadata = MetaData()
    for model in MODELS:
        model.__table__.to_metadata(metadata)
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)

    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def workspace(sessions: async_sessionmaker[AsyncSession]) -> AsyncGenerator[str]:
    workspace_id = str(uuid4())
    async with sessions() as session:
        await _store_history(session, workspace_id)
        await session.commit()
    yield workspace_id
    async with sessions() as session:
        for model in MODELS:
            await session.execute(delete(model).where(model.workspace_id == workspace_id))
        await session.commit()


async def _store_history(session: AsyncSession, workspace_id: str) -> None:
    clock = [START]

    def tick() -> datetime:
        clock[0] += timedelta(seconds=1)
        return clock[0]

    def batch(name: str, *, published_as: int | None) -> tuple[str, str]:
        batch_id, file_id = str(uuid4()), str(uuid4())
        session.add(
            SourceBatch(
                batch_id=batch_id,
                workspace_id=workspace_id,
                status="validated",
                checksum=uuid4().hex,
                source_system_hint="erp",
                file_count=1,
                created_at=tick(),
            )
        )
        session.add(
            SourceFile(
                file_id=file_id,
                batch_id=batch_id,
                workspace_id=workspace_id,
                storage_key=f"{workspace_id}/{name}",
                original_name=name,
                mime_type="text/csv",
                size=100,
                checksum=uuid4().hex,
                row_count=3,
            )
        )
        if published_as is not None:
            snapshot_ids[published_as] = str(uuid4())
            session.add(
                GraphSnapshot(
                    snapshot_id=snapshot_ids[published_as],
                    workspace_id=workspace_id,
                    version=published_as,
                    snapshot_hash=uuid4().hex,
                    node_count=3,
                    edge_count=1,
                    source_batch_id=batch_id,
                    sealed_at=tick(),
                )
            )
        return batch_id, file_id

    def claim(batch_id: str, file_id: str, state: str) -> None:
        session.add(
            EvidenceClaim(
                workspace_id=workspace_id,
                source_file_id=file_id,
                batch_id=batch_id,
                row_number=1,
                source_column="supplier_id",
                raw_value="S-1",
                claim_state=state,
            )
        )

    def node(
        entity_type: str, entity_id: str, attributes: dict[str, Any], first: int, last: int
    ) -> str:
        node_id = str(uuid4())
        node_ids[entity_id] = node_id
        session.add(
            GraphNode(
                node_id=node_id,
                workspace_id=workspace_id,
                entity_type=entity_type,
                entity_id=entity_id,
                attributes=attributes,
                first_seen_version=first,
                last_modified_version=last,
            )
        )
        return node_id

    def wrote(
        version: int,
        entity_type: str,
        entity_id: str,
        attributes: dict[str, Any],
        *,
        stub: bool = False,
    ) -> None:
        payload: dict[str, Any] = {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "attributes": attributes,
        }
        if stub:
            payload["_stub"] = True
        session.add(
            GraphWriteEvent(
                workspace_id=workspace_id,
                snapshot_id=snapshot_ids[version],
                operation="upsert_node",
                element_type="node",
                element_id=node_ids[entity_id],
                payload=payload,
                occurred_at=tick(),
            )
        )

    snapshot_ids: dict[int, str] = {}
    node_ids: dict[str, str] = {}

    first_batch, first_file = batch("suppliers.csv", published_as=1)
    second_batch, second_file = batch("orders.csv", published_as=2)
    third_batch, third_file = batch("suppliers_update.csv", published_as=3)
    waiting_batch, waiting_file = batch("inventory.csv", published_as=None)
    for batch_id, file_id in (
        (first_batch, first_file),
        (second_batch, second_file),
        (third_batch, third_file),
    ):
        claim(batch_id, file_id, "accepted")
    for state in ("pending_review", "pending_review", "accepted"):
        claim(waiting_batch, waiting_file, state)

    acme = {"supplier_id": "S-1", "supplier_name": "Acme Metals", "status": "active"}
    bolt = {"supplier_id": "S-2", "supplier_name": "Bolt Works", "status": "active"}
    crane = {"supplier_id": "S-9", "supplier_name": "Crane Forge", "status": "active"}
    delta = {"supplier_id": "S-3", "supplier_name": "Delta Seals", "status": "active"}
    order = {"po_number": "PO-1", "supplier_id": "S-1", "status": "delayed", "quantity": "40"}
    orphan = {
        "po_number": "PO-2",
        "supplier_id": "S-9",
        "status": "confirmed",
        "promised_date": "2099-01-01",
    }

    # Current state of the graph after version 3.
    node("Supplier", "S-1", {**acme, "status": "delayed"}, 1, 3)
    node("Supplier", "S-2", bolt, 1, 3)
    node("Supplier", "S-9", crane, 2, 3)
    node("Supplier", "S-3", delta, 3, 3)
    node("PurchaseOrder", "PO-1", order, 2, 2)
    node("PurchaseOrder", "PO-2", orphan, 2, 2)
    for source, target in (("PO-1", "S-1"), ("PO-2", "S-9")):
        session.add(
            GraphEdge(
                workspace_id=workspace_id,
                source_node_id=node_ids[source],
                target_node_id=node_ids[target],
                relationship_type="ORDERS_FROM",
                first_seen_version=2,
                last_modified_version=2,
            )
        )

    # The write log, in the order the publishes happened.
    wrote(1, "Supplier", "S-1", acme)
    wrote(1, "Supplier", "S-2", bolt)
    wrote(2, "PurchaseOrder", "PO-1", order)
    wrote(2, "Supplier", "S-1", {}, stub=True)
    wrote(2, "PurchaseOrder", "PO-2", orphan)
    wrote(2, "Supplier", "S-9", {}, stub=True)
    wrote(3, "Supplier", "S-1", {**acme, "status": "delayed"})
    wrote(3, "Supplier", "S-2", bolt)
    wrote(3, "Supplier", "S-9", crane)
    wrote(3, "Supplier", "S-3", delta)


async def _evidence(
    sessions: async_sessionmaker[AsyncSession], workspace_id: str, question: str
) -> dict[str, Any]:
    async with sessions() as session:
        return await build_workspace_evidence(session, workspace_id, question, today=TODAY)


async def test_changes_are_read_from_the_write_log(
    sessions: async_sessionmaker[AsyncSession], workspace: str
) -> None:
    evidence = await _evidence(sessions, workspace, "What changed?")

    assert evidence["workspace"]["world_state_version"] == 3
    assert evidence["workspace"]["entity_counts"] == {"PurchaseOrder": 2, "Supplier": 4}
    assert evidence["workspace"]["relationship_counts"] == {"ORDERS_FROM": 2}
    latest = evidence["result"]["latest"]
    assert evidence["result"]["kind"] == "changes"
    assert latest["version"] == 3
    assert latest["files"] == ["suppliers_update.csv"]
    assert latest["added"] == {"Supplier": {"count": 1, "examples": ["S-3"]}}
    # One record changed, and only the field that differs is reported.
    assert latest["updated"] == [
        {
            "entity_type": "Supplier",
            "entity_id": "S-1",
            "name": "Acme Metals",
            "changes": [{"field": "status", "before": "active", "after": "delayed"}],
        }
    ]
    # S-9 was only referred to by an order until this file described it.
    assert [item["entity_id"] for item in latest["completed"]] == ["S-9"]
    assert latest["resubmitted_unchanged_count"] == 1
    assert [item["version"] for item in evidence["result"]["history"]] == [2, 1]
    assert evidence["result"]["history"][0]["files"] == ["orders.csv"]


async def test_upload_status_counts_claims_per_batch(
    sessions: async_sessionmaker[AsyncSession], workspace: str
) -> None:
    result = (await _evidence(sessions, workspace, "Is my data ready?"))["result"]

    assert result["kind"] == "intake"
    assert result["batch_count"] == 4
    assert result["by_state"] == {"published": 3, "review_required": 1}
    waiting = next(item for item in result["batches"] if item["state"] == "review_required")
    assert waiting["files"] == [{"name": "inventory.csv", "rows": 3}]
    assert (waiting["claims_pending_review"], waiting["claims_accepted"]) == (2, 1)
    assert waiting["published_version"] is None
    published = {item["files"][0]["name"]: item["published_version"] for item in result["batches"]}
    assert published["suppliers_update.csv"] == 3


async def test_records_relationships_and_lateness_are_read(
    sessions: async_sessionmaker[AsyncSession], workspace: str
) -> None:
    late = (await _evidence(sessions, workspace, "Which purchase orders are late?"))["result"]
    assert late["kind"] == "late"
    assert late["assessed"] == {"PurchaseOrder": 2}
    assert [item["entity_id"] for item in late["late"]] == ["PO-1"]
    assert late["late"][0]["supplier"] == {
        "entity_type": "Supplier",
        "entity_id": "S-1",
        "name": "Acme Metals",
    }

    detail = await _evidence(sessions, workspace, "Tell me about S-1")
    assert detail["question_focus"]["matched"][0]["matched_on"] == "identifier"
    entity = detail["result"]["entities"][0]
    assert entity["record"]["attributes"]["status"] == "delayed"
    assert entity["relationships"] == [
        {
            "relationship": "ORDERS_FROM",
            "direction": "incoming",
            "count": 1,
            "examples": [{"entity_type": "PurchaseOrder", "entity_id": "PO-1", "name": None}],
        }
    ]
    assert entity["source"]["first_published_from"] == ["suppliers.csv"]
    assert entity["source"]["last_touched_from"] == ["suppliers_update.csv"]

    # Identifiers match in any letter case; names match too.
    lower = await _evidence(sessions, workspace, "what about po-2?")
    assert lower["result"]["entities"][0]["record"]["entity_id"] == "PO-2"
    named = await _evidence(sessions, workspace, "who is Crane Forge?")
    assert named["result"]["entities"][0]["record"]["entity_id"] == "S-9"

    listed = await _evidence(sessions, workspace, "Which suppliers are delayed?")
    assert listed["result"]["kind"] == "late"
    assert [row["entity_id"] for row in listed["result"]["suppliers"]] == ["S-1"]


async def test_another_workspace_sees_nothing(
    sessions: async_sessionmaker[AsyncSession], workspace: str
) -> None:
    evidence = await _evidence(sessions, str(uuid4()), "Which suppliers do I have?")

    assert evidence["result"]["kind"] == "empty_workspace"
    assert evidence["workspace"]["entity_counts"] == {}
    assert evidence["result"]["intake"]["batch_count"] == 0
    assert evidence["attention"] is None
