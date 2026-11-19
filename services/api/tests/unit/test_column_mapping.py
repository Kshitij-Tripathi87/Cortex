"""Column mapping: fixed aliases, unknown columns kept, conflicts refused."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from app.ingestion.column_mapping import (
    ENTITY_SPECS,
    decode_normalized,
    map_headers,
    map_row,
)
from app.ingestion.contracts import MappedRow, ParsedRow, ParsedSheet, ReaderLimits
from app.ingestion.normalization import normalize_header, to_json
from app.ingestion.readers import read_csv
from app.models.enums import (
    Criticality,
    EquipmentCategory,
    IngestionEntityType,
    MilestoneType,
    PurchaseOrderStatus,
)
from tests.factories import csv_bytes

LIMITS = ReaderLimits(
    max_rows=100, max_columns=30, max_cell_chars=500, max_uncompressed_bytes=10**7
)


def sheet_of(headers: list[str], rows: list[list[Any]]) -> ParsedSheet:
    return read_csv(csv_bytes(headers, rows), LIMITS)


def mapped(entity_type: IngestionEntityType, headers: list[str], row: list[Any]) -> MappedRow:
    spec = ENTITY_SPECS[entity_type]
    sheet = sheet_of(headers, [row])
    return map_row(spec, map_headers(spec, sheet), sheet.rows[0])


def codes(row: MappedRow) -> list[tuple[str, str | None]]:
    return [(issue.code, issue.column) for issue in (*row.mapping_errors, *row.mapping_warnings)]


def test_every_entity_type_has_a_specification() -> None:
    assert set(ENTITY_SPECS) == set(IngestionEntityType)
    for spec in ENTITY_SPECS.values():
        names = [field.name for field in spec.fields]
        assert len(names) == len(set(names))
        assert set(spec.natural_key) <= set(names)
        for key in spec.natural_key:
            assert spec.field(key).required, f"{spec.entity_type}: key field {key} must be required"


def test_no_alias_is_claimed_by_two_fields_of_one_entity() -> None:
    for spec in ENTITY_SPECS.values():
        owner: dict[str, str] = {}
        for field in spec.fields:
            for alias in field.aliases:
                key = normalize_header(alias)
                assert owner.setdefault(key, field.name) == field.name, (spec.entity_type, alias)


@pytest.mark.parametrize(
    ("entity_type", "header", "field"),
    [
        (IngestionEntityType.PROJECT, "Project Code", "code"),
        (IngestionEntityType.PROJECT, "Project ID", "code"),
        (IngestionEntityType.PROJECT, "Project Ref", "code"),
        (IngestionEntityType.PROJECT, "Project Name", "name"),
        (IngestionEntityType.PROJECT, "Project", "name"),
        (IngestionEntityType.EQUIPMENT, "Project", "project_code"),
        (IngestionEntityType.EQUIPMENT, "Equipment Code", "equipment_code"),
        (IngestionEntityType.EQUIPMENT, "Asset Code", "equipment_code"),
        (IngestionEntityType.EQUIPMENT, "Tag No", "equipment_code"),
        (IngestionEntityType.EQUIPMENT, "Required On Site Date", "required_on_site_date"),
        (IngestionEntityType.EQUIPMENT, "Required On-Site Date", "required_on_site_date"),
        (IngestionEntityType.EQUIPMENT, "Site Required Date", "required_on_site_date"),
        (IngestionEntityType.SUPPLIER, "Vendor Code", "supplier_code"),
        (IngestionEntityType.SUPPLIER, "Supplier Code", "supplier_code"),
        (IngestionEntityType.SUPPLIER, "Vendor Name", "name"),
        (IngestionEntityType.SUPPLIER, "Supplier Name", "name"),
        (IngestionEntityType.PURCHASE_ORDER, "PO Number", "po_number"),
        (IngestionEntityType.PURCHASE_ORDER, "Purchase Order", "po_number"),
        (
            IngestionEntityType.SUPPLIER_COMMITMENT,
            "Committed Delivery Date",
            "committed_delivery_date",
        ),
        (
            IngestionEntityType.SUPPLIER_COMMITMENT,
            "Supplier Promise Date",
            "committed_delivery_date",
        ),
        (IngestionEntityType.MILESTONE, "Planned Date", "planned_date"),
        (IngestionEntityType.MILESTONE, "Baseline Date", "planned_date"),
        (IngestionEntityType.MILESTONE, "Actual Date", "actual_date"),
        (IngestionEntityType.MILESTONE, "Completion Date", "actual_date"),
    ],
)
def test_known_aliases(entity_type: IngestionEntityType, header: str, field: str) -> None:
    assert ENTITY_SPECS[entity_type].field_by_alias[normalize_header(header)].name == field


def test_case_and_spacing_of_headers_do_not_matter() -> None:
    row = mapped(
        IngestionEntityType.PURCHASE_ORDER,
        ["  po   NUMBER ", "project_code", "VENDOR-CODE", "currency", "Status"],
        ["PO-1", "DC-1", "SUP-1", "inr", "issued"],
    )

    assert row.normalized_data == {
        "po_number": "PO-1",
        "project_code": "DC-1",
        "supplier_code": "SUP-1",
        "currency": "INR",
        "status": PurchaseOrderStatus.ISSUED,
    }
    assert codes(row) == []


def test_unknown_columns_are_kept_in_the_raw_row_and_reported() -> None:
    row = mapped(
        IngestionEntityType.SUPPLIER,
        ["Supplier Code", "Supplier Name", "Supplier Notes", "Rating"],
        ["SUP-1", "Acme", "prefers email", ""],
    )

    assert row.unknown_columns == ("Supplier Notes", "Rating")
    assert row.raw_data["Supplier Notes"] == "prefers email"  # nothing was discarded
    assert "Supplier Notes" not in row.normalized_data
    # Only the unknown column that holds a value produces a warning for the row.
    assert codes(row) == [("UNKNOWN_SOURCE_COLUMN", "Supplier Notes")]
    assert row.mapping_errors == ()


def test_two_aliases_for_one_field_with_the_same_value_are_accepted() -> None:
    spec = ENTITY_SPECS[IngestionEntityType.MILESTONE]
    sheet = sheet_of(
        ["PO Number", "Milestone Type", "Sequence No", "Planned Date", "Baseline Date"],
        [["PO-1", "DISPATCH", "1", "2026-12-01", "2026-12-01"]],
    )
    header_mapping = map_headers(spec, sheet)

    row = map_row(spec, header_mapping, sheet.rows[0])

    assert header_mapping.columns_by_field["planned_date"] == ("Planned Date", "Baseline Date")
    assert [(issue.code, issue.column) for issue in header_mapping.warnings] == [
        ("MULTIPLE_COLUMNS_FOR_FIELD", "planned_date")
    ]
    assert row.normalized_data["planned_date"] == date(2026, 12, 1)
    assert row.mapping_errors == ()


def test_two_aliases_with_conflicting_values_make_the_row_ambiguous() -> None:
    row = mapped(
        IngestionEntityType.MILESTONE,
        ["PO Number", "Milestone Type", "Sequence No", "Planned Date", "Baseline Date"],
        ["PO-1", "DISPATCH", "1", "2026-12-01", "2026-12-15"],
    )

    assert [(issue.code, issue.column) for issue in row.mapping_errors] == [
        ("AMBIGUOUS_COLUMN_MAPPING", "planned_date")
    ]
    # Neither column wins: the field has no normalized value.
    assert "planned_date" not in row.normalized_data


def test_one_of_two_aliases_being_blank_is_not_a_conflict() -> None:
    row = mapped(
        IngestionEntityType.MILESTONE,
        ["PO Number", "Milestone Type", "Sequence No", "Planned Date", "Baseline Date"],
        ["PO-1", "DISPATCH", "1", "", "2026-12-15"],
    )

    assert row.normalized_data["planned_date"] == date(2026, 12, 15)
    assert row.mapping_errors == ()


@pytest.mark.parametrize(
    ("column", "value", "code", "field"),
    [
        ("Required On-Site Date", "03/04/26", "INVALID_DATE", "required_on_site_date"),
        ("Category", "Reactor", "INVALID_ENUM", "category"),
        ("Criticality", "URGENT", "INVALID_ENUM", "criticality"),
        ("Equipment Name", "x" * 201, "VALUE_TOO_LONG", "name"),
    ],
)
def test_invalid_values_become_row_errors_naming_the_field(
    column: str, value: str, code: str, field: str
) -> None:
    values = {
        "Equipment Code": "TR-001",
        "Project Code": "DC-1",
        "Equipment Name": "Transformer",
        "Category": "TRANSFORMER",
        "Required On-Site Date": "2027-01-15",
        "Criticality": "CRITICAL",
    }
    values[column] = value

    row = mapped(IngestionEntityType.EQUIPMENT, list(values), list(values.values()))

    assert [(issue.code, issue.column) for issue in row.mapping_errors] == [(code, field)]
    assert field not in row.normalized_data
    # The message says what to do and does not repeat the cell.
    assert value not in row.mapping_errors[0].message


def test_a_missing_optional_date_with_a_declared_warning() -> None:
    row = mapped(
        IngestionEntityType.EQUIPMENT,
        ["Equipment Code", "Project Code", "Equipment Name", "Category", "Criticality"],
        ["TR-001", "DC-1", "Transformer", "TRANSFORMER", "CRITICAL"],
    )

    assert codes(row) == [("REQUIRED_ON_SITE_DATE_NOT_RECORDED", "required_on_site_date")]
    assert row.mapping_errors == ()


def test_values_are_typed_after_mapping() -> None:
    row = mapped(
        IngestionEntityType.EQUIPMENT,
        [
            "Equipment Code",
            "Project Code",
            "Equipment Name",
            "Category",
            "Required On-Site Date",
            "Criticality",
            "Manufacturer",
        ],
        [" TR-001 ", "DC-1", "Transformer", "transformers", "2027-01-15", "critical", "Halcyon"],
    )

    assert row.normalized_data == {
        "equipment_code": "TR-001",
        "project_code": "DC-1",
        "name": "Transformer",
        "category": EquipmentCategory.TRANSFORMER,
        "required_on_site_date": date(2027, 1, 15),
        "criticality": Criticality.CRITICAL,
        "spec_manufacturer": "Halcyon",
    }
    # The source row is untouched, surrounding spaces included.
    assert row.raw_data["Equipment Code"] == " TR-001 "


def test_cells_beyond_the_header_make_the_row_invalid() -> None:
    spec = ENTITY_SPECS[IngestionEntityType.PROJECT]
    sheet = read_csv(b"Project Code,Project Name\nP1,One,surplus\n", LIMITS)

    row = map_row(spec, map_headers(spec, sheet), sheet.rows[0])

    assert [issue.code for issue in row.mapping_errors] == ["ROW_SHAPE_MISMATCH"]


def test_a_formula_without_a_stored_result_blocks_the_field_it_feeds() -> None:
    spec = ENTITY_SPECS[IngestionEntityType.PURCHASE_ORDER_ITEM]
    sheet = sheet_of(["PO Number", "Equipment Code", "Quantity"], [["PO-1", "TR-001", "1"]])
    parsed = sheet.rows[0]
    with_formula = ParsedRow(
        parsed.row_number, {**parsed.raw_data, "Quantity": None}, formula_cells=("Quantity",)
    )

    row = map_row(spec, map_headers(spec, sheet), with_formula)

    assert [(issue.code, issue.column) for issue in row.mapping_errors] == [
        ("FORMULA_WITHOUT_CACHED_VALUE", "quantity")
    ]
    assert "quantity" not in row.normalized_data


def test_normalized_values_survive_the_round_trip_through_the_ledger() -> None:
    """What preview stores is exactly what commit reads back."""
    spec = ENTITY_SPECS[IngestionEntityType.MILESTONE]
    values = {
        "po_number": "PO-1",
        "milestone_type": MilestoneType.FACTORY_ACCEPTANCE_TEST,
        "sequence_no": 2,
        "planned_date": date(2026, 11, 10),
        "actual_date": date(2026, 11, 14),
    }
    stored = {key: to_json(value) for key, value in values.items()}

    assert stored["planned_date"] == "2026-11-10"
    assert decode_normalized(spec, stored) == values

    item_spec = ENTITY_SPECS[IngestionEntityType.PURCHASE_ORDER_ITEM]
    item = {
        "po_number": "PO-1",
        "equipment_code": "TR-001",
        "quantity": Decimal("2.500"),
        "unit_price": Decimal("1234.56"),
    }
    decoded = decode_normalized(item_spec, {key: to_json(value) for key, value in item.items()})
    assert decoded == item
    assert str(decoded["quantity"]) == "2.500"
