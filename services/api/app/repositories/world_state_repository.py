"""Read queries behind the World State projection.

Every query is scoped to one workspace. Counts are COUNTs over stored rows.
Nested collections are fetched for a whole page of parents at once (no query
per parent) and capped per parent with a window function.
"""

from collections.abc import Collection, Sequence
from typing import Any, NamedTuple
from uuid import UUID

from sqlalchemy import ColumnElement, Select, and_, exists, func, select
from sqlalchemy.orm import Session, aliased

from app.models.enums import MilestoneStatus, MilestoneType, ProcurementStatus, PurchaseOrderStatus
from app.models.equipment import Equipment
from app.models.milestone import Milestone
from app.models.milestone_plan_version import MilestonePlanVersion
from app.models.project import Project
from app.models.purchase_order import PurchaseOrder
from app.models.purchase_order_item import PurchaseOrderItem
from app.models.supplier import Supplier
from app.models.supplier_commitment_version import SupplierCommitmentVersion
from app.repositories.milestone_repository import lifecycle_order

# --- counts ---------------------------------------------------------------------------


def workspace_counts(session: Session, workspace_id: UUID) -> dict[str, int]:
    """Number of rows of each kind in the workspace, in one round trip."""

    def count(model: Any) -> Any:
        return (
            select(func.count()).select_from(model).where(model.workspace_id == workspace_id)
        ).scalar_subquery()

    plan_versions = (
        select(func.count())
        .select_from(MilestonePlanVersion)
        .join(Milestone, Milestone.id == MilestonePlanVersion.milestone_id)
        .where(Milestone.workspace_id == workspace_id)
    ).scalar_subquery()
    row = session.execute(
        select(
            count(Project).label("projects"),
            count(Supplier).label("suppliers"),
            count(Equipment).label("equipment"),
            count(PurchaseOrder).label("purchase_orders"),
            count(PurchaseOrderItem).label("purchase_order_items"),
            count(Milestone).label("milestones"),
            plan_versions.label("milestone_plan_versions"),
            count(SupplierCommitmentVersion).label("supplier_commitment_versions"),
        )
    ).one()
    return {key: int(value) for key, value in row._mapping.items()}


def project_counts(
    session: Session, workspace_id: UUID, project_ids: Collection[UUID]
) -> dict[UUID, dict[str, int]]:
    """Per project: equipment, purchase orders, line items and milestones."""
    counts: dict[UUID, dict[str, int]] = {
        project_id: {
            "equipment": 0,
            "purchase_orders": 0,
            "purchase_order_items": 0,
            "milestones": 0,
        }
        for project_id in project_ids
    }
    if not project_ids:
        return counts

    def grouped(key: str, statement: Select[UUID, int]) -> None:
        for project_id, value in session.execute(statement):
            counts[project_id][key] = int(value)

    grouped(
        "equipment",
        select(Equipment.project_id, func.count())
        .where(Equipment.workspace_id == workspace_id, Equipment.project_id.in_(project_ids))
        .group_by(Equipment.project_id),
    )
    grouped(
        "purchase_orders",
        select(PurchaseOrder.project_id, func.count())
        .where(
            PurchaseOrder.workspace_id == workspace_id, PurchaseOrder.project_id.in_(project_ids)
        )
        .group_by(PurchaseOrder.project_id),
    )
    grouped(
        "purchase_order_items",
        select(PurchaseOrderItem.project_id, func.count())
        .where(
            PurchaseOrderItem.workspace_id == workspace_id,
            PurchaseOrderItem.project_id.in_(project_ids),
        )
        .group_by(PurchaseOrderItem.project_id),
    )
    grouped(
        "milestones",
        select(PurchaseOrder.project_id, func.count())
        .select_from(Milestone)
        .join(PurchaseOrder, PurchaseOrder.id == Milestone.purchase_order_id)
        .where(Milestone.workspace_id == workspace_id, PurchaseOrder.project_id.in_(project_ids))
        .group_by(PurchaseOrder.project_id),
    )
    return counts


def project_supplier_count(session: Session, workspace_id: UUID, project_id: UUID) -> int:
    """Distinct suppliers named on the purchase orders of a project."""
    value = session.scalar(
        select(func.count(func.distinct(PurchaseOrder.supplier_id))).where(
            PurchaseOrder.workspace_id == workspace_id, PurchaseOrder.project_id == project_id
        )
    )
    return int(value or 0)


# --- nested collections, capped per parent --------------------------------------------


def _counts_by(session: Session, column: Any, *conditions: ColumnElement[bool]) -> dict[UUID, int]:
    rows = session.execute(select(column, func.count()).where(*conditions).group_by(column))
    return {key: int(value) for key, value in rows}


class OrderLink(NamedTuple):
    item: PurchaseOrderItem
    purchase_order: PurchaseOrder
    supplier: Supplier


