"""Purchase-order rules and transactions: header, line items, supplier commitments.

* A purchase order and its line items are created in one transaction.
* Project, supplier and equipment must belong to the workspace; equipment must
  belong to the project of the purchase order.
* Commitment history is append-only. Version numbers are allocated while the
  purchase-order row is locked, and an unchanged date creates nothing.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.errors import ErrorDetail, NotFoundError, ValidationFailedError
from app.db.session import transaction
from app.models.enums import (
    CanonicalEntityType,
    IngestionEntityType,
    PurchaseOrderStatus,
    RowOutcome,
    SupplierStatus,
)
from app.models.equipment import Equipment
from app.models.field_policy import SOURCE_OWNED_FIELDS, changed_fields
from app.models.purchase_order import PurchaseOrder
from app.models.purchase_order_item import PurchaseOrderItem
from app.models.supplier_commitment_version import SupplierCommitmentVersion
from app.repositories import (
    equipment_repository,
    project_repository,
    purchase_order_repository,
    supplier_repository,
)
from app.schemas.purchase_order import CommitmentCreate, PurchaseOrderCreate, PurchaseOrderUpdate
from app.services import workspace_service
from app.services._support import apply_changes, duplicate_key_error, unique_key_guard
from app.services.results import Applied, Page

API_ACTOR = "api"

_HEADER_SOURCE_OWNED = SOURCE_OWNED_FIELDS[IngestionEntityType.PURCHASE_ORDER]
_ITEM_SOURCE_OWNED = SOURCE_OWNED_FIELDS[IngestionEntityType.PURCHASE_ORDER_ITEM]


@dataclass(frozen=True, slots=True)
class PurchaseOrderDetail:
    """A purchase order with supplier and line items loaded, and its current commitment."""

    purchase_order: PurchaseOrder
    current_commitment: SupplierCommitmentVersion | None


def _not_found() -> NotFoundError:
    return NotFoundError("The purchase order was not found.")


def _detail(session: Session, workspace_id: UUID, purchase_order_id: UUID) -> PurchaseOrderDetail:
    purchase_order = purchase_order_repository.get_with_items_and_supplier(
        session, workspace_id, purchase_order_id
    )
    if purchase_order is None:
        raise _not_found()
    return PurchaseOrderDetail(
        purchase_order=purchase_order,
        current_commitment=purchase_order_repository.latest_commitment(
            session, workspace_id, purchase_order_id
        ),
    )


def _validate_new_purchase_order(
    session: Session, workspace_id: UUID, payload: PurchaseOrderCreate
) -> dict[UUID, Equipment]:
    """Check every reference of the request. Raises with all problems at once."""
    problems: list[ErrorDetail] = []

    if project_repository.get_by_id(session, workspace_id, payload.project_id) is None:
        problems.append(
            ErrorDetail(
                code="REFERENCE_NOT_FOUND",
                message="The project does not exist in this workspace.",
                field="project_id",
            )
        )

    supplier = supplier_repository.get_by_id(session, workspace_id, payload.supplier_id)
    if supplier is None:
        problems.append(
            ErrorDetail(
                code="REFERENCE_NOT_FOUND",
                message="The supplier does not exist in this workspace.",
                field="supplier_id",
            )
        )
    elif supplier.status != SupplierStatus.ACTIVE:
        problems.append(
            ErrorDetail(
                code="REFERENCE_INACTIVE",
                message="A new purchase order cannot name an inactive supplier.",
                field="supplier_id",
            )
        )

    equipment_by_id = equipment_repository.get_by_ids(
        session, workspace_id, {item.equipment_id for item in payload.items}
    )
    seen: set[UUID] = set()
    for index, item in enumerate(payload.items):
        field = f"items.{index}.equipment_id"
        equipment = equipment_by_id.get(item.equipment_id)
        if equipment is None:
            problems.append(
                ErrorDetail(
                    code="REFERENCE_NOT_FOUND",
                    message="The equipment does not exist in this workspace.",
                    field=field,
                )
            )
        elif equipment.project_id != payload.project_id:
            problems.append(
                ErrorDetail(
                    code="CROSS_PROJECT_REFERENCE",
                    message="The equipment belongs to a different project than the purchase order.",
                    field=field,
                )
            )
        if item.equipment_id in seen:
            problems.append(
                ErrorDetail(
                    code="DUPLICATE_NATURAL_KEY",
                    message="The same equipment appears more than once in this purchase order.",
                    field=field,
                )
            )
        seen.add(item.equipment_id)

    if problems:
        raise ValidationFailedError("The supplied record is invalid.", details=problems)
    return equipment_by_id


def create_purchase_order(
    session: Session, workspace_id: UUID, payload: PurchaseOrderCreate
) -> PurchaseOrderDetail:
    """Create the header and every line item, or nothing."""
    with transaction(session):
        workspace_service.require_active_workspace(session, workspace_id)
        _validate_new_purchase_order(session, workspace_id, payload)
        if purchase_order_repository.get_by_number(session, workspace_id, payload.po_number):
            raise duplicate_key_error("purchase order", "po_number")

        purchase_order = PurchaseOrder(
            workspace_id=workspace_id,
            project_id=payload.project_id,
            supplier_id=payload.supplier_id,
            po_number=payload.po_number,
            issue_date=payload.issue_date,
            currency=payload.currency,
            total_value=payload.total_value,
            status=payload.status,
        )
        with unique_key_guard(session, "purchase order", "po_number"):
            purchase_order_repository.add(session, purchase_order)
        purchase_order_repository.add_items(
            session,
            [
                PurchaseOrderItem(
                    workspace_id=workspace_id,
                    project_id=payload.project_id,
                    purchase_order_id=purchase_order.id,
                    equipment_id=item.equipment_id,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                )
                for item in payload.items
            ],
        )
        return _detail(session, workspace_id, purchase_order.id)


def get_purchase_order(
    session: Session, workspace_id: UUID, purchase_order_id: UUID
) -> PurchaseOrderDetail:
    workspace_service.require_active_workspace(session, workspace_id)
    return _detail(session, workspace_id, purchase_order_id)


def list_purchase_orders(
    session: Session,
    workspace_id: UUID,
    *,
    limit: int,
    offset: int,
    project_id: UUID | None = None,
    supplier_id: UUID | None = None,
    status: PurchaseOrderStatus | None = None,
) -> Page[PurchaseOrder]:
    workspace_service.require_active_workspace(session, workspace_id)
    items, total = purchase_order_repository.list_for_workspace(
        session,
        workspace_id,
        limit=limit,
        offset=offset,
        project_id=project_id,
        supplier_id=supplier_id,
        status=status,
    )
    return Page(items=items, total=total, limit=limit, offset=offset)


def update_purchase_order(
    session: Session, workspace_id: UUID, purchase_order_id: UUID, patch: PurchaseOrderUpdate
) -> PurchaseOrderDetail:
    with transaction(session):
        workspace_service.require_active_workspace(session, workspace_id)
        purchase_order = purchase_order_repository.get_by_id(
            session, workspace_id, purchase_order_id
        )
        if purchase_order is None:
            raise _not_found()
        apply_changes(purchase_order, patch.changes())
        session.flush()
        return _detail(session, workspace_id, purchase_order_id)


# --- supplier commitments -------------------------------------------------------------


def record_commitment(
    session: Session,
    purchase_order: PurchaseOrder,
    *,
    committed_delivery_date: date,
    recorded_by: str,
    source_reference: str | None = None,
    source_row_id: UUID | None = None,
) -> tuple[SupplierCommitmentVersion, bool]:
    """Append a commitment version unless the date is already the current one.

    ``purchase_order`` must have been loaded with its row locked in the
    running transaction: the lock is what makes ``latest + 1`` safe. Returns
    the current version and whether it was created now. Does not commit.
    """
    latest = purchase_order_repository.latest_commitment(
        session, purchase_order.workspace_id, purchase_order.id
    )
    if latest is not None and latest.committed_delivery_date == committed_delivery_date:
        return latest, False
    version = SupplierCommitmentVersion(
        workspace_id=purchase_order.workspace_id,
        purchase_order_id=purchase_order.id,
        version_no=(latest.version_no + 1) if latest is not None else 1,
        committed_delivery_date=committed_delivery_date,
        source_reference=source_reference,
        source_ingestion_row_id=source_row_id,
        recorded_by=recorded_by,
    )
    purchase_order_repository.add_commitment(session, version)
    return version, True


def append_supplier_commitment(
    session: Session,
    workspace_id: UUID,
    purchase_order_id: UUID,
    payload: CommitmentCreate,
    source_row_id: UUID | None = None,
) -> tuple[SupplierCommitmentVersion, bool]:
    """Record a supplier commitment. Returns the current version and whether it is new."""
    with transaction(session):
        workspace_service.require_active_workspace(session, workspace_id)
        purchase_order = purchase_order_repository.lock_by_id(
            session, workspace_id, purchase_order_id
        )
        if purchase_order is None:
            raise _not_found()
        return record_commitment(
            session,
            purchase_order,
            committed_delivery_date=payload.committed_delivery_date,
            recorded_by=payload.recorded_by or API_ACTOR,
            source_reference=payload.source_reference,
            source_row_id=source_row_id,
        )


def list_supplier_commitments(
    session: Session, workspace_id: UUID, purchase_order_id: UUID, *, limit: int, offset: int
) -> Page[SupplierCommitmentVersion]:
    """Commitment history, oldest version first."""
    workspace_service.require_active_workspace(session, workspace_id)
    if purchase_order_repository.get_by_id(session, workspace_id, purchase_order_id) is None:
        raise _not_found()
    items, total = purchase_order_repository.list_commitments(
        session, workspace_id, purchase_order_id, limit=limit, offset=offset
    )
    return Page(items=items, total=total, limit=limit, offset=offset)


# --- import path: these write inside the ingestion commit and never commit themselves ---


def apply_source_record(
    session: Session,
    workspace_id: UUID,
    *,
    existing: PurchaseOrder | None,
    values: Mapping[str, Any],
) -> Applied:
    """Create the purchase-order header, or change its source-owned fields.

    ``values["project_id"]`` and ``values["supplier_id"]`` are resolved in this
    workspace. For an existing header the caller has verified they are unchanged.
    """
    if existing is None:
        purchase_order = PurchaseOrder(
            workspace_id=workspace_id,
            project_id=values["project_id"],
            supplier_id=values["supplier_id"],
            po_number=values["po_number"],
            issue_date=values.get("issue_date"),
            currency=values["currency"],
            total_value=values.get("total_value"),
            status=values["status"],
        )
        purchase_order_repository.add(session, purchase_order)
        return Applied(CanonicalEntityType.PURCHASE_ORDER, purchase_order.id, RowOutcome.CREATED)

    current = {name: getattr(existing, name) for name in _HEADER_SOURCE_OWNED}
    changed = changed_fields(current, values, _HEADER_SOURCE_OWNED)
    apply_changes(existing, {name: values[name] for name in changed})
    session.flush()
    outcome = RowOutcome.UPDATED if changed else RowOutcome.UNCHANGED
    return Applied(CanonicalEntityType.PURCHASE_ORDER, existing.id, outcome)


def apply_item_record(
    session: Session,
    *,
    existing: PurchaseOrderItem | None,
    purchase_order: PurchaseOrder,
    equipment: Equipment,
    values: Mapping[str, Any],
) -> Applied:
    """Create the line item, or change its quantity and unit price."""
    if existing is None:
        item = PurchaseOrderItem(
            workspace_id=purchase_order.workspace_id,
            project_id=purchase_order.project_id,
            purchase_order_id=purchase_order.id,
            equipment_id=equipment.id,
            quantity=values["quantity"],
            unit_price=values.get("unit_price"),
        )
        purchase_order_repository.add_items(session, [item])
        return Applied(CanonicalEntityType.PURCHASE_ORDER_ITEM, item.id, RowOutcome.CREATED)

    current = {name: getattr(existing, name) for name in _ITEM_SOURCE_OWNED}
    changed = changed_fields(current, values, _ITEM_SOURCE_OWNED)
    apply_changes(existing, {name: values[name] for name in changed})
    session.flush()
    outcome = RowOutcome.UPDATED if changed else RowOutcome.UNCHANGED
    return Applied(CanonicalEntityType.PURCHASE_ORDER_ITEM, existing.id, outcome)


def apply_commitment_record(
    session: Session,
    *,
    purchase_order: PurchaseOrder,
    values: Mapping[str, Any],
    recorded_by: str,
    source_row_id: UUID,
) -> Applied:
    """Append a commitment version for a source row; the purchase order must be locked."""
    version, created = record_commitment(
        session,
        purchase_order,
        committed_delivery_date=values["committed_delivery_date"],
        recorded_by=values.get("recorded_by") or recorded_by,
        source_reference=values.get("source_reference"),
        source_row_id=source_row_id,
    )
    return Applied(
        CanonicalEntityType.SUPPLIER_COMMITMENT_VERSION,
        version.id,
        RowOutcome.CREATED if created else RowOutcome.UNCHANGED,
        versions_created=1 if created else 0,
    )
