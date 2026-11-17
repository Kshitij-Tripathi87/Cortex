"""Facts the Ask box derives from published records.

Every rule is checked on small hand-built records with a fixed "today", so a
failure names the rule that broke: what counts as late, what counts as short,
how a delay is traced to stock and customer orders, and how the words of a
question are matched to records. Values that cannot be read are never guessed.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from app.modules.nexus_spine.p0_migration.workspace_facts import (
    NodeRecord,
    WorkspaceIndex,
    apply_value_filters,
    assess_flow,
    assess_stock,
    attention_summary,
    build_exposure,
    counterparties,
    diff_attributes,
    format_number,
    late_flows,
    link_names,
    match_value_filters,
    parse_date,
    parse_number,
    points_at,
    stock_positions,
    supplier_rollup,
)

TODAY = date(2026, 11, 17)


def rec(entity_type: str, entity_id: str, **attributes: Any) -> NodeRecord:
    return NodeRecord(
        node_id=f"{entity_type}:{entity_id}",
        entity_type=entity_type,
        entity_id=entity_id,
        attributes=attributes,
    )


def pump_workspace() -> WorkspaceIndex:
    """Two suppliers of one casting, a bill of materials and two customer orders."""
    return WorkspaceIndex(
        [
            rec("Supplier", "S-101", supplier_id="S-101", supplier_name="Bharat Castings Pvt Ltd", status="delayed"),
            rec("Supplier", "S-100", supplier_id="S-100", supplier_name="Acme Metals GmbH", status="active"),
            rec("Product", "C-2000", sku="C-2000", product_name="Cast Iron Housing"),
            rec("Product", "C-2001", sku="C-2001", product_name="Drive Motor"),
            rec("Product", "P-1000", sku="P-1000", product_name="Pump A"),
            rec("Facility", "WH-PUNE", warehouse_id="WH-PUNE", warehouse_name="Pune Store", _facility_type="warehouse"),
            rec("Facility", "WH-HAM", warehouse_id="WH-HAM", warehouse_name="Hamburg DC", _facility_type="warehouse"),
            rec("Customer", "CU-1", customer_id="CU-1", customer_name="Delta Water Works"),
            rec(
                "PurchaseOrder", "PO-1", po_number="PO-1", supplier_id="S-101", sku="C-2000", quantity="400",
                promised_date="2026-11-05", expected_date="2026-11-26", status="delayed", ship_to_facility_id="WH-PUNE",
            ),
            rec(
                "PurchaseOrder", "PO-2", po_number="PO-2", supplier_id="S-101", sku="C-2000", quantity="250",
                promised_date="2026-11-24", expected_date="2026-12-15", status="delayed",
            ),
            rec(
                "PurchaseOrder", "PO-3", po_number="PO-3", supplier_id="S-100", sku="C-2000", quantity="150",
                promised_date="2026-11-24", expected_date="2026-11-24", status="confirmed",
            ),
            rec(
                "PurchaseOrder", "PO-4", po_number="PO-4", supplier_id="S-100", sku="C-2001", quantity="90",
                promised_date="2026-10-01", status="delivered", actual_delivery_date="2026-10-01",
            ),
            rec("InventoryItem", "INV-1", inventory_id="INV-1", sku="C-2000", facility_id="WH-PUNE", quantity_on_hand="120", safety_stock="300"),
            rec("InventoryItem", "INV-2", inventory_id="INV-2", sku="C-2000", facility_id="WH-HAM", quantity_on_hand="500", safety_stock="150"),
            rec("InventoryItem", "INV-3", inventory_id="INV-3", sku="C-2001", facility_id="WH-PUNE", quantity_on_hand="410", safety_stock="150"),
            rec("BOM", "B-1", bom_id="B-1", parent_sku="P-1000", child_sku="C-2000", quantity_per_unit="1"),
            rec(
                "SalesOrder", "SO-1", so_number="SO-1", customer_id="CU-1", sku="P-1000", quantity="20",
                promised_date="2026-12-01", status="confirmed",
            ),
            rec(
                "SalesOrder", "SO-2", so_number="SO-2", customer_id="CU-1", sku="C-2001", quantity="5",
                promised_date="2026-12-05", status="confirmed",
            ),
        ]
    )  # fmt: skip


# ── Reading values ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "number"),
    [
        ("400", 400.0),
        ("210.50", 210.5),
        ("1,500", 1500.0),
        ("1,234,567.25", 1234567.25),
        ("1,23,456", 123456.0),
        ("12,34,567.5", 1234567.5),
        ("1.234,5", 1234.5),
        ("12,5", 12.5),
        ("-3", -3.0),
        ("1e3", 1000.0),
    ],
)
def test_parse_number_reads_unambiguous_notations(text: str, number: float) -> None:
    assert parse_number(text) == number


@pytest.mark.parametrize(
    "text", ["", "  ", "n/a", "12 units", "1,2,3", "abc", None, True, "nan", "inf"]
)
def test_parse_number_refuses_to_guess(text: Any) -> None:
    assert parse_number(text) is None


def test_parse_date_reads_iso_and_refuses_ambiguous_notations() -> None:
    assert parse_date("2026-11-05") == date(2026, 11, 5)
    assert parse_date("2026/11/05") == date(2026, 11, 5)
    assert parse_date("2026-08-18T18:00:00Z") == date(2026, 8, 18)
    assert parse_date("2026-11-05 09:30:00") == date(2026, 11, 5)
    # 05/11/2026 could be 5 November or 11 May: not read.
    assert parse_date("05/11/2026") is None
    assert parse_date("11-05-2026") is None
    assert parse_date("next week") is None
    assert parse_date("2026-13-40") is None
    assert parse_date("") is None


def test_format_number_keeps_whole_numbers_whole() -> None:
    assert format_number(1500.0) == "1,500"
    assert format_number(0.71) == "0.71"
    assert format_number(12.5) == "12.5"


# ── Lateness ─────────────────────────────────────────────────────────────────


def flow(**attributes: Any) -> dict[str, Any]:
    record = rec("PurchaseOrder", "PO-X", po_number="PO-X", **attributes)
    return assess_flow(record, WorkspaceIndex([record]), TODAY)


def test_an_order_is_late_when_its_status_says_so() -> None:
    result = flow(status="Delayed")
    assert result["late"] is True
    assert result["reasons"] == ["status is Delayed"]
    # Statuses that need attention are flagged too.
    assert flow(status="on hold")["late"] is True
    assert flow(order_status="at_risk")["reasons"] == ["order_status is at_risk"]


def test_an_order_is_late_when_expected_after_promised() -> None:
    result = flow(status="in_transit", promised_date="2026-12-01", expected_date="2026-12-09")
    assert result["late"] is True
    assert result["days_late"] == 8
    assert result["reasons"] == ["now expected 2026-12-09, 8 days after the promised 2026-12-01"]


def test_an_open_order_past_its_promised_date_is_late_as_of_today() -> None:
    result = flow(status="confirmed", promised_date="2026-11-16")
    assert result["late"] is True
    assert result["days_late"] == 1
    assert result["reasons"] == ["promised for 2026-11-16 and not marked as delivered 1 day later"]
    # The same order asked about a day earlier is not late: the verdict depends
    # on the date it is judged against, which the answer states.
    record = rec("PurchaseOrder", "PO-X", status="confirmed", promised_date="2026-11-16")
    assert assess_flow(record, WorkspaceIndex([record]), date(2026, 11, 16))["late"] is False


def test_an_on_time_or_closed_order_is_not_late() -> None:
    assert (
        flow(status="confirmed", promised_date="2026-12-01", expected_date="2026-12-01")["late"]
        is False
    )
    assert (
        flow(status="confirmed", promised_date="2026-12-01", expected_date="2026-11-28")["late"]
        is False
    )
    delivered = flow(
        status="delivered", promised_date="2026-10-01", actual_delivery_date="2026-10-01"
    )
    assert (
        delivered["late"] is False
        and delivered["open"] is False
        and delivered["delivered_late"] is False
    )
    # Cancelled long ago: closed, so not counted as overdue.
    assert flow(status="cancelled", promised_date="2026-01-01")["late"] is False


def test_an_order_that_arrived_late_is_reported_separately_from_open_late_orders() -> None:
    result = flow(status="delivered", promised_date="2026-10-01", actual_delivery_date="2026-10-04")
    assert result["late"] is False
    assert result["delivered_late"] is True
    assert result["days_late"] == 3


def test_dates_that_cannot_be_read_are_reported_not_guessed() -> None:
    result = flow(status="confirmed", promised_date="05/12/2026", expected_date="12/12/2026")
    assert result["late"] is False
    assert result["promised_date"] is None
    assert result["unreadable_date_fields"] == ["promised_date", "expected_date"]


def test_other_date_and_status_column_names_are_understood() -> None:
    result = flow(order_status="open", sla_due_date="2026-08-18T18:00:00Z")
    assert result["late"] is True
    assert result["promised_field"] == "sla_due_date"
    result = flow(status="confirmed", requested_delivery_date="2026-12-01", eta="2026-12-03")
    assert result["days_late"] == 2


def test_late_flows_counts_and_orders_by_days_late() -> None:
    index = pump_workspace()
    result = late_flows(index, TODAY)
    assert result["assessed"] == {"PurchaseOrder": 4, "SalesOrder": 2}
    assert [item["entity_id"] for item in result["late"]] == ["PO-1", "PO-2"]
    assert result["late_count"] == 2
    assert result["delivered_late_count"] == 0

    only_orders = late_flows(index, TODAY, entity_types=["PurchaseOrder"])
    assert only_orders["assessed"] == {"PurchaseOrder": 4}

    supplier = index.get("Supplier", "S-100")
    assert supplier is not None
    about_acme = late_flows(index, TODAY, focus=[supplier])
    assert about_acme["assessed"] == {"PurchaseOrder": 2}
    assert about_acme["late"] == []


# ── Stock ────────────────────────────────────────────────────────────────────


def test_stock_below_its_own_threshold_is_short() -> None:
    index = pump_workspace()
    result = stock_positions(index)
    assert result["assessed"] == 3
    assert [item["entity_id"] for item in result["short"]] == ["INV-1"]
    short = result["short"][0]
    assert (short["on_hand"], short["threshold"], short["shortfall"]) == (120.0, 300.0, 180.0)
    assert short["threshold_field"] == "safety_stock"
    assert short["product"]["entity_id"] == "C-2000"
    assert short["facility"]["name"] == "Pune Store"


def test_stock_without_threshold_or_quantity_is_not_judged() -> None:
    index = WorkspaceIndex(
        [
            rec("InventoryItem", "I-1", sku="A", quantity_on_hand="10"),
            rec("InventoryItem", "I-2", sku="B", quantity_on_hand="lots"),
            rec("InventoryItem", "I-3", sku="C", quantity_on_hand="0", reorder_point="5"),
        ]
    )
    result = stock_positions(index)
    assert result["assessed"] == 2
    assert result["without_threshold"] == 1
    assert result["without_quantity"] == 1
    assert [item["entity_id"] for item in result["short"]] == ["I-3"]
    assert result["short"][0]["out_of_stock"] is True
    assert result["short"][0]["threshold_field"] == "reorder_point"
    first = index.get("InventoryItem", "I-1")
    assert first is not None
    assert assess_stock(first, index) is not None
    assert assess_stock(first, index)["below_threshold"] is False  # type: ignore[index]


# ── Exposure ─────────────────────────────────────────────────────────────────


def test_exposure_traces_late_supply_to_stock_and_customer_orders() -> None:
    result = build_exposure(pump_workspace(), TODAY)
    assert [item["entity_id"] for item in result["late_supply"]] == ["PO-1", "PO-2"]
    assert len(result["parts_at_risk"]) == 1
    part = result["parts_at_risk"][0]
    assert part["product"]["entity_id"] == "C-2000"
    assert part["late_orders"] == ["PO-1", "PO-2"]
    assert part["late_quantity"] == 650.0
    assert part["stock_state"] == "below_threshold"
    assert [item["entity_id"] for item in part["stock"]] == ["INV-1", "INV-2"]
    # The casting goes into Pump A, which a customer has ordered.
    assert [item["entity_id"] for item in part["goes_into"]] == ["P-1000"]
    assert part["customer_orders"] == ["SO-1"]
    assert result["customer_order_count"] == 1
    order = result["customer_orders"][0]
    assert order["entity_id"] == "SO-1"
    assert order["needs_part"]["entity_id"] == "C-2000"
    assert order["through_product"]["entity_id"] == "P-1000"
    # SO-2 is for a part with no late supply: not exposed.
    assert "SO-2" not in [item["entity_id"] for item in result["customer_orders"]]
    assert result["gaps"] == []


def test_exposure_reports_on_time_cover_and_other_suppliers_from_the_data() -> None:
    part = build_exposure(pump_workspace(), TODAY)["parts_at_risk"][0]
    assert [item["entity_id"] for item in part["on_time_supply"]] == ["PO-3"]
    assert part["on_time_supply"][0]["due"] == "2026-11-24"
    assert [
        (item["entity_id"], item["order_count"], item["late_order_count"])
        for item in part["other_suppliers"]
    ] == [("S-100", 1, 0)]


def test_exposure_names_the_links_it_cannot_follow() -> None:
    index = WorkspaceIndex(
        [
            rec("Product", "C-1", sku="C-1"),
            rec("PurchaseOrder", "PO-1", sku="C-1", status="delayed", quantity="10"),
            rec("PurchaseOrder", "PO-2", status="delayed"),
        ]
    )
    result = build_exposure(index, TODAY)
    assert result["gaps"] == ["no_sales_orders", "no_bill_of_materials", "no_inventory"]
    assert result["parts_at_risk"][0]["stock_state"] == "no_inventory_record"
    assert result["late_supply_without_product"] == ["PO-2"]
    assert result["customer_orders"] == []


def test_exposure_is_empty_when_nothing_is_late() -> None:
    index = WorkspaceIndex(
        [
            rec("Product", "C-1", sku="C-1"),
            rec("PurchaseOrder", "PO-1", sku="C-1", status="confirmed", promised_date="2099-01-01"),
        ]
    )
    result = build_exposure(index, TODAY)
    assert result["late_supply"] == [] and result["parts_at_risk"] == []


def test_exposure_can_be_limited_to_the_records_a_question_names() -> None:
    index = pump_workspace()
    acme = index.get("Supplier", "S-100")
    bharat = index.get("Supplier", "S-101")
    assert acme is not None and bharat is not None
    assert build_exposure(index, TODAY, focus=[acme])["late_supply"] == []
    assert len(build_exposure(index, TODAY, focus=[bharat])["late_supply"]) == 2


def test_supplier_rollup_and_counterparties_count_published_orders() -> None:
    index = pump_workspace()
    rows = {row["entity_id"]: row for row in supplier_rollup(index, TODAY)}
    assert (rows["S-101"]["order_count"], rows["S-101"]["late_order_count"]) == (2, 2)
    assert rows["S-101"]["flag"]["status"] == "delayed"
    assert (rows["S-100"]["order_count"], rows["S-100"]["late_order_count"]) == (2, 0)
    assert rows["S-100"]["flag"] is None

    casting = index.get("Product", "C-2000")
    assert casting is not None
    parties = counterparties(index, TODAY, casting)
    assert [
        (row["entity_id"], row["order_count"], row["late_order_count"])
        for row in parties["suppliers"]
    ] == [
        ("S-101", 2, 2),
        ("S-100", 1, 0),
    ]
    warehouse = index.get("Facility", "WH-PUNE")
    assert warehouse is not None
    assert counterparties(index, TODAY, warehouse) == {}


def test_attention_summary_counts_what_stands_out() -> None:
    summary = attention_summary(pump_workspace(), TODAY)
    assert summary["late_by_type"] == {"PurchaseOrder": ["PO-1", "PO-2"]}
    assert summary["stock_short_count"] == 1
    assert [item["entity_id"] for item in summary["flagged"]] == ["S-101"]


# ── Linking records ──────────────────────────────────────────────────────────


def test_references_follow_identifiers_in_any_case_and_unique_names() -> None:
    index = WorkspaceIndex(
        [
            rec("Supplier", "S-1", supplier_name="Glen Systems"),
            rec("Supplier", "S-2", supplier_name="Twin Traders"),
            rec("Supplier", "S-3", supplier_name="Twin Traders"),
            rec("PurchaseOrder", "PO-1", supplier_id="s-1"),
            rec("PurchaseOrder", "PO-2", supplier_name="Glen Systems"),
            rec("PurchaseOrder", "PO-3", vendor="Twin Traders"),
            rec("PurchaseOrder", "PO-4", notes="S-1"),
        ]
    )
    supplier = index.get("Supplier", "S-1")
    orders = {record.entity_id: record for record in index.by_type["PurchaseOrder"]}
    assert index.reference(orders["PO-1"], "Supplier") is supplier
    assert index.reference(orders["PO-2"], "Supplier") is supplier
    # A name shared by two suppliers identifies neither.
    assert index.reference(orders["PO-3"], "Supplier") is None
    # A value in a column that does not point at suppliers is not a link.
    assert index.reference(orders["PO-4"], "Supplier") is None
    assert supplier is not None
    assert points_at(index, orders["PO-1"], supplier) is True
    assert points_at(index, orders["PO-4"], supplier) is False


def test_names_in_a_question_are_linked_to_records() -> None:
    index = pump_workspace()

    def linked(question: str) -> list[tuple[str, str]]:
        return [
            (item["record"].entity_id, item["matched_on"]) for item in link_names(question, index)
        ]

    assert linked("tell me about bharat castings pvt ltd") == [("S-101", "name")]
    assert linked("is bharat castings late") == [("S-101", "start_of_name")]
    assert linked("what about bharat") == [("S-101", "first_word_of_name")]
    assert linked("where is the cast iron housing") == [("C-2000", "name")]
    # Common and short words do not identify a record.
    assert linked("where are the pumps going") == []
    assert linked("which orders are late") == []


def test_a_first_word_shared_by_two_names_links_neither() -> None:
    index = WorkspaceIndex(
        [
            rec("Supplier", "S-1", supplier_name="Nordic Seals AB"),
            rec("Supplier", "S-2", supplier_name="Nordic Forgings Oy"),
        ]
    )
    assert link_names("what about nordic", index) == []
    assert [item["record"].entity_id for item in link_names("what about nordic seals", index)] == [
        "S-1"
    ]


def test_field_values_spelled_out_in_a_question_become_filters() -> None:
    suppliers = [
        rec("Supplier", "S-1", supplier_name="Acme", tier="tier_1", status="active", country="DE"),
        rec(
            "Supplier", "S-2", supplier_name="Bharat", tier="tier_1", status="delayed", country="IN"
        ),
        rec(
            "Supplier", "S-3", supplier_name="Kyoto", tier="tier_2", status="at_risk", country="JP"
        ),
    ]
    filters = match_value_filters("which tier 1 are not active", suppliers)
    assert filters == [
        {"field": "status", "value": "active", "negated": True},
        {"field": "tier", "value": "tier_1", "negated": False},
    ]
    assert [record.entity_id for record in apply_value_filters(suppliers, filters)] == ["S-2"]

    # Two values of one field are alternatives; different fields must all hold.
    either = match_value_filters("delayed or at risk ones", suppliers)
    assert [record.entity_id for record in apply_value_filters(suppliers, either)] == ["S-2", "S-3"]
    # Two-letter values such as country codes are too short to match on as
    # ordinary words ("in" is not India) ...
    assert match_value_filters("the de ones", suppliers) == []
    assert match_value_filters("which are in the list", suppliers) == []
    # ... unless the question wrote that exact code in capitals.
    in_germany = match_value_filters("which are in de", suppliers, short_codes=("DE",))
    assert in_germany == [{"field": "country", "value": "DE", "negated": False}]
    assert [r.entity_id for r in apply_value_filters(suppliers, in_germany)] == ["S-1"]
    not_india = match_value_filters("which are not in", suppliers, short_codes=("IN",))
    assert not_india == [{"field": "country", "value": "IN", "negated": True}]
    assert [r.entity_id for r in apply_value_filters(suppliers, not_india)] == ["S-1", "S-3"]
    # A code the data does not hold filters nothing.
    assert match_value_filters("which are in fr", suppliers, short_codes=("FR",)) == []
    # Values already used as a matched name are not reused as a filter.
    assert match_value_filters("acme", suppliers, exclude=["Acme"]) == []


def test_diff_attributes_reports_only_fields_that_changed() -> None:
    before = {"status": "active", "on_time_rate": "0.91", "country": "IN"}
    after = {"status": "delayed", "on_time_rate": "0.91", "tier": "tier_1", "_facility_type": "x"}
    assert diff_attributes(before, after) == [
        {"field": "status", "before": "active", "after": "delayed"},
        {"field": "tier", "before": None, "after": "tier_1"},
    ]
    # A field the newer file does not mention keeps its value: not a change.
    assert diff_attributes(before, {}) == []
