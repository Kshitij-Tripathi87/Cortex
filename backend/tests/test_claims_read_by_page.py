"""The values of a batch can be read a page at a time.

Every cell of an uploaded file is a claim, and the review page asked for all
of them at once and drew a table row for each. A file of 3,000 rows and eight
columns is 24,000 rows on the page: it took eight seconds to appear and the
browser tab was killed when the table was drawn again after a decision.

The list now takes a limit, an offset and filters, the counts by state come
from their own cheap request, and a conflict carries the values that disagree,
so the page needs neither the whole list nor a second request to show one.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import sources
from app.infrastructure import storage_client
from app.infrastructure.database import get_db
from app.infrastructure.security import AuthContext, get_current_user

# Register the models before the db_engine fixture copies Base.metadata.
from app.modules.audit.models import AuditEvent  # noqa: F401
from app.modules.compiler.models import EvidenceClaim, ReadinessAssessment  # noqa: F401
from app.modules.sources.models import SourceBatch, SourceColumnProfile, SourceFile  # noqa: F401

COLUMNS = ["supplier_id", "supplier_name", "country", "status"]
ROWS = 30


def _suppliers(rows: int = ROWS) -> bytes:
    lines = [",".join(COLUMNS)]
    for number in range(1, rows + 1):
        country = ("DE", "IN", "JP")[number % 3]
        status = "on_hold" if number % 10 == 0 else "active"
        lines.append(f"S-{number:03d},Supplier {number:03d} Works,{country},{status}")
    return ("\n".join(lines) + "\n").encode()


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


class _Caller:
    """Who the requests are made as; a test may change it between requests."""

    def __init__(self, workspace_id: str) -> None:
        self.roles = ["admin"]
        self.workspace_ids = [workspace_id]


@pytest.fixture
async def intake(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[tuple[AsyncClient, str, _Caller]]:
    workspace_id = str(uuid4())
    caller = _Caller(workspace_id)
    storage = _MemoryStorage()
    monkeypatch.setattr(storage_client, "get_storage", lambda settings=None: storage)

    app = FastAPI()
    app.include_router(sources.router, prefix="/api/v1/sources")

    async def override_db() -> AsyncGenerator[AsyncSession]:
        yield db_session

    async def override_user() -> AuthContext:
        return AuthContext(
            user_id=str(uuid4()),
            roles=list(caller.roles),
            workspace_ids=list(caller.workspace_ids),
            is_anonymous=False,
        )

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, workspace_id, caller


async def _prepare(
    client: AsyncClient, workspace_id: str, content: bytes, name: str = "suppliers.csv"
) -> str:
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


async def _claims(
    client: AsyncClient, workspace_id: str, batch_id: str, **params: object
) -> list[dict[str, object]]:
    response = await client.get(
        f"/api/v1/sources/batches/{batch_id}/claims",
        params={"workspace_id": workspace_id, **params},
    )
    assert response.status_code == 200, response.text
    rows: list[dict[str, object]] = response.json()
    return rows


async def _summary(
    client: AsyncClient, workspace_id: str, batch_id: str, **params: object
) -> dict[str, int]:
    response = await client.get(
        f"/api/v1/sources/batches/{batch_id}/claims/summary",
        params={"workspace_id": workspace_id, **params},
    )
    assert response.status_code == 200, response.text
    counts: dict[str, int] = response.json()
    return counts


async def _decide(
    client: AsyncClient,
    workspace_id: str,
    batch_id: str,
    decision: str,
    columns: list[str] | None = None,
) -> None:
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


def _cell(claim: dict[str, object]) -> tuple[object, object]:
    return (claim["row_number"], claim["source_column"])


FILE_ORDER = [(row, column) for row in range(1, ROWS + 1) for column in COLUMNS]


async def test_without_a_limit_every_value_is_listed_in_file_order(
    intake: tuple[AsyncClient, str, _Caller],
) -> None:
    client, workspace_id, _caller = intake
    batch_id = await _prepare(client, workspace_id, _suppliers())

    everything = await _claims(client, workspace_id, batch_id)

    assert [_cell(claim) for claim in everything] == FILE_ORDER


async def test_pages_follow_one_another_without_a_gap_or_a_repeat(
    intake: tuple[AsyncClient, str, _Caller],
) -> None:
    client, workspace_id, _caller = intake
    batch_id = await _prepare(client, workspace_id, _suppliers())

    seen: list[dict[str, object]] = []
    for offset in range(0, ROWS * len(COLUMNS) + 50, 50):
        page = await _claims(client, workspace_id, batch_id, limit=50, offset=offset)
        assert len(page) <= 50
        seen.extend(page)

    assert [_cell(claim) for claim in seen] == FILE_ORDER
    assert len({claim["claim_id"] for claim in seen}) == ROWS * len(COLUMNS)


async def test_the_order_stays_when_values_are_decided(
    intake: tuple[AsyncClient, str, _Caller],
) -> None:
    """A database returns changed rows in another place unless told the order."""
    client, workspace_id, _caller = intake
    batch_id = await _prepare(client, workspace_id, _suppliers())
    before = await _claims(client, workspace_id, batch_id, limit=40)

    await _decide(client, workspace_id, batch_id, "rejected", ["country"])
    await _decide(client, workspace_id, batch_id, "accepted", ["supplier_id", "status"])

    after = await _claims(client, workspace_id, batch_id, limit=40)
    assert [claim["claim_id"] for claim in after] == [claim["claim_id"] for claim in before]
    assert [_cell(claim) for claim in after] == FILE_ORDER[:40]
    assert {claim["claim_state"] for claim in after} == {"accepted", "rejected", "pending_review"}


async def test_the_list_can_be_narrowed_to_a_state_a_column_a_row_or_a_text(
    intake: tuple[AsyncClient, str, _Caller],
) -> None:
    client, workspace_id, _caller = intake
    batch_id = await _prepare(client, workspace_id, _suppliers())
    await _decide(client, workspace_id, batch_id, "rejected", ["country"])
    await _decide(client, workspace_id, batch_id, "accepted", ["supplier_id"])

    waiting = await _claims(client, workspace_id, batch_id, claim_state="pending_review")
    assert {claim["source_column"] for claim in waiting} == {"supplier_name", "status"}
    assert len(waiting) == ROWS * 2

    rejected = await _claims(client, workspace_id, batch_id, claim_state="rejected", limit=500)
    assert [_cell(claim) for claim in rejected] == [(row, "country") for row in range(1, ROWS + 1)]

    names = await _claims(client, workspace_id, batch_id, source_column="supplier_name", limit=5)
    assert [claim["raw_value"] for claim in names] == [
        f"Supplier {number:03d} Works" for number in range(1, 6)
    ]

    row = await _claims(client, workspace_id, batch_id, row_number=17)
    assert [(claim["source_column"], claim["raw_value"]) for claim in row] == [
        ("supplier_id", "S-017"),
        ("supplier_name", "Supplier 017 Works"),
        ("country", "JP"),
        ("status", "active"),
    ]

    # The text as typed, whatever its case, anywhere in the value.
    held = await _claims(client, workspace_id, batch_id, value="ON_HOLD")
    assert [_cell(claim) for claim in held] == [(10, "status"), (20, "status"), (30, "status")]
    one = await _claims(client, workspace_id, batch_id, value="  s-017 ")
    assert [_cell(claim) for claim in one] == [(17, "supplier_id")]

    # Filters narrow together.
    both = await _claims(
        client,
        workspace_id,
        batch_id,
        source_column="status",
        claim_state="pending_review",
        value="hold",
    )
    assert [_cell(claim) for claim in both] == [(10, "status"), (20, "status"), (30, "status")]
    assert (
        await _claims(client, workspace_id, batch_id, source_column="country", value="hold") == []
    )


async def test_a_percent_sign_or_an_underscore_is_searched_for_as_typed(
    intake: tuple[AsyncClient, str, _Caller],
) -> None:
    client, workspace_id, _caller = intake
    content = (
        b"supplier_id,supplier_name,discount,status\n"
        b"S-1,Acme Metals,5%,on_hold\n"
        b"S-2,Nordic Seals,15,onXhold\n"
        b"S-3,Kyoto Bearings,50,active\n"
    )
    batch_id = await _prepare(client, workspace_id, content)

    percent = await _claims(client, workspace_id, batch_id, value="%")
    assert [claim["raw_value"] for claim in percent] == ["5%"]
    underscore = await _claims(client, workspace_id, batch_id, value="on_hold")
    assert [claim["raw_value"] for claim in underscore] == ["on_hold"]
    # A search for nothing is no search.
    assert len(await _claims(client, workspace_id, batch_id, value="   ")) == 12


async def test_the_counts_come_without_the_values_and_follow_the_filters(
    intake: tuple[AsyncClient, str, _Caller],
) -> None:
    client, workspace_id, _caller = intake
    batch_id = await _prepare(client, workspace_id, _suppliers())

    assert await _summary(client, workspace_id, batch_id) == {
        "total": 120,
        "pending_review": 120,
        "accepted": 0,
        "rejected": 0,
        "superseded": 0,
    }

    await _decide(client, workspace_id, batch_id, "rejected", ["country"])
    await _decide(client, workspace_id, batch_id, "accepted", ["supplier_id"])

    assert await _summary(client, workspace_id, batch_id) == {
        "total": 120,
        "pending_review": 60,
        "accepted": 30,
        "rejected": 30,
        "superseded": 0,
    }
    assert await _summary(client, workspace_id, batch_id, source_column="country") == {
        "total": 30,
        "pending_review": 0,
        "accepted": 0,
        "rejected": 30,
        "superseded": 0,
    }
    assert await _summary(client, workspace_id, batch_id, row_number=17) == {
        "total": 4,
        "pending_review": 2,
        "accepted": 1,
        "rejected": 1,
        "superseded": 0,
    }
    held = await _summary(client, workspace_id, batch_id, value="on_hold")
    assert held["total"] == 3 and held["pending_review"] == 3

    # A count and its list agree, filter for filter.
    for filters in (
        {},
        {"source_column": "status"},
        {"row_number": 3},
        {"value": "works"},
        {"source_column": "supplier_name", "value": "01"},
    ):
        counted = await _summary(client, workspace_id, batch_id, **filters)
        listed = await _claims(client, workspace_id, batch_id, **filters)
        assert counted["total"] == len(listed), filters
        for state in ("pending_review", "accepted", "rejected", "superseded"):
            assert counted[state] == sum(claim["claim_state"] == state for claim in listed)


async def test_a_page_is_at_most_five_hundred_values(
    intake: tuple[AsyncClient, str, _Caller],
) -> None:
    client, workspace_id, _caller = intake
    batch_id = await _prepare(client, workspace_id, _suppliers())
    path = f"/api/v1/sources/batches/{batch_id}/claims"

    for params in ({"limit": 0}, {"limit": 501}, {"offset": -1}, {"row_number": -1}):
        refused = await client.get(path, params={"workspace_id": workspace_id, **params})
        assert refused.status_code == 422, params
    assert len(await _claims(client, workspace_id, batch_id, limit=500)) == 120
    assert await _claims(client, workspace_id, batch_id, limit=10, offset=1000) == []


async def test_a_conflict_carries_the_values_that_disagree(
    intake: tuple[AsyncClient, str, _Caller],
) -> None:
    client, workspace_id, _caller = intake
    content = (
        b"supplier_id,supplier_name,country\n"
        b"S-1,Acme Metals GmbH,DE\n"
        b"S-2,Nordic Seals AB,SE\n"
        b"S-1,Acme Metals GmbH,AT\n"
    )
    batch_id = await _prepare(client, workspace_id, content)
    await _decide(client, workspace_id, batch_id, "accepted")

    response = await client.get(
        f"/api/v1/sources/batches/{batch_id}/conflicts", params={"workspace_id": workspace_id}
    )
    assert response.status_code == 200, response.text
    conflicts = response.json()
    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict["canonical_field"] == "country"
    assert [
        (claim["row_number"], claim["source_column"], claim["raw_value"], claim["claim_state"])
        for claim in conflict["claims"]
    ] == [(1, "country", "DE", "accepted"), (3, "country", "AT", "accepted")]
    assert [claim["claim_id"] for claim in conflict["claims"]] == sorted(conflict["claim_ids"])

    # Decided: the values stay with the conflict, in the state they were left.
    resolved = await client.post(
        f"/api/v1/sources/conflicts/{conflict['conflict_id']}/resolve",
        params={"workspace_id": workspace_id},
        json={
            "selected_claim_id": conflict["claims"][0]["claim_id"],
            "action": "approved",
            "rationale": "The supplier master says Germany.",
        },
    )
    assert resolved.status_code == 200, resolved.text
    after = await client.get(
        f"/api/v1/sources/batches/{batch_id}/conflicts", params={"workspace_id": workspace_id}
    )
    assert [(claim["raw_value"], claim["claim_state"]) for claim in after.json()[0]["claims"]] == [
        ("DE", "accepted"),
        ("AT", "superseded"),
    ]


async def test_the_values_of_another_workspace_are_not_counted_or_listed(
    intake: tuple[AsyncClient, str, _Caller],
) -> None:
    client, workspace_id, caller = intake
    batch_id = await _prepare(client, workspace_id, _suppliers())

    other_workspace = str(uuid4())
    caller.workspace_ids = [other_workspace]
    for path in ("claims", "claims/summary"):
        # Their own workspace, someone else's batch: not found.
        hidden = await client.get(
            f"/api/v1/sources/batches/{batch_id}/{path}",
            params={"workspace_id": other_workspace, "limit": 10},
        )
        assert hidden.status_code == 404, path
        # Someone else's workspace: refused.
        refused = await client.get(
            f"/api/v1/sources/batches/{batch_id}/{path}",
            params={"workspace_id": workspace_id, "limit": 10},
        )
        assert refused.status_code == 403, path


async def test_a_viewer_can_read_the_counts_and_a_page(
    intake: tuple[AsyncClient, str, _Caller],
) -> None:
    client, workspace_id, caller = intake
    batch_id = await _prepare(client, workspace_id, _suppliers())

    caller.roles = ["viewer"]
    assert (await _summary(client, workspace_id, batch_id))["total"] == 120
    assert len(await _claims(client, workspace_id, batch_id, limit=25)) == 25
