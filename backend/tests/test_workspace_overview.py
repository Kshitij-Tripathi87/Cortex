"""The Command Center figures come from the published records.

The cockpit used to count only the risk register, which nothing writes from
an upload: a workspace with three late purchase orders showed "0 open
disruptions" and "World state: Not available" beside an Ask box that listed
the three orders. These tests drive the product's own routes (upload ->
prepare -> review -> publish) and then read ``GET /nexus/workspace/overview``
and ``GET /sources/batches``. They compare the result with the uploaded files
and with what the Ask box answers from the same data.
"""

from __future__ import annotations

import json
from datetime import datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.nexus_spine.p0_migration import workspace_evidence
from app.modules.nexus_spine.p0_migration.workspace_overview import (
    MAX_OVERVIEW_ITEMS,
    build_workspace_overview,
)
from tests.test_ask_grounded_answers import (  # noqa: F401  (stack is a fixture)
    INVENTORY,
    PURCHASE_ORDERS,
    SUPPLIERS,
    Stack,
    stack,
)
from tests.test_ask_workspace_evidence_postgres import TODAY as PG_TODAY
from tests.test_ask_workspace_evidence_postgres import (  # noqa: F401  (fixtures)
    sessions,
    workspace,
)

OVERVIEW = "/api/v1/nexus/workspace/overview"
BATCHES = "/api/v1/sources/batches"


async def _overview(stack: Stack, workspace_id: str | None = None) -> dict:  # noqa: F811
    response = await stack.client.get(
        OVERVIEW, params={"workspace_id": workspace_id or stack.workspace_id}
    )
    assert response.status_code == 200, response.text
    overview: dict = response.json()["data"]["overview"]
    return overview


# ── What the overview reports ────────────────────────────────────────────────


async def test_overview_counts_what_the_published_files_hold(stack: Stack) -> None:  # noqa: F811
    await stack.publish_all()
    overview = await _overview(stack)

    # Five files were published one after another: the data is at version 5.
    assert overview["published"]["version"] == 5
    assert overview["published"]["files"] == ["inventory.csv"]
    assert overview["as_of"] == "2026-11-17"
    # Totals, not the first page of a list.
    assert overview["records"]["total"] == 27
    assert {item["entity_type"]: item["count"] for item in overview["records"]["by_type"]} == {
        "PurchaseOrder": 7,
        "InventoryItem": 6,
        "Product": 6,
        "Supplier": 6,
        "Facility": 2,
    }
    assert overview["records"]["by_type"][0]["noun"] == "purchase orders"
    assert overview["relationships"]["total"] == 26
    assert overview["reading"] == {"complete": True, "records_read": 27, "records_total": 27}

    # Three of the seven purchase orders say they are delayed.
    late = overview["late"]
    assert (late["count"], late["checked"]) == (3, 7)
    assert [item["entity_id"] for item in late["items"]] == ["PO-5001", "PO-5002", "PO-5006"]
    first = late["items"][0]
    assert first["noun"] == "purchase order"
    assert first["days_late"] == 21
    assert first["subject"] == "400 x C-2000 Cast Iron Housing from S-101 Bharat Castings Pvt Ltd"
    assert first["reasons"] == (
        "status is delayed; now expected 2026-11-26, 21 days after the promised 2026-11-05"
    )
    assert first["text"] == f"PO-5001: {first['subject']}; {first['reasons']}."

    # Three of the six stock records are under their safety stock, worst first.
    stock = overview["stock"]
    assert (stock["count"], stock["checked"]) == (3, 6)
    assert [item["entity_id"] for item in stock["items"]] == ["INV-5", "INV-1", "INV-4"]
    assert stock["items"][1]["where"] == "C-2000 Cast Iron Housing at WH-PUNE Pune Plant Store"
    assert stock["items"][1]["detail"] == "120 on hand against a safety stock of 300 (180 short)"
    assert stock["items"][1]["out_of_stock"] is False

    # Two suppliers carry a status that marks a problem.
    flagged = overview["flagged"]
    assert flagged["count"] == 2
    assert [item["text"] for item in flagged["items"]] == [
        "S-101 Bharat Castings Pvt Ltd: status is delayed.",
        "S-105 Kyoto Bearings KK: status is at_risk.",
    ]

    assert overview["attention_count"] == 3 + 3 + 2
    # Records that are fine are not listed.
    listed = json.dumps([late["items"], stock["items"], flagged["items"]])
    for fine in ("PO-5003", "PO-5004", "PO-5005", "PO-5007", "INV-2", "INV-3", "INV-6", "S-100"):
        assert fine not in listed


