"""Row validation against a reference snapshot. No database is involved."""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.ingestion.column_mapping import ENTITY_SPECS, map_headers, map_row
from app.ingestion.contracts import (
    CandidateRow,
    ReaderLimits,
    RecordRef,
    ReferenceSnapshot,
    RowAssessment,
)
from app.ingestion.readers import read_csv
from app.ingestion.row_validation import assess_rows, candidate
from app.models.enums import (
    IngestionEntityType,
    MilestoneStatus,
    PlannedAction,
    ProjectStatus,
    PurchaseOrderStatus,
    SupplierStatus,
)
from tests.factories import csv_bytes

LIMITS = ReaderLimits(
    max_rows=100, max_columns=30, max_cell_chars=500, max_uncompressed_bytes=10**7
)

PROJECT_A = uuid4()
PROJECT_B = uuid4()
SUPPLIER = uuid4()
INACTIVE_SUPPLIER = uuid4()
EQUIPMENT_A = uuid4()
EQUIPMENT_B = uuid4()
ORDER_A = uuid4()

SNAPSHOT = ReferenceSnapshot(
    projects={
        "DC-A": RecordRef(
            PROJECT_A,
            {
                "name": "Alpha",
                "location": "Pune",
                "status": ProjectStatus.ACTIVE,
                "target_completion_date": date(2027, 9, 30),
            },
        ),
        "DC-B": RecordRef(
            PROJECT_B,
            {
                "name": "Beta",
                "location": None,
                "status": ProjectStatus.PLANNING,
                "target_completion_date": None,
            },
        ),
    },
    suppliers={
        "SUP-1": RecordRef(
            SUPPLIER,
            {"name": "Acme", "country": None, "city": None, "status": SupplierStatus.ACTIVE},
        ),
        "SUP-OLD": RecordRef(
            INACTIVE_SUPPLIER,
            {"name": "Old", "country": None, "city": None, "status": SupplierStatus.INACTIVE},
        ),
    },
    equipment={
        "EQ-A": RecordRef(EQUIPMENT_A, {"project_id": PROJECT_A}),
        "EQ-B": RecordRef(EQUIPMENT_B, {"project_id": PROJECT_B}),
    },
    purchase_orders={
        "PO-A": RecordRef(
            ORDER_A,
            {
                "project_id": PROJECT_A,
                "supplier_id": SUPPLIER,
                "issue_date": None,
                "currency": "INR",
                "total_value": None,
                "status": PurchaseOrderStatus.ISSUED,
            },
        )
    },
)


def assess(
    entity_type: IngestionEntityType,
    headers: list[str],
    rows: list[list[Any]],
    snapshot: ReferenceSnapshot = SNAPSHOT,
) -> list[RowAssessment]:
    """Run a small CSV through reading, mapping, field checks and the batch assessment."""
    spec = ENTITY_SPECS[entity_type]
    sheet = read_csv(csv_bytes(headers, rows), LIMITS)
    header_mapping = map_headers(spec, sheet)
    candidates = [candidate(spec, map_row(spec, header_mapping, row)) for row in sheet.rows]
    return assess_rows(entity_type, candidates, snapshot)


def errors(assessment: RowAssessment) -> list[tuple[str, str | None]]:
    return [(issue.code, issue.column) for issue in assessment.errors]


def warnings(assessment: RowAssessment) -> list[tuple[str, str | None]]:
    return [(issue.code, issue.column) for issue in assessment.warnings]


PO_HEADERS = ["PO Number", "Project Code", "Supplier Code", "Currency", "Status"]
ITEM_HEADERS = ["PO Number", "Equipment Code", "Quantity", "Unit Price"]
EQUIPMENT_HEADERS = [
    "Equipment Code",
    "Project Code",
    "Equipment Name",
    "Category",
    "Required On-Site Date",
    "Criticality",
]


# --- required fields and ranges -------------------------------------------------------


def test_missing_required_value() -> None:
    (row,) = assess(IngestionEntityType.PROJECT, ["Project Code", "Project Name"], [["P1", ""]])

    assert errors(row) == [("REQUIRED_FIELD_MISSING", "name")]
    assert row.planned_action is None
    assert row.resolved == {}


