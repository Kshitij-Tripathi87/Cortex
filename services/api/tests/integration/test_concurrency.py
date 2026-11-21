"""Writers that meet: who waits for whom, and what the data looks like afterwards.

Two kinds of test:

* *Held-lock tests* are deterministic. One session holds a row lock, a second
  writer is started, and the test waits until PostgreSQL itself reports that
  writer as waiting for a lock. Only then is the lock released. Without the
  lock in the code under test the writer never waits, and the test fails.
* *Race tests* release several writers at once and check the outcome. They
  prove the outcome is right however the race falls, but a race can fall the
  harmless way; where it matters, a held-lock test stands beside them.
"""

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.errors import ConflictError
from app.db.session import Database
from app.models import (
    IngestionBatch,
    IngestionRow,
    Milestone,
    MilestonePlanVersion,
    PurchaseOrder,
    Supplier,
    SupplierCommitmentVersion,
    Workspace,
)
from app.models.enums import BatchStatus, IngestionEntityType, MilestoneType
from app.repositories import (
    ingestion_repository,
    milestone_repository,
    project_repository,
    purchase_order_repository,
)
from app.schemas.project import ProjectUpdate
from app.schemas.purchase_order import CommitmentCreate, PurchaseOrderUpdate
from app.schemas.supplier import SupplierCreate
from app.services import (
    ingestion_service,
    milestone_service,
    project_service,
    purchase_order_service,
    supplier_service,
)
from app.services.ingestion_service import PreviewResult, UploadedFile
from tests import factories
from tests.factories import csv_bytes
from tests.importing import (
    COMMITMENT_HEADERS,
    LIMITS,
    MILESTONE_HEADERS,
    SUPPLIER_HEADERS,
    Importer,
    import_small_dataset,
    table_counts,
)

pytestmark = pytest.mark.db

E = IngestionEntityType

WAIT_SECONDS = 15


@pytest.fixture
def importer(session: Session, workspace: Workspace) -> Importer:
    return Importer(session, workspace.id)


# --- helpers --------------------------------------------------------------------------


def lock_waiters(db: Database) -> int:
    """How many sessions PostgreSQL reports as waiting for a lock right now."""
    with db.engine.connect() as connection:
        return int(
            connection.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND wait_event_type = 'Lock'"
                )
            ).scalar_one()
        )


def wait_until_blocked(db: Database, thread: threading.Thread) -> None:
    """Return once the database reports a session waiting for a lock.

    Fails if the writer finishes, or the time runs out, without ever waiting:
    that is what happens when the code under test takes no lock.
    """
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        if lock_waiters(db) >= 1:
            return
        assert thread.is_alive(), "the writer finished without waiting for the lock"
        time.sleep(0.02)
    pytest.fail("no session was reported as waiting for a lock")


class Writer:
    """Runs one operation in its own thread and session, and keeps what came of it."""

    def __init__(self, db: Database, work: Callable[[Session], Any]) -> None:
        self.outcome: Any = None
        self._db = db
        self._work = work
        self.thread = threading.Thread(target=self._run)

    def _run(self) -> None:
        with self._db.session() as own_session:
            try:
                self.outcome = self._work(own_session)
            except Exception as exc:  # reported by the test that started the writer
                self.outcome = exc

    def start(self) -> "Writer":
        self.thread.start()
        return self

    def finish(self) -> Any:
        self.thread.join(timeout=WAIT_SECONDS)
        assert not self.thread.is_alive(), "the writer is still running"
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


@contextmanager
def holder(db: Database) -> Iterator[Session]:
    """A session of 'another writer'. Whatever it locks stays locked until it commits."""
    other = db.new_session()
    try:
        yield other
    finally:
        other.rollback()
        other.close()


def purchase_order(session: Session, po_number: str) -> PurchaseOrder:
    session.rollback()
    order = session.scalar(select(PurchaseOrder).where(PurchaseOrder.po_number == po_number))
    assert order is not None
    return order


def commitment_dates(session: Session, purchase_order_id: UUID) -> list[tuple[int, str]]:
    session.rollback()
    versions = session.scalars(
        select(SupplierCommitmentVersion)
        .where(SupplierCommitmentVersion.purchase_order_id == purchase_order_id)
        .order_by(SupplierCommitmentVersion.version_no)
    )
    return [(version.version_no, str(version.committed_delivery_date)) for version in versions]


