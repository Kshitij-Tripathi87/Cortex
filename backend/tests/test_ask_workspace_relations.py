"""Facts the Ask box derives for questions it used to misread.

Pure functions over plain records: how a name is recognised, how records are
linked through orders, how a total is computed, and how a country asked for
by name finds the code a file stores.
"""

from __future__ import annotations

import csv
import io
from datetime import date

import pytest

from app.modules.graph.entity_keys import canonical_column_name
from app.modules.nexus_spine.p0_migration.question_focus import parse_question
from app.modules.nexus_spine.p0_migration.workspace_facts import (
    NodeRecord,
    WorkspaceIndex,
    _negated,
    aggregate_records,
    apply_value_filters,
    link_names,
    link_single_words,
    match_value_filters,
    numeric_fields,
    open_flows,
    related_records,
    resolve_numeric_field,
)
from tests.test_ask_grounded_answers import (
    INVENTORY,
    PRODUCTS,
    PURCHASE_ORDERS,
    SUPPLIERS,
    WAREHOUSES,
)

TODAY = date(2026, 11, 17)


def _records() -> list[NodeRecord]:
    records: list[NodeRecord] = []
    for kind, id_field, content in (
        ("Supplier", "supplier_id", SUPPLIERS),
        ("Product", "sku", PRODUCTS),
        ("Facility", "warehouse_id", WAREHOUSES),
        ("PurchaseOrder", "po_number", PURCHASE_ORDERS),
        ("InventoryItem", "inventory_id", INVENTORY),
    ):
        for row in csv.DictReader(io.StringIO(content.decode())):
            records.append(
                NodeRecord(
                    node_id=f"{kind}:{row[id_field]}",
                    entity_type=kind,
                    entity_id=row[id_field],
                    attributes={
                        canonical_column_name(key, kind): value for key, value in row.items()
                    },
                )
            )
    return records


@pytest.fixture(scope="module")
def index() -> WorkspaceIndex:
    return WorkspaceIndex(_records())


def _named(question: str, index: WorkspaceIndex) -> dict[str, str]:
    return {
        match["record"].entity_id: match["matched_on"]
        for match in link_names(parse_question(question).normalized, index)
    }


# ── Names ───────────────────────────────────────────────────────────────────


def test_a_plural_names_the_record(index: WorkspaceIndex) -> None:
    assert _named("Who supplies ball bearings?", index) == {"C-2004": "start_of_name"}
    assert _named("tell me about bharat casting", index) == {"S-101": "start_of_name"}
    assert _named("where are the cast iron housings", index) == {"C-2000": "name"}


def test_words_from_inside_a_name_identify_it(index: WorkspaceIndex) -> None:
    assert _named("who makes the iron housing", index) == {"C-2000": "part_of_name"}
    assert _named("do we have a seal kit", index) == {"C-2002": "part_of_name"}


def test_the_words_for_a_kind_of_record_do_not_name_one(index: WorkspaceIndex) -> None:
    # "Hamburg Distribution Centre" must not be named by "distribution centre".
    assert _named("which distribution centre is short?", index) == {}
    assert _named("which plant store is that", index) == {}
    # With the word that identifies it, it is.
    assert _named("the Hamburg distribution centre", index) == {"WH-HAM": "name"}
    assert _named("what is at pune", index) == {"WH-PUNE": "first_word_of_name"}


def test_one_word_of_a_name_is_a_last_resort(index: WorkspaceIndex) -> None:
    def found(words: list[str], avoid: tuple[str, ...] = ()) -> list[str]:
        return [
            match["record"].entity_id
            for match in link_single_words(words, index, avoid_types=avoid)
        ]

    # "Who supplies bearings?" asks about the bearings, not the supplier
    # called "Kyoto Bearings".
    assert found(["bearings"], ("Supplier",)) == ["C-2004"]
    assert found(["bearings"]) == ["C-2004", "S-105"]
    assert found(["housings"]) == ["C-2000"]
    # Record kinds, company forms and short or everyday words name nothing.
    assert found(["centre", "gmbh", "plant", "kit", "the", "which"]) == []
    # A word carried by too many names identifies none of them.
    crowded = WorkspaceIndex(
        [
            NodeRecord(f"n{n}", "Product", f"P-{n}", {"product_name": f"Bracket type {n}"})
            for n in range(4)
        ]
    )
    assert link_single_words(["bracket"], crowded) == []


# ── Links ───────────────────────────────────────────────────────────────────


