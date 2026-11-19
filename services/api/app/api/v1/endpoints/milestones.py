"""Milestone routes, nested under a purchase order."""

from uuid import UUID

from fastapi import APIRouter, Response, status

from app.api.deps import PaginationDep, SessionDep, WorkspaceDep
from app.schemas.milestone import (
    MilestoneCreate,
    MilestoneListResponse,
    MilestoneRead,
    MilestoneUpdate,
    PlanVersionCreate,
    PlanVersionRead,
)
from app.services import milestone_service

router = APIRouter(
    prefix="/workspaces/{workspace_id}/purchase-orders/{po_id}/milestones", tags=["milestones"]
)


def _read(history: milestone_service.MilestoneHistory) -> MilestoneRead:
    milestone = history.milestone
    return MilestoneRead(
        id=milestone.id,
        purchase_order_id=milestone.purchase_order_id,
        milestone_type=milestone.milestone_type,
        sequence_no=milestone.sequence_no,
        status=milestone.status,
        actual_date=milestone.actual_date,
        plan_version_count=history.plan_version_count,
        current_plan=(
            PlanVersionRead.model_validate(history.current_plan)
            if history.current_plan is not None
            else None
        ),
        plan_versions=[PlanVersionRead.model_validate(item) for item in history.plan_versions],
        created_at=milestone.created_at,
        updated_at=milestone.updated_at,
    )


@router.post(
    "",
    response_model=MilestoneRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a milestone with its first plan version",
)
def create_milestone(
    workspace: WorkspaceDep, session: SessionDep, po_id: UUID, payload: MilestoneCreate
) -> MilestoneRead:
    return _read(
        milestone_service.create_milestone(session, workspace.workspace_id, po_id, payload)
    )


@router.get("", response_model=MilestoneListResponse, summary="List milestones and their plans")
def list_milestones(
    workspace: WorkspaceDep, session: SessionDep, po_id: UUID, page: PaginationDep
) -> MilestoneListResponse:
    result = milestone_service.list_milestones(
        session, workspace.workspace_id, po_id, limit=page.limit, offset=page.offset
    )
    return MilestoneListResponse(
        items=[_read(item) for item in result.items],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )


@router.get(
    "/{milestone_id}", response_model=MilestoneRead, summary="Retrieve a milestone and its plans"
)
def get_milestone(
    workspace: WorkspaceDep, session: SessionDep, po_id: UUID, milestone_id: UUID
) -> MilestoneRead:
    return _read(
        milestone_service.get_milestone_history(
            session, workspace.workspace_id, po_id, milestone_id
        )
    )


@router.patch(
    "/{milestone_id}", response_model=MilestoneRead, summary="Record actual date and status"
)
def update_milestone(
    workspace: WorkspaceDep,
    session: SessionDep,
    po_id: UUID,
    milestone_id: UUID,
    payload: MilestoneUpdate,
) -> MilestoneRead:
    return _read(
        milestone_service.record_actual_milestone(
            session, workspace.workspace_id, po_id, milestone_id, payload
        )
    )


@router.post(
    "/{milestone_id}/plan-versions",
    response_model=MilestoneRead,
    status_code=status.HTTP_201_CREATED,
    summary="Append a planned date as a new plan version",
    responses={
        status.HTTP_200_OK: {
            "model": MilestoneRead,
            "description": "The date is already the current plan; nothing was created.",
        }
    },
)
def append_plan_version(
    workspace: WorkspaceDep,
    session: SessionDep,
    po_id: UUID,
    milestone_id: UUID,
    payload: PlanVersionCreate,
    response: Response,
) -> MilestoneRead:
    history, created = milestone_service.append_plan_version(
        session,
        workspace.workspace_id,
        po_id,
        milestone_id,
        payload.planned_date,
        payload.recorded_by,
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    return _read(history)
