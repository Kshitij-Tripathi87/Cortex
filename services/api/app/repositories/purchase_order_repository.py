"""Purchase-order, line-item and commitment queries, scoped to one workspace."""

from collections.abc import Collection
from uuid import UUID

from sqlalchemy import func, select, tuple_
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models.enums import PurchaseOrderStatus
from app.models.purchase_order import PurchaseOrder
from app.models.purchase_order_item import PurchaseOrderItem
from app.models.supplier_commitment_version import SupplierCommitmentVersion
from app.repositories._pagination import fetch_page

# --- purchase orders ------------------------------------------------------------------


def get_by_id(
    session: Session, workspace_id: UUID, purchase_order_id: UUID
) -> PurchaseOrder | None:
    return session.scalar(
        select(PurchaseOrder).where(
            PurchaseOrder.workspace_id == workspace_id, PurchaseOrder.id == purchase_order_id
        )
    )


def lock_by_id(
    session: Session, workspace_id: UUID, purchase_order_id: UUID
) -> PurchaseOrder | None:
    """Load the purchase order and lock its row until the transaction ends.

    Serialises writers that allocate the next commitment version.
    """
    return session.scalar(
        select(PurchaseOrder)
        .where(PurchaseOrder.workspace_id == workspace_id, PurchaseOrder.id == purchase_order_id)
        .with_for_update()
    )


def get_by_number(session: Session, workspace_id: UUID, po_number: str) -> PurchaseOrder | None:
    return session.scalar(
        select(PurchaseOrder).where(
            PurchaseOrder.workspace_id == workspace_id, PurchaseOrder.po_number == po_number
        )
    )


def get_by_numbers(
    session: Session, workspace_id: UUID, numbers: Collection[str], *, for_update: bool = False
) -> dict[str, PurchaseOrder]:
    if not numbers:
        return {}
    statement = (
        select(PurchaseOrder)
        .where(PurchaseOrder.workspace_id == workspace_id, PurchaseOrder.po_number.in_(numbers))
        .order_by(PurchaseOrder.po_number)
    )
    if for_update:
        statement = statement.with_for_update()
    return {order.po_number: order for order in session.scalars(statement)}


def get_with_items_and_supplier(
    session: Session, workspace_id: UUID, purchase_order_id: UUID
) -> PurchaseOrder | None:
    """The purchase order with its supplier and its line items (and their equipment) loaded."""
    return session.scalar(
        select(PurchaseOrder)
        .where(PurchaseOrder.workspace_id == workspace_id, PurchaseOrder.id == purchase_order_id)
        .options(
            joinedload(PurchaseOrder.supplier),
            selectinload(PurchaseOrder.items).joinedload(PurchaseOrderItem.equipment),
        )
        .execution_options(populate_existing=True)
    )


def list_for_workspace(
    session: Session,
    workspace_id: UUID,
    *,
    limit: int,
    offset: int,
    project_id: UUID | None = None,
    supplier_id: UUID | None = None,
    status: PurchaseOrderStatus | None = None,
) -> tuple[list[PurchaseOrder], int]:
    statement = select(PurchaseOrder).where(PurchaseOrder.workspace_id == workspace_id)
    if project_id is not None:
        statement = statement.where(PurchaseOrder.project_id == project_id)
    if supplier_id is not None:
        statement = statement.where(PurchaseOrder.supplier_id == supplier_id)
    if status is not None:
        statement = statement.where(PurchaseOrder.status == status)
    return fetch_page(
        session,
        statement,
        order_by=(PurchaseOrder.po_number, PurchaseOrder.id),
        limit=limit,
        offset=offset,
    )


def add(session: Session, purchase_order: PurchaseOrder) -> PurchaseOrder:
    session.add(purchase_order)
    session.flush()
    return purchase_order


# --- line items -----------------------------------------------------------------------


def add_items(session: Session, items: Collection[PurchaseOrderItem]) -> None:
    session.add_all(items)
    session.flush()


def get_items_by_pairs(
    session: Session,
    workspace_id: UUID,
    pairs: Collection[tuple[UUID, UUID]],
    *,
    for_update: bool = False,
) -> dict[tuple[UUID, UUID], PurchaseOrderItem]:
    """Line items for the given (purchase order id, equipment id) pairs."""
    if not pairs:
        return {}
    statement = (
        select(PurchaseOrderItem)
        .where(
            PurchaseOrderItem.workspace_id == workspace_id,
            tuple_(PurchaseOrderItem.purchase_order_id, PurchaseOrderItem.equipment_id).in_(pairs),
        )
        .order_by(PurchaseOrderItem.purchase_order_id, PurchaseOrderItem.equipment_id)
    )
    if for_update:
        statement = statement.with_for_update()
    return {
        (item.purchase_order_id, item.equipment_id): item for item in session.scalars(statement)
    }


# --- supplier commitments -------------------------------------------------------------


def latest_commitment(
    session: Session, workspace_id: UUID, purchase_order_id: UUID
) -> SupplierCommitmentVersion | None:
    """The current commitment: the version with the greatest version number."""
    return session.scalar(
        select(SupplierCommitmentVersion)
        .where(
            SupplierCommitmentVersion.workspace_id == workspace_id,
            SupplierCommitmentVersion.purchase_order_id == purchase_order_id,
        )
        .order_by(SupplierCommitmentVersion.version_no.desc())
        .limit(1)
    )


def latest_commitments(
    session: Session, workspace_id: UUID, purchase_order_ids: Collection[UUID]
) -> dict[UUID, SupplierCommitmentVersion]:
    """The current commitment of each given purchase order, in one query."""
    if not purchase_order_ids:
        return {}
    statement = (
        select(SupplierCommitmentVersion)
        .where(
            SupplierCommitmentVersion.workspace_id == workspace_id,
            SupplierCommitmentVersion.purchase_order_id.in_(purchase_order_ids),
        )
        .ext(distinct_on(SupplierCommitmentVersion.purchase_order_id))
        .order_by(
            SupplierCommitmentVersion.purchase_order_id, SupplierCommitmentVersion.version_no.desc()
        )
    )
    return {version.purchase_order_id: version for version in session.scalars(statement)}


def commitment_counts(
    session: Session, workspace_id: UUID, purchase_order_ids: Collection[UUID]
) -> dict[UUID, int]:
    if not purchase_order_ids:
        return {}
    rows = session.execute(
        select(SupplierCommitmentVersion.purchase_order_id, func.count())
        .where(
            SupplierCommitmentVersion.workspace_id == workspace_id,
            SupplierCommitmentVersion.purchase_order_id.in_(purchase_order_ids),
        )
        .group_by(SupplierCommitmentVersion.purchase_order_id)
    )
    return {purchase_order_id: int(count) for purchase_order_id, count in rows}


def list_commitments(
    session: Session, workspace_id: UUID, purchase_order_id: UUID, *, limit: int, offset: int
) -> tuple[list[SupplierCommitmentVersion], int]:
    """Commitment history of one purchase order, oldest version first."""
    statement = select(SupplierCommitmentVersion).where(
        SupplierCommitmentVersion.workspace_id == workspace_id,
        SupplierCommitmentVersion.purchase_order_id == purchase_order_id,
    )
    return fetch_page(
        session,
        statement,
        order_by=(SupplierCommitmentVersion.version_no,),
        limit=limit,
        offset=offset,
    )


def add_commitment(
    session: Session, version: SupplierCommitmentVersion
) -> SupplierCommitmentVersion:
    session.add(version)
    session.flush()
    return version
