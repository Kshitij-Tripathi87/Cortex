"""A file is reviewed by column, not cell by cell.

Every cell of an uploaded file is a claim that waits for a decision. The
review page offered one dialog per cell, with the kind of record typed by hand
and a suggested field that could be wrong: a supplier file of six rows took 42
dialogs, and accepting an inventory file as suggested put two columns under
one field and blocked every row. A file could only be published by a script.

These tests drive upload -> prepare -> review -> publish over HTTP, as the
page does, and check that

* preparing a file says what its rows are and names each column the way
  publishing does;
* one decision accepts or rejects whole columns, or the whole file, and is
  recorded once with its rationale;
* a file accepted that way publishes exactly as it reads;
* the checks a cell-by-cell review relied on still hold: rows that disagree
  about one record block publishing, and nothing is published without the
  column that identifies the record.
"""

from __future__ import annotations

import csv
import io
from collections.abc import AsyncGenerator
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import graph, readiness, sources
from app.common.enums import ClaimState
from app.infrastructure import storage_client
from app.infrastructure.database import get_db
from app.infrastructure.security import AuthContext, get_current_user

# Register the models before the db_engine fixture copies Base.metadata.
from app.modules.audit.models import AuditEvent
from app.modules.compiler.models import (
    EvidenceClaim,
    EvidenceConflict,
    ReadinessAssessment,  # noqa: F401
)
from app.modules.graph.entity_keys import (
    ENTITY_FOREIGN_KEYS,
    ENTITY_PRIMARY_KEYS,
    canonical_column_name,
)
from app.modules.graph.models import GraphEdge, GraphNode, GraphSnapshot  # noqa: F401
from app.modules.sources.models import SourceBatch, SourceColumnProfile, SourceFile  # noqa: F401

SUPPLIERS_CSV = (
    b"supplier_id,supplier_name,country,tier,lead_time_days,status,on_time_rate\n"
    b"S-100,Acme Metals GmbH,DE,tier_1,21,active,0.96\n"
    b"S-101,Bharat Castings Pvt Ltd,IN,tier_1,35,delayed,0.71\n"
    b"S-102,Shenzhen Microdrive Co,CN,tier_2,42,active,0.88\n"
    b"S-103,Nordic Seals AB,SE,tier_2,14,active,0.99\n"
    b"S-104,Lone Star Fasteners,US,tier_3,10,active,0.93\n"
    b"S-105,Kyoto Bearings KK,JP,tier_1,28,at_risk,0.82\n"
)
SUPPLIER_COLUMNS = [
    "supplier_id",
    "supplier_name",
    "country",
    "tier",
    "lead_time_days",
    "status",
    "on_time_rate",
]

ORDERS_CSV = (
    b"po_number,supplier_id,sku,quantity,status,ship_to_warehouse_id\n"
    b"PO-5001,S-101,C-2000,400,delayed,WH-PUNE\n"
    b"PO-5002,S-101,C-2000,250,delayed,WH-PUNE\n"
    b"PO-5003,S-102,C-2001,300,in_transit,WH-HAM\n"
)

INVENTORY_CSV = (
    b"inventory_id,sku,warehouse_id,quantity_on_hand,safety_stock\n"
    b"INV-1,C-2000,WH-PUNE,120,300\n"
    b"INV-2,C-2001,WH-PUNE,410,150\n"
    b"INV-3,C-2002,WH-HAM,2600,500\n"
    b"INV-4,C-2003,WH-HAM,90,100\n"
    b"INV-5,C-2004,WH-PUNE,1500,2000\n"
    b"INV-6,P-1000,WH-HAM,35,20\n"
)

# Column names no registry knows: nothing says what a row is.
LIEFERANTEN_CSV = b"Lieferant Nr,Firma,Land\nL-1,Acme Metals GmbH,DE\nL-2,Nordic Seals AB,SE\n"

# Two rows describe supplier S-100 and disagree about its country.
DISAGREEING_CSV = (
    b"supplier_id,supplier_name,country\n"
    b"S-100,Acme Metals GmbH,DE\n"
    b"S-100,Acme Metals GmbH,AT\n"
    b"S-101,Bharat Castings Pvt Ltd,IN\n"
)

RATIONALE = "Checked against the ERP export of 14 November."


