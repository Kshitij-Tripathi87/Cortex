"""History is append-only and every audit question has a lookup path, without inference."""

from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    IngestionBatch,
    IngestionRow,
    Milestone,
    MilestonePlanVersion,
    PurchaseOrder,
    SupplierCommitmentVersion,
    Workspace,
)
from app.models.enums import IngestionEntityType, MilestoneType, RowStatus
from app.repositories import ingestion_repository
from app.schemas.milestone import MilestoneCreate
from app.schemas.purchase_order import CommitmentCreate
from app.services import ingestion_service, milestone_service, purchase_order_service
from tests.importing import (
    COMMITMENT_HEADERS,
    MILESTONE_HEADERS,
    ORDER_HEADERS,
    Importer,
    import_small_dataset,
)

pytestmark = pytest.mark.db

E = IngestionEntityType


@pytest.fixture
def importer(session: Session, workspace: Workspace) -> Importer:
    importer = Importer(session, workspace.id)
    import_small_dataset(importer)
    return importer


def order(session: Session, po_number: str) -> PurchaseOrder:
    found = session.scalar(select(PurchaseOrder).where(PurchaseOrder.po_number == po_number))
    assert found is not None
    return found


def commitments(session: Session, po_number: str) -> list[SupplierCommitmentVersion]:
    session.expire_all()
    return list(
        session.scalars(
            select(SupplierCommitmentVersion)
            .where(SupplierCommitmentVersion.purchase_order_id == order(session, po_number).id)
            .order_by(SupplierCommitmentVersion.version_no)
        )
    )


def snapshot(version: object) -> dict[str, object]:
    """Every stored value of a version row."""
    return {column.name: getattr(version, column.name) for column in version.__table__.columns}  # type: ignore[attr-defined]


# --- append-only history ---------------------------------------------------------------


def test_commitment_history_first_revised_replayed(importer: Importer, session: Session) -> None:
    # First commitment: version 1 (created by the dataset import).
    first = commitments(session, "PO-2")
    assert [(v.version_no, v.committed_delivery_date) for v in first] == [(1, date(2026, 11, 28))]
    original = snapshot(first[0])

    # Revised: version 2, and the first is still exactly what it was.
    importer.run(
        E.SUPPLIER_COMMITMENT, COMMITMENT_HEADERS, [["PO-2", "2026-12-06", "Expediting", "R1"]]
    )
    revised = commitments(session, "PO-2")
    assert [(v.version_no, v.committed_delivery_date) for v in revised] == [
        (1, date(2026, 11, 28)),
        (2, date(2026, 12, 6)),
    ]
    assert snapshot(revised[0]) == original

    # Same date again, through the API this time: no new version.
    version, created = purchase_order_service.append_supplier_commitment(
        session,
        importer.workspace_id,
        order(session, "PO-2").id,
        CommitmentCreate(committed_delivery_date=date(2026, 12, 6)),
    )
    assert (created, version.version_no) == (False, 2)
    assert len(commitments(session, "PO-2")) == 2

    # The current commitment is the one with the greatest version number.
    page = purchase_order_service.list_supplier_commitments(
        session, importer.workspace_id, order(session, "PO-2").id, limit=50, offset=0
    )
    assert [v.version_no for v in page.items] == [1, 2]  # oldest first, explicitly
    detail = purchase_order_service.get_purchase_order(
        session, importer.workspace_id, order(session, "PO-2").id
    )
    assert detail.current_commitment is not None
    assert detail.current_commitment.version_no == 2


def test_plan_history_first_revised_replayed(importer: Importer, session: Session) -> None:
    purchase_order = order(session, "PO-1")
    created = milestone_service.create_milestone(
        session,
        importer.workspace_id,
        purchase_order.id,
        MilestoneCreate(milestone_type=MilestoneType.DISPATCH, planned_date=date(2026, 12, 1)),
    )
    milestone_id = created.milestone.id
    assert [(v.version_no, v.planned_date) for v in created.plan_versions] == [
        (1, date(2026, 12, 1))
    ]
    original = snapshot(created.plan_versions[0])

    revised, was_created = milestone_service.append_plan_version(
        session, importer.workspace_id, purchase_order.id, milestone_id, date(2026, 12, 15)
    )
    assert was_created is True
    assert [(v.version_no, v.planned_date) for v in revised.plan_versions] == [
        (1, date(2026, 12, 1)),
        (2, date(2026, 12, 15)),
    ]
    session.expire_all()
    stored = session.scalars(
        select(MilestonePlanVersion)
        .where(MilestonePlanVersion.milestone_id == milestone_id)
        .order_by(MilestonePlanVersion.version_no)
    ).all()
    assert snapshot(stored[0]) == original  # the first plan was not rewritten

    replay, was_created = milestone_service.append_plan_version(
        session, importer.workspace_id, purchase_order.id, milestone_id, date(2026, 12, 15)
    )
    assert (was_created, replay.plan_version_count) == (False, 2)
    assert replay.current_plan is not None
    assert replay.current_plan.version_no == 2


