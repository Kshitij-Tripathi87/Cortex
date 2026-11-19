"""Helpers that drive the import services in tests, the way the API does."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Equipment,
    IngestionBatch,
    IngestionRow,
    Milestone,
    MilestonePlanVersion,
    Project,
    PurchaseOrder,
    PurchaseOrderItem,
    Supplier,
    SupplierCommitmentVersion,
)
from app.models.enums import IngestionEntityType
from app.services import ingestion_service
from app.services.ingestion_service import CommitResult, ImportLimits, PreviewResult, UploadedFile
from tests.factories import csv_bytes

LIMITS = ImportLimits(
    max_upload_bytes=5_000_000, max_rows=1_000, max_columns=50, max_cell_chars=500
)

CANONICAL_MODELS = (
    Project,
    Supplier,
    Equipment,
    PurchaseOrder,
    PurchaseOrderItem,
    Milestone,
    MilestonePlanVersion,
    SupplierCommitmentVersion,
)
LEDGER_MODELS = (IngestionBatch, IngestionRow)

PROJECT_HEADERS = ["Project Code", "Project Name", "Location", "Status", "Target Completion Date"]
SUPPLIER_HEADERS = ["Supplier Code", "Supplier Name", "Country", "City", "Status"]
EQUIPMENT_HEADERS = [
    "Equipment Code",
    "Project Code",
    "Equipment Name",
    "Category",
    "Required On-Site Date",
    "Criticality",
]
ORDER_HEADERS = ["PO Number", "Project Code", "Supplier Code", "Currency", "Status"]
ITEM_HEADERS = ["PO Number", "Equipment Code", "Quantity", "Unit Price"]
MILESTONE_HEADERS = [
    "PO Number",
    "Milestone Type",
    "Sequence No",
    "Planned Date",
    "Actual Date",
    "Status",
]
COMMITMENT_HEADERS = ["PO Number", "Committed Delivery Date", "Recorded By", "Source Reference"]


def table_counts(session: Session, *models: type) -> dict[str, int]:
    """Row counts straight from PostgreSQL, after ending the session's transaction."""
    session.rollback()
    return {
        model.__name__: int(session.scalar(select(func.count()).select_from(model)) or 0)
        for model in (models or CANONICAL_MODELS)
    }


class Importer:
    """Previews and commits small CSV files through the ingestion service."""

    def __init__(self, session: Session, workspace_id: UUID) -> None:
        self.session = session
        self.workspace_id = workspace_id
        self._files = 0

    def preview(
        self,
        entity_type: IngestionEntityType,
        headers: Sequence[str],
        rows: Sequence[Sequence[Any]],
        *,
        filename: str | None = None,
    ) -> PreviewResult:
        self._files += 1
        name = filename or f"{entity_type.value}_{self._files}.csv"
        upload = UploadedFile(name, "text/csv", csv_bytes(headers, rows))
        return ingestion_service.preview_import(
            self.session, self.workspace_id, upload, entity_type, limits=LIMITS
        )

    def commit(self, batch_id: UUID) -> CommitResult:
        return ingestion_service.commit_import(self.session, self.workspace_id, batch_id)

    def run(
        self,
        entity_type: IngestionEntityType,
        headers: Sequence[str],
        rows: Sequence[Sequence[Any]],
        *,
        filename: str | None = None,
    ) -> CommitResult:
        """Preview and commit a file in which every row is expected to be valid."""
        preview = self.preview(entity_type, headers, rows, filename=filename)
        assert preview.batch.invalid_rows == 0, list(preview.errors)
        return self.commit(preview.batch.id)

    def rows(self, batch_id: UUID) -> list[IngestionRow]:
        self.session.rollback()
        return list(
            self.session.scalars(
                select(IngestionRow)
                .where(IngestionRow.batch_id == batch_id)
                .order_by(IngestionRow.row_number)
                .execution_options(populate_existing=True)
            )
        )

    def batch(self, batch_id: UUID) -> IngestionBatch:
        self.session.rollback()
        batch = self.session.scalar(
            select(IngestionBatch)
            .where(IngestionBatch.id == batch_id)
            .execution_options(populate_existing=True)
        )
        assert batch is not None
        return batch


def import_small_dataset(importer: Importer) -> None:
    """One project, two suppliers, three pieces of equipment, two purchase orders.

    Everything goes through preview and commit, in dependency order.
    """
    E = IngestionEntityType
    importer.run(
        E.PROJECT, PROJECT_HEADERS, [["DC-1", "Project one", "Pune", "ACTIVE", "2027-09-30"]]
    )
    importer.run(
        E.SUPPLIER,
        SUPPLIER_HEADERS,
        [
            ["SUP-1", "Supplier one", "India", "Pune", "ACTIVE"],
            ["SUP-2", "Supplier two", "", "", ""],
        ],
    )
    importer.run(
        E.EQUIPMENT,
        EQUIPMENT_HEADERS,
        [
            ["EQ-1", "DC-1", "Transformer", "TRANSFORMER", "2027-02-01", "CRITICAL"],
            ["EQ-2", "DC-1", "UPS module", "UPS", "2026-12-15", "HIGH"],
            ["EQ-3", "DC-1", "Generator", "GENERATOR", "2027-01-18", "CRITICAL"],
        ],
    )
    importer.run(
        E.PURCHASE_ORDER,
        ORDER_HEADERS,
        [
            ["PO-1", "DC-1", "SUP-1", "INR", "ISSUED"],
            ["PO-2", "DC-1", "SUP-2", "EUR", "IN_PRODUCTION"],
        ],
    )
    importer.run(
        E.PURCHASE_ORDER_ITEM,
        ITEM_HEADERS,
        [["PO-1", "EQ-1", "1", "1000.50"], ["PO-2", "EQ-2", "2.5", "200.00"]],
    )
    importer.run(
        E.MILESTONE,
        MILESTONE_HEADERS,
        [
            ["PO-1", "PO_ACKNOWLEDGEMENT", "1", "2026-06-08", "2026-06-08", ""],
            ["PO-1", "DELIVERY", "1", "2026-12-15", "", ""],
            ["PO-2", "FACTORY_ACCEPTANCE_TEST", "1", "2026-11-10", "2026-11-14", "COMPLETED"],
        ],
    )
    importer.run(
        E.SUPPLIER_COMMITMENT,
        COMMITMENT_HEADERS,
        [["PO-1", "2026-12-15", "Procurement desk", "REF-1"], ["PO-2", "2026-11-28", "", ""]],
    )
