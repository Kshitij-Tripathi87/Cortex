"""Deterministic factories for canonical records and source files.

Record factories write through the ORM and commit, so the data is visible to
the API under test. They exist to set a scene quickly; the behaviour of the
services is tested through the services and the API, not through these.
"""

import csv
import io
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from openpyxl import Workbook
from sqlalchemy.orm import Session

from app.models import (
    Equipment,
    Milestone,
    MilestonePlanVersion,
    Project,
    PurchaseOrder,
    PurchaseOrderItem,
    Supplier,
    SupplierCommitmentVersion,
    Workspace,
)
from app.models.enums import (
    Criticality,
    EquipmentCategory,
    MilestoneStatus,
    MilestoneType,
    ProcurementStatus,
    ProjectStatus,
    PurchaseOrderStatus,
    SupplierStatus,
    WorkspaceStatus,
)
from tests.constants import DEV_WORKSPACE_ID

TEST_ACTOR = "test"


def _save[RecordT](session: Session, record: RecordT) -> RecordT:
    session.add(record)
    session.commit()
    return record


def make_workspace(
    session: Session,
    *,
    workspace_id: UUID = DEV_WORKSPACE_ID,
    slug: str = "nexus-test",
    name: str = "Nexus Test Workspace",
    status: WorkspaceStatus = WorkspaceStatus.ACTIVE,
) -> Workspace:
    return _save(session, Workspace(id=workspace_id, slug=slug, name=name, status=status))


def make_project(
    session: Session, workspace: Workspace, *, code: str = "DC-T-001", **values: Any
) -> Project:
    fields: dict[str, Any] = {
        "name": f"Project {code}",
        "location": "Pune, Maharashtra",
        "status": ProjectStatus.ACTIVE,
        "target_completion_date": date(2027, 9, 30),
    }
    fields.update(values)
    return _save(session, Project(workspace_id=workspace.id, code=code, **fields))


def make_supplier(
    session: Session, workspace: Workspace, *, supplier_code: str = "SUP-T-001", **values: Any
) -> Supplier:
    fields: dict[str, Any] = {
        "name": f"Supplier {supplier_code}",
        "country": "India",
        "city": "Pune",
        "status": SupplierStatus.ACTIVE,
    }
    fields.update(values)
    return _save(
        session, Supplier(workspace_id=workspace.id, supplier_code=supplier_code, **fields)
    )


def make_equipment(
    session: Session, project: Project, *, equipment_code: str = "EQ-T-001", **values: Any
) -> Equipment:
    fields: dict[str, Any] = {
        "name": f"Equipment {equipment_code}",
        "category": EquipmentCategory.TRANSFORMER,
        "criticality": Criticality.CRITICAL,
        "procurement_status": ProcurementStatus.NOT_STARTED,
        "required_on_site_date": date(2027, 1, 15),
    }
    fields.update(values)
    return _save(
        session,
        Equipment(
            workspace_id=project.workspace_id,
            project_id=project.id,
            equipment_code=equipment_code,
            **fields,
        ),
    )


def make_purchase_order(
    session: Session,
    project: Project,
    supplier: Supplier,
    *,
    po_number: str = "PO-T-001",
    **values: Any,
) -> PurchaseOrder:
    fields: dict[str, Any] = {
        "currency": "INR",
        "status": PurchaseOrderStatus.ISSUED,
        "issue_date": date(2026, 6, 1),
    }
    fields.update(values)
    return _save(
        session,
        PurchaseOrder(
            workspace_id=project.workspace_id,
            project_id=project.id,
            supplier_id=supplier.id,
            po_number=po_number,
            **fields,
        ),
    )


def make_item(
    session: Session,
    purchase_order: PurchaseOrder,
    equipment: Equipment,
    *,
    quantity: Decimal = Decimal("1"),
    unit_price: Decimal | None = None,
) -> PurchaseOrderItem:
    return _save(
        session,
        PurchaseOrderItem(
            workspace_id=purchase_order.workspace_id,
            project_id=purchase_order.project_id,
            purchase_order_id=purchase_order.id,
            equipment_id=equipment.id,
            quantity=quantity,
            unit_price=unit_price,
        ),
    )


def make_milestone(
    session: Session,
    purchase_order: PurchaseOrder,
    *,
    milestone_type: MilestoneType = MilestoneType.PO_ACKNOWLEDGEMENT,
    sequence_no: int = 1,
    planned_date: date = date(2026, 6, 8),
    actual_date: date | None = None,
    status: MilestoneStatus | None = None,
) -> Milestone:
    """A milestone with plan version 1."""
    milestone = Milestone(
        workspace_id=purchase_order.workspace_id,
        purchase_order_id=purchase_order.id,
        milestone_type=milestone_type,
        sequence_no=sequence_no,
        actual_date=actual_date,
        status=status
        or (MilestoneStatus.COMPLETED if actual_date is not None else MilestoneStatus.PENDING),
    )
    session.add(milestone)
    session.flush()
    session.add(
        MilestonePlanVersion(
            milestone_id=milestone.id,
            version_no=1,
            planned_date=planned_date,
            recorded_by=TEST_ACTOR,
        )
    )
    session.commit()
    return milestone


def make_commitment(
    session: Session,
    purchase_order: PurchaseOrder,
    *,
    committed_delivery_date: date,
    version_no: int = 1,
) -> SupplierCommitmentVersion:
    return _save(
        session,
        SupplierCommitmentVersion(
            workspace_id=purchase_order.workspace_id,
            purchase_order_id=purchase_order.id,
            version_no=version_no,
            committed_delivery_date=committed_delivery_date,
            recorded_by=TEST_ACTOR,
        ),
    )


# --- source files ---------------------------------------------------------------------


def csv_bytes(headers: Sequence[str], rows: Sequence[Sequence[Any]], *, bom: bool = False) -> bytes:
    """A UTF-8 CSV file as the bytes a client would upload."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(headers)
    writer.writerows(rows)
    data = buffer.getvalue().encode("utf-8")
    return (b"\xef\xbb\xbf" + data) if bom else data


def xlsx_bytes(sheets: Mapping[str, Sequence[Sequence[Any]]]) -> bytes:
    """An XLSX workbook with the given sheets (name -> rows, first row = header)."""
    workbook = Workbook()
    default = workbook.active
    assert default is not None
    workbook.remove(default)
    for name, rows in sheets.items():
        sheet = workbook.create_sheet(title=name)
        for row in rows:
            sheet.append(list(row))
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
