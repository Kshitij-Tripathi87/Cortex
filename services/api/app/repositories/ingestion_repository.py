"""Ingestion ledger queries: batches, source rows, provenance.

Batches are always loaded with their workspace. Rows are loaded through a
batch that was itself loaded that way, or joined to it.
"""

from collections.abc import Collection, Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import BatchStatus, IngestionEntityType, RowStatus
from app.models.ingestion import IngestionBatch, IngestionRow
from app.repositories._pagination import fetch_page


def get_by_id(session: Session, workspace_id: UUID, batch_id: UUID) -> IngestionBatch | None:
    return session.scalar(
        select(IngestionBatch).where(
            IngestionBatch.workspace_id == workspace_id, IngestionBatch.id == batch_id
        )
    )


def lock_for_commit(session: Session, workspace_id: UUID, batch_id: UUID) -> IngestionBatch | None:
    """Load the batch and lock its row until the transaction ends.

    A second commit request for the same batch waits here, then sees the state
    the first one left behind. This lock is what keeps a batch from being
    committed twice.
    """
    return session.scalar(
        select(IngestionBatch)
        .where(IngestionBatch.workspace_id == workspace_id, IngestionBatch.id == batch_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def get_by_checksum(
    session: Session,
    workspace_id: UUID,
    entity_type: IngestionEntityType,
    sha256: str,
    *,
    for_update: bool = False,
) -> IngestionBatch | None:
    """The batch that already holds these bytes for this entity type, if any.

    FAILED batches are left out: a failed batch wrote nothing canonical, and
    the same file may be submitted again as a new batch.
    """
    statement = select(IngestionBatch).where(
        IngestionBatch.workspace_id == workspace_id,
        IngestionBatch.entity_type == entity_type,
        IngestionBatch.file_sha256 == sha256,
        IngestionBatch.status != BatchStatus.FAILED,
    )
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    return session.scalar(statement)


def list_for_workspace(
    session: Session,
    workspace_id: UUID,
    *,
    limit: int,
    offset: int,
    status: BatchStatus | None = None,
    entity_type: IngestionEntityType | None = None,
) -> tuple[list[IngestionBatch], int]:
    """Batches of the workspace, newest first."""
    statement = select(IngestionBatch).where(IngestionBatch.workspace_id == workspace_id)
    if status is not None:
        statement = statement.where(IngestionBatch.status == status)
    if entity_type is not None:
        statement = statement.where(IngestionBatch.entity_type == entity_type)
    return fetch_page(
        session,
        statement,
        order_by=(IngestionBatch.created_at.desc(), IngestionBatch.id),
        limit=limit,
        offset=offset,
    )


def add_batch(session: Session, batch: IngestionBatch) -> IngestionBatch:
    session.add(batch)
    session.flush()
    return batch


def add_rows(session: Session, rows: Collection[IngestionRow]) -> None:
    session.add_all(rows)
    session.flush()


def list_rows(
    session: Session, batch_id: UUID, statuses: Collection[RowStatus] | None = None
) -> list[IngestionRow]:
    """Every row of a batch in source order, optionally restricted to some statuses."""
    statement = select(IngestionRow).where(IngestionRow.batch_id == batch_id)
    if statuses is not None:
        statement = statement.where(IngestionRow.status.in_(statuses))
    return list(session.scalars(statement.order_by(IngestionRow.row_number)))


def rows_page(
    session: Session,
    batch_id: UUID,
    *,
    limit: int,
    offset: int,
    status: RowStatus | None = None,
) -> tuple[list[IngestionRow], int]:
    statement = select(IngestionRow).where(IngestionRow.batch_id == batch_id)
    if status is not None:
        statement = statement.where(IngestionRow.status == status)
    return fetch_page(
        session, statement, order_by=(IngestionRow.row_number,), limit=limit, offset=offset
    )


def sources_for_entity(
    session: Session,
    workspace_id: UUID,
    entity_type: str,
    entity_id: UUID,
    *,
    limit: int,
    offset: int,
) -> tuple[Sequence[tuple[IngestionRow, IngestionBatch]], int]:
    """The source rows that point at one canonical record, oldest batch first."""
    conditions = (
        IngestionBatch.workspace_id == workspace_id,
        IngestionRow.canonical_entity_type == entity_type,
        IngestionRow.canonical_entity_id == entity_id,
    )
    total = session.scalar(
        select(func.count())
        .select_from(IngestionRow)
        .join(IngestionBatch, IngestionBatch.id == IngestionRow.batch_id)
        .where(*conditions)
    )
    rows = session.execute(
        select(IngestionRow, IngestionBatch)
        .join(IngestionBatch, IngestionBatch.id == IngestionRow.batch_id)
        .where(*conditions)
        .order_by(IngestionBatch.created_at, IngestionBatch.id, IngestionRow.row_number)
        .limit(limit)
        .offset(offset)
    ).all()
    return [(row, batch) for row, batch in rows], int(total or 0)


def batch_status_counts(session: Session, workspace_id: UUID) -> dict[BatchStatus, int]:
    rows = session.execute(
        select(IngestionBatch.status, func.count())
        .where(IngestionBatch.workspace_id == workspace_id)
        .group_by(IngestionBatch.status)
    )
    return {status: int(count) for status, count in rows}


def row_status_counts(session: Session, workspace_id: UUID) -> dict[RowStatus, int]:
    rows = session.execute(
        select(IngestionRow.status, func.count())
        .join(IngestionBatch, IngestionBatch.id == IngestionRow.batch_id)
        .where(IngestionBatch.workspace_id == workspace_id)
        .group_by(IngestionRow.status)
    )
    return {status: int(count) for status, count in rows}
