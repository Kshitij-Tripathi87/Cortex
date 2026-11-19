"""Supplier contracts. There is no rating or reliability field by design."""

from datetime import datetime
from typing import ClassVar
from uuid import UUID

from app.models.enums import SupplierStatus
from app.schemas.common import (
    CodeText,
    NameText,
    Page,
    PatchModel,
    PlaceText,
    RequestModel,
    ResponseModel,
)


class SupplierCreate(RequestModel):
    supplier_code: CodeText
    name: NameText
    country: PlaceText | None = None
    city: PlaceText | None = None
    status: SupplierStatus = SupplierStatus.ACTIVE


class SupplierUpdate(PatchModel):
    """The supplier code is the natural key and cannot be changed."""

    not_nullable: ClassVar[frozenset[str]] = frozenset({"name", "status"})

    name: NameText | None = None
    country: PlaceText | None = None
    city: PlaceText | None = None
    status: SupplierStatus | None = None


class SupplierRead(ResponseModel):
    id: UUID
    workspace_id: UUID
    supplier_code: str
    name: str
    country: str | None
    city: str | None
    status: SupplierStatus
    created_at: datetime
    updated_at: datetime


class SupplierSummary(ResponseModel):
    """The supplier as shown next to a purchase order."""

    id: UUID
    supplier_code: str
    name: str
    status: SupplierStatus


class SupplierListResponse(Page[SupplierRead]):
    """Suppliers ordered by supplier code."""
