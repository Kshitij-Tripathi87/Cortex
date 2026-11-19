"""Purchase-order and supplier-commitment routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from app.api.deps import PaginationDep, SessionDep, WorkspaceDep
from app.models.enums import PurchaseOrderStatus
from app.schemas.purchase_order import (
    CommitmentCreate,
    CommitmentListResponse,
    CommitmentRead,
    PurchaseOrderCreate,
    PurchaseOrderDetail,
    PurchaseOrderItemRead,
    PurchaseOrderListResponse,
    PurchaseOrderRead,
    PurchaseOrderUpdate,
)
from app.schemas.supplier import SupplierSummary
from app.services import purchase_order_service

router = APIRouter(prefix="/workspaces/{workspace_id}/purchase-orders", tags=["purchase orders"])


def _detail(result: purchase_order_service.PurchaseOrderDetail) -> PurchaseOrderDetail:
    order = result.purchase_order
    header = PurchaseOrderRead.model_validate(order)
    return PurchaseOrderDetail(
        **header.model_dump(),
        supplier=SupplierSummary.model_validate(order.supplier),
        items=[
            PurchaseOrderItemRead(
                id=item.id,
                equipment_id=item.equipment_id,
                equipment_code=item.equipment.equipment_code,
                equipment_name=item.equipment.name,
                quantity=item.quantity,
                unit_price=item.unit_price,
                created_at=item.created_at,
                updated_at=item.updated_at,
            )
            for item in order.items
        ],
        current_commitment=(
            CommitmentRead.model_validate(result.current_commitment)
            if result.current_commitment is not None
            else None
        ),
    )


@router.get("", response_model=PurchaseOrderListResponse, summary="List purchase orders")
def list_purchase_orders(
    workspace: WorkspaceDep,
    session: SessionDep,
    page: PaginationDep,
    project_id: Annotated[UUID | None, Query()] = None,
    supplier_id: Annotated[UUID | None, Query()] = None,
    order_status: Annotated[PurchaseOrderStatus | None, Query(alias="status")] = None,
) -> PurchaseOrderListResponse:
    result = purchase_order_service.list_purchase_orders(
        session,
        workspace.workspace_id,
        limit=page.limit,
        offset=page.offset,
        project_id=project_id,
        supplier_id=supplier_id,
        status=order_status,
    )
    return PurchaseOrderListResponse(
        items=[PurchaseOrderRead.model_validate(item) for item in result.items],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )


@router.post(
    "",
    response_model=PurchaseOrderDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Create a purchase order with its line items",
)
def create_purchase_order(
    workspace: WorkspaceDep, session: SessionDep, payload: PurchaseOrderCreate
) -> PurchaseOrderDetail:
    return _detail(
        purchase_order_service.create_purchase_order(session, workspace.workspace_id, payload)
    )


@router.get("/{po_id}", response_model=PurchaseOrderDetail, summary="Retrieve a purchase order")
def get_purchase_order(
    workspace: WorkspaceDep, session: SessionDep, po_id: UUID
) -> PurchaseOrderDetail:
    return _detail(
        purchase_order_service.get_purchase_order(session, workspace.workspace_id, po_id)
    )


@router.patch("/{po_id}", response_model=PurchaseOrderDetail, summary="Update a purchase order")
def update_purchase_order(
    workspace: WorkspaceDep, session: SessionDep, po_id: UUID, payload: PurchaseOrderUpdate
) -> PurchaseOrderDetail:
    return _detail(
        purchase_order_service.update_purchase_order(
            session, workspace.workspace_id, po_id, payload
        )
    )


@router.post(
    "/{po_id}/commitments",
    response_model=CommitmentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Append a supplier commitment version",
    responses={
        status.HTTP_200_OK: {
            "model": CommitmentRead,
            "description": "The date is already the current commitment; nothing was created.",
        }
    },
)
def append_commitment(
    workspace: WorkspaceDep,
    session: SessionDep,
    po_id: UUID,
    payload: CommitmentCreate,
    response: Response,
) -> CommitmentRead:
    version, created = purchase_order_service.append_supplier_commitment(
        session, workspace.workspace_id, po_id, payload
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    return CommitmentRead.model_validate(version)


@router.get(
    "/{po_id}/commitments",
    response_model=CommitmentListResponse,
    summary="Retrieve the commitment history, oldest version first",
)
def list_commitments(
    workspace: WorkspaceDep, session: SessionDep, po_id: UUID, page: PaginationDep
) -> CommitmentListResponse:
    result = purchase_order_service.list_supplier_commitments(
        session, workspace.workspace_id, po_id, limit=page.limit, offset=page.offset
    )
    return CommitmentListResponse(
        items=[CommitmentRead.model_validate(item) for item in result.items],
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )
