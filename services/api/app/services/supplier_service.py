"""Supplier rules and transactions. No rating or reliability figure is ever produced here."""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.db.session import transaction
from app.models.enums import (
    CanonicalEntityType,
    IngestionEntityType,
    RowOutcome,
    SupplierStatus,
)
from app.models.field_policy import SOURCE_OWNED_FIELDS, changed_fields
from app.models.supplier import Supplier
from app.repositories import supplier_repository
from app.schemas.supplier import SupplierCreate, SupplierUpdate
from app.services import workspace_service
from app.services._support import apply_changes, duplicate_key_error, unique_key_guard
from app.services.results import Applied, Page

_SOURCE_OWNED = SOURCE_OWNED_FIELDS[IngestionEntityType.SUPPLIER]


def _not_found() -> NotFoundError:
    return NotFoundError("The supplier was not found.")


def create_supplier(session: Session, workspace_id: UUID, payload: SupplierCreate) -> Supplier:
    with transaction(session):
        workspace_service.require_active_workspace(session, workspace_id)
        if supplier_repository.get_by_code(session, workspace_id, payload.supplier_code):
            raise duplicate_key_error("supplier", "supplier_code")
        supplier = Supplier(
            workspace_id=workspace_id,
            supplier_code=payload.supplier_code,
            name=payload.name,
            country=payload.country,
            city=payload.city,
            status=payload.status,
        )
        with unique_key_guard(session, "supplier", "supplier_code"):
            supplier_repository.add(session, supplier)
        return supplier


def get_supplier(session: Session, workspace_id: UUID, supplier_id: UUID) -> Supplier:
    workspace_service.require_active_workspace(session, workspace_id)
    supplier = supplier_repository.get_by_id(session, workspace_id, supplier_id)
    if supplier is None:
        raise _not_found()
    return supplier


def list_suppliers(
    session: Session,
    workspace_id: UUID,
    *,
    limit: int,
    offset: int,
    status: SupplierStatus | None = None,
) -> Page[Supplier]:
    workspace_service.require_active_workspace(session, workspace_id)
    items, total = supplier_repository.list_for_workspace(
        session, workspace_id, limit=limit, offset=offset, status=status
    )
    return Page(items=items, total=total, limit=limit, offset=offset)


def update_supplier(
    session: Session, workspace_id: UUID, supplier_id: UUID, patch: SupplierUpdate
) -> Supplier:
    """Change name, location or status. INACTIVE keeps every purchase order and its history."""
    with transaction(session):
        workspace_service.require_active_workspace(session, workspace_id)
        supplier = supplier_repository.get_by_id(session, workspace_id, supplier_id)
        if supplier is None:
            raise _not_found()
        apply_changes(supplier, patch.changes())
        session.flush()
        return supplier


def apply_source_record(
    session: Session, workspace_id: UUID, *, existing: Supplier | None, values: Mapping[str, Any]
) -> Applied:
    """Create the supplier, or change its source-owned fields. Does not commit."""
    if existing is None:
        supplier = Supplier(
            workspace_id=workspace_id,
            supplier_code=values["supplier_code"],
            name=values["name"],
            country=values.get("country"),
            city=values.get("city"),
            status=values.get("status", SupplierStatus.ACTIVE),
        )
        supplier_repository.add(session, supplier)
        return Applied(CanonicalEntityType.SUPPLIER, supplier.id, RowOutcome.CREATED)

    current = {name: getattr(existing, name) for name in _SOURCE_OWNED}
    changed = changed_fields(current, values, _SOURCE_OWNED)
    apply_changes(existing, {name: values[name] for name in changed})
    session.flush()
    outcome = RowOutcome.UPDATED if changed else RowOutcome.UNCHANGED
    return Applied(CanonicalEntityType.SUPPLIER, existing.id, outcome)