def test_missing_required_column_fails_every_row() -> None:
    rows = assess(IngestionEntityType.PROJECT, ["Project Name"], [["One"], ["Two"]])

    assert [errors(row) for row in rows] == [[("REQUIRED_FIELD_MISSING", "code")]] * 2


@pytest.mark.parametrize("quantity", ["0", "-1", "-0.5"])
def test_zero_or_negative_quantity(quantity: str) -> None:
    (row,) = assess(
        IngestionEntityType.PURCHASE_ORDER_ITEM, ITEM_HEADERS, [["PO-A", "EQ-A", quantity, ""]]
    )

    assert errors(row) == [("MUST_BE_POSITIVE", "quantity")]


def test_negative_unit_price() -> None:
    (row,) = assess(
        IngestionEntityType.PURCHASE_ORDER_ITEM, ITEM_HEADERS, [["PO-A", "EQ-A", "1", "-10"]]
    )

    assert errors(row) == [("MUST_BE_NON_NEGATIVE", "unit_price")]


def test_sequence_number_must_be_positive() -> None:
    (row,) = assess(
        IngestionEntityType.MILESTONE,
        ["PO Number", "Milestone Type", "Sequence No", "Planned Date"],
        [["PO-A", "DISPATCH", "0", "2026-12-01"]],
    )

    assert errors(row) == [("MUST_BE_POSITIVE", "sequence_no")]


@pytest.mark.parametrize("currency", ["RS", "RUPEES", "12A", "₹"])
def test_invalid_currency(currency: str) -> None:
    (row,) = assess(
        IngestionEntityType.PURCHASE_ORDER,
        PO_HEADERS,
        [["PO-9", "DC-A", "SUP-1", currency, "ISSUED"]],
    )

    assert errors(row) == [("INVALID_CURRENCY", "currency")]


def test_a_field_that_failed_to_parse_is_not_also_reported_as_missing() -> None:
    (row,) = assess(
        IngestionEntityType.MILESTONE,
        ["PO Number", "Milestone Type", "Sequence No", "Planned Date"],
        [["PO-A", "DISPATCH", "1", "03/04/26"]],
    )

    assert errors(row) == [("INVALID_DATE", "planned_date")]


# --- references -----------------------------------------------------------------------


def test_missing_referenced_project() -> None:
    (row,) = assess(
        IngestionEntityType.EQUIPMENT,
        EQUIPMENT_HEADERS,
        [["EQ-9", "DC-NOPE", "X", "UPS", "2027-01-01", "HIGH"]],
    )

    assert errors(row) == [("REFERENCE_NOT_FOUND", "project_code")]


def test_missing_supplier_and_project_are_both_reported() -> None:
    (row,) = assess(
        IngestionEntityType.PURCHASE_ORDER,
        PO_HEADERS,
        [["PO-9", "DC-NOPE", "SUP-NOPE", "INR", "ISSUED"]],
    )

    assert errors(row) == [
        ("REFERENCE_NOT_FOUND", "project_code"),
        ("REFERENCE_NOT_FOUND", "supplier_code"),
    ]


def test_a_record_of_another_workspace_is_simply_not_found() -> None:
    """The snapshot is workspace-scoped, so a foreign record is absent from it.

    The answer must be the same as for a record that exists nowhere: a
    distinct code would reveal that it exists in another workspace.
    """
    only_own_workspace = ReferenceSnapshot(projects={"DC-A": SNAPSHOT.projects["DC-A"]})

    foreign, missing = assess(
        IngestionEntityType.EQUIPMENT,
        EQUIPMENT_HEADERS,
        [
            ["EQ-1", "DC-B", "X", "UPS", "2027-01-01", "HIGH"],
            ["EQ-2", "DC-ZZZ", "Y", "UPS", "2027-01-01", "HIGH"],
        ],
        only_own_workspace,
    )

    assert errors(foreign) == errors(missing) == [("REFERENCE_NOT_FOUND", "project_code")]
    assert foreign.errors[0].message == missing.errors[0].message
    assert all("CROSS_WORKSPACE" not in issue.code for issue in (*foreign.issues, *missing.issues))