def test_versions_have_no_update_or_delete_operation() -> None:
    """History can only be appended to: the services offer nothing else."""
    for module in (purchase_order_service, milestone_service):
        names = [name for name in dir(module) if not name.startswith("_")]
        assert not [name for name in names if "delete" in name or "remove" in name]
    assert not [
        name
        for name in dir(purchase_order_service)
        if "commitment" in name and ("update" in name or "edit" in name)
    ]


# --- provenance ------------------------------------------------------------------------


def test_a_version_points_at_the_source_row_that_introduced_it(
    importer: Importer, session: Session
) -> None:
    result = importer.run(
        E.SUPPLIER_COMMITMENT,
        COMMITMENT_HEADERS,
        [["PO-2", "2026-12-06", "Expediting", "LTR-17"]],
        filename="revision.csv",
    )
    (row,) = importer.rows(result.batch.id)
    current = commitments(session, "PO-2")[-1]

    assert current.source_ingestion_row_id == row.id
    assert (current.recorded_by, current.source_reference) == ("Expediting", "LTR-17")
    # The row points back at the version it produced.
    assert (row.canonical_entity_type, row.canonical_entity_id) == (
        "supplier_commitment_version",
        current.id,
    )
    assert row.raw_data["Committed Delivery Date"] == "2026-12-06"
    assert row.normalized_data["committed_delivery_date"] == "2026-12-06"


def test_a_version_without_recorded_by_is_attributed_to_its_file(
    importer: Importer, session: Session
) -> None:
    importer.run(
        E.SUPPLIER_COMMITMENT,
        COMMITMENT_HEADERS,
        [["PO-2", "2026-12-06", "", ""]],
        filename="expediting.csv",
    )

    assert commitments(session, "PO-2")[-1].recorded_by == "import:expediting.csv"


def test_a_version_created_through_the_api_has_no_source_row(
    importer: Importer, session: Session
) -> None:
    version, _ = purchase_order_service.append_supplier_commitment(
        session,
        importer.workspace_id,
        order(session, "PO-1").id,
        CommitmentCreate(committed_delivery_date=date(2027, 1, 10), recorded_by="planner"),
    )

    assert version.source_ingestion_row_id is None
    assert version.recorded_by == "planner"


def test_a_re_plan_points_at_the_row_that_changed_the_date(
    importer: Importer, session: Session
) -> None:
    result = importer.run(
        E.MILESTONE, MILESTONE_HEADERS, [["PO-1", "DELIVERY", "1", "2027-01-05", "", ""]]
    )
    (row,) = importer.rows(result.batch.id)
    session.expire_all()
    versions = session.scalars(
        select(MilestonePlanVersion)
        .join(Milestone, Milestone.id == MilestonePlanVersion.milestone_id)
        .where(Milestone.milestone_type == MilestoneType.DELIVERY)
        .order_by(MilestonePlanVersion.version_no)
    ).all()

    assert [v.version_no for v in versions] == [1, 2]
    assert versions[1].source_ingestion_row_id == row.id
    # Version 1 still points at the row of the original import, a different one.
    assert versions[0].source_ingestion_row_id not in {None, row.id}


# --- the audit questions of the playbook, answered by lookups --------------------------


def test_which_file_supplied_this_purchase_order(importer: Importer, session: Session) -> None:
    purchase_order = order(session, "PO-1")

    sources = ingestion_service.list_sources(
        session, importer.workspace_id, "purchase_order", purchase_order.id, limit=50, offset=0
    )

    assert sources.total == 1
    source = sources.items[0]
    assert source.batch.entity_type is E.PURCHASE_ORDER
    assert source.batch.original_filename.startswith("purchase_order_")
    assert len(source.batch.file_sha256) == 64
    assert source.row.raw_data["PO Number"] == "PO-1"