def equipment_order_links(
    session: Session, workspace_id: UUID, equipment_ids: Collection[UUID], *, per_equipment: int
) -> tuple[dict[UUID, list[OrderLink]], dict[UUID, int]]:
    """Per equipment: the purchase orders whose line items name it, by PO number."""
    if not equipment_ids:
        return {}, {}
    conditions = (
        PurchaseOrderItem.workspace_id == workspace_id,
        PurchaseOrderItem.equipment_id.in_(equipment_ids),
    )
    rank = (
        func.row_number()
        .over(partition_by=PurchaseOrderItem.equipment_id, order_by=PurchaseOrder.po_number)
        .label("rank")
    )
    ranked = (
        select(PurchaseOrderItem.id.label("item_id"), rank)
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderItem.purchase_order_id)
        .where(*conditions)
        .subquery()
    )
    rows = session.execute(
        select(PurchaseOrderItem, PurchaseOrder, Supplier)
        .join(ranked, ranked.c.item_id == PurchaseOrderItem.id)
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderItem.purchase_order_id)
        .join(Supplier, Supplier.id == PurchaseOrder.supplier_id)
        .where(ranked.c.rank <= per_equipment)
        .order_by(PurchaseOrderItem.equipment_id, PurchaseOrder.po_number)
    )
    links: dict[UUID, list[OrderLink]] = {}
    for item, purchase_order, supplier in rows:
        links.setdefault(item.equipment_id, []).append(OrderLink(item, purchase_order, supplier))
    return links, _counts_by(session, PurchaseOrderItem.equipment_id, *conditions)


class LineItem(NamedTuple):
    item: PurchaseOrderItem
    equipment: Equipment


def line_items_for_orders(
    session: Session, workspace_id: UUID, purchase_order_ids: Collection[UUID], *, per_order: int
) -> tuple[dict[UUID, list[LineItem]], dict[UUID, int]]:
    """Per purchase order: its line items with their equipment, by equipment code."""
    if not purchase_order_ids:
        return {}, {}
    conditions = (
        PurchaseOrderItem.workspace_id == workspace_id,
        PurchaseOrderItem.purchase_order_id.in_(purchase_order_ids),
    )
    rank = (
        func.row_number()
        .over(partition_by=PurchaseOrderItem.purchase_order_id, order_by=Equipment.equipment_code)
        .label("rank")
    )
    ranked = (
        select(PurchaseOrderItem.id.label("item_id"), rank)
        .join(Equipment, Equipment.id == PurchaseOrderItem.equipment_id)
        .where(*conditions)
        .subquery()
    )
    rows = session.execute(
        select(PurchaseOrderItem, Equipment)
        .join(ranked, ranked.c.item_id == PurchaseOrderItem.id)
        .join(Equipment, Equipment.id == PurchaseOrderItem.equipment_id)
        .where(ranked.c.rank <= per_order)
        .order_by(PurchaseOrderItem.purchase_order_id, Equipment.equipment_code)
    )
    items: dict[UUID, list[LineItem]] = {}
    for item, equipment in rows:
        items.setdefault(item.purchase_order_id, []).append(LineItem(item, equipment))
    return items, _counts_by(session, PurchaseOrderItem.purchase_order_id, *conditions)


def milestones_for_orders(
    session: Session, workspace_id: UUID, purchase_order_ids: Collection[UUID], *, per_order: int
) -> tuple[dict[UUID, list[Milestone]], dict[UUID, int]]:
    """Per purchase order: its milestones in lifecycle order, then by sequence number."""
    if not purchase_order_ids:
        return {}, {}
    conditions = (
        Milestone.workspace_id == workspace_id,
        Milestone.purchase_order_id.in_(purchase_order_ids),
    )
    order = (lifecycle_order(), Milestone.sequence_no, Milestone.id)
    rank = (
        func.row_number()
        .over(partition_by=Milestone.purchase_order_id, order_by=order)
        .label("rank")
    )
    ranked = select(Milestone, rank).where(*conditions).subquery()
    milestone = aliased(Milestone, ranked)
    rows = session.scalars(
        select(milestone)
        .where(ranked.c.rank <= per_order)
        .order_by(milestone.purchase_order_id, ranked.c.rank)
    )
    grouped: dict[UUID, list[Milestone]] = {}
    for item in rows:
        grouped.setdefault(item.purchase_order_id, []).append(item)
    return grouped, _counts_by(session, Milestone.purchase_order_id, *conditions)


