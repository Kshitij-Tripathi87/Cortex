"""Equipment contracts."""

from datetime import date, datetime
from typing import ClassVar
from uuid import UUID

from pydantic import ConfigDict

from app.models.enums import Criticality, EquipmentCategory, ProcurementStatus
from app.schemas.common import (
    CodeText,
    IsoDate,
    NameText,
    Page,
    PatchModel,
    RequestModel,
    ResponseModel,
    SpecificationText,
)


class EquipmentSpecification(RequestModel):
    """Descriptive attributes of a piece of equipment. Unknown keys are rejected."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    description: SpecificationText | None = None
    manufacturer: SpecificationText | None = None
    model: SpecificationText | None = None
    notes: SpecificationText | None = None

    def as_stored(self) -> dict[str, str] | None:
        """The JSON object kept in the database: only the attributes that were given."""
        return self.model_dump(exclude_none=True) or None


class EquipmentCreate(RequestModel):
    project_id: UUID
    equipment_code: CodeText
    name: NameText
    category: EquipmentCategory
    criticality: Criticality
    procurement_status: ProcurementStatus = ProcurementStatus.NOT_STARTED
    required_on_site_date: IsoDate | None = None
    specification: EquipmentSpecification | None = None


class EquipmentUpdate(PatchModel):
    """Equipment code and project are fixed after creation."""

    not_nullable: ClassVar[frozenset[str]] = frozenset(
        {"name", "category", "criticality", "procurement_status"}
    )

    name: NameText | None = None
    category: EquipmentCategory | None = None
    criticality: Criticality | None = None
    procurement_status: ProcurementStatus | None = None
    required_on_site_date: IsoDate | None = None
    specification: EquipmentSpecification | None = None


class EquipmentRead(ResponseModel):
    id: UUID
    workspace_id: UUID
    project_id: UUID
    equipment_code: str
    name: str
    category: EquipmentCategory
    criticality: Criticality
    procurement_status: ProcurementStatus
    required_on_site_date: date | None
    specification: EquipmentSpecification | None
    created_at: datetime
    updated_at: datetime


class EquipmentListResponse(Page[EquipmentRead]):
    """Equipment ordered by equipment code."""
