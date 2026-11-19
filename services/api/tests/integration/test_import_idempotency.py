"""Importing the same thing twice changes nothing; importing a change changes only that."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Equipment,
    Milestone,
    MilestonePlanVersion,
    Project,
    PurchaseOrder,
    PurchaseOrderItem,
    Supplier,
    SupplierCommitmentVersion,
    Workspace,
)
from app.models.enums import (
    BatchStatus,
    IngestionEntityType,
    MilestoneStatus,
    ProjectStatus,
    RowOutcome,
    RowStatus,
)
from tests.importing import (
    CANONICAL_MODELS,
    COMMITMENT_HEADERS,
    EQUIPMENT_HEADERS,
    ITEM_HEADERS,
    LEDGER_MODELS,
    MILESTONE_HEADERS,
    ORDER_HEADERS,
    PROJECT_HEADERS,
    SUPPLIER_HEADERS,
    Importer,
    import_small_dataset,
    table_counts,
)

pytestmark = pytest.mark.db

E = IngestionEntityType


@pytest.fixture
def importer(session: Session, workspace: Workspace) -> Importer:
    importer = Importer(session, workspace.id)
    import_small_dataset(importer)
    return importer


def outcomes(importer: Importer, batch_id: object) -> list[tuple[str, str | None]]:
    return [
        (row.status.value, row.outcome.value if row.outcome else None)
        for row in importer.rows(batch_id)  # type: ignore[arg-type]
    ]


# --- the same file ---------------------------------------------------------------------


def test_the_same_file_is_one_batch_and_one_import(importer: Importer, session: Session) -> None:
    rows = [["SUP-9", "Supplier nine", "India", "Pune", "ACTIVE"]]
    first = importer.preview(E.SUPPLIER, SUPPLIER_HEADERS, rows, filename="a.csv")
    committed = importer.commit(first.batch.id)
    canonical = table_counts(session)
    ledger = table_counts(session, *LEDGER_MODELS)

    again = importer.preview(E.SUPPLIER, SUPPLIER_HEADERS, rows, filename="b.csv")
    replay = importer.commit(again.batch.id)

    assert again.duplicate_file is True
    assert again.created is False
    assert again.batch.id == first.batch.id
    assert again.batch.status is BatchStatus.COMMITTED
    assert replay.replayed is True
    # The replay returns the recorded result of the first commit.
    assert replay.batch.commit_summary == committed.batch.commit_summary
    assert replay.batch.committed_at == committed.batch.committed_at
    assert (replay.batch.committed_rows, replay.batch.skipped_rows) == (1, 0)
    assert table_counts(session) == canonical
    assert table_counts(session, *LEDGER_MODELS) == ledger


def test_committing_a_committed_batch_again_writes_nothing(
    importer: Importer, session: Session
) -> None:
    preview = importer.preview(
        E.SUPPLIER_COMMITMENT, COMMITMENT_HEADERS, [["PO-1", "2027-01-10", "", ""]]
    )
    importer.commit(preview.batch.id)
    before = table_counts(session)
    versions_before = [v.id for v in session.scalars(select(SupplierCommitmentVersion))]

    for _ in range(3):
        replay = importer.commit(preview.batch.id)
        assert replay.replayed is True

    assert table_counts(session) == before
    assert sorted(versions_before) == sorted(
        v.id for v in session.scalars(select(SupplierCommitmentVersion))
    )


def test_re_importing_the_whole_dataset_changes_no_count(
    importer: Importer, session: Session
) -> None:
    """The same rows in new files (different bytes): every record is recognised."""
    before = table_counts(session)
    project_updated_at = session.scalar(select(Project.updated_at))

    # A trailing column changes the bytes of every file without changing a value.
    importer.run(
        E.PROJECT,
        [*PROJECT_HEADERS, "Remark"],
        [["DC-1", "Project one", "Pune", "ACTIVE", "2027-09-30", ""]],
    )
    suppliers = importer.run(
        E.SUPPLIER,
        [*SUPPLIER_HEADERS, "Remark"],
        [
            ["SUP-1", "Supplier one", "India", "Pune", "ACTIVE", ""],
            ["SUP-2", "Supplier two", "", "", "", ""],
        ],
    )
    importer.run(
        E.EQUIPMENT,
        [*EQUIPMENT_HEADERS, "Remark"],
        [["EQ-1", "DC-1", "Transformer", "TRANSFORMER", "2027-02-01", "CRITICAL", ""]],
    )
    importer.run(
        E.PURCHASE_ORDER,
        [*ORDER_HEADERS, "Remark"],
        [["PO-1", "DC-1", "SUP-1", "INR", "ISSUED", ""]],
    )
    importer.run(
        E.PURCHASE_ORDER_ITEM, [*ITEM_HEADERS, "Remark"], [["PO-1", "EQ-1", "1", "1000.50", ""]]
    )
    milestones = importer.run(
        E.MILESTONE,
        [*MILESTONE_HEADERS, "Remark"],
        [["PO-1", "PO_ACKNOWLEDGEMENT", "1", "2026-06-08", "2026-06-08", "", ""]],
    )
    commitments = importer.run(
        E.SUPPLIER_COMMITMENT,
        [*COMMITMENT_HEADERS, "Remark"],
        [["PO-1", "2026-12-15", "Someone else", "REF-2", ""]],
    )

    assert table_counts(session) == before
    # Nothing was touched: the rows are skipped as unchanged and still linked.
    assert outcomes(importer, suppliers.batch.id) == [("SKIPPED", "UNCHANGED")] * 2
    assert outcomes(importer, milestones.batch.id) == [("SKIPPED", "UNCHANGED")]
    assert outcomes(importer, commitments.batch.id) == [("SKIPPED", "UNCHANGED")]
    assert (suppliers.batch.committed_rows, suppliers.batch.skipped_rows) == (0, 2)
    assert suppliers.batch.commit_summary == {
        "entities": {"supplier": {"created": 0, "updated": 0, "unchanged": 2}}
    }
    assert all(row.canonical_entity_id is not None for row in importer.rows(suppliers.batch.id))
    assert session.scalar(select(Project.updated_at)) == project_updated_at


# --- a different file with the same natural keys ---------------------------------------


def test_known_records_are_resolved_and_only_source_owned_fields_change(
    importer: Importer, session: Session
) -> None:
    project_id = session.scalar(select(Project.id))

    result = importer.run(
        E.PROJECT,
        PROJECT_HEADERS,
        [
            ["DC-1", "Project one, renamed", "", "ON_HOLD", ""],
            ["DC-2", "A second project", "", "", ""],
        ],
    )

    assert table_counts(session, Project) == {"Project": 2}  # one new, the other resolved
    assert result.batch.commit_summary == {
        "entities": {"project": {"created": 1, "updated": 1, "unchanged": 0}}
    }
    assert outcomes(importer, result.batch.id) == [
        ("COMMITTED", "UPDATED"),
        ("COMMITTED", "CREATED"),
    ]
    session.expire_all()
    project = session.scalar(select(Project).where(Project.code == "DC-1"))
    assert project is not None
    assert project.id == project_id  # the same record, not a twin
    assert (project.name, project.status) == ("Project one, renamed", ProjectStatus.ON_HOLD)
    # Blank cells did not clear what was stored.
    assert (project.location, project.target_completion_date) == ("Pune", date(2027, 9, 30))


def test_line_item_quantity_and_price_follow_the_source(
    importer: Importer, session: Session
) -> None:
    result = importer.run(
        E.PURCHASE_ORDER_ITEM,
        ITEM_HEADERS,
        [["PO-1", "EQ-1", "3", ""], ["PO-1", "EQ-3", "1", "50"]],
    )

    assert outcomes(importer, result.batch.id) == [
        ("COMMITTED", "UPDATED"),
        ("COMMITTED", "CREATED"),
    ]
    session.expire_all()
    items = {
        code: item
        for item, code in session.execute(
            select(PurchaseOrderItem, Equipment.equipment_code).join(
                Equipment, Equipment.id == PurchaseOrderItem.equipment_id
            )
        )
    }
    assert items["EQ-1"].quantity == Decimal("3")
    assert items["EQ-1"].unit_price == Decimal("1000.50")  # blank price: kept
    assert table_counts(session)["PurchaseOrderItem"] == 3


def test_an_import_does_not_move_a_record_to_another_parent(
    importer: Importer, session: Session
) -> None:
    importer.run(E.PROJECT, PROJECT_HEADERS, [["DC-2", "A second project", "", "", ""]])

    order = importer.preview(
        E.PURCHASE_ORDER, ORDER_HEADERS, [["PO-1", "DC-2", "SUP-2", "INR", "ISSUED"]]
    )
    equipment = importer.preview(
        E.EQUIPMENT,
        EQUIPMENT_HEADERS,
        [["EQ-1", "DC-2", "Transformer", "TRANSFORMER", "2027-02-01", "CRITICAL"]],
    )

    assert [(e["column"], e["code"]) for e in order.errors] == [
        ("project_code", "IMMUTABLE_FIELD_CONFLICT"),
        ("supplier_code", "IMMUTABLE_FIELD_CONFLICT"),
    ]
    assert [(e["column"], e["code"]) for e in equipment.errors] == [
        ("project_code", "IMMUTABLE_FIELD_CONFLICT")
    ]
    session.expire_all()
    stored = session.scalar(select(PurchaseOrder).where(PurchaseOrder.po_number == "PO-1"))
    supplier = session.scalar(select(Supplier).where(Supplier.supplier_code == "SUP-1"))
    assert stored is not None
    assert supplier is not None
    assert stored.supplier_id == supplier.id


# --- versions --------------------------------------------------------------------------


def commitment_versions(session: Session, po_number: str) -> list[tuple[int, str]]:
    session.expire_all()
    rows = session.execute(
        select(
            SupplierCommitmentVersion.version_no, SupplierCommitmentVersion.committed_delivery_date
        )
        .join(PurchaseOrder, PurchaseOrder.id == SupplierCommitmentVersion.purchase_order_id)
        .where(PurchaseOrder.po_number == po_number)
        .order_by(SupplierCommitmentVersion.version_no)
    )
    return [(version, str(day)) for version, day in rows]


def test_a_commitment_version_is_appended_only_when_the_date_differs(
    importer: Importer, session: Session
) -> None:
    assert commitment_versions(session, "PO-2") == [(1, "2026-11-28")]

    same_date_other_file = importer.run(
        E.SUPPLIER_COMMITMENT, COMMITMENT_HEADERS, [["PO-2", "2026-11-28", "Expediting", "R2"]]
    )
    assert commitment_versions(session, "PO-2") == [(1, "2026-11-28")]
    assert outcomes(importer, same_date_other_file.batch.id) == [("SKIPPED", "UNCHANGED")]

    revised = importer.run(
        E.SUPPLIER_COMMITMENT, COMMITMENT_HEADERS, [["PO-2", "2026-12-06", "Expediting", "R3"]]
    )
    assert commitment_versions(session, "PO-2") == [(1, "2026-11-28"), (2, "2026-12-06")]
    assert outcomes(importer, revised.batch.id) == [("COMMITTED", "CREATED")]
    assert revised.batch.commit_summary == {
        "entities": {"supplier_commitment_version": {"created": 1, "updated": 0, "unchanged": 0}}
    }

    importer.run(
        E.SUPPLIER_COMMITMENT, [*COMMITMENT_HEADERS, "Remark"], [["PO-2", "2026-12-06", "", "", ""]]
    )
    assert commitment_versions(session, "PO-2") == [(1, "2026-11-28"), (2, "2026-12-06")]

    back = importer.run(
        E.SUPPLIER_COMMITMENT,
        [*COMMITMENT_HEADERS, "Remark"],
        [["PO-2", "2026-11-28", "", "", "x"]],
    )
    # Compared with the current version, not with any earlier one: this is a change.
    assert commitment_versions(session, "PO-2") == [
        (1, "2026-11-28"),
        (2, "2026-12-06"),
        (3, "2026-11-28"),
    ]
    assert outcomes(importer, back.batch.id) == [("COMMITTED", "CREATED")]


def plan_versions(session: Session, milestone_type: str) -> list[tuple[int, str]]:
    session.expire_all()
    rows = session.execute(
        select(MilestonePlanVersion.version_no, MilestonePlanVersion.planned_date)
        .join(Milestone, Milestone.id == MilestonePlanVersion.milestone_id)
        .where(Milestone.milestone_type == milestone_type)
        .order_by(MilestonePlanVersion.version_no)
    )
    return [(version, str(day)) for version, day in rows]


def test_a_plan_version_is_appended_only_when_the_planned_date_differs(
    importer: Importer, session: Session
) -> None:
    same = importer.run(
        E.MILESTONE,
        [*MILESTONE_HEADERS, "Remark"],
        [["PO-1", "DELIVERY", "1", "2026-12-15", "", "", ""]],
    )
    assert plan_versions(session, "DELIVERY") == [(1, "2026-12-15")]
    assert outcomes(importer, same.batch.id) == [("SKIPPED", "UNCHANGED")]

    replanned = importer.run(
        E.MILESTONE, MILESTONE_HEADERS, [["PO-1", "DELIVERY", "1", "2027-01-05", "", ""]]
    )
    assert plan_versions(session, "DELIVERY") == [(1, "2026-12-15"), (2, "2027-01-05")]
    assert outcomes(importer, replanned.batch.id) == [("COMMITTED", "UPDATED")]
    assert replanned.batch.commit_summary == {
        "entities": {
            "milestone": {"created": 0, "updated": 1, "unchanged": 0},
            "milestone_plan_version": {"created": 1, "updated": 0, "unchanged": 0},
        }
    }
    assert table_counts(session)["Milestone"] == 3  # the milestone itself was not duplicated


def test_an_actual_date_is_recorded_without_touching_the_plan(
    importer: Importer, session: Session
) -> None:
    result = importer.run(
        E.MILESTONE, MILESTONE_HEADERS, [["PO-1", "DELIVERY", "1", "2026-12-15", "2026-12-19", ""]]
    )

    assert outcomes(importer, result.batch.id) == [("COMMITTED", "UPDATED")]
    assert plan_versions(session, "DELIVERY") == [(1, "2026-12-15")]
    milestone = session.scalar(select(Milestone).where(Milestone.milestone_type == "DELIVERY"))
    assert milestone is not None
    # Planned 15 December, actual 19 December: both are kept, neither is adjusted.
    assert (milestone.status, milestone.actual_date) == (
        MilestoneStatus.COMPLETED,
        date(2026, 12, 19),
    )


# --- duplicates inside one file ---------------------------------------------------------


def test_identical_rows_in_one_file_are_applied_once_and_both_linked(
    importer: Importer, session: Session
) -> None:
    row = ["SUP-9", "Supplier nine", "", "", ""]

    result = importer.run(
        E.SUPPLIER, SUPPLIER_HEADERS, [row, ["SUP-8", "Supplier eight", "", "", ""], row]
    )

    assert table_counts(session, Supplier) == {"Supplier": 4}
    rows = importer.rows(result.batch.id)
    assert [(r.status, r.outcome) for r in rows] == [
        (RowStatus.COMMITTED, RowOutcome.CREATED),
        (RowStatus.COMMITTED, RowOutcome.CREATED),
        (RowStatus.SKIPPED, RowOutcome.DUPLICATE_ROW),
    ]
    assert rows[2].canonical_entity_id == rows[0].canonical_entity_id
    assert (result.batch.committed_rows, result.batch.skipped_rows) == (2, 1)
    assert result.batch.commit_summary == {
        "entities": {"supplier": {"created": 2, "updated": 0, "unchanged": 0}}
    }


def test_conflicting_rows_in_one_file_are_rejected_whatever_their_order(
    importer: Importer, session: Session
) -> None:
    forward = importer.preview(
        E.SUPPLIER,
        SUPPLIER_HEADERS,
        [["SUP-9", "Name A", "", "", ""], ["SUP-9", "Name B", "", "", ""]],
    )
    backward = importer.preview(
        E.SUPPLIER,
        SUPPLIER_HEADERS,
        [["SUP-9", "Name B", "", "", ""], ["SUP-9", "Name A", "", "", ""]],
    )

    for preview in (forward, backward):
        assert (preview.batch.valid_rows, preview.batch.invalid_rows) == (0, 2)
        assert {e["code"] for e in preview.errors} == {"DUPLICATE_NATURAL_KEY"}
    assert table_counts(session, Supplier) == {"Supplier": 2}
    assert not session.scalars(select(Supplier).where(Supplier.supplier_code == "SUP-9")).all()


def test_no_table_is_touched_by_a_full_replay(importer: Importer, session: Session) -> None:
    """Every model, canonical and ledger, has the same row count after replaying a file."""
    preview = importer.preview(E.SUPPLIER, SUPPLIER_HEADERS, [["SUP-9", "Nine", "", "", ""]])
    importer.commit(preview.batch.id)
    before = table_counts(session, *CANONICAL_MODELS, *LEDGER_MODELS)

    importer.preview(E.SUPPLIER, SUPPLIER_HEADERS, [["SUP-9", "Nine", "", "", ""]])
    importer.commit(preview.batch.id)

    assert table_counts(session, *CANONICAL_MODELS, *LEDGER_MODELS) == before
