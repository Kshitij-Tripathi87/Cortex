"""World State response contracts (docs/architecture/world-state-contract.md).

Facts only. No field here is a score, a probability, a recommendation or a
comparison of two dates, and none is computed from the clock except
``generated_at``.
"""

from datetime import date, datetime
from uuid import UUID

from pydantic import Field

from app.models.enums import (
    Criticality,
    EquipmentCategory,
    MilestoneStatus,
    MilestoneType,
    ProcurementStatus,
    ProjectStatus,
    PurchaseOrderStatus,
    QualityDimension,
    WorkspaceStatus,
)
from app.schemas.common import Money, Page, Quantity, ResponseModel
from app.schemas.equipment import EquipmentSpecification
from app.schemas.supplier import SupplierSummary

# --- data quality ---------------------------------------------------------------------


class QualityWarning(ResponseModel):
    """Something that is not recorded. A statement about the data, not about a party."""

    dimension: QualityDimension
    code: str
    entity_type: str
    entity_id: UUID
    reference: str = Field(description="Natural key of the record, for display.")
    project_id: UUID
    message: str


class RecordQuality(ResponseModel):
    warning_counts: dict[str, int] = Field(
        description="Complete count per warning code. Codes without occurrences are omitted."
    )
    warnings: list[QualityWarning] = Field(
        description="At most 100 warnings, ordered by code, then by reference."
    )
    warnings_truncated: bool


class IngestionLedgerSummary(ResponseModel):
    batches: dict[str, int] = Field(description="Ingestion batches by status.")
    rows: dict[str, int] = Field(description="Source rows by status.")


class WorkspaceQuality(RecordQuality):
    valid_records: int = Field(description="Source rows that are VALID, COMMITTED or SKIPPED.")
    invalid_records: int = Field(description="Source rows that are INVALID or FAILED.")
    ingestion: IngestionLedgerSummary


# --- workspace level ------------------------------------------------------------------


class WorkspaceCounts(ResponseModel):
    """Number of stored rows of each kind in the workspace, whatever their status."""

    projects: int
    suppliers: int
    equipment: int
    purchase_orders: int
    purchase_order_items: int
    milestones: int
    milestone_plan_versions: int
    supplier_commitment_versions: int


class WorldStateSummary(ResponseModel):
    workspace_id: UUID
    generated_at: datetime
    summary: WorkspaceCounts
    data_quality: WorkspaceQuality


class WorkspaceIdentity(ResponseModel):
    id: UUID
    name: str
    slug: str
    status: WorkspaceStatus


class ProjectCounts(ResponseModel):
    equipment: int
    purchase_orders: int
    purchase_order_items: int
    milestones: int


class ProjectOverview(ResponseModel):
    id: UUID
    code: str
    name: str
    location: str | None
    status: ProjectStatus
    target_completion_date: date | None
    counts: ProjectCounts


class ProjectOverviewPage(Page[ProjectOverview]):
    """Projects ordered by code."""


class WorkspaceWorldState(WorldStateSummary):
    workspace: WorkspaceIdentity
    projects: ProjectOverviewPage


# --- project level --------------------------------------------------------------------


class ProjectIdentity(ResponseModel):
    id: UUID
    code: str
    name: str
    location: str | None
    status: ProjectStatus
    target_completion_date: date | None


class ProjectSummaryCounts(ProjectCounts):
    suppliers: int = Field(description="Distinct suppliers named on the project's purchase orders.")


class EquipmentOrderLink(ResponseModel):
    """A purchase order whose line item names the equipment, with its supplier."""

    purchase_order_id: UUID
    po_number: str
    purchase_order_item_id: UUID
    quantity: Quantity
    supplier: SupplierSummary


class EquipmentState(ResponseModel):
    id: UUID
    equipment_code: str
    name: str
    category: EquipmentCategory
    criticality: Criticality
    procurement_status: ProcurementStatus
    required_on_site_date: date | None
    specification: EquipmentSpecification | None
    purchase_order_count: int
    purchase_orders: list[EquipmentOrderLink] = Field(
        description=(
            "Empty when no purchase order line item names the equipment. No supplier is "
            "inferred. At most the first 20; purchase_order_count is the total."
        )
    )


class EquipmentStatePage(Page[EquipmentState]):
    """Equipment ordered by equipment code."""


class LineItemState(ResponseModel):
    id: UUID
    equipment_id: UUID
    equipment_code: str
    equipment_name: str
    quantity: Quantity
    unit_price: Money | None


class PlanVersionState(ResponseModel):
    version_no: int
    planned_date: date
    recorded_at: datetime
    recorded_by: str
    source_ingestion_row_id: UUID | None


class MilestoneState(ResponseModel):
    id: UUID
    milestone_type: MilestoneType
    sequence_no: int
    status: MilestoneStatus
    actual_date: date | None = Field(
        description="Null until an actual completion date is recorded. Never compared to the plan."
    )
    plan_version_count: int
    current_plan: PlanVersionState | None = Field(
        description="The plan version with the greatest version number."
    )
    plan_history: list[PlanVersionState] | None = Field(
        description="Null unless include_history is set; then oldest first, latest 50 versions."
    )


class CommitmentVersionState(ResponseModel):
    version_no: int
    committed_delivery_date: date
    source_reference: str | None
    recorded_at: datetime
    recorded_by: str
    source_ingestion_row_id: UUID | None


class PurchaseOrderState(ResponseModel):
    id: UUID
    po_number: str
    status: PurchaseOrderStatus
    issue_date: date | None
    currency: str
    total_value: Money | None
    supplier: SupplierSummary
    line_item_count: int
    line_items: list[LineItemState] = Field(
        description="Ordered by equipment code; at most the first 200."
    )
    milestone_count: int
    milestones: list[MilestoneState] = Field(
        description="Lifecycle order of the type, then sequence number; at most the first 200."
    )
    commitment_version_count: int
    current_commitment: CommitmentVersionState | None = Field(
        description="The commitment with the greatest version number; null when none is recorded."
    )
    commitment_history: list[CommitmentVersionState] | None = Field(
        description="Null unless include_history is set; then oldest first, latest 50 versions."
    )


class PurchaseOrderStatePage(Page[PurchaseOrderState]):
    """Purchase orders ordered by PO number."""


class ProjectWorldState(ResponseModel):
    workspace_id: UUID
    generated_at: datetime
    project: ProjectIdentity
    summary: ProjectSummaryCounts
    equipment: EquipmentStatePage
    purchase_orders: PurchaseOrderStatePage
    data_quality: RecordQuality