def test_a_supplier_is_linked_to_a_product_through_the_orders_that_name_both(
    index: WorkspaceIndex,
) -> None:
    bearing = index.get("Product", "C-2004")
    assert bearing is not None
    link = related_records(index, TODAY, "Supplier", [bearing])
    assert link["via"] == "orders"
    assert [record.entity_id for record in link["records"]] == ["S-105"]
    assert link["orders"] == {"S-105": {"order_count": 1, "late_order_count": 1}}

    housing = index.get("Product", "C-2000")
    assert housing is not None
    link = related_records(index, TODAY, "Supplier", [housing])
    # Most orders first.
    assert [record.entity_id for record in link["records"]] == ["S-101", "S-100"]
    assert link["orders"]["S-101"] == {"order_count": 2, "late_order_count": 2}
    assert link["orders"]["S-100"] == {"order_count": 1, "late_order_count": 0}


def test_the_link_works_from_the_supplier_side_too(index: WorkspaceIndex) -> None:
    supplier = index.get("Supplier", "S-101")
    assert supplier is not None
    link = related_records(index, TODAY, "Product", [supplier])
    assert link["via"] == "orders"
    assert [record.entity_id for record in link["records"]] == ["C-2000"]


def test_a_field_that_names_the_record_is_used_before_orders(index: WorkspaceIndex) -> None:
    supplier = index.get("Supplier", "S-101")
    order = index.get("PurchaseOrder", "PO-5001")
    assert supplier is not None and order is not None
    # The order has a supplier field.
    link = related_records(index, TODAY, "PurchaseOrder", [supplier])
    assert link["via"] == "refers_to"
    assert [record.entity_id for record in link["records"]] == ["PO-5001", "PO-5002"]
    # The other way round: the order names its warehouse.
    link = related_records(index, TODAY, "Facility", [order])
    assert link["via"] == "referred_by"
    assert [record.entity_id for record in link["records"]] == ["WH-PUNE"]


def test_no_link_is_reported_as_none(index: WorkspaceIndex) -> None:
    pump = index.get("Product", "P-1000")
    assert pump is not None
    # No order is for the pump.
    assert related_records(index, TODAY, "Supplier", [pump])["records"] == []


def test_open_orders_leave_out_delivered_and_closed_ones() -> None:
    records = [
        NodeRecord("a", "PurchaseOrder", "PO-1", {"status": "confirmed"}),
        NodeRecord("b", "PurchaseOrder", "PO-2", {"status": "delivered"}),
        NodeRecord(
            "c", "PurchaseOrder", "PO-3", {"status": "in_transit", "received_date": "2026-11-01"}
        ),
        NodeRecord("d", "Supplier", "S-1", {"supplier_name": "Acme"}),
    ]
    kept = open_flows(WorkspaceIndex(records), TODAY, records)
    # A record that is not an order or shipment is not judged.
    assert [record.entity_id for record in kept] == ["PO-1", "S-1"]


# ── Figures ─────────────────────────────────────────────────────────────────


def test_numeric_fields_leave_out_identifiers_and_dates(index: WorkspaceIndex) -> None:
    assert numeric_fields(index.by_type["PurchaseOrder"]) == ["quantity"]
    assert numeric_fields(index.by_type["Supplier"]) == ["lead_time_days", "on_time_rate"]
    assert numeric_fields(index.by_type["InventoryItem"]) == ["quantity_on_hand", "safety_stock"]
    assert numeric_fields(index.by_type["Facility"]) == []


def test_a_field_is_named_by_the_words_of_its_name(index: WorkspaceIndex) -> None:
    suppliers = index.by_type["Supplier"]
    orders = index.by_type["PurchaseOrder"]
    stock = index.by_type["InventoryItem"]
    products = index.by_type["Product"]
    assert (
        resolve_numeric_field(["what", "is", "the", "lead", "time", "of", "my"], suppliers)
        == "lead_time_days"
    )
    assert resolve_numeric_field(["on", "time", "rate"], suppliers) == "on_time_rate"
    assert resolve_numeric_field(["safety", "stocks"], stock) == "safety_stock"
    assert resolve_numeric_field(["price"], products) == "unit_price"
    # "Most expensive" asks about the price.
    assert resolve_numeric_field(["most", "expensive"], products) == "unit_price"
    # No field word at all: the usual quantity of the kind of record.
    assert resolve_numeric_field([], orders) == "quantity"
    assert resolve_numeric_field([], stock) == "quantity_on_hand"
    # Suppliers have no usual quantity.
    assert resolve_numeric_field([], suppliers) is None
    # Something else was asked for by name: the quantity is not offered instead.
    assert resolve_numeric_field(["value"], orders, allow_usual=False) is None


