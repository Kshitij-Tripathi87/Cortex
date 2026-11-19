"""A published record is linked to the cells of its own row.

Regression: publishing linked every record of a file to every accepted value
of that file. That was one link per column while a claim covered a whole
column; since claims are one cell each it is rows x rows x columns. A file of
300 suppliers with eight columns wrote 720,000 links and took over a minute;
3,000 rows needed 72 million and the API process was killed for memory. Nobody
met it on the site because a file of that size could not be reviewed there;
reviewing by column made it one click away.

The links are also what the record is evidenced by, and "this supplier rests
on the cells of all 300 rows" is not true. A record now links to the accepted
cells of the rows that describe it, a relationship to the two cells that state
it, and a record that is only referred to links to the cells that name it.

The tests drive upload -> prepare -> review by column -> publish over HTTP.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import graph, sources
from app.common.enums import ClaimState
from app.common.ids import uuid7
from app.infrastructure import storage_client
from app.infrastructure.database import get_db
from app.infrastructure.security import AuthContext, get_current_user

# Register the models before the db_engine fixture copies Base.metadata.
from app.modules.audit.models import AuditEvent  # noqa: F401
from app.modules.compiler.models import EvidenceClaim, ReadinessAssessment  # noqa: F401
from app.modules.graph.models import (
    GraphEdge,
    GraphNode,
    GraphSnapshot,  # noqa: F401
    GraphWriteEvent,
    ProvenanceLink,
)
from app.modules.sources.models import SourceBatch, SourceColumnProfile, SourceFile  # noqa: F401

SUPPLIERS_CSV = (
    b"supplier_id,supplier_name,country,tier,lead_time_days,status\n"
    b"S-100,Acme Metals GmbH,DE,tier_1,21,active\n"
    b"S-101,Bharat Castings Pvt Ltd,IN,tier_1,35,delayed\n"
    b"S-102,Nordic Seals AB,SE,tier_2,14,active\n"
    b"S-103,Shenzhen Motor Works,CN,tier_1,42,active\n"
    b"S-104,Lakeshore Fasteners Inc,US,tier_2,10,active\n"
    b"S-105,Kyoto Bearings KK,JP,tier_1,28,at_risk\n"
    b"S-106,Porto Gaskets Lda,PT,tier_2,18,active\n"
    b"S-107,Gdansk Forgings SA,PL,tier_1,30,delayed\n"
)

# Three orders, two of them from the same supplier. No supplier file is
# published, so both suppliers exist only because an order names them.
ORDERS_CSV = (
    b"po_number,supplier_id,sku,quantity,status\n"
    b"PO-1,S-100,P-1,40,confirmed\n"
    b"PO-2,S-100,P-2,15,confirmed\n"
    b"PO-3,S-101,P-1,60,late\n"
)


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


@pytest.fixture
async def intake(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[tuple[AsyncClient, str]]:
    workspace_id = str(uuid4())
    storage = _MemoryStorage()
    monkeypatch.setattr(storage_client, "get_storage", lambda settings=None: storage)

    app = FastAPI()
    app.include_router(sources.router, prefix="/api/v1/sources")
    app.include_router(graph.router, prefix="/api/v1/graph")

    async def override_db() -> AsyncGenerator[AsyncSession]:
        yield db_session

    async def override_user() -> AuthContext:
        return AuthContext(
            user_id=str(uuid4()),
            roles=["admin"],
            workspace_ids=[workspace_id],
            is_anonymous=False,
        )

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, workspace_id


async def _prepare(client: AsyncClient, workspace_id: str, name: str, content: bytes) -> str:
    """Upload a file and prepare its claims; returns the batch."""
    upload = await client.post(
        "/api/v1/sources/upload",
        data={"workspace_id": workspace_id, "source_system_hint": "erp"},
        files={"file": (name, content, "text/csv")},
    )
    assert upload.status_code == 200, upload.text
    batch_id = str(upload.json()["batch_id"])
    prepared = await client.post(
        f"/api/v1/sources/batches/{batch_id}/compile", params={"workspace_id": workspace_id}
    )
    assert prepared.status_code == 200, prepared.text
    return batch_id


async def _decide(
    client: AsyncClient,
    workspace_id: str,
    batch_id: str,
    decision: str,
    columns: list[str] | None = None,
) -> None:
    """One decision for whole columns of the batch's only file (all when not named)."""
    query = {"workspace_id": workspace_id}
    listing = await client.get(f"/api/v1/sources/batches/{batch_id}/columns", params=query)
    assert listing.status_code == 200, listing.text
    body: dict[str, object] = {
        "decision": decision,
        "rationale": "Checked against the ERP export.",
        "source_file_id": listing.json()["files"][0]["file_id"],
    }
    if columns is not None:
        body["source_columns"] = columns
    decided = await client.post(
        f"/api/v1/sources/batches/{batch_id}/columns/review", params=query, json=body
    )
    assert decided.status_code == 200, decided.text