async def test_overview_says_the_same_as_the_ask_box(stack: Stack) -> None:  # noqa: F811
    await stack.publish_all()
    overview = await _overview(stack)

    # The summary is the "what stands out" part of the overview answer, word for word.
    answer = (await stack.ask("What needs attention?"))["response"]
    assert len(overview["summary"]) == 3
    for sentence in overview["summary"]:
        assert f"- {sentence}" in answer
    assert f"What stands out as of {overview['as_of']} (UTC):" in answer
    assert "holds 27 published records" in answer and "joined by 26 relationships" in answer
    # Both read the risk register as empty: the cockpit shows no recorded risk.
    assert "Risk register: 0 open risks." in answer

    # Each listed order and stock position reads as the detailed answers list it.
    late_answer = (await stack.ask("Which purchase orders are delayed?"))["response"]
    assert "3 of 7 purchase orders are late or flagged" in late_answer
    for item in overview["late"]["items"]:
        assert item["text"] in late_answer
    stock_answer = (await stack.ask("What is below safety stock?"))["response"]
    assert "3 of 6 stock positions are below threshold or empty" in stock_answer
    for item in overview["stock"]["items"]:
        assert item["text"] in stock_answer


async def test_overview_of_a_workspace_without_published_data(stack: Stack) -> None:  # noqa: F811
    empty = await _overview(stack)
    assert empty["published"] is None
    assert empty["records"] == {"total": 0, "by_type": []}
    assert empty["relationships"] == {"total": 0}
    assert empty["summary"] == []
    assert empty["attention_count"] == 0
    for group in ("late", "stock", "flagged"):
        assert empty[group]["count"] == 0 and empty[group]["items"] == []

    # An upload that was prepared but not reviewed and published changes nothing:
    # the cockpit counts published records only.
    await stack.publish("purchase_orders.csv", PURCHASE_ORDERS, accept=False)
    waiting = await _overview(stack)
    assert waiting["published"] is None
    assert waiting["records"]["total"] == 0
    assert waiting["late"] == {"count": 0, "checked": 0, "items": []}


async def test_overview_without_orders_or_stock_does_not_claim_they_are_fine(
    stack: Stack,  # noqa: F811
) -> None:
    await stack.publish("suppliers.csv", SUPPLIERS)
    overview = await _overview(stack)

    assert overview["published"]["version"] == 1
    assert overview["records"]["total"] == 6
    # Nothing was checked, which is different from "nothing is late".
    assert overview["late"] == {"count": 0, "checked": 0, "items": []}
    assert overview["stock"] == {"count": 0, "checked": 0, "items": []}
    assert overview["summary"][0] == (
        "No orders or shipments are published, so lateness cannot be judged."
    )
    assert overview["summary"][1] == (
        "No inventory with a readable quantity is published, so stock cannot be judged."
    )
    assert overview["flagged"]["count"] == 2
    assert overview["attention_count"] == 2


async def test_overview_lists_ten_items_and_counts_all(stack: Stack) -> None:  # noqa: F811
    rows = [b"po_number,supplier_id,quantity,promised_date,status"]
    rows += [f"PO-{number:04d},S-100,10,2026-10-01,delayed".encode() for number in range(1, 15)]
    await stack.publish("purchase_orders.csv", b"\n".join(rows) + b"\n")
    late = (await _overview(stack))["late"]

    assert late["count"] == 14 and late["checked"] == 14
    assert len(late["items"]) == MAX_OVERVIEW_ITEMS == 10