def plan_dates(session: Session, milestone_id: UUID) -> list[tuple[int, str]]:
    session.rollback()
    versions = session.scalars(
        select(MilestonePlanVersion)
        .where(MilestonePlanVersion.milestone_id == milestone_id)
        .order_by(MilestonePlanVersion.version_no)
    )
    return [(version.version_no, str(version.planned_date)) for version in versions]


def delivery_milestone(session: Session, order: PurchaseOrder) -> Milestone:
    milestone = session.scalar(
        select(Milestone).where(
            Milestone.purchase_order_id == order.id,
            Milestone.milestone_type == MilestoneType.DELIVERY,
        )
    )
    assert milestone is not None
    return milestone


# --- commitment versions: the purchase order row is the lock ---------------------------


def test_a_commitment_import_waits_for_a_writer_that_holds_the_purchase_order(
    importer: Importer, session: Session, db: Database
) -> None:
    import_small_dataset(importer)  # PO-1 has commitment version 1: 2026-12-15
    order = purchase_order(session, "PO-1")
    batch_id = importer.preview(
        E.SUPPLIER_COMMITMENT, COMMITMENT_HEADERS, [["PO-1", "2027-01-20", "", ""]]
    ).batch.id
    workspace_id = importer.workspace_id
    session.rollback()

    with holder(db) as other:
        locked = purchase_order_repository.lock_by_id(other, workspace_id, order.id)
        assert locked is not None
        writer = Writer(
            db, lambda own: ingestion_service.commit_import(own, workspace_id, batch_id)
        ).start()

        # The import cannot read "the latest version" while someone else may be
        # about to add one. It waits.
        wait_until_blocked(db, writer.thread)
        purchase_order_service.record_commitment(
            other, locked, committed_delivery_date=date(2027, 1, 10), recorded_by="other writer"
        )
        other.commit()

        result = writer.finish()

    assert result.batch.status is BatchStatus.COMMITTED
    # Numbered after the other writer's version, not beside it.
    assert commitment_dates(session, order.id) == [
        (1, "2026-12-15"),
        (2, "2027-01-10"),
        (3, "2027-01-20"),
    ]


def test_an_api_commitment_waits_for_a_writer_that_holds_the_purchase_order(
    importer: Importer, session: Session, db: Database
) -> None:
    import_small_dataset(importer)
    order = purchase_order(session, "PO-1")
    workspace_id = importer.workspace_id
    session.rollback()

    with holder(db) as other:
        locked = purchase_order_repository.lock_by_id(other, workspace_id, order.id)
        assert locked is not None
        writer = Writer(
            db,
            lambda own: purchase_order_service.append_supplier_commitment(
                own,
                workspace_id,
                order.id,
                CommitmentCreate(committed_delivery_date=date(2027, 1, 20)),
            ),
        ).start()

        wait_until_blocked(db, writer.thread)
        purchase_order_service.record_commitment(
            other, locked, committed_delivery_date=date(2027, 1, 10), recorded_by="other writer"
        )
        other.commit()

        version, created = writer.finish()

    assert (version.version_no, created) == (3, True)
    assert [number for number, _ in commitment_dates(session, order.id)] == [1, 2, 3]


def test_a_commitment_that_became_current_while_waiting_is_not_appended_twice(
    importer: Importer, session: Session, db: Database
) -> None:
    """The date is compared with the latest version *after* the wait, not before it."""
    import_small_dataset(importer)
    order = purchase_order(session, "PO-1")
    workspace_id = importer.workspace_id
    session.rollback()

    with holder(db) as other:
        locked = purchase_order_repository.lock_by_id(other, workspace_id, order.id)
        assert locked is not None
        writer = Writer(
            db,
            lambda own: purchase_order_service.append_supplier_commitment(
                own,
                workspace_id,
                order.id,
                CommitmentCreate(committed_delivery_date=date(2027, 1, 10)),
            ),
        ).start()

        wait_until_blocked(db, writer.thread)
        # The other writer records the very date the waiting writer brings.
        purchase_order_service.record_commitment(
            other, locked, committed_delivery_date=date(2027, 1, 10), recorded_by="other writer"
        )
        other.commit()

        version, created = writer.finish()

    assert (version.version_no, created) == (2, False)
    assert commitment_dates(session, order.id) == [(1, "2026-12-15"), (2, "2027-01-10")]


# --- plan versions: the milestone row is the lock ---------------------------------------