class _MemoryStorage:
    """Stand-in for the S3 client: keeps uploaded bytes in memory."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def object_exists(self, key: str) -> bool:
        return key in self.objects

    def put_object(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> None:
        self.objects[key] = bytes(data)

    def get_object(self, key: str) -> bytes:
        return self.objects[key]


class _Review:
    """One workspace and its reviewer, talking to the routes over HTTP."""

    def __init__(self, client: AsyncClient, workspace_id: str, actor: dict[str, Any]) -> None:
        self.client = client
        self.workspace_id = workspace_id
        self.query = {"workspace_id": workspace_id}
        # What the next request is made as; a test changes it to another role.
        self.actor = actor

    async def upload_only(self, name: str, data: bytes) -> tuple[str, str]:
        """Upload a file without preparing its claims. Returns (batch id, file id)."""
        upload = await self.client.post(
            "/api/v1/sources/upload",
            data={"workspace_id": self.workspace_id, "source_system_hint": "erp"},
            files={"file": (name, data, "text/csv")},
        )
        assert upload.status_code == 200, upload.text
        return str(upload.json()["batch_id"]), str(upload.json()["file_id"])

    async def upload(self, name: str, data: bytes) -> tuple[str, str]:
        """Upload a file and prepare its claims. Returns (batch id, file id)."""
        batch_id, file_id = await self.upload_only(name, data)
        prepared = await self.client.post(
            f"/api/v1/sources/batches/{batch_id}/compile", params=self.query
        )
        assert prepared.status_code == 200, prepared.text
        return batch_id, file_id

    async def claims(self, batch_id: str) -> list[dict[str, Any]]:
        response = await self.client.get(
            f"/api/v1/sources/batches/{batch_id}/claims", params=self.query
        )
        assert response.status_code == 200, response.text
        return list(response.json())

    async def columns(self, batch_id: str, **params: str) -> dict[str, Any]:
        response = await self.client.get(
            f"/api/v1/sources/batches/{batch_id}/columns", params={**self.query, **params}
        )
        assert response.status_code == 200, response.text
        return dict(response.json())

    async def decide(self, batch_id: str, file_id: str, decision: str, **body: Any) -> Any:
        return await self.client.post(
            f"/api/v1/sources/batches/{batch_id}/columns/review",
            params=self.query,
            json={
                "decision": decision,
                "rationale": RATIONALE,
                "source_file_id": file_id,
                **body,
            },
        )

    async def review_one(self, batch_id: str, claim_id: str, decision: str, **body: Any) -> Any:
        """The decision for a single value, as the table of values makes it."""
        return await self.client.post(
            f"/api/v1/sources/batches/{batch_id}/claims/{claim_id}/review",
            params=self.query,
            json={"decision": decision, "rationale": RATIONALE, **body},
        )

    async def publish(self, batch_id: str) -> Any:
        return await self.client.post(
            f"/api/v1/graph/batches/{batch_id}/compile", params=self.query
        )

    async def readiness(self, batch_id: str) -> dict[str, Any]:
        response = await self.client.post(
            f"/api/v1/readiness/batches/{batch_id}", params=self.query
        )
        assert response.status_code == 200, response.text
        return dict(response.json())


@pytest.fixture
async def review(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[_Review]:
    workspace_id = str(uuid4())
    storage = _MemoryStorage()
    monkeypatch.setattr(storage_client, "get_storage", lambda settings=None: storage)
    actor: dict[str, Any] = {
        "user_id": str(uuid4()),
        "roles": ["admin"],
        "workspace_ids": [workspace_id],
    }

    app = FastAPI()
    app.include_router(sources.router, prefix="/api/v1/sources")
    app.include_router(graph.router, prefix="/api/v1/graph")
    app.include_router(readiness.router, prefix="/api/v1/readiness")

    async def override_db() -> AsyncGenerator[AsyncSession]:
        yield db_session

    async def override_user() -> AuthContext:
        return AuthContext(
            user_id=actor["user_id"],
            roles=list(actor["roles"]),
            workspace_ids=list(actor["workspace_ids"]),
            is_anonymous=False,
        )

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield _Review(client, workspace_id, actor)


def _rows(data: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(data.decode())))


def _by_column(claims: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for claim in claims:
        grouped.setdefault(claim["source_column"], []).append(claim)
    return grouped


def _column(view: dict[str, Any], name: str) -> dict[str, Any]:
    (file,) = view["files"]
    return next(column for column in file["columns"] if column["source_column"] == name)


async def _published(db: AsyncSession, workspace_id: str, entity_type: str) -> dict[str, dict]:
    nodes = (
        await db.scalars(
            select(GraphNode)
            .where(GraphNode.workspace_id == workspace_id)
            .where(GraphNode.entity_type == entity_type)
        )
    ).all()
    return {node.entity_id: dict(node.attributes) for node in nodes}


async def _stored_claims(db: AsyncSession, batch_id: str) -> list[EvidenceClaim]:
    # The routes changed these rows through the same session.
    db.expire_all()
    result = await db.scalars(select(EvidenceClaim).where(EvidenceClaim.batch_id == batch_id))
    return list(result.all())


def _as_published(data: bytes, entity: str, leave_out: tuple[str, ...] = ()) -> dict[str, dict]:
    """The rows of a file as records: key -> its fields under the published names."""
    key_field = ENTITY_PRIMARY_KEYS[entity]
    records: dict[str, dict] = {}
    for row in _rows(data):
        fields = {
            canonical_column_name(column, entity): value
            for column, value in row.items()
            if column not in leave_out
        }
        records[fields[key_field]] = fields
    return records


# ── Preparing a file ────────────────────────────────────────────────


async def test_preparing_a_file_says_what_its_rows_are(
    review: _Review, db_session: AsyncSession
) -> None:
    batch_id, _ = await review.upload_only("suppliers.csv", SUPPLIERS_CSV)
    prepared = await review.client.post(
        f"/api/v1/sources/batches/{batch_id}/compile", params=review.query
    )
    assert prepared.status_code == 200, prepared.text

    claims = await review.claims(batch_id)

    assert len(claims) == 6 * 7
    assert {claim["canonical_entity"] for claim in claims} == {"Supplier"}
    for claim in claims:
        # The name publishing gives the column, not a guess about it.
        assert claim["canonical_field"] == canonical_column_name(claim["source_column"], "Supplier")
        assert claim["confidence"] == 1.0
        # Nothing about the name is in doubt ...
        assert claim["requires_review"] is False
        # ... and the value is still for a person to decide.
        assert claim["claim_state"] == ClaimState.PENDING_REVIEW.value
    assert _by_column(claims)["supplier_id"][0]["canonical_field"] == "supplier_id"
    # The answer counts the values whose name is a guess. None is here,
    # although all 42 wait for a decision.
    assert prepared.json()["claims_created"] == 6 * 7
    assert prepared.json()["claims_requiring_review"] == 0
    stored = await _stored_claims(db_session, batch_id)
    assert {claim.provenance["mapping_source"] for claim in stored} == {"row_entity"}


async def test_a_column_that_names_another_record_gets_the_field_publishing_uses(
    review: _Review,
) -> None:
    batch_id, _ = await review.upload("purchase_orders.csv", ORDERS_CSV)

    claims = _by_column(await review.claims(batch_id))
    view = await review.columns(batch_id)

    assert {claim["canonical_entity"] for group in claims.values() for claim in group} == {
        "PurchaseOrder"
    }
    linked = 0
    for column in ("supplier_id", "ship_to_warehouse_id", "sku", "quantity"):
        published_as = canonical_column_name(column, "PurchaseOrder")
        assert {claim["canonical_field"] for claim in claims[column]} == {published_as}
        shown = _column(view, column)
        assert shown["canonical_field"] == published_as
        link = ENTITY_FOREIGN_KEYS.get(("PurchaseOrder", published_as))
        if link is None:
            assert (shown["role"], shown["links_to"]) == ("value", None)
        else:
            assert (shown["role"], shown["links_to"]) == ("link", link[0])
            linked += 1
    # The supplier of an order is another record, and the view says so.
    assert _column(view, "supplier_id")["links_to"] == "Supplier"
    assert linked >= 1
    assert _column(view, "po_number")["role"] == "key"


async def test_a_file_whose_columns_do_not_say_keeps_the_profilers_guess(
    review: _Review, db_session: AsyncSession
) -> None:
    batch_id, _ = await review.upload("lieferanten.csv", LIEFERANTEN_CSV)

    claims = await review.claims(batch_id)
    assert len(claims) == 6
    # Nothing says what a row is, so nothing is claimed about it.
    assert {claim["canonical_entity"] for claim in claims} == {None}
    stored = await _stored_claims(db_session, batch_id)
    assert {claim.provenance["mapping_source"] for claim in stored} == {"column_profile"}

    (file,) = (await review.columns(batch_id))["files"]
    assert (file["entity"], file["entity_source"], file["key_column"]) == (None, None, None)
    assert [column["role"] for column in file["columns"]] == ["value", "value", "value"]


async def test_a_single_value_can_be_accepted_as_suggested(review: _Review) -> None:
    """It used to need the kind of record typed into a dialog for every cell."""
    batch_id, _ = await review.upload("suppliers.csv", SUPPLIERS_CSV)
    claim = _by_column(await review.claims(batch_id))["country"][0]

    accepted = await review.review_one(batch_id, claim["claim_id"], "accepted")

    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["claim_state"] == ClaimState.ACCEPTED.value
    assert accepted.json()["canonical_entity"] == "Supplier"
    assert accepted.json()["canonical_field"] == canonical_column_name("country", "Supplier")

    # A file that does not say what its rows are still needs to be told.
    other_batch, _ = await review.upload("lieferanten.csv", LIEFERANTEN_CSV)
    unnamed = (await review.claims(other_batch))[0]
    refused = await review.review_one(other_batch, unnamed["claim_id"], "accepted")
    assert refused.status_code == 422, refused.text


# ── The view of the columns ─────────────────────────────────────────


async def test_the_column_view_says_what_each_column_is(review: _Review) -> None:
    batch_id, file_id = await review.upload("suppliers.csv", SUPPLIERS_CSV)

    view = await review.columns(batch_id)

    assert view["batch_id"] == batch_id
    (file,) = view["files"]
    assert file["file_id"] == file_id
    assert file["name"] == "suppliers.csv"
    assert file["rows"] == 6
    assert (file["entity"], file["entity_source"]) == ("Supplier", "columns")
    assert (file["key_field"], file["key_column"]) == ("supplier_id", "supplier_id")
    assert file["problem"] is None
    # In the order of the file.
    assert [column["source_column"] for column in file["columns"]] == SUPPLIER_COLUMNS
    assert [column["role"] for column in file["columns"]] == ["key"] + ["value"] * 6
    for column in file["columns"]:
        assert column["canonical_field"] == canonical_column_name(
            column["source_column"], "Supplier"
        )
        assert (column["pending"], column["accepted"], column["rejected"]) == (6, 0, 0)
        assert (column["superseded"], column["in_conflict"]) == (0, 0)
    # A few of its values, from the top of the file.
    assert _column(view, "supplier_id")["examples"] == ["S-100", "S-101", "S-102"]
    assert _column(view, "country")["examples"] == ["DE", "IN", "CN"]
    assert _column(view, "tier")["examples"] == ["tier_1", "tier_2", "tier_3"]

    # The kinds a file can be told it holds, each with what identifies one.
    kinds = {kind["entity"]: kind["key_field"] for kind in view["record_kinds"]}
    assert kinds == ENTITY_PRIMARY_KEYS
    assert [kind["entity"] for kind in view["record_kinds"]] == sorted(ENTITY_PRIMARY_KEYS)


async def test_the_column_view_follows_the_decisions(review: _Review) -> None:
    batch_id, file_id = await review.upload("suppliers.csv", SUPPLIERS_CSV)

    assert (await review.decide(batch_id, file_id, "rejected", source_columns=["tier"])).is_success
    view = await review.columns(batch_id)
    assert (_column(view, "tier")["pending"], _column(view, "tier")["rejected"]) == (0, 6)
    assert _column(view, "country")["pending"] == 6

    assert (await review.decide(batch_id, file_id, "accepted")).is_success
    view = await review.columns(batch_id)
    for name in SUPPLIER_COLUMNS:
        column = _column(view, name)
        expected = (0, 0, 6) if name == "tier" else (0, 6, 0)
        assert (column["pending"], column["accepted"], column["rejected"]) == expected, name


async def test_the_column_view_of_an_unprepared_upload_shows_its_columns(
    review: _Review,
) -> None:
    batch_id, _ = await review.upload_only("suppliers.csv", SUPPLIERS_CSV)

    (file,) = (await review.columns(batch_id))["files"]

    assert (file["entity"], file["key_column"]) == ("Supplier", "supplier_id")
    assert [column["source_column"] for column in file["columns"]] == SUPPLIER_COLUMNS
    # Nothing to decide yet; the examples are what the profiler kept.
    assert {column["pending"] for column in file["columns"]} == {0}
    assert all(column["examples"] for column in file["columns"])
    assert set(_column({"files": [file]}, "country")["examples"]) <= {
        "DE",
        "IN",
        "CN",
        "SE",
        "US",
        "JP",
    }


# ── One decision for a file ─────────────────────────────────────────


async def test_one_decision_accepts_a_file_and_it_publishes_as_it_reads(
    review: _Review, db_session: AsyncSession
) -> None:
    batch_id, file_id = await review.upload("suppliers.csv", SUPPLIERS_CSV)

    decided = await review.decide(batch_id, file_id, "accepted")

    assert decided.status_code == 200, decided.text
    body = decided.json()
    assert body["decision"] == "accepted"
    assert body["source_file_id"] == file_id
    assert body["canonical_entity"] == "Supplier"
    assert body["columns"] == {
        column: canonical_column_name(column, "Supplier") for column in SUPPLIER_COLUMNS
    }
    assert body["claims_decided"] == 42
    assert (body["claims_left_in_conflict"], body["conflicts_detected"]) == (0, 0)
    assert body["readiness"] == "ready"

    stored = await _stored_claims(db_session, batch_id)
    assert {claim.claim_state for claim in stored} == {ClaimState.ACCEPTED.value}
    assert {claim.provenance["human_mapping_review"]["scope"] for claim in stored} == {"column"}
    # Each value knows the record of its own row.
    by_row = {
        row: {c.provenance["entity_key"] for c in stored if c.row_number == row}
        for row in range(1, 7)
    }
    assert by_row == {row: {f"S-10{row - 1}"} for row in range(1, 7)}

    # One decision, recorded once, with the reason given.
    events = (
        await db_session.scalars(
            select(AuditEvent)
            .where(AuditEvent.workspace_id == review.workspace_id)
            .where(AuditEvent.event_type == "evidence.columns.reviewed")
        )
    ).all()
    assert len(events) == 1
    assert events[0].payload["rationale"] == RATIONALE
    assert events[0].payload["claims_decided"] == 42
    assert events[0].payload["source_file"] == "suppliers.csv"
    assert events[0].actor_id == review.actor["user_id"]

    published = await review.publish(batch_id)
    assert published.status_code == 200, published.text
    assert published.json()["node_count"] == 6
    assert await _published(db_session, review.workspace_id, "Supplier") == _as_published(
        SUPPLIERS_CSV, "Supplier"
    )


async def test_accepting_stock_by_column_does_not_invent_conflicts(
    review: _Review, db_session: AsyncSession
) -> None:
    """The guess put the stock on hand and the safety stock under one field,
    which made every row of an inventory file disagree with itself."""
    batch_id, file_id = await review.upload("inventory.csv", INVENTORY_CSV)

    view = await review.columns(batch_id)
    on_hand = _column(view, "quantity_on_hand")["canonical_field"]
    safety = _column(view, "safety_stock")["canonical_field"]
    assert on_hand != safety

    decided = await review.decide(batch_id, file_id, "accepted")
    assert decided.status_code == 200, decided.text
    assert decided.json()["claims_decided"] == 30
    assert decided.json()["conflicts_detected"] == 0
    assert decided.json()["readiness"] == "ready"

    published = await review.publish(batch_id)
    assert published.status_code == 200, published.text
    (entity,) = {claim["canonical_entity"] for claim in await review.claims(batch_id)}
    records = await _published(db_session, review.workspace_id, entity)
    assert len(records) == 6
    stock = sorted((record[on_hand], record[safety]) for record in records.values())
    assert stock == sorted(
        (row["quantity_on_hand"], row["safety_stock"]) for row in _rows(INVENTORY_CSV)
    )


async def test_rows_that_disagree_about_one_record_still_block_publishing(
    review: _Review,
) -> None:
    batch_id, file_id = await review.upload("suppliers.csv", DISAGREEING_CSV)

    decided = await review.decide(batch_id, file_id, "accepted")

    assert decided.status_code == 200, decided.text
    assert decided.json()["claims_decided"] == 9
    # Rows 1 and 2 give supplier S-100 two countries.
    assert decided.json()["conflicts_detected"] == 1
    assert decided.json()["readiness"] == "blocked"
    assert (await review.readiness(batch_id))["blocking_conflict_count"] == 1

    refused = await review.publish(batch_id)
    assert refused.status_code == 409, refused.text


async def test_a_second_decision_finds_nothing_left(review: _Review) -> None:
    batch_id, file_id = await review.upload("suppliers.csv", SUPPLIERS_CSV)
    assert (await review.decide(batch_id, file_id, "accepted")).is_success

    again = await review.decide(batch_id, file_id, "accepted")

    assert again.status_code == 409, again.text
    assert again.json()["detail"] == "No value of these columns waits for a decision."


async def test_a_whole_file_can_be_rejected(review: _Review, db_session: AsyncSession) -> None:
    batch_id, file_id = await review.upload("suppliers.csv", SUPPLIERS_CSV)

    decided = await review.decide(batch_id, file_id, "rejected")

    assert decided.status_code == 200, decided.text
    assert decided.json()["claims_decided"] == 42
    assert decided.json()["canonical_entity"] is None
    assert decided.json()["columns"] == {column: None for column in SUPPLIER_COLUMNS}
    stored = await _stored_claims(db_session, batch_id)
    assert {claim.claim_state for claim in stored} == {ClaimState.REJECTED.value}
    # Nothing accepted, nothing to publish.
    assert (await review.publish(batch_id)).status_code == 409


async def test_readiness_does_not_call_rejected_values_accepted(review: _Review) -> None:
    # Rejecting a column is one click, so "all claims accepted" would stand
    # on the page beside the count of rejected values.
    batch_id, file_id = await review.upload("suppliers.csv", SUPPLIERS_CSV)
    assert (await review.decide(batch_id, file_id, "rejected", source_columns=["tier"])).is_success
    assert (await review.decide(batch_id, file_id, "accepted")).is_success

    readiness = await review.readiness(batch_id)

    assert readiness["state"] == "ready"
    assert readiness["accepted_claim_count"] == 36
    assert readiness["explanation"] == (
        "36 claims accepted and 6 rejected, no conflicts. "
        "The accepted claims are ready for downstream use."
    )


async def test_readiness_of_a_wholly_rejected_file_says_nothing_can_be_published(
    review: _Review,
) -> None:
    batch_id, file_id = await review.upload("suppliers.csv", SUPPLIERS_CSV)
    assert (await review.decide(batch_id, file_id, "rejected")).is_success

    readiness = await review.readiness(batch_id)

    assert readiness["accepted_claim_count"] == 0
    assert readiness["explanation"] == (
        "Every claim was rejected, so nothing of this batch can be published."
    )


async def test_readiness_of_a_wholly_accepted_file_reads_as_before(review: _Review) -> None:
    batch_id, file_id = await review.upload("suppliers.csv", SUPPLIERS_CSV)
    assert (await review.decide(batch_id, file_id, "accepted")).is_success

    readiness = await review.readiness(batch_id)

    assert readiness["state"] == "ready"
    assert readiness["explanation"] == (
        "All claims accepted, no conflicts. Batch is ready for downstream use."
    )


async def test_readiness_writes_large_counts_as_the_page_does(review: _Review) -> None:
    rows = "".join(f"S-{number},Supplier {number},DE\n" for number in range(1, 351))
    batch_id, _ = await review.upload(
        "many_suppliers.csv", f"supplier_id,supplier_name,country\n{rows}".encode()
    )

    readiness = await review.readiness(batch_id)

    assert readiness["pending_claim_count"] == 1050
    assert readiness["explanation"] == "1,050 claims and 0 conflicts require review."


async def test_columns_are_decided_one_at_a_time_and_a_rejected_one_is_left_out(
    review: _Review, db_session: AsyncSession
) -> None:
    batch_id, file_id = await review.upload("suppliers.csv", SUPPLIERS_CSV)

    rejected = await review.decide(batch_id, file_id, "rejected", source_columns=["tier"])
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["claims_decided"] == 6
    assert rejected.json()["columns"] == {"tier": None}
    assert rejected.json()["readiness"] == "review_required"

    for column in ("supplier_id", "supplier_name"):
        one = await review.decide(batch_id, file_id, "accepted", source_columns=[column])
        assert one.status_code == 200, one.text
        assert one.json()["claims_decided"] == 6
        assert list(one.json()["columns"]) == [column]

    rest = await review.decide(batch_id, file_id, "accepted")
    assert rest.status_code == 200, rest.text
    # What was still waiting, and only that.
    assert rest.json()["claims_decided"] == 6 * 4
    assert sorted(rest.json()["columns"]) == sorted(
        ["country", "lead_time_days", "status", "on_time_rate"]
    )
    assert rest.json()["readiness"] == "ready"

    assert (await review.publish(batch_id)).status_code == 200
    assert await _published(db_session, review.workspace_id, "Supplier") == _as_published(
        SUPPLIERS_CSV, "Supplier", leave_out=("tier",)
    )


async def test_a_value_rejected_on_its_own_stays_rejected(
    review: _Review, db_session: AsyncSession
) -> None:
    batch_id, file_id = await review.upload("suppliers.csv", SUPPLIERS_CSV)
    wrong = next(
        claim
        for claim in await review.claims(batch_id)
        if claim["source_column"] == "on_time_rate" and claim["row_number"] == 2
    )
    assert (await review.review_one(batch_id, wrong["claim_id"], "rejected")).is_success

    decided = await review.decide(batch_id, file_id, "accepted")

    assert decided.status_code == 200, decided.text
    assert decided.json()["claims_decided"] == 41
    states = {claim["claim_id"]: claim["claim_state"] for claim in await review.claims(batch_id)}
    assert states[wrong["claim_id"]] == ClaimState.REJECTED.value

    assert (await review.publish(batch_id)).status_code == 200
    records = await _published(db_session, review.workspace_id, "Supplier")
    rate = canonical_column_name("on_time_rate", "Supplier")
    assert rate not in records["S-101"]
    assert records["S-100"][rate] == "0.96"


async def test_a_column_can_be_published_under_another_name(
    review: _Review, db_session: AsyncSession
) -> None:
    batch_id, file_id = await review.upload("suppliers.csv", SUPPLIERS_CSV)

    decided = await review.decide(
        batch_id, file_id, "accepted", canonical_fields={"on_time_rate": "delivery_reliability"}
    )

    assert decided.status_code == 200, decided.text
    assert decided.json()["columns"]["on_time_rate"] == "delivery_reliability"
    assert _column(await review.columns(batch_id), "on_time_rate")["canonical_field"] == (
        "delivery_reliability"
    )
    assert (await review.publish(batch_id)).status_code == 200
    records = await _published(db_session, review.workspace_id, "Supplier")
    assert records["S-103"]["delivery_reliability"] == "0.99"
    assert "on_time_rate" not in records["S-103"]


async def test_the_rest_of_a_column_keeps_the_name_its_accepted_values_have(
    review: _Review,
) -> None:
    batch_id, file_id = await review.upload("suppliers.csv", SUPPLIERS_CSV)
    first = _by_column(await review.claims(batch_id))["country"][0]
    named = await review.review_one(
        batch_id,
        first["claim_id"],
        "accepted",
        canonical_entity="Supplier",
        canonical_field="registered_country",
    )
    assert named.status_code == 200, named.text
    assert _column(await review.columns(batch_id), "country")["canonical_field"] == (
        "registered_country"
    )

    # One column, one name: another name for the rest would split it.
    other = await review.decide(
        batch_id,
        file_id,
        "accepted",
        source_columns=["country"],
        canonical_fields={"country": "nation"},
    )
    assert other.status_code == 422, other.text
    assert other.json()["detail"] == (
        "country already has accepted values published as registered_country; "
        "the rest of the column has to use the same name"
    )

    rest = await review.decide(batch_id, file_id, "accepted", source_columns=["country"])
    assert rest.status_code == 200, rest.text
    assert rest.json()["claims_decided"] == 5
    assert rest.json()["columns"] == {"country": "registered_country"}
    country = _by_column(await review.claims(batch_id))["country"]
    assert {claim["canonical_field"] for claim in country} == {"registered_country"}


# ── Decisions that are refused, with nothing changed ──────────────────────────


async def _nothing_decided(review: _Review, batch_id: str) -> bool:
    claims = await review.claims(batch_id)
    return {claim["claim_state"] for claim in claims} == {ClaimState.PENDING_REVIEW.value}


async def test_the_identifying_column_cannot_be_rejected_on_its_own(review: _Review) -> None:
    batch_id, file_id = await review.upload("suppliers.csv", SUPPLIERS_CSV)

    refused = await review.decide(batch_id, file_id, "rejected", source_columns=["supplier_id"])

    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"].startswith(
        "supplier_id identifies the record of each row. Without it the other columns"
    )
    assert "Reject every column of the file instead" in refused.json()["detail"]
    assert await _nothing_decided(review, batch_id)

    # With every other column it is the whole file, which can be rejected.
    whole = await review.decide(batch_id, file_id, "rejected", source_columns=SUPPLIER_COLUMNS)
    assert whole.status_code == 200, whole.text


async def test_nothing_is_accepted_once_the_identifying_values_are_gone(
    review: _Review,
) -> None:
    batch_id, file_id = await review.upload("suppliers.csv", SUPPLIERS_CSV)
    for claim in _by_column(await review.claims(batch_id))["supplier_id"]:
        assert (await review.review_one(batch_id, claim["claim_id"], "rejected")).is_success

    refused = await review.decide(batch_id, file_id, "accepted")

    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"] == (
        "The values of supplier_id, which identifies each Supplier, were all rejected or "
        "withdrawn. Without them no row of this file can be published."
    )
    waiting = [
        claim for claim in await review.claims(batch_id) if claim["source_column"] != "supplier_id"
    ]
    assert {claim["claim_state"] for claim in waiting} == {ClaimState.PENDING_REVIEW.value}


async def test_two_columns_cannot_be_published_under_one_field(review: _Review) -> None:
    batch_id, file_id = await review.upload("suppliers.csv", SUPPLIERS_CSV)
    status_field = canonical_column_name("status", "Supplier")

    refused = await review.decide(
        batch_id, file_id, "accepted", canonical_fields={"tier": status_field}
    )

    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"] == (
        f"tier and status would both be published as {status_field}. "
        "Give each its own field name, or reject one of them."
    )
    assert await _nothing_decided(review, batch_id)


@pytest.mark.parametrize(
    ("body", "said"),
    [
        ({"source_columns": ["no_such_column"]}, "no_such_column: not a column of suppliers.csv"),
        ({"source_columns": []}, "Name at least one column, or leave the list out for all"),
        ({"canonical_fields": {"tier": "Not A Name"}}, "cannot be a field name"),
        ({"canonical_fields": {"no_such_column": "tier"}}, "no_such_column: not a column of"),
        (
            {"source_columns": ["supplier_id"], "canonical_fields": {"tier": "level"}},
            "A field name was given for tier, which is not part of this decision",
        ),
        (
            {"canonical_entity": "PurchaseOrder"},
            "The rows of this file are Supplier records (recognised from its column names); "
            "they cannot be accepted as PurchaseOrder.",
        ),
    ],
)
async def test_an_acceptance_that_cannot_be_published_is_refused(
    review: _Review, body: dict[str, Any], said: str
) -> None:
    batch_id, file_id = await review.upload("suppliers.csv", SUPPLIERS_CSV)

    refused = await review.decide(batch_id, file_id, "accepted", **body)

    assert refused.status_code == 422, refused.text
    assert said in refused.json()["detail"]
    assert await _nothing_decided(review, batch_id)


async def test_a_rejection_takes_no_mapping(review: _Review) -> None:
    batch_id, file_id = await review.upload("suppliers.csv", SUPPLIERS_CSV)

    for body in ({"canonical_entity": "Supplier"}, {"canonical_fields": {"tier": "level"}}):
        refused = await review.decide(batch_id, file_id, "rejected", **body)
        assert refused.status_code == 422, refused.text
        assert refused.json()["detail"] == "A rejection takes no kind of record and no field names"
    assert await _nothing_decided(review, batch_id)


async def test_a_decision_needs_a_reason(review: _Review) -> None:
    batch_id, file_id = await review.upload("suppliers.csv", SUPPLIERS_CSV)

    for rationale in ("", "ok"):
        refused = await review.decide(batch_id, file_id, "accepted", rationale=rationale)
        assert refused.status_code == 422, refused.text
    unknown = await review.decide(batch_id, file_id, "maybe")
    assert unknown.status_code == 422, unknown.text
    assert await _nothing_decided(review, batch_id)


async def test_values_in_an_open_conflict_are_left_to_the_conflict(
    review: _Review, db_session: AsyncSession
) -> None:
    batch_id, file_id = await review.upload("suppliers.csv", SUPPLIERS_CSV)
    disputed = [c for c in await review.claims(batch_id) if c["source_column"] == "country"][:2]
    db_session.add(
        EvidenceConflict(
            conflict_id=str(uuid4()),
            workspace_id=review.workspace_id,
            batch_id=batch_id,
            claim_ids=[claim["claim_id"] for claim in disputed],
            canonical_entity="Supplier",
            canonical_field="country",
            severity="major",
            blocking=True,
            status="open",
            review_required=True,
            explanation="Raised by an earlier review.",
        )
    )
    await db_session.flush()
    assert _column(await review.columns(batch_id), "country")["in_conflict"] == 2

    decided = await review.decide(batch_id, file_id, "accepted")
    assert decided.status_code == 200, decided.text
    assert decided.json()["claims_decided"] == 40
    assert decided.json()["claims_left_in_conflict"] == 2
    assert decided.json()["readiness"] == "blocked"
    states = {claim["claim_id"]: claim["claim_state"] for claim in await review.claims(batch_id)}
    assert {states[claim["claim_id"]] for claim in disputed} == {ClaimState.PENDING_REVIEW.value}

    # Only the conflict can decide them now, and the answer says so.
    again = await review.decide(batch_id, file_id, "accepted", source_columns=["country"])
    assert again.status_code == 409, again.text
    assert again.json()["detail"] == (
        "2 values of these columns belong to an open conflict and can only be decided there."
    )


# ── A file whose columns do not say what its rows are ───────────────────────


async def test_a_file_nothing_recognises_needs_its_kind_and_its_identifying_column(
    review: _Review, db_session: AsyncSession
) -> None:
    batch_id, file_id = await review.upload("lieferanten.csv", LIEFERANTEN_CSV)

    untold = await review.decide(batch_id, file_id, "accepted")
    assert untold.status_code == 422, untold.text
    assert untold.json()["detail"] == (
        "The column names do not say what kind of record each row of this file is. "
        "Choose the kind of record and the column that identifies each one."
    )

    unknown_kind = await review.decide(batch_id, file_id, "accepted", canonical_entity="Spaceship")
    assert unknown_kind.status_code == 422, unknown_kind.text
    assert unknown_kind.json()["detail"] == "Spaceship is not a kind of record a file can hold"

    no_key = await review.decide(batch_id, file_id, "accepted", canonical_entity="Supplier")
    assert no_key.status_code == 422, no_key.text
    assert no_key.json()["detail"] == (
        "No column of this file holds the supplier_id that identifies each Supplier. "
        "Name the column that does (publish it as supplier_id), or choose another kind of record."
    )
    assert await _nothing_decided(review, batch_id)

    # What the columns would be for a kind that is only being considered.
    (proposed,) = (await review.columns(batch_id, entity="Supplier"))["files"]
    assert (proposed["entity"], proposed["entity_source"]) == ("Supplier", "proposed")
    assert (proposed["key_field"], proposed["key_column"]) == ("supplier_id", None)

    told = await review.decide(
        batch_id,
        file_id,
        "accepted",
        canonical_entity="Supplier",
        canonical_fields={"Lieferant Nr": "supplier_id", "Firma": "supplier_name"},
    )
    assert told.status_code == 200, told.text
    assert told.json()["canonical_entity"] == "Supplier"
    assert told.json()["claims_decided"] == 6
    assert told.json()["columns"]["Lieferant Nr"] == "supplier_id"
    assert told.json()["columns"]["Firma"] == "supplier_name"
    land = told.json()["columns"]["Land"]
    assert told.json()["readiness"] == "ready"

    # From here on the accepted values say what the rows are.
    (file,) = (await review.columns(batch_id))["files"]
    assert (file["entity"], file["entity_source"]) == ("Supplier", "review")
    assert (file["key_field"], file["key_column"]) == ("supplier_id", "Lieferant Nr")
    assert _column({"files": [file]}, "Lieferant Nr")["role"] == "key"

    published = await review.publish(batch_id)
    assert published.status_code == 200, published.text
    assert await _published(db_session, review.workspace_id, "Supplier") == {
        "L-1": {"supplier_id": "L-1", "supplier_name": "Acme Metals GmbH", land: "DE"},
        "L-2": {"supplier_id": "L-2", "supplier_name": "Nordic Seals AB", land: "SE"},
    }


async def test_the_identifying_column_has_to_come_first(review: _Review) -> None:
    batch_id, file_id = await review.upload("lieferanten.csv", LIEFERANTEN_CSV)

    early = await review.decide(
        batch_id, file_id, "accepted", canonical_entity="Supplier", source_columns=["Firma"]
    )
    assert early.status_code == 422, early.text
    assert early.json()["detail"].startswith("No column of this file holds the supplier_id")
    # Naming it without deciding it is not enough either.
    aside = await review.decide(
        batch_id,
        file_id,
        "accepted",
        canonical_entity="Supplier",
        source_columns=["Firma"],
        canonical_fields={"Lieferant Nr": "supplier_id"},
    )
    assert aside.status_code == 422, aside.text
    assert await _nothing_decided(review, batch_id)

    key = await review.decide(
        batch_id,
        file_id,
        "accepted",
        canonical_entity="Supplier",
        source_columns=["Lieferant Nr"],
        canonical_fields={"Lieferant Nr": "supplier_id"},
    )
    assert key.status_code == 200, key.text
    assert key.json()["claims_decided"] == 2

    # The rest no longer needs to be told what the rows are.
    rest = await review.decide(batch_id, file_id, "accepted")
    assert rest.status_code == 200, rest.text
    assert rest.json()["canonical_entity"] == "Supplier"
    assert rest.json()["claims_decided"] == 4
    assert rest.json()["readiness"] == "ready"

    # And cannot be told something else.
    assert (await review.decide(batch_id, file_id, "accepted")).status_code == 409


async def test_claims_prepared_before_kinds_were_suggested_are_decided_the_same_way(
    review: _Review, db_session: AsyncSession
) -> None:
    """Uploads prepared earlier carry no kind of record and the profiler's guess."""
    batch_id, file_id = await review.upload("inventory.csv", INVENTORY_CSV)
    for claim in await _stored_claims(db_session, batch_id):
        claim.canonical_entity = None
        if claim.source_column in {"quantity_on_hand", "safety_stock"}:
            # The guess that made every row disagree with itself.
            claim.canonical_field = "quantity"
        claim.confidence = 0.7
        claim.provenance = {**claim.provenance, "mapping_source": None}
    await db_session.flush()

    view = await review.columns(batch_id)
    on_hand = _column(view, "quantity_on_hand")["canonical_field"]
    safety = _column(view, "safety_stock")["canonical_field"]
    assert "quantity" not in {on_hand, safety} or on_hand != safety

    decided = await review.decide(batch_id, file_id, "accepted")

    assert decided.status_code == 200, decided.text
    assert decided.json()["claims_decided"] == 30
    assert decided.json()["conflicts_detected"] == 0
    assert decided.json()["readiness"] == "ready"
    stored = await _stored_claims(db_session, batch_id)
    (entity,) = {claim.canonical_entity for claim in stored}
    assert entity == decided.json()["canonical_entity"]
    for claim in stored:
        assert claim.canonical_field == canonical_column_name(claim.source_column, entity)
        assert claim.confidence == 1.0
    assert (await review.publish(batch_id)).status_code == 200


# ── Who may decide ───────────────────────────────────────────────────


async def test_only_a_reviewer_of_the_workspace_decides(review: _Review) -> None:
    batch_id, file_id = await review.upload("suppliers.csv", SUPPLIERS_CSV)

    review.actor["roles"] = ["viewer"]
    # Reading how the file stands is open to everyone in the workspace.
    assert (await review.columns(batch_id))["files"][0]["entity"] == "Supplier"
    refused = await review.decide(batch_id, file_id, "accepted")
    assert refused.status_code == 403, refused.text

    review.actor["roles"] = ["admin"]
    review.actor["workspace_ids"] = [str(uuid4())]
    outsider = await review.decide(batch_id, file_id, "accepted")
    assert outsider.status_code == 403, outsider.text
    listing = await review.client.get(
        f"/api/v1/sources/batches/{batch_id}/columns", params=review.query
    )
    assert listing.status_code == 403, listing.text

    review.actor["workspace_ids"] = [review.workspace_id]
    assert await _nothing_decided(review, batch_id)
    review.actor["roles"] = ["operator"]
    assert (await review.decide(batch_id, file_id, "accepted")).status_code == 200


async def test_a_batch_of_another_workspace_is_not_found(review: _Review) -> None:
    batch_id, file_id = await review.upload("suppliers.csv", SUPPLIERS_CSV)
    other_batch, other_file = await review.upload("more.csv", DISAGREEING_CSV)

    # A file of another batch is not a file of this one.
    mixed = await review.decide(batch_id, other_file, "accepted")
    assert mixed.status_code == 404, mixed.text
    assert mixed.json()["detail"] == "File not found in this batch"
    assert (await review.decide(batch_id, str(uuid4()), "accepted")).status_code == 404

    # Someone of another workspace asking in their own workspace's name.
    elsewhere = str(uuid4())
    review.actor["workspace_ids"] = [elsewhere]
    query = {"workspace_id": elsewhere}
    listing = await review.client.get(f"/api/v1/sources/batches/{batch_id}/columns", params=query)
    assert listing.status_code == 404, listing.text
    decided = await review.client.post(
        f"/api/v1/sources/batches/{batch_id}/columns/review",
        params=query,
        json={"decision": "accepted", "rationale": RATIONALE, "source_file_id": file_id},
    )
    assert decided.status_code == 404, decided.text

    review.actor["workspace_ids"] = [review.workspace_id]
    assert await _nothing_decided(review, batch_id)
    assert await _nothing_decided(review, other_batch)


