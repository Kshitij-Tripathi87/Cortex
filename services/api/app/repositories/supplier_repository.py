"""Supplier queries. Every function is scoped to one workspace."""

from collections.abc import Collection
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import SupplierStatus
from app.models.supplier import Supplier
from app.repositories._pagination import fetch_page


def get_by_id(
    session: Session, workspace_id: UUID, supplier_id: UUID, *, for_update: bool = False
) -> Supplier | None:
    """The supplier; with ``for_update`` its row stays locked until the transaction ends."""
    statement = select(Supplier).where(
        Supplier.workspace_id == workspace_id, Supplier.id == supplier_id
    )
    if for_update:
        statement = statement.with_for_update()
    return session.scalar(statement)


def get_by_code(session: Session, workspace_id: UUID, supplier_code: str) -> Supplier | None:
    return session.scalar(
        select(Supplier).where(
            Supplier.workspace_id == workspace_id, Supplier.supplier_code == supplier_code
        )
    )


def get_by_codes(
    session: Session, workspace_id: UUID, codes: Collection[str], *, for_update: bool = False
) -> dict[str, Supplier]:
    if not codes:
        return {}
    statement = (
        select(Supplier)
        .where(Supplier.workspace_id == workspace_id, Supplier.supplier_code.in_(codes))
        .order_by(Supplier.supplier_code)
    )
    if for_update:
        statement = statement.with_for_update()
    return {supplier.supplier_code: supplier for supplier in session.scalars(statement)}


def get_by_ids(session: Session, workspace_id: UUID, ids: Collection[UUID]) -> dict[UUID, Supplier]:
    if not ids:
        return {}
    statement = select(Supplier).where(Supplier.workspace_id == workspace_id, Supplier.id.in_(ids))
    return {supplier.id: supplier for supplier in session.scalars(statement)}


def list_for_workspace(
    session: Session,
    workspace_id: UUID,
    *,
    limit: int,
    offset: int,
    status: SupplierStatus | None = None,
) -> tuple[list[Supplier], int]:
    statement = select(Supplier).where(Supplier.workspace_id == workspace_id)
    if status is not None:
        statement = statement.where(Supplier.status == status)
    return fetch_page(
        session,
        statement,
        order_by=(Supplier.supplier_code, Supplier.id),
        limit=limit,
        offset=offset,
    )


def add(session: Session, supplier: Supplier) -> Supplier:
    session.add(supplier)
    session.flush()
    return supplier