async def _publish(client: AsyncClient, workspace_id: str, batch_id: str) -> dict[str, object]:
    published = await client.post(
        f"/api/v1/graph/batches/{batch_id}/compile", params={"workspace_id": workspace_id}
    )
    assert published.status_code == 200, published.text
    body: dict[str, object] = published.json()
    assert body["integrity_passed"] is True
    return body


async def _cells(db: AsyncSession, batch_id: str) -> dict[str, tuple[int, str, str]]:
    """claim id -> (row number, column, state) for every claim of the batch."""
    claims = (
        await db.scalars(select(EvidenceClaim).where(EvidenceClaim.batch_id == batch_id))
    ).all()
    return {
        claim.claim_id: (claim.row_number, claim.source_column, claim.claim_state)
        for claim in claims
    }


async def _links(db: AsyncSession, workspace_id: str) -> dict[tuple[str, str], set[str]]:
    """(element type, element id) -> the claim ids it is linked to."""
    links = (
        await db.scalars(select(ProvenanceLink).where(ProvenanceLink.workspace_id == workspace_id))
    ).all()
    by_element: dict[tuple[str, str], set[str]] = defaultdict(set)
    for link in links:
        by_element[(link.graph_element_type, link.graph_element_id)].add(link.claim_id)
    return by_element


async def _nodes(db: AsyncSession, workspace_id: str) -> dict[tuple[str, str], GraphNode]:
    nodes = (
        await db.scalars(select(GraphNode).where(GraphNode.workspace_id == workspace_id))
    ).all()
    return {(node.entity_type, node.entity_id): node for node in nodes}


async def test_a_record_is_linked_to_the_cells_of_its_own_row(
    intake: tuple[AsyncClient, str], db_session: AsyncSession
) -> None:
    client, workspace_id = intake
    batch_id = await _prepare(client, workspace_id, "suppliers.csv", SUPPLIERS_CSV)
    await _decide(client, workspace_id, batch_id, "accepted")
    published = await _publish(client, workspace_id, batch_id)

    # Eight records of six cells each. It used to be 8 x 48 = 384.
    assert published["node_count"] == 8
    assert published["provenance_link_count"] == 8 * 6

    cells = await _cells(db_session, batch_id)
    links = await _links(db_session, workspace_id)
    nodes = await _nodes(db_session, workspace_id)
    assert len(nodes) == 8
    for row_number, supplier_id in enumerate(
        ["S-100", "S-101", "S-102", "S-103", "S-104", "S-105", "S-106", "S-107"], start=1
    ):
        linked = links[("node", nodes[("Supplier", supplier_id)].node_id)]
        assert {cells[claim_id][0] for claim_id in linked} == {row_number}, supplier_id
        assert sorted(cells[claim_id][1] for claim_id in linked) == sorted(
            ["supplier_id", "supplier_name", "country", "tier", "lead_time_days", "status"]
        )

    # The write event of a record names the same cells, not the whole file.
    events = (
        await db_session.scalars(
            select(GraphWriteEvent).where(GraphWriteEvent.workspace_id == workspace_id)
        )
    ).all()
    assert len(events) == 8
    for event in events:
        assert set(event.provenance_claim_ids) == links[("node", event.element_id)]


async def test_the_links_grow_with_the_file_and_not_with_its_square(
    intake: tuple[AsyncClient, str],
) -> None:
    client, workspace_id = intake
    rows = 250
    content = "supplier_id,supplier_name,country,status\n" + "".join(
        f"S-{number},Supplier {number} Works,{('DE', 'IN', 'JP')[number % 3]},active\n"
        for number in range(1, rows + 1)
    )
    batch_id = await _prepare(client, workspace_id, "suppliers.csv", content.encode())
    await _decide(client, workspace_id, batch_id, "accepted")
    published = await _publish(client, workspace_id, batch_id)

    assert published["node_count"] == rows
    # One link per accepted cell. It used to be 250 x 1,000 = 250,000.
    assert published["provenance_link_count"] == rows * 4


async def test_a_rejected_cell_supports_nothing(
    intake: tuple[AsyncClient, str], db_session: AsyncSession
) -> None:
    client, workspace_id = intake
    batch_id = await _prepare(client, workspace_id, "suppliers.csv", SUPPLIERS_CSV)
    await _decide(client, workspace_id, batch_id, "rejected", ["tier"])
    await _decide(client, workspace_id, batch_id, "accepted")
    published = await _publish(client, workspace_id, batch_id)

    assert published["provenance_link_count"] == 8 * 5
    cells = await _cells(db_session, batch_id)
    links = await _links(db_session, workspace_id)
    linked = {claim_id for claim_ids in links.values() for claim_id in claim_ids}
    assert {cells[claim_id][2] for claim_id in linked} == {ClaimState.ACCEPTED.value}
    assert "tier" not in {cells[claim_id][1] for claim_id in linked}
    for node in (await _nodes(db_session, workspace_id)).values():
        assert "tier" not in node.attributes


async def test_a_relationship_is_linked_to_the_cells_that_state_it(
    intake: tuple[AsyncClient, str], db_session: AsyncSession
) -> None:
    client, workspace_id = intake
    batch_id = await _prepare(client, workspace_id, "purchase_orders.csv", ORDERS_CSV)
    await _decide(client, workspace_id, batch_id, "accepted")
    published = await _publish(client, workspace_id, batch_id)

    cells = await _cells(db_session, batch_id)
    links = await _links(db_session, workspace_id)
    nodes = await _nodes(db_session, workspace_id)
    by_cell = {(row, column): claim_id for claim_id, (row, column, _state) in cells.items()}

    # An order rests on the five cells of its row.
    for row_number, po_number in enumerate(["PO-1", "PO-2", "PO-3"], start=1):
        order = nodes[("PurchaseOrder", po_number)]
        assert links[("node", order.node_id)] == {
            by_cell[(row_number, column)]
            for column in ["po_number", "supplier_id", "sku", "quantity", "status"]
        }

    # A supplier that only orders refer to rests on the cells that name it.
    assert links[("node", nodes[("Supplier", "S-100")].node_id)] == {
        by_cell[(1, "supplier_id")],
        by_cell[(2, "supplier_id")],
    }
    assert links[("node", nodes[("Supplier", "S-101")].node_id)] == {by_cell[(3, "supplier_id")]}

    # "PO-3 is ordered from S-101" rests on the cell that identifies the order
    # and the cell that names the supplier; the quantity says nothing about it.
    edges = (
        await db_session.scalars(select(GraphEdge).where(GraphEdge.workspace_id == workspace_id))
    ).all()
    node_by_id = {node.node_id: key for key, node in nodes.items()}
    stated = {
        (node_by_id[edge.source_node_id][1], node_by_id[edge.target_node_id][1]): edge
        for edge in edges
        if node_by_id[edge.target_node_id][0] == "Supplier"
    }
    assert sorted(stated) == [("PO-1", "S-100"), ("PO-2", "S-100"), ("PO-3", "S-101")]
    for row_number, key in enumerate(sorted(stated), start=1):
        assert links[("edge", stated[key].edge_id)] == {
            by_cell[(row_number, "po_number")],
            by_cell[(row_number, "supplier_id")],
        }

    assert published["provenance_link_count"] == sum(len(claim_ids) for claim_ids in links.values())
    # Nothing is linked to the whole file (15 cells).
    assert max(len(claim_ids) for claim_ids in links.values()) == 5


async def test_a_record_described_by_two_rows_is_linked_to_both(
    intake: tuple[AsyncClient, str], db_session: AsyncSession
) -> None:
    client, workspace_id = intake
    content = (
        b"supplier_id,supplier_name,country\n"
        b"S-100,Acme Metals GmbH,DE\n"
        b"S-101,Bharat Castings Pvt Ltd,IN\n"
        b"S-100,Acme Metals GmbH,DE\n"
    )
    batch_id = await _prepare(client, workspace_id, "suppliers.csv", content)
    await _decide(client, workspace_id, batch_id, "accepted")
    published = await _publish(client, workspace_id, batch_id)

    assert published["node_count"] == 2
    cells = await _cells(db_session, batch_id)
    links = await _links(db_session, workspace_id)
    nodes = await _nodes(db_session, workspace_id)
    acme = links[("node", nodes[("Supplier", "S-100")].node_id)]
    assert sorted((cells[claim_id][0], cells[claim_id][1]) for claim_id in acme) == sorted(
        (row, column) for row in (1, 3) for column in ("supplier_id", "supplier_name", "country")
    )
    bharat = links[("node", nodes[("Supplier", "S-101")].node_id)]
    assert {cells[claim_id][0] for claim_id in bharat} == {2}


async def test_a_claim_about_a_whole_column_supports_every_row(
    intake: tuple[AsyncClient, str], db_session: AsyncSession
) -> None:
    """Claims written before row-level preparation carry row number 0."""
    client, workspace_id = intake
    batch_id = await _prepare(client, workspace_id, "suppliers.csv", SUPPLIERS_CSV)
    await _decide(client, workspace_id, batch_id, "accepted")
    file_id = (
        await db_session.scalars(select(SourceFile.file_id).where(SourceFile.batch_id == batch_id))
    ).one()
    whole_column = EvidenceClaim(
        claim_id=uuid7(),
        workspace_id=workspace_id,
        source_file_id=file_id,
        batch_id=batch_id,
        row_number=0,
        source_column="country",
        canonical_entity="Supplier",
        canonical_field="country",
        raw_value="DE",
        normalized_value="DE",
        confidence=1.0,
        claim_state=ClaimState.ACCEPTED.value,
        provenance={},
        requires_review=False,
    )
    db_session.add(whole_column)
    await db_session.flush()

    published = await _publish(client, workspace_id, batch_id)

    assert published["provenance_link_count"] == 8 * (6 + 1)
    links = await _links(db_session, workspace_id)
    assert len(links) == 8
    assert all(whole_column.claim_id in claim_ids for claim_ids in links.values())