def test_a_milestone_import_waits_for_a_writer_that_holds_the_milestone(
    importer: Importer, session: Session, db: Database
) -> None:
    import_small_dataset(importer)  # PO-1 DELIVERY #1 is planned for 2026-12-15
    order = purchase_order(session, "PO-1")
    milestone = delivery_milestone(session, order)
    batch_id = importer.preview(
        E.MILESTONE, MILESTONE_HEADERS, [["PO-1", "DELIVERY", "1", "2027-01-05", "", ""]]
    ).batch.id
    workspace_id = importer.workspace_id
    session.rollback()

    with holder(db) as other:
        locked = milestone_repository.get_by_id(
            other, workspace_id, milestone.id, purchase_order_id=order.id, for_update=True
        )
        assert locked is not None
        writer = Writer(
            db, lambda own: ingestion_service.commit_import(own, workspace_id, batch_id)
        ).start()

        wait_until_blocked(db, writer.thread)
        milestone_service.record_plan(
            other, locked, planned_date=date(2026, 12, 20), recorded_by="other writer"
        )
        other.commit()

        result = writer.finish()

    assert result.batch.status is BatchStatus.COMMITTED
    assert plan_dates(session, milestone.id) == [
        (1, "2026-12-15"),
        (2, "2026-12-20"),
        (3, "2027-01-05"),
    ]


def test_an_api_re_plan_waits_for_a_writer_that_holds_the_milestone(
    importer: Importer, session: Session, db: Database
) -> None:
    import_small_dataset(importer)
    order = purchase_order(session, "PO-1")
    milestone = delivery_milestone(session, order)
    workspace_id = importer.workspace_id
    session.rollback()

    with holder(db) as other:
        locked = milestone_repository.get_by_id(
            other, workspace_id, milestone.id, purchase_order_id=order.id, for_update=True
        )
        assert locked is not None
        writer = Writer(
            db,
            lambda own: milestone_service.append_plan_version(
                own, workspace_id, order.id, milestone.id, date(2027, 1, 5)
            ),
        ).start()

        wait_until_blocked(db, writer.thread)
        milestone_service.record_plan(
            other, locked, planned_date=date(2026, 12, 20), recorded_by="other writer"
        )
        other.commit()

        _, created = writer.finish()

    assert created is True
    assert [number for number, _ in plan_dates(session, milestone.id)] == [1, 2, 3]


# --- patch requests: the record row is the lock ------------------------------------------


def test_a_project_patch_waits_for_a_writer_that_holds_the_record(
    db: Database, session: Session, workspace: Workspace
) -> None:
    """A patch reads the record it changes under a row lock.

    Without the lock the request could read the old row, a second writer
    could commit in between, and the patch would be applied to a record that
    no longer looks the way it was compared against.
    """
    project = factories.make_project(session, workspace, code="DC-PATCH")
    project_id, workspace_id = project.id, workspace.id
    session.rollback()

    with holder(db) as other:
        locked = project_repository.get_by_id(other, workspace_id, project_id, for_update=True)
        assert locked is not None
        writer = Writer(
            db,
            lambda own: project_service.update_project(
                own, workspace_id, project_id, ProjectUpdate(name="Renamed by the writer")
            ),
        ).start()

        wait_until_blocked(db, writer.thread)
        locked.location = "Changed by the holder"
        other.commit()

        updated = writer.finish()

    # The patch saw the holder's change and kept it; only its own field moved.
    assert (updated.name, updated.location) == ("Renamed by the writer", "Changed by the holder")


def test_a_purchase_order_patch_waits_for_a_writer_that_holds_the_order(
    db: Database, session: Session, workspace: Workspace
) -> None:
    project = factories.make_project(session, workspace, code="DC-PATCH-PO")
    supplier = factories.make_supplier(session, workspace, supplier_code="SUP-PATCH")
    order = factories.make_purchase_order(session, project, supplier, po_number="PO-PATCH")
    order_id, workspace_id = order.id, workspace.id
    session.rollback()

    with holder(db) as other:
        locked = purchase_order_repository.lock_by_id(other, workspace_id, order_id)
        assert locked is not None
        writer = Writer(
            db,
            lambda own: purchase_order_service.update_purchase_order(
                own, workspace_id, order_id, PurchaseOrderUpdate(issue_date=date(2026, 7, 1))
            ),
        ).start()

        wait_until_blocked(db, writer.thread)
        locked.total_value = Decimal("1234.56")
        other.commit()

        detail = writer.finish()

    assert detail.issue_date == date(2026, 7, 1)
    assert detail.total_value == Decimal("1234.56")


