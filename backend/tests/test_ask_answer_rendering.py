"""The sentences the built-in assistant writes from evidence.

Published records are stored directly and read through the same evidence
builder the Ask route uses, then rendered. The assertions quote whole sentences
so the wording, the numbers and the honesty about missing data are all pinned:
an answer never claims more than the records support.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

# Register the models before the db_engine fixture copies Base.metadata.
from app.modules.compiler.models import EvidenceClaim, EvidenceConflict
from app.modules.graph.models import GraphEdge, GraphNode, GraphSnapshot, GraphWriteEvent  # noqa: F401
from app.modules.nexus_spine.p0_migration import workspace_evidence
from app.modules.nexus_spine.p0_migration.answer_rendering import (
    no_evidence_answer,
    render_answer,
    render_tool_answer,
    render_workspace_answer,
    summarize_evidence,
    world_state_version_of,
)
from app.modules.nexus_spine.p0_migration.workspace_evidence import build_workspace_evidence
from app.modules.sources.models import SourceBatch, SourceFile

TODAY = date(2026, 11, 17)
Record = tuple[str, str, dict[str, Any]]


async def publish(
    session: AsyncSession, workspace_id: str, records: list[Record], *, file: str = "data.csv"
) -> None:
    """Store records as one published version that came from one file."""
    batch_id = str(uuid4())
    session.add(
        SourceBatch(
            batch_id=batch_id,
            workspace_id=workspace_id,
            status="validated",
            checksum=uuid4().hex,
            source_system_hint="erp",
            file_count=1,
        )
    )
    session.add(
        SourceFile(
            batch_id=batch_id,
            workspace_id=workspace_id,
            storage_key=f"{workspace_id}/{file}",
            original_name=file,
            mime_type="text/csv",
            size=10,
            checksum=uuid4().hex,
            row_count=len(records),
        )
    )
    session.add(
        GraphSnapshot(
            workspace_id=workspace_id,
            version=1,
            snapshot_hash=uuid4().hex,
            node_count=len(records),
            source_batch_id=batch_id,
        )
    )
    for entity_type, entity_id, attributes in records:
        session.add(
            GraphNode(
                workspace_id=workspace_id,
                entity_type=entity_type,
                entity_id=entity_id,
                attributes=attributes,
            )
        )
    await session.flush()


async def answer(
    session: AsyncSession, workspace_id: str, question: str, *, brief: bool = False, **options: Any
) -> str:
    evidence = await build_workspace_evidence(
        session, workspace_id, question, today=TODAY, **options
    )
    return render_workspace_answer(evidence, brief=brief)


PUMP_RECORDS: list[Record] = [
    ("Supplier", "S-101", {"supplier_id": "S-101", "supplier_name": "Bharat Castings", "status": "delayed"}),
    ("Product", "C-2000", {"sku": "C-2000", "product_name": "Cast Iron Housing"}),
    ("Product", "P-1000", {"sku": "P-1000", "product_name": "Pump A"}),
    ("Customer", "CU-1", {"customer_id": "CU-1", "customer_name": "Delta Water Works"}),
    ("Facility", "WH-1", {"warehouse_id": "WH-1", "warehouse_name": "Pune Store", "_facility_type": "warehouse"}),
    (
        "PurchaseOrder",
        "PO-1",
        {
            "po_number": "PO-1", "supplier_id": "S-101", "sku": "C-2000", "quantity": "400",
            "promised_date": "2026-11-05", "expected_date": "2026-11-26", "status": "delayed",
        },
    ),
    ("InventoryItem", "INV-1", {"inventory_id": "INV-1", "sku": "C-2000", "facility_id": "WH-1", "quantity_on_hand": "120", "safety_stock": "300"}),
    ("BOM", "B-1", {"bom_id": "B-1", "parent_sku": "P-1000", "child_sku": "C-2000"}),
    (
        "SalesOrder",
        "SO-1",
        {"so_number": "SO-1", "customer_id": "CU-1", "sku": "P-1000", "quantity": "20", "promised_date": "2026-12-01", "status": "confirmed"},
    ),
]  # fmt: skip


async def test_exposure_follows_a_delay_to_the_customer_order(db_session: AsyncSession) -> None:
    workspace_id = str(uuid4())
    await publish(db_session, workspace_id, PUMP_RECORDS)

    text = await answer(db_session, workspace_id, "Which orders are exposed?")

    assert text.startswith("1 late or flagged supply order affects 1 part as of 2026-11-17 (UTC):")
    assert (
        "- C-2000 Cast Iron Housing: 400 units late on PO-1 from S-101 Bharat Castings. Stock is "
        "already below threshold: 120 on hand at WH-1 Pune Store against a safety stock of 300 "
        "(180 short). It goes into P-1000 Pump A. 1 open customer order needs it."
    ) in text
    assert "1 open customer order depends on these parts:" in text
    assert (
        "- SO-1 for CU-1 Delta Water Works: 20 x P-1000 Pump A, promised 2026-12-01 "
        "(contains C-2000 Cast Iron Housing)."
    ) in text
    # Sales orders and a bill of materials are published, so no gap is reported.
    assert "cannot trace" not in text
    assert text.endswith("Source: your published data, version 1 (data.csv).")


async def test_nothing_late_is_said_plainly_with_the_rule_used(db_session: AsyncSession) -> None:
    workspace_id = str(uuid4())
    await publish(
        db_session,
        workspace_id,
        [
            ("PurchaseOrder", "PO-1", {"po_number": "PO-1", "status": "confirmed", "promised_date": "2099-01-01"}),
            ("PurchaseOrder", "PO-2", {"po_number": "PO-2", "status": "delivered", "promised_date": "2026-10-01", "actual_delivery_date": "2026-10-04"}),
            ("PurchaseOrder", "PO-3", {"po_number": "PO-3", "status": "confirmed", "promised_date": "01/02/2099"}),
        ],
    )  # fmt: skip

    late = await answer(db_session, workspace_id, "Which purchase orders are late?")
    assert late.startswith(
        "None of the 3 purchase orders is late or flagged as of 2026-11-17 (UTC)."
    )
    assert "An order counts as late when its status says so" in late
    # An order that arrived late is closed: mentioned, not counted as open and late.
    assert "1 more arrived late and is closed: PO-2." in late
    assert "1 record has a date I could not read (I read dates written as YYYY-MM-DD)" in late

    exposed = await answer(db_session, workspace_id, "Which orders are exposed?")
    assert exposed.startswith(
        "No order or shipment in your published data is late or flagged as of 2026-11-17 (UTC), "
        "so no delay is putting orders at risk."
    )


async def test_missing_kinds_of_data_are_named_not_papered_over(db_session: AsyncSession) -> None:
    workspace_id = str(uuid4())
    await publish(
        db_session,
        workspace_id,
        [("Supplier", "S-1", {"supplier_id": "S-1", "supplier_name": "Acme Metals"})],
        file="suppliers.csv",
    )

    late = await answer(db_session, workspace_id, "Which orders are late?")
    assert late.startswith(
        "I found no orders or shipments in your published data, so I cannot tell what is late."
    )
    stock = await answer(db_session, workspace_id, "What is below safety stock?")
    assert stock.startswith("No inventory is published in this workspace, so I cannot judge stock.")
    summary = await answer(db_session, workspace_id, "Give me a summary")
    assert (
        "Your workspace holds 1 published record: 1 supplier, joined by 0 relationships." in summary
    )
    assert "- No orders or shipments are published, so lateness cannot be judged." in summary
    assert (
        "- No inventory with a readable quantity is published, so stock cannot be judged."
        in summary
    )
    customers = await answer(db_session, workspace_id, "Which customers do I have?")
    assert customers.startswith("There are no customers in your published data.")
    assert 'Try asking: "tell me about S-1" and "what changed?".' in customers


async def test_stock_answers_say_which_positions_could_not_be_judged(
    db_session: AsyncSession,
) -> None:
    workspace_id = str(uuid4())
    await publish(
        db_session,
        workspace_id,
        [
            (
                "InventoryItem",
                "I-1",
                {"sku": "A-1", "quantity_on_hand": "40", "safety_stock": "10"},
            ),
            ("InventoryItem", "I-2", {"sku": "A-2", "quantity_on_hand": "7"}),
            ("InventoryItem", "I-3", {"sku": "A-3", "quantity_on_hand": "plenty"}),
        ],
    )

    text = await answer(db_session, workspace_id, "What is below safety stock?")

    assert text.startswith("None of the 2 stock positions is below its threshold.")
    assert "1 position has no safety-stock or reorder field, so I could not judge it." in text
    assert "1 inventory record has no readable on-hand quantity." in text


async def test_long_lists_are_cut_with_the_full_count_stated(db_session: AsyncSession) -> None:
    workspace_id = str(uuid4())
    suppliers: list[Record] = [
        ("Supplier", f"S-{number:03d}", {"supplier_id": f"S-{number:03d}", "tier": "tier_1" if number % 2 else "tier_2"})
        for number in range(1, 31)
    ]  # fmt: skip
    await publish(db_session, workspace_id, suppliers)

    text = await answer(db_session, workspace_id, "Which suppliers do I have?")
    assert text.startswith("You have 30 suppliers:")
    assert text.count("\n- S-") == 8
    assert "- and 22 more." in text

    filtered = await answer(db_session, workspace_id, "Which tier_2 suppliers do I have?")
    assert filtered.startswith("15 of 30 suppliers match tier = tier_2:")
    assert "S-001" not in filtered and "S-002" in filtered


async def test_a_partial_read_of_a_large_workspace_is_disclosed(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace_id = str(uuid4())
    orders: list[Record] = [
        ("PurchaseOrder", f"PO-{number}", {"po_number": f"PO-{number}", "status": "delayed"})
        for number in range(1, 8)
    ]
    await publish(db_session, workspace_id, orders)
    monkeypatch.setattr(workspace_evidence, "MAX_NODES_PER_TYPE", 4)

    text = await answer(db_session, workspace_id, "Which purchase orders are late?")

    # Only the records read are judged, and the answer says so.
    assert text.startswith("4 of 4 purchase orders are late or flagged")
    assert "I read 4 of 7 purchase orders" in text
    assert "cover only the records read" in text


async def test_upload_states_are_explained(db_session: AsyncSession) -> None:
    workspace_id = str(uuid4())

    def upload(
        name: str, claims: dict[str, int], *, conflicts: int = 0, blocking: bool = False
    ) -> None:
        batch_id, file_id = str(uuid4()), str(uuid4())
        db_session.add(
            SourceBatch(
                batch_id=batch_id,
                workspace_id=workspace_id,
                status="validated",
                checksum=uuid4().hex,
                source_system_hint="erp",
                file_count=1,
            )
        )
        db_session.add(
            SourceFile(
                file_id=file_id,
                batch_id=batch_id,
                workspace_id=workspace_id,
                storage_key=name,
                original_name=name,
                mime_type="text/csv",
                size=1,
                checksum=uuid4().hex,
                row_count=4,
            )
        )
        for state, count in claims.items():
            for _ in range(count):
                db_session.add(
                    EvidenceClaim(
                        workspace_id=workspace_id,
                        source_file_id=file_id,
                        batch_id=batch_id,
                        row_number=1,
                        source_column="a",
                        raw_value="b",
                        claim_state=state,
                    )
                )
        for _ in range(conflicts):
            db_session.add(
                EvidenceConflict(
                    workspace_id=workspace_id,
                    batch_id=batch_id,
                    claim_ids=[],
                    blocking=blocking,
                    status="open",
                    explanation="two values",
                )
            )

    upload("new.csv", {})
    upload("waiting.csv", {"pending_review": 3, "accepted": 1})
    upload("ready.csv", {"accepted": 8})
    upload("blocked.csv", {"accepted": 2}, conflicts=2, blocking=True)
    upload("rejected.csv", {"rejected": 5})
    await db_session.flush()  # fmt: skip

    text = await answer(db_session, workspace_id, "Is my data ready?")

    assert text.startswith("Nothing is published in this workspace yet")
    assert "5 uploads in progress:" in text
    assert "- blocked.csv (4 rows): blocked by 2 conflicts that must be resolved first." in text
    assert "- waiting.csv (4 rows): 3 claims waiting for review." in text
    assert "- ready.csv (4 rows): ready to publish (8 claims accepted)." in text
    assert (
        "- rejected.csv (4 rows): reviewed, but no claim was accepted, so there is nothing to publish."
        in text
    )
    assert "- new.csv (4 rows): uploaded, not prepared for review yet." in text
    # What blocks publishing is listed first.
    assert text.index("blocked.csv") < text.index("waiting.csv") < text.index("ready.csv")


async def test_decision_brief_reports_no_alternative_when_the_data_has_none(
    db_session: AsyncSession,
) -> None:
    workspace_id = str(uuid4())
    await publish(db_session, workspace_id, PUMP_RECORDS)

    text = await answer(db_session, workspace_id, "What should I do about S-101?", brief=True)

    assert "What your data shows about the options:" in text
    assert (
        "- C-2000 Cast Iron Housing: no other open order for it is on time; no other supplier "
        "appears on your published orders for it."
    ) in text
    assert "this built-in assistant does not choose an action for you" in text


def test_tool_failures_and_unavailable_actions_are_explained() -> None:
    failed = render_tool_answer("nexus.graph.read", {"error": "tool failed"})
    assert failed == (
        "I could not read that data: the lookup (nexus.graph.read) failed. Nothing was changed. "
        "Please try again; if it keeps failing, the cause is in the service log."
    )
    # Whatever the evidence carries as the error, its text is not repeated to the user.
    leaked = render_tool_answer("nexus.graph.read", {"error": "connecting to 10.0.0.5:6379"})
    assert leaked == failed
    assert summarize_evidence("nexus.graph.read", {"error": "connecting to 10.0.0.5:6379"}) == (
        "Lookup failed."
    )
    unavailable = render_tool_answer("nexus.decision.approve", {"error": "tool not registered"})
    assert unavailable.startswith("Approving a decision is not available from the Ask box.")
    missing = render_tool_answer("nexus.graph.read", {"error": "tool not registered"})
    assert missing == (
        "That lookup (nexus.graph.read) is not available from the Ask box. Nothing was changed."
    )
    assert summarize_evidence("nexus.graph.read", {"error": "tool not registered"}) == (
        "Lookup not available."
    )


def test_other_tools_are_rendered_as_sentences() -> None:
    assert render_tool_answer(
        "nexus.forecast.read", {"forecasts": [], "count": 0, "sku_filter": "SKU-42"}
    ) == (
        "No forecast is stored for SKU-42 in this workspace. Forecasts appear here after a demand "
        "run; uploading files does not create one."
    )
    forecast = render_tool_answer(
        "nexus.forecast.read",
        {
            "forecasts": [{"sku": "SKU-42", "p50": 120.0, "p80": 150.0, "p95": 180.5, "horizon_days": 14, "created_at": "2026-11-10T08:00:00+00:00"}],
            "count": 1,
            "sku_filter": "SKU-42",
        },
    )  # fmt: skip
    assert "- SKU-42: P50 120, P80 150, P95 180.5 over 14 days (created 2026-11-10)." in forecast

    assert render_tool_answer("nexus.decision.list", {"decisions": [], "count": 0}) == (
        "No decisions are recorded in this workspace."
    )
    decisions = render_tool_answer(
        "nexus.decision.list",
        {
            "decisions": [
                {"decision_id": "D-1", "situation": "Expedite PO-1", "phase": "proposed"}
            ],
            "count": 1,
        },
    )
    assert decisions == "1 decision in this workspace:\n- D-1 Expedite PO-1 (proposed)"

    # A payload with its own summary is quoted, not dumped.
    assert render_tool_answer(
        "nexus.cockpit.read", {"summary": "World state v12: 5 SKUs healthy", "version": 12}
    ) == ("World state v12: 5 SKUs healthy")
    generic = render_tool_answer(
        "nexus.demand.run",
        {"status": "insufficient_history", "observations_found": 1, "rows": [1, 2]},
    )
    assert generic == "- status: insufficient_history\n- observations found: 1\n- rows: 2 items"
    for text in (forecast, decisions, generic):
        assert "{" not in text and "}" not in text


def test_answers_without_evidence_offer_real_examples() -> None:
    assert "Which purchase orders are late?" in no_evidence_answer("unknown")
    assert no_evidence_answer("greeting").startswith("Hello.")
    assert "I only read" in no_evidence_answer("help")
    assert no_evidence_answer("forecast_query").startswith(
        "I read that as a forecast query request"
    )
    assert render_answer("unknown", []) == no_evidence_answer("unknown")
    # Evidence from two tools is rendered as two blocks.
    assert (
        render_answer("explain", [("a", {"summary": "one"}), ("b", {"message": "two"})])
        == "one\n\ntwo"
    )


def test_evidence_summary_and_version_are_read_from_the_tool_output() -> None:
    assert summarize_evidence("nexus.graph.read", {"error": "boom"}) == "Lookup failed."
    assert (
        summarize_evidence("nexus.decision.list", {"decisions": [], "count": 0})
        == "Read 0 decisions."
    )
    assert summarize_evidence("x", {"status": "completed"}) == "Status: completed."
    empty = {"workspace_data": {"workspace": {"world_state_version": 0}, "question_focus": {}}}
    assert (
        summarize_evidence("nexus.graph.read", empty)
        == "Nothing is published in this workspace yet."
    )

    assert (
        world_state_version_of({"workspace_data": {"workspace": {"world_state_version": 7}}}) == 7
    )
    assert world_state_version_of({"world_state_version": 3}) == 3
    assert world_state_version_of({"graph": {"world_state_version": 2}}) == 2
    assert world_state_version_of({"summary": "x", "version": 12}) is None
    assert world_state_version_of("text") is None
