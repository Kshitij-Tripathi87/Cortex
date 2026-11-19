"""The import lifecycle on PostgreSQL: preview, commit, failure and concurrency."""

import threading
from collections.abc import Callable
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, InvalidStateError, NotFoundError
from app.db.session import Database
from app.models import (
    IngestionBatch,
    Project,
    PurchaseOrder,
    Supplier,
    SupplierCommitmentVersion,
    Workspace,
)
from app.models.enums import (
    BatchStatus,
    IngestionEntityType,
    RowOutcome,
    RowStatus,
    SupplierStatus,
)
from app.repositories import supplier_repository
from app.services import ingestion_service, supplier_service
from tests import factories
from tests.importing import (
    COMMITMENT_HEADERS,
    EQUIPMENT_HEADERS,
    ITEM_HEADERS,
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

SUPPLIERS = [
    ["SUP-1", "Supplier one", "India", "Pune", "ACTIVE"],
    ["SUP-2", "Supplier two", "", "", ""],
    ["SUP-3", "Supplier three", "", "", ""],
    ["SUP-4", "Supplier four", "", "", ""],
]


@pytest.fixture
def importer(session: Session, workspace: Workspace) -> Importer:
    return Importer(session, workspace.id)


def statuses(importer: Importer, batch_id: Any) -> list[tuple[int, str, str | None]]:
    return [
        (row.row_number, row.status.value, row.outcome.value if row.outcome else None)
        for row in importer.rows(batch_id)
    ]


# --- the lifecycle --------------------------------------------------------------------


def test_every_entity_type_goes_from_preview_to_canonical_records(
    importer: Importer, session: Session
) -> None:
    import_small_dataset(importer)

    assert table_counts(session) == {
        "Project": 1,
        "Supplier": 2,
        "Equipment": 3,
        "PurchaseOrder": 2,
        "PurchaseOrderItem": 2,
        "Milestone": 3,
        "MilestonePlanVersion": 3,
        "SupplierCommitmentVersion": 2,
    }
    batches = session.scalars(select(IngestionBatch)).all()
    assert len(batches) == 7
    assert {batch.status for batch in batches} == {BatchStatus.COMMITTED}
    assert all(batch.committed_at is not None and batch.failure_code is None for batch in batches)
    assert sum(batch.committed_rows for batch in batches) == 15


def test_commit_reports_counters_and_links_each_row_to_its_record(
    importer: Importer, session: Session
) -> None:
    preview = importer.preview(E.SUPPLIER, SUPPLIER_HEADERS, SUPPLIERS[:2])
    assert preview.batch.status is BatchStatus.PREVIEWED
    assert table_counts(session, Supplier) == {"Supplier": 0}  # nothing canonical yet

    result = importer.commit(preview.batch.id)

    batch = result.batch
    assert result.replayed is False
    assert batch.status is BatchStatus.COMMITTED
    assert (batch.total_rows, batch.valid_rows, batch.invalid_rows) == (2, 2, 0)
    assert (batch.committed_rows, batch.skipped_rows, batch.failed_rows) == (2, 0, 0)
    assert batch.commit_summary == {
        "entities": {"supplier": {"created": 2, "updated": 0, "unchanged": 0}}
    }

    suppliers = {s.supplier_code: s for s in session.scalars(select(Supplier))}
    rows = importer.rows(batch.id)
    assert [(row.status, row.outcome) for row in rows] == [
        (RowStatus.COMMITTED, RowOutcome.CREATED)
    ] * 2
    assert [(row.canonical_entity_type, row.canonical_entity_id) for row in rows] == [
        ("supplier", suppliers["SUP-1"].id),
        ("supplier", suppliers["SUP-2"].id),
    ]
    assert suppliers["SUP-1"].workspace_id == importer.workspace_id
    assert suppliers["SUP-2"].status is SupplierStatus.ACTIVE  # default for a blank cell on create


def test_the_valid_subset_is_committed_and_invalid_rows_stay_visible(
    importer: Importer, session: Session
) -> None:
    preview = importer.preview(
        E.SUPPLIER,
        SUPPLIER_HEADERS,
        [
            SUPPLIERS[0],
            ["SUP-BAD", "", "", "", ""],
            SUPPLIERS[1],
            ["SUP-X", "Other", "", "", "DORMANT"],
        ],
    )
    assert (preview.batch.valid_rows, preview.batch.invalid_rows) == (2, 2)

    result = importer.commit(preview.batch.id)

    batch = result.batch
    # COMMITTED means the valid rows were processed, not that every row was valid.
    assert batch.status is BatchStatus.COMMITTED
    assert (batch.valid_rows, batch.invalid_rows, batch.committed_rows, batch.skipped_rows) == (
        2,
        2,
        2,
        0,
    )
    assert table_counts(session, Supplier) == {"Supplier": 2}
    assert statuses(importer, batch.id) == [
        (2, "COMMITTED", "CREATED"),
        (3, "INVALID", None),
        (4, "COMMITTED", "CREATED"),
        (5, "INVALID", None),
    ]
    invalid = [row for row in importer.rows(batch.id) if row.status is RowStatus.INVALID]
    assert [row.validation_errors[0]["code"] for row in invalid] == [
        "REQUIRED_FIELD_MISSING",
        "INVALID_ENUM",
    ]
    assert all(row.canonical_entity_id is None for row in invalid)
    assert invalid[0].raw_data["Supplier Code"] == "SUP-BAD"  # the source row is still there


def test_a_batch_without_a_valid_row_cannot_be_committed(
    importer: Importer, session: Session
) -> None:
    preview = importer.preview(E.SUPPLIER, SUPPLIER_HEADERS, [["", "No code", "", "", ""]])

    with pytest.raises(InvalidStateError) as failure:
        importer.commit(preview.batch.id)

    assert failure.value.code == "BATCH_NOT_COMMITTABLE"
    # It stays previewed, so a corrected dependency can still make it committable.
    assert importer.batch(preview.batch.id).status is BatchStatus.PREVIEWED


def test_unknown_or_foreign_batches_are_not_found(importer: Importer, session: Session) -> None:
    other = factories.make_workspace(session, workspace_id=uuid4(), slug="other")
    foreign = Importer(session, other.id).preview(E.SUPPLIER, SUPPLIER_HEADERS, SUPPLIERS[:1])

    for batch_id in (uuid4(), foreign.batch.id):
        with pytest.raises(NotFoundError):
            importer.commit(batch_id)
    assert table_counts(session, Supplier) == {"Supplier": 0}
    assert importer.batch(foreign.batch.id).status is BatchStatus.PREVIEWED


def test_dependency_order_is_enforced_by_references(importer: Importer, session: Session) -> None:
    """A purchase order cannot be committed before its supplier exists as a record."""
    importer.run(E.PROJECT, PROJECT_HEADERS, [["DC-1", "Project one", "", "", ""]])
    suppliers = importer.preview(
        E.SUPPLIER, SUPPLIER_HEADERS, SUPPLIERS[:1]
    )  # previewed, not committed
    orders = importer.preview(
        E.PURCHASE_ORDER, ORDER_HEADERS, [["PO-1", "DC-1", "SUP-1", "INR", "ISSUED"]]
    )

    assert orders.batch.valid_rows == 0
    assert [(e["column"], e["code"]) for e in orders.errors] == [
        ("supplier_code", "REFERENCE_NOT_FOUND")
    ]

    importer.commit(suppliers.batch.id)
    refreshed = importer.preview(
        E.PURCHASE_ORDER, ORDER_HEADERS, [["PO-1", "DC-1", "SUP-1", "INR", "ISSUED"]]
    )
    assert refreshed.duplicate_file is True
    assert refreshed.batch.id == orders.batch.id
    assert refreshed.batch.valid_rows == 1
    importer.commit(refreshed.batch.id)
    assert table_counts(session, PurchaseOrder) == {"PurchaseOrder": 1}


# --- failure: all or nothing ----------------------------------------------------------


def test_a_reference_that_became_invalid_after_preview_fails_the_whole_batch(
    importer: Importer, session: Session
) -> None:
    importer.run(E.PROJECT, PROJECT_HEADERS, [["DC-1", "Project one", "", "", ""]])
    importer.run(E.SUPPLIER, SUPPLIER_HEADERS, SUPPLIERS[:2])
    orders = [
        ["PO-1", "DC-1", "SUP-1", "INR", "ISSUED"],
        ["PO-2", "DC-1", "SUP-2", "INR", "ISSUED"],
    ]
    preview = importer.preview(E.PURCHASE_ORDER, ORDER_HEADERS, orders)
    assert preview.batch.valid_rows == 2

    # Between preview and commit the second supplier is deactivated.
    supplier = supplier_repository.get_by_code(session, importer.workspace_id, "SUP-2")
    assert supplier is not None
    supplier.status = SupplierStatus.INACTIVE
    session.commit()

    with pytest.raises(ConflictError) as failure:
        importer.commit(preview.batch.id)

    assert failure.value.code == "COMMIT_CONFLICT"
    assert [(d.row_number, d.column, d.code) for d in failure.value.details] == [
        (3, "supplier_code", "REFERENCE_INACTIVE")
    ]
    # Nothing was committed, not even the row that was still fine.
    assert table_counts(session, PurchaseOrder) == {"PurchaseOrder": 0}
    batch = importer.batch(preview.batch.id)
    assert (batch.status, batch.failure_code, batch.committed_at) == (
        BatchStatus.FAILED,
        "COMMIT_CONFLICT",
        None,
    )
    assert (batch.committed_rows, batch.skipped_rows, batch.failed_rows) == (0, 1, 1)
    assert statuses(importer, batch.id) == [
        (2, "SKIPPED", "ROLLED_BACK"),
        (3, "FAILED", "REJECTED"),
    ]
    rejected = importer.rows(batch.id)[1]
    assert rejected.validation_errors == [
        {
            "code": "REFERENCE_INACTIVE",
            "message": "The supplier is inactive. A new purchase order cannot name it.",
            "column": "supplier_code",
            "stage": "commit",
        }
    ]
    assert all(row.canonical_entity_id is None for row in importer.rows(batch.id))

    # A failed batch cannot be retried...
    with pytest.raises(InvalidStateError) as again:
        importer.commit(batch.id)
    assert again.value.code == "BATCH_NOT_COMMITTABLE"

    # ...but the same file can be submitted again, as a new batch, and now says why.
    resubmitted = importer.preview(E.PURCHASE_ORDER, ORDER_HEADERS, orders)
    assert resubmitted.duplicate_file is False
    assert resubmitted.batch.id != batch.id
    assert (resubmitted.batch.valid_rows, resubmitted.batch.invalid_rows) == (1, 1)
    assert table_counts(session, IngestionBatch) == {"IngestionBatch": 4}


def _fail_on_call(number: int, original: Callable[..., Any]) -> Callable[..., Any]:
    calls = {"count": 0}

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        calls["count"] += 1
        if calls["count"] == number:
            raise RuntimeError("simulated failure in the middle of the batch")
        return original(*args, **kwargs)

    return wrapper


def test_an_unexpected_failure_mid_batch_leaves_no_partial_records(
    importer: Importer, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    preview = importer.preview(E.SUPPLIER, SUPPLIER_HEADERS, SUPPLIERS)
    monkeypatch.setattr(
        supplier_service,
        "apply_source_record",
        _fail_on_call(3, supplier_service.apply_source_record),
    )

    with pytest.raises(RuntimeError, match="simulated failure"):
        importer.commit(preview.batch.id)

    # Two suppliers had already been written inside the transaction. None survives.
    assert table_counts(session, Supplier) == {"Supplier": 0}
    batch = importer.batch(preview.batch.id)
    assert (batch.status, batch.failure_code) == (BatchStatus.FAILED, "COMMIT_FAILED")
    assert (batch.committed_rows, batch.skipped_rows, batch.failed_rows) == (0, 4, 0)
    assert {status for _, status, _ in statuses(importer, batch.id)} == {"SKIPPED"}
    assert {outcome for _, _, outcome in statuses(importer, batch.id)} == {"ROLLED_BACK"}

    monkeypatch.undo()
    retry = importer.preview(E.SUPPLIER, SUPPLIER_HEADERS, SUPPLIERS)  # same bytes, new batch
    assert retry.batch.id != batch.id
    importer.commit(retry.batch.id)
    assert table_counts(session, Supplier) == {"Supplier": 4}


def test_a_database_constraint_failure_mid_batch_rolls_everything_back(
    importer: Importer, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The commit believes SUP-3 is new while it exists: the unique key refuses the insert."""
    existing = factories.make_supplier(
        session,
        session.get(Workspace, importer.workspace_id),
        supplier_code="SUP-3",
        name="Already here",  # type: ignore[arg-type]
    )
    preview = importer.preview(E.SUPPLIER, SUPPLIER_HEADERS, SUPPLIERS)
    monkeypatch.setattr(supplier_repository, "get_by_codes", lambda *args, **kwargs: {})

    with pytest.raises(ConflictError) as failure:
        importer.commit(preview.batch.id)

    assert failure.value.code == "COMMIT_CONFLICT"
    monkeypatch.undo()
    assert table_counts(session, Supplier) == {"Supplier": 1}
    session.refresh(existing)
    assert existing.name == "Already here"
    batch = importer.batch(preview.batch.id)
    assert (batch.status, batch.failure_code, batch.committed_rows) == (
        BatchStatus.FAILED,
        "COMMIT_CONFLICT",
        0,
    )


def test_commit_refuses_rows_whose_stored_values_no_longer_validate(
    importer: Importer, session: Session
) -> None:
    """Equipment moved to another project after an item file was previewed."""
    importer.run(
        E.PROJECT, PROJECT_HEADERS, [["DC-1", "One", "", "", ""], ["DC-2", "Two", "", "", ""]]
    )
    importer.run(E.SUPPLIER, SUPPLIER_HEADERS, SUPPLIERS[:1])
    importer.run(
        E.EQUIPMENT,
        EQUIPMENT_HEADERS,
        [["EQ-1", "DC-1", "Transformer", "TRANSFORMER", "2027-02-01", "HIGH"]],
    )
    importer.run(E.PURCHASE_ORDER, ORDER_HEADERS, [["PO-1", "DC-1", "SUP-1", "INR", "ISSUED"]])
    preview = importer.preview(
        E.PURCHASE_ORDER_ITEM, ITEM_HEADERS, [["PO-1", "EQ-1", "1", "10.00"]]
    )
    assert preview.batch.valid_rows == 1

    other_project = session.scalar(select(Project).where(Project.code == "DC-2"))
    assert other_project is not None
    session.execute(
        PurchaseOrder.__table__.update().values(project_id=other_project.id)  # the order moves away
    )
    session.commit()

    with pytest.raises(ConflictError) as failure:
        importer.commit(preview.batch.id)

    assert [(d.row_number, d.code) for d in failure.value.details] == [
        (2, "CROSS_PROJECT_REFERENCE")
    ]
    assert table_counts(session)["PurchaseOrderItem"] == 0


# --- concurrency ----------------------------------------------------------------------


def _in_parallel(db: Database, work: Callable[[Session], Any], workers: int = 2) -> list[Any]:
    """Run ``work`` in several threads, each with its own session, released together."""
    barrier = threading.Barrier(workers)
    outcomes: list[Any] = [None] * workers

    def run(index: int) -> None:
        with db.session() as own_session:
            barrier.wait(timeout=10)
            try:
                outcomes[index] = work(own_session)
            except Exception as exc:  # the outcome of interest in some tests
                outcomes[index] = exc

    threads = [threading.Thread(target=run, args=(index,)) for index in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not any(thread.is_alive() for thread in threads)
    return outcomes


def test_two_concurrent_commits_of_one_batch_take_effect_once(
    importer: Importer, session: Session, db: Database
) -> None:
    import_small_dataset(importer)
    preview = importer.preview(
        E.SUPPLIER_COMMITMENT,
        COMMITMENT_HEADERS,
        [["PO-1", "2027-01-10", "", ""], ["PO-2", "2026-12-06", "", ""]],
    )
    workspace_id, batch_id = importer.workspace_id, preview.batch.id
    session.rollback()

    outcomes = _in_parallel(
        db, lambda own: ingestion_service.commit_import(own, workspace_id, batch_id), workers=4
    )

    assert all(isinstance(outcome, ingestion_service.CommitResult) for outcome in outcomes), (
        outcomes
    )
    # Exactly one request did the work; the others found it done.
    assert sorted(outcome.replayed for outcome in outcomes) == [False, True, True, True]
    assert {outcome.batch.committed_rows for outcome in outcomes} == {2}
    versions = session.scalars(
        select(SupplierCommitmentVersion).order_by(
            SupplierCommitmentVersion.purchase_order_id, SupplierCommitmentVersion.version_no
        )
    ).all()
    assert len(versions) == 4  # two from the first import, two from this one: no duplicate
    assert sorted(version.version_no for version in versions) == [1, 1, 2, 2]


def test_two_batches_that_touch_the_same_order_allocate_distinct_versions(
    importer: Importer, session: Session, db: Database
) -> None:
    import_small_dataset(importer)
    first = importer.preview(
        E.SUPPLIER_COMMITMENT, COMMITMENT_HEADERS, [["PO-1", "2027-01-10", "", ""]]
    )
    second = importer.preview(
        E.SUPPLIER_COMMITMENT, COMMITMENT_HEADERS, [["PO-1", "2027-01-20", "", ""]]
    )
    workspace_id = importer.workspace_id
    batch_ids = iter([first.batch.id, second.batch.id])
    lock = threading.Lock()
    session.rollback()

    def commit_next(own: Session) -> Any:
        with lock:
            batch_id = next(batch_ids)
        return ingestion_service.commit_import(own, workspace_id, batch_id)

    outcomes = _in_parallel(db, commit_next)

    assert all(isinstance(outcome, ingestion_service.CommitResult) for outcome in outcomes), (
        outcomes
    )
    order = session.scalar(select(PurchaseOrder).where(PurchaseOrder.po_number == "PO-1"))
    assert order is not None
    versions = session.scalars(
        select(SupplierCommitmentVersion)
        .where(SupplierCommitmentVersion.purchase_order_id == order.id)
        .order_by(SupplierCommitmentVersion.version_no)
    ).all()
    # Whichever batch went first: three versions, numbered without a gap or a clash.
    assert [version.version_no for version in versions] == [1, 2, 3]
    assert {str(version.committed_delivery_date) for version in versions[1:]} == {
        "2027-01-10",
        "2027-01-20",
    }


def test_milestone_rows_create_the_milestone_and_its_first_plan(
    importer: Importer, session: Session
) -> None:
    import_small_dataset(importer)

    result = importer.run(
        E.MILESTONE,
        MILESTONE_HEADERS,
        [
            ["PO-2", "DISPATCH", "1", "2026-12-01", "", ""],
            ["PO-2", "DISPATCH", "2", "2026-12-08", "", "PENDING"],
        ],
    )

    assert result.batch.commit_summary == {
        "entities": {
            "milestone": {"created": 2, "updated": 0, "unchanged": 0},
            "milestone_plan_version": {"created": 2, "updated": 0, "unchanged": 0},
        }
    }
    assert table_counts(session)["Milestone"] == 5
    assert table_counts(session)["MilestonePlanVersion"] == 5
