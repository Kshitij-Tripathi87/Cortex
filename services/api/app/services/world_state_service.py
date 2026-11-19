"""World State: what the workspace knows, read back in one piece.

A projection of rows in PostgreSQL, assembled on every call. Nothing is stored
for it and nothing is cached, so it cannot drift from the records.

* Every query is scoped to the workspace.
* All queries of one call run in one read-only REPEATABLE READ transaction:
  counts and lists describe the same instant.
* Collections are paged or capped, and ordered deterministically.
* Facts only. Nothing here compares two dates, rates a record or recommends
  anything, and the clock is read once, for ``generated_at``.
"""

from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.errors import NotFoundError
from app.db.session import read_snapshot
from app.models.equipment import Equipment
from app.models.milestone import Milestone
from app.models.milestone_plan_version import MilestonePlanVersion
from app.models.purchase_order import PurchaseOrder
from app.models.supplier import Supplier
from app.models.supplier_commitment_version import SupplierCommitmentVersion
from app.repositories import (
    equipment_repository,
    milestone_repository,
    project_repository,
    purchase_order_repository,
    supplier_repository,
    world_state_repository,
)
from app.repositories.world_state_repository import LineItem, OrderLink
from app.schemas.equipment import EquipmentSpecification
from app.schemas.supplier import SupplierSummary
from app.schemas.world_state import (
    CommitmentVersionState,
    EquipmentOrderLink,
    EquipmentState,
    EquipmentStatePage,
    IngestionLedgerSummary,
    LineItemState,
    MilestoneState,
    PlanVersionState,
    ProjectCounts,
    ProjectIdentity,
    ProjectOverview,
    ProjectOverviewPage,
    ProjectSummaryCounts,
    ProjectWorldState,
    PurchaseOrderState,
    PurchaseOrderStatePage,
    QualityWarning,
    RecordQuality,
    WorkspaceCounts,
    WorkspaceIdentity,
    WorkspaceQuality,
    WorkspaceWorldState,
    WorldStateSummary,
)
from app.services import data_quality_service, workspace_service
from app.services.data_quality_service import RecordQualityReport

# Caps of the nested collections. Each has a count beside it in the response,
# so a shortened list is visible as such.
EQUIPMENT_ORDER_LINK_LIMIT = 20
LINE_ITEM_LIMIT = 200
MILESTONE_LIMIT = 200
HISTORY_LIMIT = 50


# --- assembly: pure functions from records to the response shapes ----------------------


def _warnings(report: RecordQualityReport) -> list[QualityWarning]:
    return [
        QualityWarning(
            dimension=warning.dimension,
            code=warning.code,
            entity_type=warning.entity_type,
            entity_id=warning.entity_id,
            reference=warning.reference,
            project_id=warning.project_id,
            message=warning.message,
        )
        for warning in report.warnings
    ]


def record_quality_state(report: RecordQualityReport) -> RecordQuality:
    return RecordQuality(
        warning_counts=dict(report.warning_counts),
        warnings=_warnings(report),
        warnings_truncated=report.truncated,
    )


def plan_version_state(version: MilestonePlanVersion) -> PlanVersionState:
    return PlanVersionState.model_validate(version)


def commitment_state(version: SupplierCommitmentVersion) -> CommitmentVersionState:
    return CommitmentVersionState.model_validate(version)


def equipment_state(
    equipment: Equipment, links: Sequence[OrderLink], purchase_order_count: int
) -> EquipmentState:
    """One piece of equipment with the purchase orders that name it.

    No link means no purchase order line item is recorded: the list is empty
    and no supplier is made up.
    """
    return EquipmentState(
        id=equipment.id,
        equipment_code=equipment.equipment_code,
        name=equipment.name,
        category=equipment.category,
        criticality=equipment.criticality,
        procurement_status=equipment.procurement_status,
        required_on_site_date=equipment.required_on_site_date,
        specification=(
            EquipmentSpecification.model_validate(equipment.specification)
            if equipment.specification
            else None
        ),
        purchase_order_count=purchase_order_count,
        purchase_orders=[
            EquipmentOrderLink(
                purchase_order_id=link.purchase_order.id,
                po_number=link.purchase_order.po_number,
                purchase_order_item_id=link.item.id,
                quantity=link.item.quantity,
                supplier=SupplierSummary.model_validate(link.supplier),
            )
            for link in links
        ],
    )


def milestone_state(
    milestone: Milestone,
    current_plan: MilestonePlanVersion | None,
    plan_version_count: int,
    plan_history: Sequence[MilestonePlanVersion] | None,
) -> MilestoneState:
    """A milestone with its plan and its actual state, side by side and uncompared."""
    return MilestoneState(
        id=milestone.id,
        milestone_type=milestone.milestone_type,
        sequence_no=milestone.sequence_no,
        status=milestone.status,
        actual_date=milestone.actual_date,
        plan_version_count=plan_version_count,
        current_plan=plan_version_state(current_plan) if current_plan is not None else None,
        plan_history=(
            [plan_version_state(version) for version in plan_history]
            if plan_history is not None
            else None
        ),
    )


def purchase_order_state(
    purchase_order: PurchaseOrder,
    supplier: Supplier,
    *,
    line_items: Sequence[LineItem],
    line_item_count: int,
    milestones: Sequence[MilestoneState],
    milestone_count: int,
    current_commitment: SupplierCommitmentVersion | None,
    commitment_version_count: int,
    commitment_history: Sequence[SupplierCommitmentVersion] | None,
) -> PurchaseOrderState:
    return PurchaseOrderState(
        id=purchase_order.id,
        po_number=purchase_order.po_number,
        status=purchase_order.status,
        issue_date=purchase_order.issue_date,
        currency=purchase_order.currency,
        total_value=purchase_order.total_value,
        supplier=SupplierSummary.model_validate(supplier),
        line_item_count=line_item_count,
        line_items=[
            LineItemState(
                id=line.item.id,
                equipment_id=line.equipment.id,
                equipment_code=line.equipment.equipment_code,
                equipment_name=line.equipment.name,
                quantity=line.item.quantity,
                unit_price=line.item.unit_price,
            )
            for line in line_items
        ],
        milestone_count=milestone_count,
        milestones=list(milestones),
        commitment_version_count=commitment_version_count,
        current_commitment=(
            commitment_state(current_commitment) if current_commitment is not None else None
        ),
        commitment_history=(
            [commitment_state(version) for version in commitment_history]
            if commitment_history is not None
            else None
        ),
    )


# --- queries + assembly ---------------------------------------------------------------


def _workspace_quality(session: Session, workspace_id: UUID) -> WorkspaceQuality:
    records = data_quality_service.record_quality(session, workspace_id)
    ledger = data_quality_service.ledger_quality(session, workspace_id)
    return WorkspaceQuality(
        valid_records=ledger.valid_records,
        invalid_records=ledger.invalid_records,
        ingestion=IngestionLedgerSummary(batches=ledger.batches, rows=ledger.rows),
        warning_counts=dict(records.warning_counts),
        warnings=_warnings(records),
        warnings_truncated=records.truncated,
    )


def _summary(session: Session, workspace_id: UUID) -> WorldStateSummary:
    return WorldStateSummary(
        workspace_id=workspace_id,
        generated_at=utcnow(),
        summary=WorkspaceCounts(**world_state_repository.workspace_counts(session, workspace_id)),
        data_quality=_workspace_quality(session, workspace_id),
    )


def get_workspace_world_state_summary(session: Session, workspace_id: UUID) -> WorldStateSummary:
    """Counts and data quality of the workspace, from the database as it is now."""
    with read_snapshot(session):
        workspace_service.require_active_workspace(session, workspace_id)
        return _summary(session, workspace_id)


def get_workspace_world_state(
    session: Session, workspace_id: UUID, *, limit: int = 50, offset: int = 0
) -> WorkspaceWorldState:
    """The summary plus the workspace and one page of its projects."""
    with read_snapshot(session):
        workspace = workspace_service.require_active_workspace(session, workspace_id)
        summary = _summary(session, workspace_id)
        projects, total = project_repository.list_for_workspace(
            session, workspace_id, limit=limit, offset=offset
        )
        counts = world_state_repository.project_counts(
            session, workspace_id, [project.id for project in projects]
        )
        return WorkspaceWorldState(
            workspace_id=workspace_id,
            generated_at=summary.generated_at,
            summary=summary.summary,
            data_quality=summary.data_quality,
            workspace=WorkspaceIdentity.model_validate(workspace),
            projects=ProjectOverviewPage(
                items=[
                    ProjectOverview(
                        id=project.id,
                        code=project.code,
                        name=project.name,
                        location=project.location,
                        status=project.status,
                        target_completion_date=project.target_completion_date,
                        counts=ProjectCounts(**counts[project.id]),
                    )
                    for project in projects
                ],
                total=total,
                limit=limit,
                offset=offset,
            ),
        )