def test_every_file_that_mentioned_a_record_is_listed(importer: Importer, session: Session) -> None:
    importer.run(
        E.PURCHASE_ORDER,
        ORDER_HEADERS,
        [["PO-1", "DC-1", "SUP-1", "INR", "ACKNOWLEDGED"]],
        filename="update.csv",
    )
    importer.run(
        E.PURCHASE_ORDER,
        [*ORDER_HEADERS, "Remark"],
        [["PO-1", "DC-1", "SUP-1", "INR", "ACKNOWLEDGED", ""]],
        filename="repeat.csv",
    )

    sources = ingestion_service.list_sources(
        session,
        importer.workspace_id,
        "purchase_order",
        order(session, "PO-1").id,
        limit=50,
        offset=0,
    )

    # Created, then updated, then confirmed unchanged: three statements about one record.
    assert [(s.row.status.value, s.row.outcome.value) for s in sources.items] == [  # type: ignore[union-attr]
        ("COMMITTED", "CREATED"),
        ("COMMITTED", "UPDATED"),
        ("SKIPPED", "UNCHANGED"),
    ]
    assert [s.batch.original_filename for s in sources.items][1:] == ["update.csv", "repeat.csv"]


def test_which_source_row_introduced_the_current_commitment_and_what_was_before(
    importer: Importer, session: Session
) -> None:
    importer.run(
        E.SUPPLIER_COMMITMENT,
        COMMITMENT_HEADERS,
        [["PO-2", "2026-12-06", "", ""]],
        filename="revision.csv",
    )
    history = commitments(session, "PO-2")
    current, previous = history[-1], history[-2]

    row = session.get(IngestionRow, current.source_ingestion_row_id)
    assert row is not None
    batch = session.get(IngestionBatch, row.batch_id)
    assert batch is not None

    assert (batch.original_filename, row.row_number) == ("revision.csv", 2)
    assert (previous.version_no, previous.committed_delivery_date) == (1, date(2026, 11, 28))


def test_why_was_an_input_row_not_committed(importer: Importer, session: Session) -> None:
    preview = importer.preview(
        E.SUPPLIER_COMMITMENT,
        COMMITMENT_HEADERS,
        [
            ["PO-1", "2027-02-01", "", ""],
            ["PO-404", "2027-02-01", "", ""],
            ["PO-2", "01/02/2027", "", ""],
        ],
    )
    importer.commit(preview.batch.id)

    rows = importer.rows(preview.batch.id)
    explanations = [
        (row.row_number, row.status, [error["code"] for error in row.validation_errors])
        for row in rows
    ]
    assert explanations == [
        (2, RowStatus.COMMITTED, []),
        (3, RowStatus.INVALID, ["REFERENCE_NOT_FOUND"]),
        (4, RowStatus.INVALID, ["INVALID_DATE"]),
    ]
    assert (
        rows[2].raw_data["Committed Delivery Date"] == "01/02/2027"
    )  # what the source said is kept


def test_was_this_file_imported_before(importer: Importer, session: Session) -> None:
    rows = [["PO-1", "2027-02-01", "", ""]]
    first = importer.run(E.SUPPLIER_COMMITMENT, COMMITMENT_HEADERS, rows)
    checksum = first.batch.file_sha256

    found = ingestion_repository.get_by_checksum(
        session, importer.workspace_id, E.SUPPLIER_COMMITMENT, checksum
    )
    as_another_entity = ingestion_repository.get_by_checksum(
        session, importer.workspace_id, E.MILESTONE, checksum
    )
    unknown = ingestion_repository.get_by_checksum(
        session, importer.workspace_id, E.SUPPLIER_COMMITMENT, "0" * 64
    )

    assert found is not None
    assert (found.id, found.committed_at) == (first.batch.id, first.batch.committed_at)
    assert as_another_entity is None
    assert unknown is None


def test_the_ledger_keeps_the_source_and_the_normalized_values_side_by_side(
    importer: Importer, session: Session
) -> None:
    result = importer.run(
        E.SUPPLIER_COMMITMENT,
        [" po number ", "Supplier Promise Date", "Internal Remark"],
        [[" PO-1 ", "2027-02-01", "phoned on Tuesday"]],
    )
    (row,) = importer.rows(result.batch.id)

    # The source, untouched: original headers, original spacing, the unmapped column.
    assert row.raw_data == {
        "po number": " PO-1 ",
        "Supplier Promise Date": "2027-02-01",
        "Internal Remark": "phoned on Tuesday",
    }
    # The canonical reading of it.
    assert row.normalized_data == {"po_number": "PO-1", "committed_delivery_date": "2027-02-01"}
    assert [warning["code"] for warning in row.warnings] == ["UNKNOWN_SOURCE_COLUMN"]