# --- a batch is committed once: the batch row is the lock --------------------------------


def test_a_second_commit_waits_for_the_first_and_then_reports_its_result(
    importer: Importer, session: Session, db: Database
) -> None:
    import_small_dataset(importer)
    order = purchase_order(session, "PO-1")
    batch_id = importer.preview(
        E.SUPPLIER_COMMITMENT, COMMITMENT_HEADERS, [["PO-1", "2027-01-20", "", ""]]
    ).batch.id
    workspace_id = importer.workspace_id
    session.rollback()

    with holder(db) as first:
        # The first commit, stopped at the point where it holds the batch.
        locked = ingestion_repository.lock_for_commit(first, workspace_id, batch_id)
        assert locked is not None
        assert locked.status is BatchStatus.PREVIEWED
        writer = Writer(
            db, lambda own: ingestion_service.commit_import(own, workspace_id, batch_id)
        ).start()

        wait_until_blocked(db, writer.thread)
        first.rollback()  # the first commit gives up; the batch is still PREVIEWED

        result = writer.finish()

    # The waiting request found the batch uncommitted and did the work itself, once.
    assert (result.replayed, result.batch.committed_rows) == (False, 1)
    assert commitment_dates(session, order.id) == [(1, "2026-12-15"), (2, "2027-01-20")]


# --- a deadlock: PostgreSQL ends one of the two -------------------------------------------


def test_a_commit_ended_by_a_deadlock_writes_nothing_and_can_be_sent_again(
    importer: Importer, session: Session, db: Database
) -> None:
    """Two writers, each holding a purchase order the other needs.

    The import locks its purchase orders in order of their number: it takes
    PO-1 and waits for PO-2, which the other writer holds. The other writer
    then asks for PO-1. Neither can move; PostgreSQL ends the one that waited
    first, which is the import.

    (The waiter that finds the cycle is ended, and each waiter looks once,
    ``deadlock_timeout`` after it began to wait: one second by default. The
    other writer asks for PO-1 some 20 ms after the import began to wait, so
    it is the import that finds it.)
    """
    import_small_dataset(importer)
    first, second = purchase_order(session, "PO-1"), purchase_order(session, "PO-2")
    batch_id = importer.preview(
        E.SUPPLIER_COMMITMENT,
        COMMITMENT_HEADERS,
        [["PO-1", "2027-01-20", "", ""], ["PO-2", "2027-01-21", "", ""]],
    ).batch.id
    workspace_id = importer.workspace_id
    session.rollback()

    with holder(db) as other:
        assert purchase_order_repository.lock_by_id(other, workspace_id, second.id) is not None
        writer = Writer(
            db, lambda own: ingestion_service.commit_import(own, workspace_id, batch_id)
        ).start()
        wait_until_blocked(db, writer.thread)  # the import holds PO-1 and waits for PO-2

        # Blocks until PostgreSQL has ended the import, then gets the lock.
        assert purchase_order_repository.lock_by_id(other, workspace_id, first.id) is not None

        with pytest.raises(ConflictError) as failure:
            writer.finish()
        other.commit()

    assert failure.value.code == "CONFLICT"
    assert "Send the commit again" in failure.value.message
    # Nothing of the batch was written, and the batch itself is as it was.
    assert commitment_dates(session, first.id) == [(1, "2026-12-15")]
    assert commitment_dates(session, second.id) == [(1, "2026-11-28")]
    batch = importer.batch(batch_id)
    assert (batch.status, batch.failure_code) == (BatchStatus.PREVIEWED, None)

    # Sent again, with nobody in the way, it goes through.
    result = importer.commit(batch_id)
    assert (result.replayed, result.batch.committed_rows) == (False, 2)
    assert commitment_dates(session, first.id) == [(1, "2026-12-15"), (2, "2027-01-20")]
    assert commitment_dates(session, second.id) == [(1, "2026-11-28"), (2, "2027-01-21")]


# --- natural keys: the unique key decides between two creators ---------------------------


def _create_supplier(workspace_id: UUID, name: str) -> Callable[[Session], Supplier]:
    payload = SupplierCreate(supplier_code="SUP-RACE", name=name)
    return lambda own: supplier_service.create_supplier(own, workspace_id, payload)


