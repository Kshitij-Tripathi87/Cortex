"""The Ask box answers from the rows a workspace uploaded and published.

Each test drives the product's own routes over HTTP: upload -> prepare ->
review -> publish, then `POST /nexus/vanessa/ask`. The assertions compare the
answer with values that appear in the uploaded files, so an answer that is
vague, made up, or read from another workspace fails.

Before this work the built-in assistant answered most of these questions with
"I didn't catch that" or with raw JSON cut at 300 characters.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import graph, nexus_persistent, sources
from app.infrastructure import storage_client
from app.infrastructure.database import get_db
from app.infrastructure.security import AuthContext

# Register the models before the db_engine fixture copies Base.metadata.
from app.modules.audit.models import AuditEvent  # noqa: F401
from app.modules.compiler.models import EvidenceClaim, ReadinessAssessment  # noqa: F401
from app.modules.graph import cache as graph_cache
from app.modules.graph import context_engine
from app.modules.graph.entity_keys import canonical_column_name, infer_entity_type
from app.modules.graph.models import GraphEdge, GraphNode, GraphSnapshot  # noqa: F401
from app.modules.nexus_spine.p0_migration import vanessa_tools, workspace_evidence
from app.modules.nexus_spine.p0_migration.llm_adapter import (
    OpenAICompatibleLLMAdapter,
    reset_llm_adapter,
)
from app.modules.nexus_spine.persistence import models as _nexus_models  # noqa: F401
from app.modules.sources.models import SourceBatch, SourceColumnProfile, SourceFile  # noqa: F401

TODAY = date(2026, 11, 17)

SUPPLIERS = b"""supplier_id,supplier_name,country,tier,lead_time_days,status,on_time_rate
S-100,Acme Metals GmbH,DE,tier_1,21,active,0.96
S-101,Bharat Castings Pvt Ltd,IN,tier_1,35,delayed,0.71
S-102,Shenzhen Microdrive Co,CN,tier_2,42,active,0.88
S-103,Nordic Seals AB,SE,tier_2,14,active,0.99
S-104,Lone Star Fasteners,US,tier_3,10,active,0.93
S-105,Kyoto Bearings KK,JP,tier_1,28,at_risk,0.82
"""
PRODUCTS = b"""sku,product_name,category,unit_price
P-1000,Centrifugal Pump CP-40,finished_good,1850.00
C-2000,Cast Iron Housing,component,210.00
C-2001,Drive Motor 2kW,component,640.00
C-2002,Mechanical Seal Kit,component,95.00
C-2003,Hex Bolt M12 Box,component,18.50
C-2004,Ball Bearing 6205,component,7.20
"""
WAREHOUSES = b"""warehouse_id,warehouse_name,city,country
WH-PUNE,Pune Plant Store,Pune,IN
WH-HAM,Hamburg Distribution Centre,Hamburg,DE
"""
# Lateness here never depends on the day the test runs: late orders say so in
# their status and dates, and the on-time ones are promised far in the future.
PURCHASE_ORDERS = b"""po_number,supplier_id,sku,quantity,order_date,promised_date,expected_date,status,ship_to_warehouse_id
PO-5001,S-101,C-2000,400,2026-10-01,2026-11-05,2026-11-26,delayed,WH-PUNE
PO-5002,S-101,C-2000,250,2026-10-20,2026-11-24,2026-12-15,delayed,WH-PUNE
PO-5003,S-102,C-2001,300,2026-10-05,2099-01-10,2099-01-10,in_transit,WH-PUNE
PO-5004,S-103,C-2002,1200,2026-10-28,2099-01-20,2099-01-20,confirmed,WH-HAM
PO-5005,S-104,C-2003,80,2026-11-01,2099-01-18,2099-01-18,confirmed,WH-HAM
PO-5006,S-105,C-2004,5000,2026-10-12,2026-11-12,2026-11-20,delayed,WH-PUNE
PO-5007,S-100,C-2000,150,2026-11-03,2099-01-24,2099-01-24,confirmed,WH-HAM
"""
INVENTORY = b"""inventory_id,sku,warehouse_id,quantity_on_hand,safety_stock
INV-1,C-2000,WH-PUNE,120,300
INV-2,C-2001,WH-PUNE,410,150
INV-3,C-2002,WH-HAM,2600,500
INV-4,C-2003,WH-HAM,90,100
INV-5,C-2004,WH-PUNE,1500,2000
INV-6,P-1000,WH-HAM,35,20
"""
FILES: tuple[tuple[str, bytes], ...] = (
    ("suppliers.csv", SUPPLIERS),
    ("products.csv", PRODUCTS),
    ("warehouses.csv", WAREHOUSES),
    ("purchase_orders.csv", PURCHASE_ORDERS),
    ("inventory.csv", INVENTORY),
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


@dataclass
class Stack:
    client: AsyncClient
    workspace_id: str
    # The signed-in user the routes see; tests change the role or the access list.
    user: dict[str, Any] = field(default_factory=dict)

    async def publish(self, name: str, content: bytes, *, accept: bool = True) -> str:
        """Upload a file, prepare its claims, accept them and publish the batch."""
        query = {"workspace_id": self.workspace_id}
        upload = await self.client.post(
            "/api/v1/sources/upload",
            data={"workspace_id": self.workspace_id, "source_system_hint": "erp"},
            files={"file": (name, content, "text/csv")},
        )
        assert upload.status_code == 200, upload.text
        batch_id = str(upload.json()["batch_id"])
        prepared = await self.client.post(
            f"/api/v1/sources/batches/{batch_id}/compile", params=query
        )
        assert prepared.status_code == 200, prepared.text
        if not accept:
            return batch_id

        header = content.decode().splitlines()[0].split(",")
        entity = infer_entity_type(header)
        claims = await self.client.get(
            f"/api/v1/sources/batches/{batch_id}/claims", params={**query, "limit": 500}
        )
        assert claims.status_code == 200, claims.text
        for claim in claims.json():
            review = await self.client.post(
                f"/api/v1/sources/batches/{batch_id}/claims/{claim['claim_id']}/review",
                params=query,
                json={
                    "decision": "accepted",
                    "rationale": "Checked against the ERP export.",
                    "canonical_entity": entity,
                    "canonical_field": canonical_column_name(claim["source_column"], entity),
                },
            )
            assert review.status_code == 200, review.text
        published = await self.client.post(
            f"/api/v1/graph/batches/{batch_id}/compile", params=query
        )
        assert published.status_code == 200, published.text
        return batch_id

    async def publish_all(self) -> None:
        for name, content in FILES:
            await self.publish(name, content)

    async def ask(self, question: str, *, workspace_id: str | None = None) -> dict[str, Any]:
        response = await self.client.post(
            "/api/v1/nexus/vanessa/ask",
            params={"workspace_id": workspace_id or self.workspace_id},
            json={"query": question},
        )
        assert response.status_code == 200, response.text
        data: dict[str, Any] = response.json()["data"]
        return data


@pytest.fixture
async def stack(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[Stack]:
    workspace_id = str(uuid4())
    storage = _MemoryStorage()
    monkeypatch.setattr(storage_client, "get_storage", lambda settings=None: storage)
    # Answers state the date lateness is judged against; pin it.
    monkeypatch.setattr(workspace_evidence, "_today", lambda: TODAY)
    # Signals are computed through two caches that default to Redis. Use the
    # product's own no-op caches so the answers do not depend on a running
    # Redis (one CI job runs the suite without services).
    monkeypatch.setattr(graph_cache, "create_cache", lambda settings=None: graph_cache.NoOpCache())
    monkeypatch.setattr(
        context_engine,
        "create_context_cache",
        lambda settings=None: context_engine.NoOpContextCache(),
    )
    reset_llm_adapter()

    app = FastAPI()
    app.include_router(sources.router, prefix="/api/v1/sources")
    app.include_router(graph.router, prefix="/api/v1/graph")
    app.include_router(nexus_persistent.router, prefix="/api/v1")

    user: dict[str, Any] = {
        "user_id": str(uuid4()),
        "roles": ["admin"],
        "workspace_ids": [workspace_id],
    }

    async def override_db() -> AsyncGenerator[AsyncSession]:
        yield db_session

    async def override_user() -> AuthContext:
        return AuthContext(
            user_id=user["user_id"],
            roles=list(user["roles"]),
            workspace_ids=list(user["workspace_ids"]),
            is_anonymous=False,
        )

    app.dependency_overrides[get_db] = override_db
    # Override the dependency object each router captured at import.
    for module in (sources, graph, nexus_persistent):
        app.dependency_overrides[module.get_current_user] = override_user

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield Stack(client=client, workspace_id=workspace_id, user=user)
    reset_llm_adapter()


def _assert_plain_language(text: str) -> None:
    """An answer is sentences and "- " lists, never a dump of the tool output."""
    assert text.strip()
    for marker in ("{", "}", '":', "[tool:", "...(truncated)"):
        assert marker not in text, f"answer contains {marker!r}: {text[:300]}"


async def test_answers_are_read_from_the_uploaded_rows(stack: Stack) -> None:
    await stack.publish_all()

    suppliers = await stack.ask("Which suppliers do I have?")
    assert suppliers["intent"] == "graph_query"
    assert suppliers["actions_taken"] == ["nexus.graph.read"]
    assert suppliers["permission_denied"] is None
    assert suppliers["world_state_version"] == 5
    assert suppliers["response"].startswith("You have 6 suppliers:")
    for name in (
        "S-100 Acme Metals GmbH",
        "S-101 Bharat Castings Pvt Ltd",
        "S-102 Shenzhen Microdrive Co",
        "S-103 Nordic Seals AB",
        "S-104 Lone Star Fasteners",
        "S-105 Kyoto Bearings KK",
    ):
        assert name in suppliers["response"]
    assert "status: delayed; on_time_rate: 0.71" in suppliers["response"]
    assert "Source: your published data, version 5" in suppliers["response"]
    # The evidence list says in one line what was read.
    assert suppliers["evidence"][0]["tool"] == "nexus.graph.read"
    assert suppliers["evidence"][0]["summary"] == "Read 27 published records from version 5."
    _assert_plain_language(suppliers["response"])

    late = await stack.ask("Which purchase orders are delayed?")
    assert "3 of 7 purchase orders are late or flagged as of 2026-11-17 (UTC):" in late["response"]
    assert (
        "PO-5001: 400 x C-2000 Cast Iron Housing from S-101 Bharat Castings Pvt Ltd; status is "
        "delayed; now expected 2026-11-26, 21 days after the promised 2026-11-05."
    ) in late["response"]
    assert (
        "PO-5006: 5,000 x C-2004 Ball Bearing 6205 from S-105 Kyoto Bearings KK" in late["response"]
    )
    # Orders that are on time are not listed as late.
    for on_time in ("PO-5003", "PO-5004", "PO-5005", "PO-5007"):
        assert on_time not in late["response"]
    _assert_plain_language(late["response"])

    stock = await stack.ask("What is below safety stock?")
    assert "3 of 6 stock positions are below threshold or empty:" in stock["response"]
    assert (
        "C-2000 Cast Iron Housing at WH-PUNE Pune Plant Store: 120 on hand against a safety "
        "stock of 300 (180 short)."
    ) in stock["response"]
    assert "(10 short)" in stock["response"] and "(500 short)" in stock["response"]
    # Positions above their safety stock are not reported as short.
    assert "C-2001" not in stock["response"] and "P-1000" not in stock["response"]

    exposed = await stack.ask("Which orders are exposed?")
    assert exposed["intent"] == "risk_query"
    assert exposed["actions_taken"] == ["nexus.risk.read"]
    assert "3 late or flagged supply orders affect 2 parts" in exposed["response"]
    assert "C-2000 Cast Iron Housing: 650 units late on PO-5001 and PO-5002" in exposed["response"]
    assert "Stock is already below threshold: 120 on hand at WH-PUNE" in exposed["response"]
    # The data holds no sales orders: the answer says so instead of guessing.
    assert (
        "No sales orders are published, so I cannot trace these delays to customer deliveries."
        in exposed["response"]
    )
    assert "Risk register: no open risks are recorded" in exposed["response"]
    _assert_plain_language(exposed["response"])

    detail = await stack.ask("Tell me about supplier S-101")
    assert detail["response"].startswith(
        "S-101 is a supplier in your published data: Bharat Castings Pvt Ltd."
    )
    assert "2 purchase orders refer to it: PO-5001 and PO-5002." in detail["response"]
    assert "Its orders are for: C-2000 Cast Iron Housing (2 orders, 2 late)." in detail["response"]
    assert "first published in version 1 from suppliers.csv" in detail["response"]
    assert detail["evidence"][0]["summary"] == (
        "Read 27 published records from version 5; matched S-101 Bharat Castings Pvt Ltd."
    )

    by_name = await stack.ask("tell me about bharat castings")
    assert by_name["response"].startswith("S-101 is a supplier in your published data")

    summary = await stack.ask("Give me a summary")
    assert summary["actions_taken"] == ["nexus.cockpit.read"]
    assert "Your workspace holds 27 published records:" in summary["response"]
    assert (
        "3 of 7 purchase orders are late or flagged: PO-5001, PO-5002 and PO-5006."
        in summary["response"]
    )
    assert "S-105 Kyoto Bearings KK (at_risk)" in summary["response"]
    _assert_plain_language(summary["response"])

    ready = await stack.ask("Is my data ready?")
    assert ready["response"].startswith("All 5 uploads are published.")
    assert "inventory.csv (6 rows): published as version 5." in ready["response"]


async def test_the_answer_does_not_depend_on_how_politely_it_was_asked(stack: Stack) -> None:
    await stack.publish_all()
    plain = await stack.ask("Which purchase orders are delayed?")
    assert "3 of 7 purchase orders are late or flagged" in plain["response"]

    for phrasing in (
        "Can you tell me which purchase orders are delayed?",
        "Hey Cortex, which purchase orders are delayed?",
        "do you know which purchase orders are delayed",
    ):
        asked = await stack.ask(phrasing)
        assert asked["intent"] == "graph_query", phrasing
        assert asked["response"] == plain["response"], phrasing


async def test_open_questions_get_what_stands_out(stack: Stack) -> None:
    await stack.publish_all()
    for question in ("What needs my attention?", "Anything I should worry about?"):
        answer = await stack.ask(question)
        assert answer["intent"] == "state_overview", question
        assert answer["actions_taken"] == ["nexus.cockpit.read"]
        text = answer["response"]
        assert "What stands out as of 2026-11-17 (UTC):" in text
        assert "3 of 7 purchase orders are late or flagged: PO-5001, PO-5002 and PO-5006." in text
        assert "3 of 6 stock positions are below threshold" in text
        assert "S-101 Bharat Castings Pvt Ltd (delayed)" in text
        _assert_plain_language(text)


async def test_a_summary_of_one_record_is_about_that_record(stack: Stack) -> None:
    await stack.publish_all()
    whole = await stack.ask("Give me a summary")
    assert whole["response"].startswith("Your workspace holds 27 published records")

    for question in ("Summarise S-101", "Any issues with S-101?"):
        answer = await stack.ask(question)
        text = answer["response"]
        assert text.startswith(
            "S-101 is a supplier in your published data: Bharat Castings Pvt Ltd."
        ), question
        assert "PO-5001" in text and "PO-5002" in text
        assert "Your workspace holds" not in text
        _assert_plain_language(text)


async def test_values_named_in_a_question_narrow_the_list(stack: Stack) -> None:
    await stack.publish_all()

    in_germany = await stack.ask("Which suppliers are in DE?")
    assert in_germany["response"].startswith("1 of 6 suppliers matches country = DE:")
    assert "S-100 Acme Metals GmbH" in in_germany["response"]
    for other in ("S-101", "S-102", "S-103", "S-104", "S-105"):
        assert other not in in_germany["response"]

    # "in" as an ordinary word is not the country code IN.
    everyone = await stack.ask("Which suppliers are in my data?")
    assert everyone["response"].startswith("You have 6 suppliers:")

    tier_one = await stack.ask("tier 1 suppliers")
    assert tier_one["response"].startswith("3 of 6 suppliers match tier = tier_1:")

    in_transit = await stack.ask("orders in transit")
    assert in_transit["response"].startswith("1 of 7 purchase orders matches status = in_transit:")
    assert "PO-5003" in in_transit["response"]

    enough = await stack.ask("Do we have enough C-2000?")
    assert enough["response"].startswith(
        "1 of 1 stock position is below threshold or empty:\n"
        "- C-2000 Cast Iron Housing at WH-PUNE Pune Plant Store: 120 on hand against a safety "
        "stock of 300 (180 short)."
    )
    short = await stack.ask("What are we short on?")
    assert short["response"].startswith("3 of 6 stock positions are below threshold or empty:")


async def test_what_should_i_do_lists_the_options_the_data_shows(stack: Stack) -> None:
    await stack.publish_all()

    answer = await stack.ask("What should I do about the delay from supplier S-101?")
    text = answer["response"]

    assert answer["intent"] == "recommend"
    assert answer["actions_taken"] == ["nexus.recommend"]
    assert "2 of 2 purchase orders linked to S-101 Bharat Castings Pvt Ltd are late" in text
    assert "What that puts at risk (1 part):" in text
    assert "What your data shows about the options:" in text
    # Another open order for the same part, and another supplier on record for it.
    assert "PO-5007 (150 units, due 2099-01-24)" in text
    assert "S-100 Acme Metals GmbH (1 order, 0 late)" in text
    # It reports facts and does not pick an action or invent a cost.
    assert "does not choose an action for you" in text
    assert "₹" not in text and "$" not in text
    _assert_plain_language(text)


async def test_what_changed_reports_the_fields_a_new_upload_changed(stack: Stack) -> None:
    await stack.publish("suppliers.csv", SUPPLIERS)
    update = (
        b"supplier_id,supplier_name,country,tier,lead_time_days,status,on_time_rate\n"
        b"S-100,Acme Metals GmbH,DE,tier_1,21,active,0.96\n"
        b"S-103,Nordic Seals AB,SE,tier_2,14,suspended,0.64\n"
        b"S-106,Porto Gaskets Lda,PT,tier_2,18,active,0.90\n"
    )
    await stack.publish("suppliers_november.csv", update)

    text = (await stack.ask("What changed?"))["response"]

    assert text.startswith("The latest publish is version 2, from suppliers_november.csv")
    assert "Added 1 supplier: S-106." in text
    assert "Changed 1 existing record:" in text
    assert "S-103 Nordic Seals AB: status active -> suspended; on_time_rate 0.99 -> 0.64." in text
    # A row sent again with the same values is not reported as a change.
    assert "1 record was resubmitted with no change." in text
    assert "S-100" not in text.split("Earlier versions:")[0].replace("S-106", "")
    assert "Version 1: suppliers.csv" in text

    # The changed value is what later questions are answered from.
    detail = (await stack.ask("Tell me about S-103"))["response"]
    assert "status: suspended; on_time_rate: 0.64" in detail


async def test_nothing_is_answered_from_an_upload_that_is_not_published(stack: Stack) -> None:
    await stack.publish("suppliers.csv", SUPPLIERS, accept=False)

    answer = await stack.ask("Which suppliers do I have?")
    assert answer["response"].startswith(
        "Nothing is published in this workspace yet, so I have no data to answer from."
    )
    # The rows are uploaded but unreviewed: they must not leak into an answer.
    assert "Bharat" not in answer["response"] and "S-101" not in answer["response"]
    assert "suppliers.csv (6 rows): 42 claims waiting for review." in answer["response"]
    assert answer["world_state_version"] == 0

    ready = (await stack.ask("Is my data ready?"))["response"]
    assert "42 claims waiting for review" in ready


async def test_a_record_that_does_not_exist_is_reported_as_missing(stack: Stack) -> None:
    await stack.publish_all()

    missing = (await stack.ask("Tell me about PO-9999"))["response"]
    assert missing.startswith("I could not find PO-9999 in your published data.")
    assert "It holds" in missing and "7 purchase orders" in missing

    customers = (await stack.ask("Which customers do I have?"))["response"]
    assert customers.startswith("There are no customers in your published data.")

    mixed = (await stack.ask("Compare PO-5001 with PO-9999 status"))["response"]
    assert "I could not find PO-9999 in your published data." in mixed


async def test_viewer_reads_data_but_cannot_ask_for_recommendations(stack: Stack) -> None:
    await stack.publish_all()
    stack.user["roles"] = ["viewer"]

    allowed = await stack.ask("Which purchase orders are delayed?")
    assert allowed["permission_denied"] is None
    assert "PO-5001" in allowed["response"]

    denied = await stack.ask("What should I do about the delay from supplier S-101?")
    assert denied["permission_denied"] is not None
    assert "nexus.recommend" in denied["permission_denied"]
    assert denied["evidence"] == [] and denied["actions_taken"] == []
    # The denial says why; it does not claim that no evidence exists.
    assert denied["response"].startswith("I cannot do that.")
    assert "PO-5001" not in denied["response"]


async def test_answers_never_cross_workspaces(stack: Stack) -> None:
    await stack.publish_all()
    published_workspace = stack.workspace_id
    other_workspace = str(uuid4())

    # A user of another workspace sees an empty workspace, not these rows.
    stack.user["workspace_ids"] = [other_workspace]
    answer = await stack.ask("Which suppliers do I have?", workspace_id=other_workspace)
    assert answer["response"].startswith("Nothing is published in this workspace yet")
    assert "Bharat" not in json.dumps(answer)

    # And cannot ask about a workspace they do not belong to.
    refused = await stack.client.post(
        "/api/v1/nexus/vanessa/ask",
        params={"workspace_id": published_workspace},
        json={"query": "Which suppliers do I have?"},
    )
    assert refused.status_code in {403, 404}
    assert "Bharat" not in refused.text


async def test_questions_it_cannot_read_get_examples_not_a_guess(stack: Stack) -> None:
    await stack.publish_all()

    unknown = await stack.ask("asdf qwerty zxcv")
    assert unknown["intent"] == "unknown"
    assert unknown["actions_taken"] == [] and unknown["evidence"] == []
    assert "Which purchase orders are late?" in unknown["response"]

    help_text = (await stack.ask("help"))["response"]
    assert "what is late, what is short, what is exposed" in help_text

    signals = (await stack.ask("show active signals"))["response"]
    # Signals come from graph structure; the answer says so rather than
    # presenting them as delays or shortages.
    assert "not from the dates, statuses or quantities in your files" in signals


async def _signals_unreachable(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    raise ConnectionError("Error 111 connecting to cache-7.internal:6379. Connection refused.")


async def test_a_recommendation_does_not_depend_on_signals(
    stack: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Signals are a supplement: without them the answer still comes from the data."""
    await stack.publish_all()
    monkeypatch.setattr(vanessa_tools, "_signal_read", _signals_unreachable)

    answer = await stack.ask("What should I do about the delay from supplier S-101?")
    assert answer["intent"] == "recommend"
    assert answer["actions_taken"] == ["nexus.recommend"]
    text = answer["response"]
    assert "2 of 2 purchase orders linked to S-101 Bharat Castings Pvt Ltd are late" in text
    assert "PO-5007 (150 units, due 2099-01-24)" in text
    assert "this built-in assistant does not choose an action for you" in text
    assert "cache-7.internal" not in json.dumps(answer)