async def test_overview_says_when_only_part_of_the_records_was_read(
    stack: Stack,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await stack.publish_all()
    monkeypatch.setattr(workspace_evidence, "MAX_NODES_PER_TYPE", 4)
    overview = await _overview(stack)

    # The totals stay whole; the reading says how much the findings cover.
    assert overview["records"]["total"] == 27
    assert overview["reading"]["complete"] is False
    assert overview["reading"]["records_total"] == 27
    assert overview["reading"]["records_read"] == 4 + 4 + 4 + 4 + 2
    assert overview["late"]["checked"] == 4


# ── Who may read it ──────────────────────────────────────────────────────────


async def test_overview_is_readable_by_a_viewer_and_closed_to_other_workspaces(
    stack: Stack,  # noqa: F811
) -> None:
    await stack.publish_all()
    published_workspace = stack.workspace_id
    other_workspace = str(uuid4())

    stack.user["roles"] = ["viewer"]
    assert (await _overview(stack))["late"]["count"] == 3

    # A user of another workspace reads their own (empty) workspace ...
    stack.user["workspace_ids"] = [other_workspace]
    theirs = await _overview(stack, other_workspace)
    assert theirs["published"] is None and theirs["records"]["total"] == 0
    assert "PO-5001" not in json.dumps(theirs)

    # ... and is refused the workspace they do not belong to.
    refused = await stack.client.get(OVERVIEW, params={"workspace_id": published_workspace})
    assert refused.status_code == 403
    assert "PO-5001" not in refused.text
    refused_list = await stack.client.get(BATCHES, params={"workspace_id": published_workspace})
    assert refused_list.status_code == 403
    assert "purchase_orders.csv" not in refused_list.text


async def test_overview_requires_the_workspace_parameter(stack: Stack) -> None:  # noqa: F811
    assert (await stack.client.get(OVERVIEW)).status_code == 422
    assert (await stack.client.get(BATCHES)).status_code == 422


# ── The list of uploads ──────────────────────────────────────────────────────


async def test_uploads_are_listed_with_their_files_and_state(stack: Stack) -> None:  # noqa: F811
    nothing = await stack.client.get(BATCHES, params={"workspace_id": stack.workspace_id})
    assert nothing.status_code == 200
    assert nothing.json() == {"batch_count": 0, "batches": []}

    published_id = await stack.publish("suppliers.csv", SUPPLIERS)
    waiting_id = await stack.publish("inventory.csv", INVENTORY, accept=False)

    response = await stack.client.get(BATCHES, params={"workspace_id": stack.workspace_id})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["batch_count"] == 2
    by_id = {batch["batch_id"]: batch for batch in body["batches"]}
    assert set(by_id) == {published_id, waiting_id}

    published = by_id[published_id]
    assert published["state"] == "published"
    assert published["published_version"] == 1
    assert published["files"] == [{"name": "suppliers.csv", "rows": 6}]
    assert published["claims_pending_review"] == 0 and published["claims_accepted"] > 0

    waiting = by_id[waiting_id]
    assert waiting["state"] == "review_required"
    assert waiting["published_version"] is None
    assert waiting["files"] == [{"name": "inventory.csv", "rows": 6}]
    assert waiting["claims_pending_review"] > 0

    # Every timestamp says which time zone it is in, so a browser cannot read
    # it as local time.
    for batch in body["batches"]:
        assert datetime.fromisoformat(batch["uploaded_at"]).utcoffset() is not None

    # The Ask box reads the same list.
    answer = (await stack.ask("Is my data ready?"))["response"]
    assert "inventory.csv" in answer and "suppliers.csv" in answer


# ── On PostgreSQL ────────────────────────────────────────────────────────────


async def test_overview_reads_from_postgresql(
    sessions: async_sessionmaker[AsyncSession],  # noqa: F811
    workspace: str,  # noqa: F811
) -> None:
    """The route tests run on SQLite; production reads PostgreSQL through asyncpg."""
    async with sessions() as session:
        overview = await build_workspace_overview(session, workspace, today=PG_TODAY)
        uploads = await workspace_evidence.list_uploads(session, workspace)

    assert overview["as_of"] == "2026-11-17"
    assert overview["published"]["version"] == 3
    assert overview["published"]["files"] == ["suppliers_update.csv"]
    assert datetime.fromisoformat(overview["published"]["published_at"]).utcoffset() is not None
    assert overview["records"]["total"] == 6
    assert overview["relationships"]["total"] == 2
    assert overview["reading"]["complete"] is True
    # PO-1 says "delayed"; PO-2 is promised for 2099.
    assert (overview["late"]["count"], overview["late"]["checked"]) == (1, 2)
    assert overview["late"]["items"][0]["entity_id"] == "PO-1"
    assert overview["late"]["items"][0]["text"] == (
        "PO-1: 40 units from S-1 Acme Metals; status is delayed."
    )
    assert overview["stock"] == {"count": 0, "checked": 0, "items": []}
    assert [item["entity_id"] for item in overview["flagged"]["items"]] == ["S-1"]
    assert overview["attention_count"] == 2

    assert uploads["batch_count"] == 4
    states = sorted(batch["state"] for batch in uploads["batches"])
    assert states == ["published", "published", "published", "review_required"]
    for batch in uploads["batches"]:
        assert datetime.fromisoformat(batch["uploaded_at"]).utcoffset() is not None