def _equipment_page(
    session: Session, workspace_id: UUID, project_id: UUID, *, limit: int, offset: int
) -> EquipmentStatePage:
    equipment, total = equipment_repository.list_for_workspace(
        session, workspace_id, limit=limit, offset=offset, project_id=project_id
    )
    links, link_counts = world_state_repository.equipment_order_links(
        session,
        workspace_id,
        [item.id for item in equipment],
        per_equipment=EQUIPMENT_ORDER_LINK_LIMIT,
    )
    return EquipmentStatePage(
        items=[
            equipment_state(item, links.get(item.id, []), link_counts.get(item.id, 0))
            for item in equipment
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


def _milestone_states(
    session: Session, milestones: Mapping[UUID, Sequence[Milestone]], *, include_history: bool
) -> dict[UUID, list[MilestoneState]]:
    """Milestone states per purchase order, with three queries for all of them."""
    ids = [milestone.id for group in milestones.values() for milestone in group]
    current = milestone_repository.latest_plan_versions(session, ids)
    counts = milestone_repository.plan_version_counts(session, ids)
    history = (
        milestone_repository.recent_plan_versions(session, ids, per_milestone=HISTORY_LIMIT)
        if include_history
        else None
    )
    return {
        purchase_order_id: [
            milestone_state(
                milestone,
                current.get(milestone.id),
                counts.get(milestone.id, 0),
                history.get(milestone.id, []) if history is not None else None,
            )
            for milestone in group
        ]
        for purchase_order_id, group in milestones.items()
    }


def _purchase_order_page(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    *,
    limit: int,
    offset: int,
    include_history: bool,
) -> PurchaseOrderStatePage:
    orders, total = purchase_order_repository.list_for_workspace(
        session, workspace_id, limit=limit, offset=offset, project_id=project_id
    )
    order_ids = [order.id for order in orders]
    suppliers = supplier_repository.get_by_ids(
        session, workspace_id, {order.supplier_id for order in orders}
    )
    line_items, line_item_counts = world_state_repository.line_items_for_orders(
        session, workspace_id, order_ids, per_order=LINE_ITEM_LIMIT
    )
    milestones, milestone_counts = world_state_repository.milestones_for_orders(
        session, workspace_id, order_ids, per_order=MILESTONE_LIMIT
    )
    milestone_states = _milestone_states(session, milestones, include_history=include_history)
    current_commitments = purchase_order_repository.latest_commitments(
        session, workspace_id, order_ids
    )
    commitment_counts = purchase_order_repository.commitment_counts(
        session, workspace_id, order_ids
    )
    commitment_history = (
        world_state_repository.recent_commitments(
            session, workspace_id, order_ids, per_order=HISTORY_LIMIT
        )
        if include_history
        else None
    )
    return PurchaseOrderStatePage(
        items=[
            purchase_order_state(
                order,
                suppliers[order.supplier_id],
                line_items=line_items.get(order.id, []),
                line_item_count=line_item_counts.get(order.id, 0),
                milestones=milestone_states.get(order.id, []),
                milestone_count=milestone_counts.get(order.id, 0),
                current_commitment=current_commitments.get(order.id),
                commitment_version_count=commitment_counts.get(order.id, 0),
                commitment_history=(
                    commitment_history.get(order.id, []) if commitment_history is not None else None
                ),
            )
            for order in orders
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


def get_project_world_state(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    *,
    equipment_limit: int = 50,
    equipment_offset: int = 0,
    po_limit: int = 50,
    po_offset: int = 0,
    include_history: bool = False,
) -> ProjectWorldState:
    """One project with its equipment, purchase orders, line items, milestones and commitments."""
    with read_snapshot(session):
        workspace_service.require_active_workspace(session, workspace_id)
        project = project_repository.get_by_id(session, workspace_id, project_id)
        if project is None:
            raise NotFoundError("The project was not found.")
        counts = world_state_repository.project_counts(session, workspace_id, [project.id])
        return ProjectWorldState(
            workspace_id=workspace_id,
            generated_at=utcnow(),
            project=ProjectIdentity.model_validate(project),
            summary=ProjectSummaryCounts(
                **counts[project.id],
                suppliers=world_state_repository.project_supplier_count(
                    session, workspace_id, project.id
                ),
            ),
            equipment=_equipment_page(
                session, workspace_id, project.id, limit=equipment_limit, offset=equipment_offset
            ),
            purchase_orders=_purchase_order_page(
                session,
                workspace_id,
                project.id,
                limit=po_limit,
                offset=po_offset,
                include_history=include_history,
            ),
            data_quality=record_quality_state(
                data_quality_service.record_quality(session, workspace_id, project.id)
            ),
        )