async def test_a_failed_lookup_is_reported_without_internal_details(
    stack: Stack, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    await stack.publish_all()
    monkeypatch.setattr(vanessa_tools, "_signal_read", _signals_unreachable)

    with caplog.at_level("ERROR"):
        answer = await stack.ask("show active signals")
    assert answer["response"] == (
        "I could not read that data: the lookup (nexus.signal.read) failed. Nothing was changed. "
        "Please try again; if it keeps failing, the cause is in the service log."
    )
    assert answer["actions_taken"] == []
    assert answer["evidence"] == [
        {
            "source": "tool:nexus.signal.read",
            "tool": "nexus.signal.read",
            "summary": "Lookup failed.",
            "data_excerpt": {"error": "tool failed"},
        }
    ]
    # The host name in the exception reaches the log, with the trace id, and nothing else.
    assert "cache-7.internal" not in json.dumps(answer)
    logged = [record for record in caplog.records if "nexus.signal.read" in record.getMessage()]
    assert logged and answer["trace_id"] in logged[0].getMessage()
    assert "cache-7.internal" in caplog.text


async def test_configured_model_is_given_the_same_grounded_evidence(
    stack: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    await stack.publish_all()
    requests: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(payload)
        if "response_format" in payload:
            # The model is unsure what the question is.
            content = '{"intent":"unknown","confidence":0.2,"entities":{}}'
        else:
            content = "MODEL ANSWER"
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    model_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = OpenAICompatibleLLMAdapter(
        base_url="https://model-gateway.example/v1",
        api_key="test-secret",
        model="test-model",
        client=model_client,
    )
    monkeypatch.setattr(nexus_persistent, "get_llm_adapter", lambda settings=None: adapter)
    try:
        answer = await stack.ask("Which purchase orders are delayed?")
    finally:
        await model_client.aclose()

    # The words of the question name workspace data, so it is still read.
    assert answer["intent"] == "graph_query"
    assert answer["actions_taken"] == ["nexus.graph.read"]
    assert answer["response"] == "MODEL ANSWER"
    assert answer["world_state_version"] == 5

    classify, synthesize = requests
    assert "graph_query for questions about" in classify["messages"][0]["content"]
    system_prompt = synthesize["messages"][0]["content"]
    assert "only the supplied workspace-scoped tool evidence" in system_prompt
    assert "Write plain text" in system_prompt
    # The model is handed the facts the built-in answer is made from.
    evidence = json.loads(synthesize["messages"][1]["content"])["evidence"]
    for fact in (
        "PO-5001",
        "Bharat Castings Pvt Ltd",
        "now expected 2026-11-26, 21 days after the promised 2026-11-05",
        '"late_count":3',
        '"as_of":"2026-11-17"',
    ):
        assert fact in evidence, fact
    assert "evidence truncated" not in evidence
    # The workspace evidence leads the payload, ahead of the legacy fields.
    assert evidence.index('"workspace_data"') < evidence.index('"snapshot_id"')