def test_line_item_with_equipment_from_another_project() -> None:
    (row,) = assess(
        IngestionEntityType.PURCHASE_ORDER_ITEM, ITEM_HEADERS, [["PO-A", "EQ-B", "1", ""]]
    )

    assert errors(row) == [("CROSS_PROJECT_REFERENCE", "equipment_code")]


def test_line_item_references() -> None:
    unknown_order, unknown_equipment, valid = assess(
        IngestionEntityType.PURCHASE_ORDER_ITEM,
        ITEM_HEADERS,
        [
            ["PO-ZZ", "EQ-A", "1", ""],
            ["PO-A", "EQ-ZZ", "1", ""],
            ["PO-A", "EQ-A", "2.5", "1234.56"],
        ],
    )

    assert errors(unknown_order) == [("REFERENCE_NOT_FOUND", "po_number")]
    assert errors(unknown_equipment) == [("REFERENCE_NOT_FOUND", "equipment_code")]
    assert errors(valid) == []
    assert valid.planned_action is PlannedAction.CREATE
    assert valid.resolved["quantity"] == Decimal("2.5")
    assert valid.resolved["unit_price"] == Decimal("1234.56")


def test_a_new_purchase_order_cannot_name_an_inactive_supplier() -> None:
    (row,) = assess(
        IngestionEntityType.PURCHASE_ORDER,
        PO_HEADERS,
        [["PO-9", "DC-A", "SUP-OLD", "INR", "ISSUED"]],
    )

    assert errors(row) == [("REFERENCE_INACTIVE", "supplier_code")]


def test_an_existing_purchase_order_of_a_now_inactive_supplier_stays_valid() -> None:
    snapshot = ReferenceSnapshot(
        projects=SNAPSHOT.projects,
        suppliers=SNAPSHOT.suppliers,
        purchase_orders={
            "PO-OLD": RecordRef(
                uuid4(),
                {**SNAPSHOT.purchase_orders["PO-A"].values, "supplier_id": INACTIVE_SUPPLIER},
            )
        },
    )

    (row,) = assess(
        IngestionEntityType.PURCHASE_ORDER,
        PO_HEADERS,
        [["PO-OLD", "DC-A", "SUP-OLD", "INR", "DELIVERED"]],
        snapshot,
    )

    assert errors(row) == []
    assert row.planned_action is PlannedAction.UPDATE


# --- natural keys ---------------------------------------------------------------------


def test_duplicate_natural_key_within_a_file_with_different_values() -> None:
    first, second, other = assess(
        IngestionEntityType.PROJECT,
        ["Project Code", "Project Name"],
        [["P1", "One"], ["P1", "Uno"], ["P2", "Two"]],
    )

    # Both colliding rows are rejected; the order of the rows decides nothing.
    assert errors(first) == errors(second) == [("DUPLICATE_NATURAL_KEY", "code")]
    assert "2, 3" in first.errors[0].message
    assert errors(other) == []
    assert (first.planned_action, second.planned_action) == (None, None)


def test_the_same_collision_in_reverse_order_gives_the_same_verdict() -> None:
    forward = assess(
        IngestionEntityType.PROJECT,
        ["Project Code", "Project Name"],
        [["P1", "One"], ["P1", "Uno"]],
    )
    backward = assess(
        IngestionEntityType.PROJECT,
        ["Project Code", "Project Name"],
        [["P1", "Uno"], ["P1", "One"]],
    )

    assert [errors(row) for row in forward] == [errors(row) for row in backward]


def test_identical_rows_are_harmless_repeats() -> None:
    first, repeat = assess(
        IngestionEntityType.PROJECT,
        ["Project Code", "Project Name"],
        [["P1", "One"], ["P1", "One"]],
    )

    assert errors(first) == errors(repeat) == []
    assert first.planned_action is PlannedAction.CREATE
    assert first.duplicate_of is None
    assert repeat.duplicate_of == first.row_number
    assert repeat.planned_action is PlannedAction.NO_CHANGE
    assert warnings(repeat) == [("DUPLICATE_ROW", None)]


def test_a_collision_with_an_otherwise_invalid_row_rejects_both() -> None:
    valid, broken = assess(
        IngestionEntityType.PROJECT,
        ["Project Code", "Project Name", "Status"],
        [["P1", "One", "ACTIVE"], ["P1", "One", "NOT-A-STATUS"]],
    )

    assert ("DUPLICATE_NATURAL_KEY", "code") in errors(valid)
    assert ("INVALID_ENUM", "status") in errors(broken)
    assert ("DUPLICATE_NATURAL_KEY", "code") in errors(broken)


