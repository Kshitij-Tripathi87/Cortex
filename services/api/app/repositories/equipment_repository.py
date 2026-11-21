"""Equipment queries. Every function is scoped to one workspace."""

from collections.abc import Collection
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import Criticality, EquipmentCategory, ProcurementStatus
from app.models.equipment import Equipment
from app.repositories._pagination import fetch_page


def get_by_id(
    session: Session, workspace_id: UUID, equipment_id: UUID, *, for_update: bool = False
) -> Equipment | None:
    """The equipment record; with ``for_update`` its row stays locked until the transaction ends."""
    statement = select(Equipment).where(
        Equipment.workspace_id == workspace_id, Equipment.id == equipment_id
    )
    if for_update:
        statement = statement.with_for_update()
    return session.scalar(statement)


def get_by_code(session: Session, workspace_id: UUID, equipment_code: str) -> Equipment | None:
    return session.scalar(
        select(Equipment).where(
            Equipment.workspace_id == workspace_id, Equipment.equipment_code == equipment_code
        )
    )


def get_by_codes(
    session: Session, workspace_id: UUID, codes: Collection[str], *, for_update: bool = False
) -> dict[str, Equipment]:
    if not codes:
        return {}
    statement = (
        select(Equipment)
        .where(Equipment.workspace_id == workspace_id, Equipment.equipment_code.in_(codes))
        .order_by(Equipment.equipment_code)
    )
    if for_update:
        statement = statement.with_for_update()
    return {equipment.equipment_code: equipment for equipment in session.scalars(statement)}


def get_by_ids(
    session: Session, workspace_id: UUID, ids: Collection[UUID]
) -> dict[UUID, Equipment]:
    if not ids:
        return {}
    statement = select(Equipment).where(
        Equipment.workspace_id == workspace_id, Equipment.id.in_(ids)
    )
    return {equipment.id: equipment for equipment in session.scalars(statement)}


def list_for_workspace(
    session: Session,
    workspace_id: UUID,
    *,
    limit: int,
    offset: int,
    project_id: UUID | None = None,
    category: EquipmentCategory | None = None,
    criticality: Criticality | None = None,
    procurement_status: ProcurementStatus | None = None,
) -> tuple[list[Equipment], int]:
    statement = select(Equipment).where(Equipment.workspace_id == workspace_id)
    if project_id is not None:
        statement = statement.where(Equipment.project_id == project_id)
    if category is not None:
        statement = statement.where(Equipment.category == category)
    if criticality is not None:
        statement = statement.where(Equipment.criticality == criticality)
    if procurement_status is not None:
        statement = statement.where(Equipment.procurement_status == procurement_status)
    return fetch_page(
        session,
        statement,
        order_by=(Equipment.equipment_code, Equipment.id),
        limit=limit,
        offset=offset,
    )


def add(session: Session, equipment: Equipment) -> Equipment:
    session.add(equipment)
    session.flush()
    return equipment
