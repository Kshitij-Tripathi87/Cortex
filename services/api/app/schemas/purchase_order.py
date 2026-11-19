"""Purchase-order, line-item and supplier-commitment contracts."""

from datetime import date, datetime
from typing import ClassVar
from uuid import UUID

from pydantic import Field

from app.models.enums import PurchaseOrderStatus
from app.schemas.common import (
    ActorText,
    CurrencyCode,
    IsoDate,
    Money,
    Page,
    PatchModel,
    PoNumberText,
    Quantity,
    RequestModel,
    ResponseModel,
    SourceReferenceText,
)
from app.schemas.supplier import SupplierSummary

MAX_ITEMS_PER_REQUEST = 500


class PurchaseOrderItemCreate(RequestModel):
    equipment_id: UUID
    quantity: Quantity
    unit_price: Money | None = None


class PurchaseOrderCreate(RequestModel):
    """A purchase order and its line items, created together or not at all."""

    project_id: UUID
    supplier_id: UUID
    po_number: PoNumberText
    currency: CurrencyCode
    status: PurchaseOrderStatus = PurchaseOrderStatus.DRAFT
    issue_date: IsoDate | None = None
    total_value: Money | None = None
    items: list[PurchaseOrderItemCreate] = Field(
        default_factory=list, max_length=MAX_ITEMS_PER_REQUEST
    )


class PurchaseOrderUpdate(PatchModel):
    """PO number, project and supplier are fixed after creation."""

    not_nullable: ClassVar[frozenset[str]] = frozenset({"currency", "status"})

    issue_date: IsoDate | None = None
    currency: CurrencyCode | None = None
    total_value: Money | None = None
    status: PurchaseOrderStatus | None = None


class PurchaseOrderRead(ResponseModel):
    id: UUID
    workspace_id: UUID
    project_id: UUID
    supplier_id: UUID
    po_number: str
    issue_date: date | None
    currency: str
    total_value: Money | None
    status: PurchaseOrderStatus
    created_at: datetime
    updated_at: datetime


class PurchaseOrderItemRead(ResponseModel):
    id: UUID
    equipment_id: UUID
    equipment_code: str
    equipment_name: str
    quantity: Quantity
    unit_price: Money | None
    created_at: datetime
    updated_at: datetime


class CommitmentCreate(RequestModel):
    committed_delivery_date: IsoDate
    recorded_by: ActorText | None = None
    source_reference: SourceReferenceText | None = None


class CommitmentRead(ResponseModel):
    id: UUID
    purchase_order_id: UUID
    version_no: int
    committed_delivery_date: date
    source_reference: str | None
    recorded_at: datetime
    recorded_by: str
    source_ingestion_row_id: UUID | None


class PurchaseOrderDetail(PurchaseOrderRead):
    supplier: SupplierSummary
    items: list[PurchaseOrderItemRead]
    current_commitment: CommitmentRead | None = Field(
        description="The commitment version with the greatest version number, if any."
    )


class PurchaseOrderListResponse(Page[PurchaseOrderRead]):
    """Purchase orders ordered by PO number."""


class CommitmentListResponse(Page[CommitmentRead]):
    """Commitment history, oldest version first."""