def test_composite_natural_key_of_milestones() -> None:
    rows = assess(
        IngestionEntityType.MILESTONE,
        ["PO Number", "Milestone Type", "Sequence No", "Planned Date"],
        [
            ["PO-A", "DISPATCH", "1", "2026-12-01"],
            ["PO-A", "DISPATCH", "2", "2026-12-05"],  # same type, other sequence: fine
            ["PO-A", "DELIVERY", "1", "2026-12-09"],
            ["PO-A", "DISPATCH", "1", "2026-12-20"],  # collides with the first row
        ],
    )

    assert [bool(errors(row)) for row in rows] == [True, False, False, True]
    assert errors(rows[0]) == [("DUPLICATE_NATURAL_KEY", "sequence_no")]


def test_two_commitments_for_one_purchase_order_in_one_file_are_a_conflict() -> None:
    """Which of two dates is the later statement cannot be read from row order."""
    first, second = assess(
        IngestionEntityType.SUPPLIER_COMMITMENT,
        ["PO Number", "Committed Delivery Date"],
        [["PO-A", "2026-11-28"], ["PO-A", "2026-12-06"]],
    )

    assert errors(first) == errors(second) == [("DUPLICATE_NATURAL_KEY", "po_number")]


# --- existing records: update policy --------------------------------------------------


def test_duplicate_natural_key_against_the_database_resolves_the_existing_record() -> None:
    """A key that exists is not an error and not a second record: it is an update or nothing."""
    unchanged, changed, new = assess(
        IngestionEntityType.PROJECT,
        ["Project Code", "Project Name", "Location", "Status", "Target Completion Date"],
        [
            ["DC-A", "Alpha", "Pune", "ACTIVE", "2027-09-30"],
            ["DC-B", "Beta", "", "ON_HOLD", ""],
            ["DC-C", "Gamma", "", "", ""],
        ],
    )

    assert [errors(row) for row in (unchanged, changed, new)] == [[], [], []]
    assert unchanged.planned_action is PlannedAction.NO_CHANGE
    assert changed.planned_action is PlannedAction.UPDATE
    assert new.planned_action is PlannedAction.CREATE


def test_a_blank_cell_is_not_a_change() -> None:
    """Blank means "not supplied": it never clears a stored value."""
    (row,) = assess(
        IngestionEntityType.PROJECT,
        ["Project Code", "Project Name", "Location", "Status"],
        [["DC-A", "Alpha", "", ""]],
    )

    assert row.planned_action is PlannedAction.NO_CHANGE
    assert "location" not in row.resolved
    assert "status" not in row.resolved


def test_an_import_does_not_move_equipment_to_another_project() -> None:
    (row,) = assess(
        IngestionEntityType.EQUIPMENT,
        EQUIPMENT_HEADERS,
        [["EQ-A", "DC-B", "X", "UPS", "2027-01-01", "HIGH"]],
    )

    assert errors(row) == [("IMMUTABLE_FIELD_CONFLICT", "project_code")]


def test_an_import_does_not_move_a_purchase_order_to_another_project_or_supplier() -> None:
    (row,) = assess(
        IngestionEntityType.PURCHASE_ORDER,
        PO_HEADERS,
        [["PO-A", "DC-B", "SUP-OLD", "INR", "ISSUED"]],
    )

    assert errors(row) == [
        ("IMMUTABLE_FIELD_CONFLICT", "project_code"),
        ("IMMUTABLE_FIELD_CONFLICT", "supplier_code"),
    ]


def test_references_are_resolved_to_ids_for_the_commit() -> None:
    (row,) = assess(
        IngestionEntityType.PURCHASE_ORDER, PO_HEADERS, [["PO-9", "DC-A", "SUP-1", "inr", "issued"]]
    )

    assert errors(row) == []
    assert row.planned_action is PlannedAction.CREATE
    assert (row.resolved["project_id"], row.resolved["supplier_id"]) == (PROJECT_A, SUPPLIER)
    assert row.resolved["currency"] == "INR"
    assert "project_code" not in row.resolved


def test_equipment_specification_columns_are_gathered() -> None:
    (row,) = assess(
        IngestionEntityType.EQUIPMENT,
        [*EQUIPMENT_HEADERS, "Manufacturer", "Model", "Notes", "Specification"],
        [["EQ-9", "DC-A", "X", "UPS", "2027-01-01", "HIGH", "Halcyon", "U-500", "", "500 kVA"]],
    )

    assert row.resolved["specification"] == {
        "description": "500 kVA",
        "manufacturer": "Halcyon",
        "model": "U-500",
    }
    assert row.resolved["project_id"] == PROJECT_A


def test_valid_row_with_an_unknown_optional_source_field() -> None:
    (row,) = assess(
        IngestionEntityType.SUPPLIER,
        ["Supplier Code", "Supplier Name", "Payment Terms"],
        [["SUP-9", "Newco", "net 45"]],
    )

    assert errors(row) == []
    assert warnings(row) == [("UNKNOWN_SOURCE_COLUMN", "Payment Terms")]
    assert row.planned_action is PlannedAction.CREATE
    assert "Payment Terms" not in row.resolved


# --- milestones and commitments -------------------------------------------------------

MILESTONE_HEADERS = [
    "PO Number",
    "Milestone Type",
    "Sequence No",
    "Planned Date",
    "Actual Date",
    "Status",
]


def milestone_snapshot(**current: Any) -> ReferenceSnapshot:
    values = {
        "status": MilestoneStatus.PENDING,
        "actual_date": None,
        "planned_date": date(2026, 11, 10),
    }
    values.update(current)
    return ReferenceSnapshot(
        purchase_orders=SNAPSHOT.purchase_orders,
        milestones={("PO-A", "FACTORY_ACCEPTANCE_TEST", 1): RecordRef(uuid4(), values)},
    )


def test_an_actual_date_implies_completion_when_no_status_is_given() -> None:
    (row,) = assess(
        IngestionEntityType.MILESTONE,
        MILESTONE_HEADERS,
        [["PO-A", "DISPATCH", "1", "2026-12-01", "2026-12-03", ""]],
    )

    assert errors(row) == []
    assert row.planned_action is PlannedAction.CREATE


@pytest.mark.parametrize("status", ["PENDING", "CANCELLED"])
def test_an_actual_date_on_a_milestone_that_is_not_completed_is_inconsistent(status: str) -> None:
    (row,) = assess(
        IngestionEntityType.MILESTONE,
        MILESTONE_HEADERS,
        [["PO-A", "DISPATCH", "1", "2026-12-01", "2026-12-03", status]],
    )

    assert errors(row) == [("INCONSISTENT_MILESTONE_STATE", "actual_date")]


def test_completed_without_a_date_is_accepted_and_no_date_is_invented() -> None:
    (row,) = assess(
        IngestionEntityType.MILESTONE,
        MILESTONE_HEADERS,
        [["PO-A", "DISPATCH", "1", "2026-12-01", "", "COMPLETED"]],
    )

    assert errors(row) == []
    assert "actual_date" not in row.resolved


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        (
            ["PO-A", "FAT", "1", "2026-11-10", "", ""],
            PlannedAction.NO_CHANGE,
        ),  # same plan, nothing new
        (
            ["PO-A", "FAT", "1", "2026-11-17", "", ""],
            PlannedAction.UPDATE,
        ),  # re-plan -> new version
        (
            ["PO-A", "FAT", "1", "2026-11-10", "2026-11-14", ""],
            PlannedAction.UPDATE,
        ),  # actual recorded
        (["PO-A", "FAT", "1", "2026-11-10", "", "CANCELLED"], PlannedAction.UPDATE),
        (["PO-A", "FAT", "2", "2026-11-10", "", ""], PlannedAction.CREATE),  # another occurrence
    ],
)
def test_planned_action_for_an_existing_milestone(row: list[str], expected: PlannedAction) -> None:
    (assessment,) = assess(
        IngestionEntityType.MILESTONE, MILESTONE_HEADERS, [row], milestone_snapshot()
    )

    assert errors(assessment) == []
    assert assessment.planned_action is expected


def test_resetting_a_completed_milestone_to_pending_needs_the_date_cleared_first() -> None:
    snapshot = milestone_snapshot(status=MilestoneStatus.COMPLETED, actual_date=date(2026, 11, 14))

    (row,) = assess(
        IngestionEntityType.MILESTONE,
        MILESTONE_HEADERS,
        [["PO-A", "FAT", "1", "2026-11-10", "", "PENDING"]],
        snapshot,
    )

    assert errors(row) == [("INCONSISTENT_MILESTONE_STATE", "actual_date")]


def test_milestone_for_an_unknown_purchase_order() -> None:
    (row,) = assess(
        IngestionEntityType.MILESTONE,
        MILESTONE_HEADERS,
        [["PO-ZZ", "FAT", "1", "2026-11-10", "", ""]],
    )

    assert errors(row) == [("REFERENCE_NOT_FOUND", "po_number")]


def commitment_snapshot(current: date | None) -> ReferenceSnapshot:
    commitments = (
        {"PO-A": RecordRef(uuid4(), {"committed_delivery_date": current, "version_no": 1})}
        if current
        else {}
    )
    return ReferenceSnapshot(purchase_orders=SNAPSHOT.purchase_orders, commitments=commitments)


@pytest.mark.parametrize(
    ("current", "incoming", "expected"),
    [
        (None, "2026-11-28", PlannedAction.CREATE),  # first commitment -> version 1
        (date(2026, 11, 28), "2026-12-06", PlannedAction.CREATE),  # changed -> a new version
        (date(2026, 11, 28), "2026-11-28", PlannedAction.NO_CHANGE),  # same date -> nothing
    ],
)
def test_planned_action_for_a_commitment(
    current: date | None, incoming: str, expected: PlannedAction
) -> None:
    (row,) = assess(
        IngestionEntityType.SUPPLIER_COMMITMENT,
        ["PO Number", "Committed Delivery Date", "Recorded By", "Source Reference"],
        [["PO-A", incoming, "expeditor", "LTR-17"]],
        commitment_snapshot(current),
    )

    assert errors(row) == []
    assert row.planned_action is expected
    assert row.resolved["source_reference"] == "LTR-17"


def test_commitment_for_an_unknown_purchase_order() -> None:
    (row,) = assess(
        IngestionEntityType.SUPPLIER_COMMITMENT,
        ["PO Number", "Committed Delivery Date"],
        [["PO-ZZ", "2026-11-28"]],
    )

    assert errors(row) == [("REFERENCE_NOT_FOUND", "po_number")]


# --- properties of the assessment -----------------------------------------------------


def test_the_assessment_keeps_row_numbers_and_order() -> None:
    rows = assess(
        IngestionEntityType.PROJECT,
        ["Project Code", "Project Name"],
        [["P1", "One"], ["", "x"], ["P3", "Three"]],
    )

    assert [row.row_number for row in rows] == [2, 3, 4]


def test_error_messages_never_contain_the_source_values() -> None:
    secret = "CONFIDENTIAL-VALUE-91"
    rows = assess(
        IngestionEntityType.PURCHASE_ORDER,
        PO_HEADERS,
        [[secret, secret, secret, secret, secret]],
    )

    for issue in rows[0].issues:
        assert secret not in issue.message


def test_assessment_is_a_pure_function_of_rows_and_snapshot() -> None:
    rows = [
        CandidateRow(2, {"code": "DC-A", "name": "Alpha"}),
        CandidateRow(3, {"code": "DC-NEW", "name": "New"}),
    ]

    first = assess_rows(IngestionEntityType.PROJECT, rows, SNAPSHOT)
    second = assess_rows(IngestionEntityType.PROJECT, rows, SNAPSHOT)

    assert first == second
    assert [row.planned_action for row in first] == [PlannedAction.NO_CHANGE, PlannedAction.CREATE]


def test_ids_in_a_snapshot_are_the_ones_handed_back() -> None:
    (row,) = assess(
        IngestionEntityType.EQUIPMENT,
        EQUIPMENT_HEADERS,
        [["EQ-NEW", "DC-B", "X", "UPS", "2027-01-01", "HIGH"]],
    )

    assert isinstance(row.resolved["project_id"], UUID)
    assert row.resolved["project_id"] == PROJECT_B
