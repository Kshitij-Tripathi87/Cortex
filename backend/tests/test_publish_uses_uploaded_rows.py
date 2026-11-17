"""Publishing a reviewed upload must build the graph from the rows of the file.

Regression: outside staging/pilot/prod the publish route gave the graph compiler
no object-storage client, so the compiler rebuilt the rows from column profile
samples. A profile keeps at most five distinct values per column, in no row
order, so a published workspace had rows missing and attributes attached to the
wrong entity (a supplier carrying another supplier's name). The route now hands
the compiler the same stored bytes that upload and claim preparation use.

The test drives upload -> prepare -> review -> publish over HTTP, as the browser
does, and compares every published node with its row in the uploaded file.
"""

from __future__ import annotations

import csv
import io
from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import graph, sources
from app.infrastructure import storage_client
from app.infrastructure.database import get_db
from app.infrastructure.security import AuthContext, get_current_user

# Register the models before the db_engine fixture copies Base.metadata.
from app.modules.audit.models import AuditEvent  # noqa: F401
from app.modules.compiler.models import EvidenceClaim, ReadinessAssessment  # noqa: F401
from app.modules.graph.models import GraphEdge, GraphNode, GraphSnapshot  # noqa: F401
from app.modules.sources.models import SourceBatch, SourceColumnProfile, SourceFile  # noqa: F401
from app.modules.sources.profiler import MAX_SAMPLE_VALUES

# More rows than a column profile keeps, and values that repeat across rows, so
# a graph rebuilt from profile samples cannot match the file.
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


class _MemoryStorage:
    """Stand-in for the S3 client: keeps uploaded bytes in memory."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.fail_reads = False

    def object_exists(self, key: str) -> bool:
        return key in self.objects

    def put_object(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> None:
        self.objects[key] = bytes(data)

    def get_object(self, key: str) -> bytes:
        if self.fail_reads:
            raise ConnectionError("object store unreachable")
        return self.objects[key]


@pytest.fixture
async def intake(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[tuple[AsyncClient, str, _MemoryStorage]]:
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
        yield client, workspace_id, storage


async def _upload_and_accept(client: AsyncClient, workspace_id: str) -> str:
    """Upload the supplier file, prepare its claims and accept every one of them."""
    query = {"workspace_id": workspace_id}
    upload = await client.post(
        "/api/v1/sources/upload",
        data={"workspace_id": workspace_id, "source_system_hint": "erp"},
        files={"file": ("suppliers.csv", SUPPLIERS_CSV, "text/csv")},
    )
    assert upload.status_code == 200, upload.text
    batch_id = str(upload.json()["batch_id"])

    prepared = await client.post(f"/api/v1/sources/batches/{batch_id}/compile", params=query)
    assert prepared.status_code == 200, prepared.text

    claims = await client.get(
        f"/api/v1/sources/batches/{batch_id}/claims", params={**query, "limit": 500}
    )
    assert claims.status_code == 200, claims.text
    assert len(claims.json()) == 8 * 6
    for claim in claims.json():
        review = await client.post(
            f"/api/v1/sources/batches/{batch_id}/claims/{claim['claim_id']}/review",
            params=query,
            json={
                "decision": "accepted",
                "rationale": "Checked against the supplier master.",
                "canonical_entity": "Supplier",
                "canonical_field": claim["source_column"],
            },
        )
        assert review.status_code == 200, review.text
    return batch_id


async def test_publish_builds_one_node_per_uploaded_row_with_that_rows_values(
    intake: tuple[AsyncClient, str, _MemoryStorage], db_session: AsyncSession
) -> None:
    client, workspace_id, _storage = intake
    uploaded = {
        row["supplier_id"]: row for row in csv.DictReader(io.StringIO(SUPPLIERS_CSV.decode()))
    }
    # The file is larger than a column profile, so samples cannot stand in for it.
    assert len(uploaded) > MAX_SAMPLE_VALUES

    batch_id = await _upload_and_accept(client, workspace_id)
    published = await client.post(
        f"/api/v1/graph/batches/{batch_id}/compile", params={"workspace_id": workspace_id}
    )
    assert published.status_code == 200, published.text
    assert published.json()["node_count"] == len(uploaded)
    assert published.json()["integrity_passed"] is True

    nodes = (
        await db_session.scalars(
            select(GraphNode)
            .where(GraphNode.workspace_id == workspace_id)
            .where(GraphNode.entity_type == "Supplier")
        )
    ).all()
    stored = {node.entity_id: dict(node.attributes) for node in nodes}

    assert sorted(stored) == sorted(uploaded)
    for supplier_id, row in uploaded.items():
        assert stored[supplier_id] == row, f"{supplier_id} does not match its uploaded row"


async def test_publish_reports_unreadable_source_file_and_writes_nothing(
    intake: tuple[AsyncClient, str, _MemoryStorage], db_session: AsyncSession
) -> None:
    client, workspace_id, storage = intake
    batch_id = await _upload_and_accept(client, workspace_id)

    storage.fail_reads = True
    failed = await client.post(
        f"/api/v1/graph/batches/{batch_id}/compile", params={"workspace_id": workspace_id}
    )
    assert failed.status_code == 503, failed.text
    assert failed.json()["detail"] == "Source artifact could not be retrieved"

    nodes = (
        await db_session.scalars(select(GraphNode).where(GraphNode.workspace_id == workspace_id))
    ).all()
    snapshots = (
        await db_session.scalars(
            select(GraphSnapshot).where(GraphSnapshot.workspace_id == workspace_id)
        )
    ).all()
    assert list(nodes) == []
    assert list(snapshots) == []

    # Once the store is reachable again the same batch publishes in full.
    storage.fail_reads = False
    published = await client.post(
        f"/api/v1/graph/batches/{batch_id}/compile", params={"workspace_id": workspace_id}
    )
    assert published.status_code == 200, published.text
    assert published.json()["node_count"] == 8