async def test_an_unknown_kind_of_record_cannot_be_asked_for(review: _Review) -> None:
    batch_id, _ = await review.upload("lieferanten.csv", LIEFERANTEN_CSV)

    response = await review.client.get(
        f"/api/v1/sources/batches/{batch_id}/columns",
        params={**review.query, "entity": "Spaceship"},
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "Unsupported kind of record"


# ── A file that is too large ─────────────────────────────────────────────


async def test_a_file_with_more_values_than_one_upload_holds_is_refused_with_its_size(
    review: _Review, monkeypatch: pytest.MonkeyPatch
) -> None:
    """It used to end in an internal error after a quarter of a million claims."""
    from app.modules.compiler import service

    monkeypatch.setattr(service, "MAX_CLAIMS_PER_FILE", 20)
    batch_id, _ = await review.upload_only("suppliers.csv", SUPPLIERS_CSV)

    # Six rows of seven values.
    refused = await review.client.post(
        f"/api/v1/sources/batches/{batch_id}/compile", params=review.query
    )
    assert refused.status_code == 413, refused.text
    assert refused.json()["detail"] == (
        "suppliers.csv holds 42 values (rows times columns, empty cells not counted). "
        "One file can hold at most 20. Split it into smaller files and upload each."
    )
    # Nothing of it was kept.
    assert await review.claims(batch_id) == []

    # A file that just fits is prepared as usual.
    monkeypatch.setattr(service, "MAX_CLAIMS_PER_FILE", 42)
    prepared = await review.client.post(
        f"/api/v1/sources/batches/{batch_id}/compile", params=review.query
    )
    assert prepared.status_code == 200, prepared.text
    assert prepared.json()["claims_created"] == 42


# ── The view is counted in the database; a decision reads the values ──────────


async def _both_views(
    db: AsyncSession, workspace_id: str, batch_id: str, proposed: str | None = None
) -> tuple[Any, Any]:
    """The description of a file as the view builds it and as a decision does."""
    from app.modules.compiler import column_review

    # The routes changed these rows through the same session.
    db.expire_all()
    file = (await db.scalars(select(SourceFile).where(SourceFile.batch_id == batch_id))).one()
    counted = column_review._describe(
        await column_review._facts_from_database(db, workspace_id, batch_id, file), proposed
    )
    read = column_review._describe(
        await column_review._load_file_state(db, workspace_id, batch_id, file), proposed
    )
    return counted, read


async def test_the_view_and_a_decision_describe_a_file_alike(
    review: _Review, db_session: AsyncSession
) -> None:
    """Two ways to the same description: they must not drift apart."""
    # Untouched.
    batch_id, file_id = await review.upload("suppliers.csv", SUPPLIERS_CSV)
    counted, read = await _both_views(db_session, review.workspace_id, batch_id)
    assert counted == read
    assert [column.pending for column in counted.columns] == [6] * 7

    # Every state at once: a rejected column, a renamed one, single values
    # decided on their own, two values in an open conflict, one withdrawn.
    claims = await review.claims(batch_id)
    disputed = [c for c in claims if c["source_column"] == "country"][:2]
    db_session.add(
        EvidenceConflict(
            conflict_id=str(uuid4()),
            workspace_id=review.workspace_id,
            batch_id=batch_id,
            claim_ids=[claim["claim_id"] for claim in disputed],
            canonical_entity="Supplier",
            canonical_field="country",
            severity="major",
            blocking=True,
            status="open",
            review_required=True,
            explanation="Raised by an earlier review.",
        )
    )
    await db_session.flush()
    assert (await review.decide(batch_id, file_id, "rejected", source_columns=["tier"])).is_success
    renamed = await review.decide(
        batch_id,
        file_id,
        "accepted",
        source_columns=["supplier_id", "on_time_rate"],
        canonical_fields={"on_time_rate": "delivery_reliability"},
    )
    assert renamed.is_success, renamed.text
    single = next(c for c in claims if c["source_column"] == "status" and c["row_number"] == 4)
    assert (await review.review_one(batch_id, single["claim_id"], "rejected")).is_success
    withdrawn = next(c for c in claims if c["source_column"] == "lead_time_days")
    stored = await db_session.get(EvidenceClaim, withdrawn["claim_id"])
    assert stored is not None
    stored.claim_state = ClaimState.SUPERSEDED.value
    await db_session.flush()

    counted, read = await _both_views(db_session, review.workspace_id, batch_id)
    assert counted == read
    by_name = {column.source_column: column for column in counted.columns}
    assert (by_name["tier"].rejected, by_name["tier"].pending) == (6, 0)
    assert by_name["on_time_rate"].canonical_field == "delivery_reliability"
    assert (by_name["country"].pending, by_name["country"].in_conflict) == (6, 2)
    assert (by_name["status"].pending, by_name["status"].rejected) == (5, 1)
    assert (by_name["lead_time_days"].pending, by_name["lead_time_days"].superseded) == (5, 1)
    assert by_name["supplier_id"].accepted == 6
    assert counted.key_column == "supplier_id"

    # What the route answers is the counted description.
    view = await review.columns(batch_id)
    assert {
        column["source_column"]: (
            column["pending"],
            column["accepted"],
            column["rejected"],
            column["superseded"],
            column["in_conflict"],
        )
        for column in view["files"][0]["columns"]
    } == {
        column.source_column: (
            column.pending,
            column.accepted,
            column.rejected,
            column.superseded,
            column.in_conflict,
        )
        for column in read.columns
    }


async def test_the_view_and_a_decision_agree_on_a_file_nothing_recognises(
    review: _Review, db_session: AsyncSession
) -> None:
    batch_id, file_id = await review.upload("lieferanten.csv", LIEFERANTEN_CSV)
    for proposed in (None, "Supplier"):
        counted, read = await _both_views(db_session, review.workspace_id, batch_id, proposed)
        assert counted == read
        assert counted.entity == proposed

    accepted = await review.decide(
        batch_id,
        file_id,
        "accepted",
        canonical_entity="Supplier",
        source_columns=["Lieferant Nr", "Firma"],
        canonical_fields={"Lieferant Nr": "supplier_id", "Firma": "supplier_name"},
    )
    assert accepted.is_success, accepted.text
    counted, read = await _both_views(db_session, review.workspace_id, batch_id)
    assert counted == read
    assert (counted.entity, counted.entity_source, counted.key_column) == (
        "Supplier",
        "review",
        "Lieferant Nr",
    )


async def test_the_examples_of_a_column_come_from_the_top_of_the_file(
    review: _Review, db_session: AsyncSession
) -> None:
    """Three distinct values in file order, looked for in the first rows only."""
    lines = ["supplier_id,supplier_name,country,status"]
    for number in range(1, 61):
        # The country repeats; the status changes only far down the file.
        status = "active" if number <= 40 else "on_hold"
        country = ("DE", "DE", "IN")[number % 3]
        lines.append(f"S-{number:02d},Supplier {number:02d},{country},{status}")
    batch_id, _ = await review.upload("suppliers.csv", ("\n".join(lines) + "\n").encode())

    view = await review.columns(batch_id)
    assert _column(view, "supplier_id")["examples"] == ["S-01", "S-02", "S-03"]
    assert _column(view, "country")["examples"] == ["DE", "IN"]
    assert _column(view, "status")["examples"] == ["active"]
    assert _column(view, "status")["pending"] == 60

    counted, read = await _both_views(db_session, review.workspace_id, batch_id)
    assert counted == read