def test_small_words_do_not_name_a_field(index: WorkspaceIndex) -> None:
    suppliers = index.by_type["Supplier"]
    # "on" and "time" are in half of all questions; "rate" names the field.
    assert resolve_numeric_field(["quantity", "on", "from"], suppliers) is None
    assert resolve_numeric_field(["on", "time"], suppliers) is None
    assert resolve_numeric_field(["rate"], suppliers) == "on_time_rate"
    # Between two fields that share a meaningful word, the small words decide.
    records = [
        NodeRecord("a", "Supplier", "S-1", {"on_time_rate": "0.9", "defect_rate": "0.01"}),
        NodeRecord("b", "Supplier", "S-2", {"on_time_rate": "0.8", "defect_rate": "0.02"}),
    ]
    assert resolve_numeric_field(["rate"], records) is None
    assert resolve_numeric_field(["on", "time", "rate"], records) == "on_time_rate"
    assert resolve_numeric_field(["defect", "rate"], records) == "defect_rate"


def test_a_word_shared_by_two_fields_names_neither() -> None:
    products = [
        NodeRecord("a", "Product", "P-1", {"unit_price": "10", "list_price": "12"}),
        NodeRecord("b", "Product", "P-2", {"unit_price": "20", "list_price": "25"}),
    ]
    assert resolve_numeric_field(["price"], products) is None
    assert resolve_numeric_field(["list", "price"], products) == "list_price"


def test_a_total_is_broken_down_by_product(index: WorkspaceIndex) -> None:
    result = aggregate_records(index, index.by_type["PurchaseOrder"], "quantity", "sum")
    assert result["value"] == 7380
    assert (result["considered"], result["with_value"], result["without_value"]) == (7, 7, 0)
    assert result["lowest"]["value"] == 80
    assert [item["entity_id"] for item in result["lowest"]["records"]] == ["PO-5005"]
    assert result["highest"]["value"] == 5000
    rows = {row["entity_id"]: row["value"] for row in result["breakdown"]["rows"]}
    assert rows == {"C-2004": 5000, "C-2002": 1200, "C-2000": 800, "C-2001": 300, "C-2003": 80}
    # Largest first.
    assert [row["entity_id"] for row in result["breakdown"]["rows"]][:2] == ["C-2004", "C-2002"]


def test_average_highest_and_lowest(index: WorkspaceIndex) -> None:
    suppliers = index.by_type["Supplier"]
    assert aggregate_records(index, suppliers, "lead_time_days", "average")["value"] == 25
    highest = aggregate_records(index, suppliers, "lead_time_days", "max")
    assert highest["value"] == 42
    assert [item["entity_id"] for item in highest["highest"]["records"]] == ["S-102"]
    lowest = aggregate_records(index, suppliers, "lead_time_days", "min")
    assert lowest["value"] == 10
    assert [item["entity_id"] for item in lowest["lowest"]["records"]] == ["S-104"]
    # Suppliers are not broken down by product.
    assert highest["breakdown"] is None


def test_values_that_cannot_be_read_are_counted_not_guessed() -> None:
    orders = [
        NodeRecord("a", "PurchaseOrder", "PO-1", {"quantity": "100"}),
        NodeRecord("b", "PurchaseOrder", "PO-2", {"quantity": "about fifty"}),
        NodeRecord("c", "PurchaseOrder", "PO-3", {"status": "confirmed"}),
        NodeRecord("d", "PurchaseOrder", "PO-4", {"quantity": "1,250"}),
    ]
    result = aggregate_records(WorkspaceIndex(orders), orders, "quantity", "sum")
    assert result["value"] == 1350
    assert (result["with_value"], result["without_value"]) == (2, 2)
    nothing = aggregate_records(WorkspaceIndex(orders), orders, "weight", "sum")
    assert nothing["value"] is None and nothing["with_value"] == 0


# ── Countries and negation ──────────────────────────────────────────────────


def _filters(question: str, records: list[NodeRecord]) -> list[dict]:
    focus = parse_question(question)
    return match_value_filters(
        focus.residual, records, short_codes=focus.short_codes, question=question
    )


def test_a_country_asked_for_by_name_selects_the_stored_code(index: WorkspaceIndex) -> None:
    suppliers = index.by_type["Supplier"]
    for question, words in (
        ("Which suppliers are in Germany?", "germany"),
        ("German suppliers", "german"),
        ("suppliers in DEU", "DEU"),
    ):
        assert _filters(question, suppliers) == [
            {
                "field": "country",
                "value": "DE",
                "negated": False,
                "asked_as": words,
                "means": "Germany",
            }
        ], question
    selected = apply_value_filters(
        suppliers, _filters("which suppliers are in india or japan", suppliers)
    )
    assert [record.entity_id for record in selected] == ["S-101", "S-105"]


def test_a_stored_name_is_found_by_its_code() -> None:
    suppliers = [
        NodeRecord("a", "Supplier", "S-1", {"supplier_name": "Acme", "country": "Germany"}),
        NodeRecord("b", "Supplier", "S-2", {"supplier_name": "Bolt", "country": "United States"}),
    ]
    assert [item["value"] for item in _filters("suppliers in DE", suppliers)] == ["Germany"]
    assert [item["value"] for item in _filters("American suppliers", suppliers)] == [
        "United States"
    ]
    assert [item["value"] for item in _filters("suppliers in the USA", suppliers)] == [
        "United States"
    ]


def test_a_country_is_only_looked_for_in_a_country_column() -> None:
    records = [
        NodeRecord("a", "Supplier", "S-1", {"supplier_name": "Acme", "status": "IN", "tier": "DE"})
    ]
    assert _filters("suppliers in India or Germany", records) == []


def test_a_country_inside_a_matched_name_is_not_a_filter() -> None:
    products = [
        NodeRecord("a", "Product", "P-1", {"product_name": "Valve", "origin_country": "CN"})
    ]
    focus = parse_question("products from China Steel Corp")
    found = match_value_filters(
        focus.residual,
        products,
        exclude=["china steel corp"],
        short_codes=focus.short_codes,
        question="products from China Steel Corp",
    )
    assert found == []


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Which suppliers are not in DE?", ["S-101", "S-102", "S-103", "S-104", "S-105"]),
        ("suppliers outside Germany", ["S-101", "S-102", "S-103", "S-104", "S-105"]),
        ("suppliers not from the US", ["S-100", "S-101", "S-102", "S-103", "S-105"]),
        ("suppliers in DE", ["S-100"]),
        ("which suppliers are not active", ["S-101", "S-105"]),
    ],
)
def test_a_negation_excludes_the_value(
    question: str, expected: list[str], index: WorkspaceIndex
) -> None:
    suppliers = index.by_type["Supplier"]
    selected = apply_value_filters(suppliers, _filters(question, suppliers))
    assert [record.entity_id for record in selected] == expected


@pytest.mark.parametrize(
    ("before", "negated"),
    [
        ("which suppliers are not", True),
        ("which suppliers are not in", True),
        ("suppliers not from the", True),
        ("suppliers outside of", True),
        ("everything except", True),
        ("which suppliers are in", False),
        # The negation belongs to another word.
        ("suppliers that are not active in", False),
        ("", False),
    ],
)
def test_what_counts_as_a_negation(before: str, negated: bool) -> None:
    assert _negated(before) is negated


# ── Wording ─────────────────────────────────────────────────────────────────


def test_a_single_order_that_is_on_time_is_said_to_be_on_time() -> None:
    """ "The 1 purchase order" used to be followed by "is late or flagged"."""
    from app.modules.nexus_spine.p0_migration.answer_rendering import attention_sentences
    from app.modules.nexus_spine.p0_migration.workspace_facts import attention_summary

    on_time = {"status": "confirmed", "promised_date": "2099-01-01"}
    one = WorkspaceIndex([NodeRecord("a", "PurchaseOrder", "PO-1", on_time)])
    assert attention_sentences(attention_summary(one, TODAY))[0] == (
        "The 1 purchase order is not late or flagged."
    )
    two = WorkspaceIndex(
        [
            NodeRecord("a", "PurchaseOrder", "PO-1", on_time),
            NodeRecord("b", "PurchaseOrder", "PO-2", on_time),
        ]
    )
    assert attention_sentences(attention_summary(two, TODAY))[0] == (
        "None of the 2 purchase orders is late or flagged."
    )
    mixed = WorkspaceIndex(
        [
            NodeRecord("a", "PurchaseOrder", "PO-1", on_time),
            NodeRecord("b", "Shipment", "SH-1", on_time),
        ]
    )
    assert attention_sentences(attention_summary(mixed, TODAY))[0] == (
        "None of the 2 orders and shipments is late or flagged."
    )