def test_a_record_created_while_another_writer_holds_its_key_is_a_duplicate(
    db: Database, session: Session, workspace: Workspace
) -> None:
    """Both writers looked for the code and neither could see the other.

    The second insert waits on the unique key until the first writer commits,
    and is then refused by the database. The caller is told the code is taken,
    as if the first record had been there all along.
    """
    with holder(db) as other:
        other.add(Supplier(workspace_id=workspace.id, supplier_code="SUP-RACE", name="First"))
        other.flush()
        writer = Writer(db, _create_supplier(workspace.id, "Second")).start()
        wait_until_blocked(db, writer.thread)
        other.commit()

    with pytest.raises(ConflictError) as failure:
        writer.finish()

    assert failure.value.code == "DUPLICATE_NATURAL_KEY"
    assert [detail.field for detail in failure.value.details] == ["supplier_code"]
    session.rollback()
    assert [supplier.name for supplier in session.scalars(select(Supplier))] == ["First"]


def test_a_record_is_created_when_the_writer_that_held_its_key_gives_up(
    db: Database, session: Session, workspace: Workspace
) -> None:
    """The same wait, and the first writer rolls back: the key was never taken."""
    with holder(db) as other:
        other.add(Supplier(workspace_id=workspace.id, supplier_code="SUP-RACE", name="First"))
        other.flush()
        writer = Writer(db, _create_supplier(workspace.id, "Second")).start()
        wait_until_blocked(db, writer.thread)
        other.rollback()

    created = writer.finish()

    assert created.supplier_code == "SUP-RACE"
    session.rollback()
    assert [supplier.name for supplier in session.scalars(select(Supplier))] == ["Second"]


# --- the same file, uploaded at the same moment ------------------------------------------


def _suppliers_file() -> UploadedFile:
    rows = [
        [f"SUP-{index:03d}", f"Supplier {index}", "India", "Pune", "ACTIVE"] for index in range(40)
    ]
    return UploadedFile("suppliers.csv", "text/csv", csv_bytes(SUPPLIER_HEADERS, rows))


def test_the_same_new_file_uploaded_at_once_is_one_batch_for_everyone(
    workspace: Workspace, session: Session, db: Database
) -> None:
    upload = _suppliers_file()
    workspace_id = workspace.id
    workers = 6
    barrier = threading.Barrier(workers)

    def preview(own: Session) -> PreviewResult:
        barrier.wait(timeout=WAIT_SECONDS)
        return ingestion_service.preview_import(
            own, workspace_id, upload, E.SUPPLIER, limits=LIMITS
        )

    writers = [Writer(db, preview).start() for _ in range(workers)]
    results = [writer.finish() for writer in writers]

    # Nobody is turned away: every caller is answered with the one batch.
    assert len({result.batch.id for result in results}) == 1
    assert sum(result.created for result in results) == 1
    assert {result.batch.total_rows for result in results} == {40}
    assert table_counts(session, IngestionBatch, IngestionRow) == {
        "IngestionBatch": 1,
        "IngestionRow": 40,
    }
    # A preview, however often it is asked for, creates no supplier.
    assert table_counts(session, Supplier) == {"Supplier": 0}


def test_an_upload_that_loses_the_race_is_answered_with_the_winning_batch(
    workspace: Workspace, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The race, replayed step by step.

    The winner's batch exists, but the loser looked for it a moment too early
    and saw nothing. Its insert is then refused by the unique index. It must
    look again and answer with the batch that is there.
    """
    upload = _suppliers_file()
    winner = ingestion_service.preview_import(
        session, workspace.id, upload, E.SUPPLIER, limits=LIMITS
    )
    assert winner.created is True

    real_lookup = ingestion_repository.get_by_checksum
    lookups = 0

    def looked_too_early(*arguments: Any, **keywords: Any) -> IngestionBatch | None:
        nonlocal lookups
        lookups += 1
        return None if lookups == 1 else real_lookup(*arguments, **keywords)

    monkeypatch.setattr(ingestion_repository, "get_by_checksum", looked_too_early)

    loser = ingestion_service.preview_import(
        session, workspace.id, upload, E.SUPPLIER, limits=LIMITS
    )

    assert lookups == 2
    assert (loser.batch.id, loser.created, loser.duplicate_file) == (winner.batch.id, False, True)
    assert table_counts(session, IngestionBatch, IngestionRow) == {
        "IngestionBatch": 1,
        "IngestionRow": 40,
    }
