"""Equipment routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import PaginationDep, SessionDep, WorkspaceDep
from app.models.enums import Criticality, EquipmentCategory, ProcurementStatus
from app.schemas.equipment import (
    EquipmentCreate,
    EquipmentListResponse,
    EquipmentRead,
    EquipmentUpdate,
)
from app.services import equipment_service

router = APIRouter(prefix="/workspaces/{workspace_id}/equipment", tags=["equipment"])


@router.get("", response_model=EquipmentListResponse, summary="List equipment")
def list_equipment(
    workspace: WorkspaceDep,
    session: SessionDep,
    page: PaginationDep,
    project_id: Annotated[UUID | None, Query()] = None,
    category: Annotated[EquipmentCategory | None, Query()] = None,
    criticality: Annotated[Criticality | None, Query()] = None,
    procurement_status: Annotated[ProcurementStatus | None, Query()] = None,
) -> EquipmentListResponse:
    result = equipment_service.list_equipment(
        session,
        workspace.workspace_id,
        limit=page.limit,
        offset=page.offset,
        project_id=project_id,
        category=category,
        criticality=criticality,
        procurement_status=procurement_status,
    )
    return EquipmentListResponse(
        items=[EquipmentRead.model_validate(item) for item in result.items],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )


@router.post(
    "",
    response_model=EquipmentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create equipment",
)
def create_equipment(
    workspace: WorkspaceDep, session: SessionDep, payload: EquipmentCreate
) -> EquipmentRead:
    equipment = equipment_service.create_equipment(session, workspace.workspace_id, payload)
    return EquipmentRead.model_validate(equipment)


@router.get("/{equipment_id}", response_model=EquipmentRead, summary="Retrieve equipment")
def get_equipment(
    workspace: WorkspaceDep, session: SessionDep, equipment_id: UUID
) -> EquipmentRead:
    equipment = equipment_service.get_equipment(session, workspace.workspace_id, equipment_id)
    return EquipmentRead.model_validate(equipment)


@router.patch("/{equipment_id}", response_model=EquipmentRead, summary="Update equipment")
def update_equipment(
    workspace: WorkspaceDep, session: SessionDep, equipment_id: UUID, payload: EquipmentUpdate
) -> EquipmentRead:
    equipment = equipment_service.update_equipment(
        session, workspace.workspace_id, equipment_id, payload
    )
    return EquipmentRead.model_validate(equipment)
