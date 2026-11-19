"""Supplier routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import PaginationDep, SessionDep, WorkspaceDep
from app.models.enums import SupplierStatus
from app.schemas.supplier import SupplierCreate, SupplierListResponse, SupplierRead, SupplierUpdate
from app.services import supplier_service

router = APIRouter(prefix="/workspaces/{workspace_id}/suppliers", tags=["suppliers"])


@router.get("", response_model=SupplierListResponse, summary="List suppliers")
def list_suppliers(
    workspace: WorkspaceDep,
    session: SessionDep,
    page: PaginationDep,
    supplier_status: Annotated[SupplierStatus | None, Query(alias="status")] = None,
) -> SupplierListResponse:
    result = supplier_service.list_suppliers(
        session,
        workspace.workspace_id,
        limit=page.limit,
        offset=page.offset,
        status=supplier_status,
    )
    return SupplierListResponse(
        items=[SupplierRead.model_validate(item) for item in result.items],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )


@router.post(
    "",
    response_model=SupplierRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a supplier",
)
def create_supplier(
    workspace: WorkspaceDep, session: SessionDep, payload: SupplierCreate
) -> SupplierRead:
    supplier = supplier_service.create_supplier(session, workspace.workspace_id, payload)
    return SupplierRead.model_validate(supplier)


@router.get("/{supplier_id}", response_model=SupplierRead, summary="Retrieve a supplier")
def get_supplier(workspace: WorkspaceDep, session: SessionDep, supplier_id: UUID) -> SupplierRead:
    supplier = supplier_service.get_supplier(session, workspace.workspace_id, supplier_id)
    return SupplierRead.model_validate(supplier)


@router.patch("/{supplier_id}", response_model=SupplierRead, summary="Update a supplier")
def update_supplier(
    workspace: WorkspaceDep, session: SessionDep, supplier_id: UUID, payload: SupplierUpdate
) -> SupplierRead:
    supplier = supplier_service.update_supplier(
        session, workspace.workspace_id, supplier_id, payload
    )
    return SupplierRead.model_validate(supplier)