def recent_commitments(
    session: Session, workspace_id: UUID, purchase_order_ids: Collection[UUID], *, per_order: int
) -> dict[UUID, list[SupplierCommitmentVersion]]:
    """The latest ``per_order`` commitment versions of each purchase order, oldest first."""
    if not purchase_order_ids:
        return {}
    rank = (
        func.row_number()
        .over(
            partition_by=SupplierCommitmentVersion.purchase_order_id,
            order_by=SupplierCommitmentVersion.version_no.desc(),
        )
        .label("rank")
    )
    ranked = (
        select(SupplierCommitmentVersion, rank)
        .where(
            SupplierCommitmentVersion.workspace_id == workspace_id,
            SupplierCommitmentVersion.purchase_order_id.in_(purchase_order_ids),
        )
        .subquery()
    )
    version = aliased(SupplierCommitmentVersion, ranked)
    rows = session.scalars(
        select(version)
        .where(ranked.c.rank <= per_order)
        .order_by(version.purchase_order_id, version.version_no)
    )
    grouped: dict[UUID, list[SupplierCommitmentVersion]] = {}
    for item in rows:
        grouped.setdefault(item.purchase_order_id, []).append(item)
    return grouped


# --- missing information --------------------------------------------------------------


class MissingRecord(NamedTuple):
    entity_id: UUID
    reference: str
    project_id: UUID


def _project_filter(column: Any, project_id: UUID | None) -> ColumnElement[bool]:
    condition: ColumnElement[bool] = (
        column == project_id if project_id is not None else column.is_not(None)
    )
    return condition


# id, reference (natural key for display), project id
MissingQuery = Select[UUID, str, UUID]


def missing_information_queries(
    workspace_id: UUID, project_id: UUID | None = None
) -> dict[str, MissingQuery]:
    """One query per kind of missing information, each yielding (id, reference, project id).

    Records that are themselves cancelled are left out: nothing more is
    expected to be recorded about them.
    """
    equipment_scope = and_(
        Equipment.workspace_id == workspace_id,
        _project_filter(Equipment.project_id, project_id),
        Equipment.procurement_status != ProcurementStatus.CANCELLED,
    )
    order_scope = and_(
        PurchaseOrder.workspace_id == workspace_id,
        _project_filter(PurchaseOrder.project_id, project_id),
        PurchaseOrder.status != PurchaseOrderStatus.CANCELLED,
    )
    has_line_item_for_equipment = exists().where(PurchaseOrderItem.equipment_id == Equipment.id)
    has_line_item_for_order = exists().where(
        PurchaseOrderItem.purchase_order_id == PurchaseOrder.id
    )
    has_acknowledgement = exists().where(
        Milestone.purchase_order_id == PurchaseOrder.id,
        Milestone.milestone_type == MilestoneType.PO_ACKNOWLEDGEMENT,
        Milestone.status != MilestoneStatus.CANCELLED,
    )
    has_commitment = exists().where(SupplierCommitmentVersion.purchase_order_id == PurchaseOrder.id)
    equipment_columns = (
        Equipment.id,
        Equipment.equipment_code.label("reference"),
        Equipment.project_id,
    )
    order_columns = (
        PurchaseOrder.id,
        PurchaseOrder.po_number.label("reference"),
        PurchaseOrder.project_id,
    )
    milestone_reference = func.concat(
        PurchaseOrder.po_number, " ", Milestone.milestone_type, " #", Milestone.sequence_no
    ).label("reference")
    return {
        "EQUIPMENT_REQUIRED_DATE_NOT_RECORDED": select(*equipment_columns).where(
            equipment_scope, Equipment.required_on_site_date.is_(None)
        ),
        "EQUIPMENT_WITHOUT_PO_LINE_ITEM": select(*equipment_columns).where(
            equipment_scope, ~has_line_item_for_equipment
        ),
        "MILESTONE_COMPLETED_WITHOUT_ACTUAL_DATE": select(
            Milestone.id, milestone_reference, PurchaseOrder.project_id
        )
        .join(PurchaseOrder, PurchaseOrder.id == Milestone.purchase_order_id)
        .where(
            Milestone.workspace_id == workspace_id,
            _project_filter(PurchaseOrder.project_id, project_id),
            Milestone.status == MilestoneStatus.COMPLETED,
            Milestone.actual_date.is_(None),
        ),
        "PO_ACKNOWLEDGEMENT_NOT_RECORDED": select(*order_columns).where(
            order_scope, ~has_acknowledgement
        ),
        "PO_WITHOUT_LINE_ITEMS": select(*order_columns).where(
            order_scope, ~has_line_item_for_order
        ),
        "PO_WITHOUT_SUPPLIER_COMMITMENT": select(*order_columns).where(
            order_scope, ~has_commitment
        ),
    }


def count_of(session: Session, statement: MissingQuery) -> int:
    return int(session.scalar(select(func.count()).select_from(statement.subquery())) or 0)


def first_missing(
    session: Session, statement: MissingQuery, *, limit: int
) -> Sequence[MissingRecord]:
    """The first ``limit`` records of a missing-information query, by reference."""
    ordered = statement.subquery()
    rows = session.execute(select(ordered).order_by(ordered.c.reference, ordered.c.id).limit(limit))
    return [MissingRecord(row[0], str(row[1]), row[2]) for row in rows]
