"""Workspace isolation at the service and repository layer.

The HTTP API of this release can address only the configured workspace, so
these tests call the services directly with two workspace ids. Workspace A
must be unable to read, list, change or reference anything of workspace B,
and must get the same answer for B's records as for records that do not
exist.
"""

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationFailedError, WorkspaceNotAvailableError
from app.models import Workspace
from app.models.enums import IngestionEntityType, MilestoneType, WorkspaceStatus
from app.repositories import (
    equipment_repository,
    ingestion_repository,
    milestone_repository,
    project_repository,
    purchase_order_repository,
    supplier_repository,
)
from app.schemas.equipment import EquipmentCreate
from app.schemas.milestone import MilestoneCreate, MilestoneUpdate
from app.schemas.project import ProjectCreate, ProjectUpdate
from app.schemas.purchase_order import (
    CommitmentCreate,
    PurchaseOrderCreate,
    PurchaseOrderItemCreate,
)
from app.schemas.supplier import SupplierUpdate
from app.services import (
    equipment_service,
    ingestion_service,
    milestone_service,
    project_service,
    purchase_order_service,
    supplier_service,
)
from app.services.ingestion_service import ImportLimits, UploadedFile
from tests import factories
from tests.factories import csv_bytes

pytestmark = pytest.mark.db

LIMITS = ImportLimits(max_upload_bytes=1_000_000, max_rows=100, max_columns=20, max_cell_chars=500)


class Tenant:
    def __init__(self, session: Session, workspace_id: UUID, slug: str, label: str) -> None:
        self.workspace = factories.make_workspace(session, workspace_id=workspace_id, slug=slug)
        self.id = self.workspace.id
        self.project = factories.make_project(session, self.workspace, code="DC-001", name=label)
        self.supplier = factories.make_supplier(
            session, self.workspace, supplier_code="SUP-001", name=label
        )
        self.equipment = factories.make_equipment(
            session, self.project, equipment_code="EQ-001", name=label
        )
        self.order = factories.make_purchase_order(
            session, self.project, self.supplier, po_number="PO-001"
        )
        self.item = factories.make_item(session, self.order, self.equipment)
        self.milestone = factories.make_milestone(session, self.order)
        self.commitment = factories.make_commitment(
            session, self.order, committed_delivery_date=date(2026, 11, 28)
        )


@pytest.fixture
def a(session: Session) -> Tenant:
    return Tenant(session, uuid4(), "tenant-a", "A")


@pytest.fixture
def b(session: Session) -> Tenant:
    return Tenant(session, uuid4(), "tenant-b", "B")


def test_lists_contain_only_the_own_workspace(session: Session, a: Tenant, b: Tenant) -> None:
    assert [
        p.id for p in project_service.list_projects(session, a.id, limit=50, offset=0).items
    ] == [a.project.id]
    assert [
        s.id for s in supplier_service.list_suppliers(session, a.id, limit=50, offset=0).items
    ] == [a.supplier.id]
    assert [
        e.id for e in equipment_service.list_equipment(session, a.id, limit=50, offset=0).items
    ] == [a.equipment.id]
    orders = purchase_order_service.list_purchase_orders(session, a.id, limit=50, offset=0)
    assert ([o.id for o in orders.items], orders.total) == ([a.order.id], 1)

    # Filtering by a foreign id finds nothing, and totals do not count foreign rows.
    foreign_filter = equipment_service.list_equipment(
        session, a.id, limit=50, offset=0, project_id=b.project.id
    )
    assert (list(foreign_filter.items), foreign_filter.total) == ([], 0)


def test_foreign_records_are_not_found_by_id(session: Session, a: Tenant, b: Tenant) -> None:
    lookups = [
        lambda: project_service.get_project(session, a.id, b.project.id),
        lambda: supplier_service.get_supplier(session, a.id, b.supplier.id),
        lambda: equipment_service.get_equipment(session, a.id, b.equipment.id),
        lambda: purchase_order_service.get_purchase_order(session, a.id, b.order.id),
        lambda: purchase_order_service.list_supplier_commitments(
            session, a.id, b.order.id, limit=50, offset=0
        ),
        lambda: milestone_service.list_milestones(session, a.id, b.order.id, limit=50, offset=0),
        lambda: milestone_service.get_milestone_history(session, a.id, b.order.id, b.milestone.id),
        # Own purchase order, foreign milestone id: still not found.
        lambda: milestone_service.get_milestone_history(session, a.id, a.order.id, b.milestone.id),
    ]
    for lookup in lookups:
        with pytest.raises(NotFoundError) as foreign:
            lookup()
        session.rollback()
        assert foreign.value.status_code == 404

    with pytest.raises(NotFoundError) as missing:
        project_service.get_project(session, a.id, uuid4())
    with pytest.raises(NotFoundError) as other:
        project_service.get_project(session, a.id, b.project.id)
    # Identical answer for "exists elsewhere" and "exists nowhere".
    assert (missing.value.code, missing.value.message) == (other.value.code, other.value.message)


def test_foreign_records_cannot_be_changed(session: Session, a: Tenant, b: Tenant) -> None:
    attempts = [
        lambda: project_service.update_project(
            session, a.id, b.project.id, ProjectUpdate(name="taken")
        ),
        lambda: supplier_service.update_supplier(
            session, a.id, b.supplier.id, SupplierUpdate(name="taken")
        ),
        lambda: purchase_order_service.append_supplier_commitment(
            session, a.id, b.order.id, CommitmentCreate(committed_delivery_date=date(2027, 1, 1))
        ),
        lambda: milestone_service.create_milestone(
            session,
            a.id,
            b.order.id,
            MilestoneCreate(milestone_type=MilestoneType.DISPATCH, planned_date=date(2027, 1, 1)),
        ),
        lambda: milestone_service.append_plan_version(
            session, a.id, b.order.id, b.milestone.id, date(2027, 1, 1)
        ),
        lambda: milestone_service.record_actual_milestone(
            session, a.id, a.order.id, b.milestone.id, MilestoneUpdate(actual_date=date(2026, 6, 9))
        ),
    ]
    for attempt in attempts:
        with pytest.raises(NotFoundError):
            attempt()
        session.rollback()

    session.expire_all()
    assert project_repository.get_by_id(session, b.id, b.project.id).name == "B"  # type: ignore[union-attr]
    assert supplier_repository.get_by_id(session, b.id, b.supplier.id).name == "B"  # type: ignore[union-attr]
    assert purchase_order_repository.latest_commitment(session, b.id, b.order.id).version_no == 1  # type: ignore[union-attr]
    assert milestone_repository.plan_version_counts(session, [b.milestone.id]) == {
        b.milestone.id: 1
    }
    assert milestone_repository.get_by_id(session, b.id, b.milestone.id).actual_date is None  # type: ignore[union-attr]


def test_foreign_records_cannot_be_referenced(session: Session, a: Tenant, b: Tenant) -> None:
    def codes(error: ValidationFailedError) -> set[tuple[str | None, str]]:
        return {(detail.field, detail.code) for detail in error.details}

    with pytest.raises(ValidationFailedError) as equipment:
        equipment_service.create_equipment(
            session,
            a.id,
            EquipmentCreate(
                project_id=b.project.id,
                equipment_code="EQ-X",
                name="x",
                category="UPS",
                criticality="LOW",
            ),
        )
    assert codes(equipment.value) == {("project_id", "REFERENCE_NOT_FOUND")}

    with pytest.raises(ValidationFailedError) as order:
        purchase_order_service.create_purchase_order(
            session,
            a.id,
            PurchaseOrderCreate(
                project_id=b.project.id,
                supplier_id=b.supplier.id,
                po_number="PO-X",
                currency="INR",
                items=[PurchaseOrderItemCreate(equipment_id=b.equipment.id, quantity=Decimal("1"))],
            ),
        )
    # Not CROSS_WORKSPACE_REFERENCE: that would say the records exist elsewhere.
    assert codes(order.value) == {
        ("project_id", "REFERENCE_NOT_FOUND"),
        ("supplier_id", "REFERENCE_NOT_FOUND"),
        ("items.0.equipment_id", "REFERENCE_NOT_FOUND"),
    }
    session.rollback()
    assert purchase_order_repository.get_by_number(session, a.id, "PO-X") is None
    assert purchase_order_repository.get_by_number(session, b.id, "PO-X") is None


def test_repositories_never_return_foreign_rows(session: Session, a: Tenant, b: Tenant) -> None:
    assert project_repository.get_by_id(session, a.id, b.project.id) is None
    assert project_repository.get_by_code(session, a.id, "DC-001").id == a.project.id  # type: ignore[union-attr]
    assert set(project_repository.get_by_codes(session, a.id, {"DC-001"}).values()) == {a.project}
    assert supplier_repository.get_by_ids(session, a.id, {a.supplier.id, b.supplier.id}) == {
        a.supplier.id: a.supplier
    }
    assert equipment_repository.get_by_ids(session, a.id, {b.equipment.id}) == {}
    assert equipment_repository.get_by_codes(session, a.id, {"EQ-001"}) == {"EQ-001": a.equipment}
    assert purchase_order_repository.get_by_id(session, a.id, b.order.id) is None
    assert purchase_order_repository.lock_by_id(session, a.id, b.order.id) is None
    assert purchase_order_repository.get_with_items_and_supplier(session, a.id, b.order.id) is None
    assert purchase_order_repository.get_by_numbers(session, a.id, {"PO-001"}) == {
        "PO-001": a.order
    }
    assert purchase_order_repository.latest_commitment(session, a.id, b.order.id) is None
    assert purchase_order_repository.latest_commitments(
        session, a.id, {a.order.id, b.order.id}
    ) == {a.order.id: a.commitment}
    assert purchase_order_repository.get_items_by_pairs(
        session, a.id, {(b.order.id, b.equipment.id), (a.order.id, a.equipment.id)}
    ) == {(a.order.id, a.equipment.id): a.item}
    assert milestone_repository.get_by_id(session, a.id, b.milestone.id) is None
    assert (
        milestone_repository.get_by_identity(
            session, a.id, b.order.id, MilestoneType.PO_ACKNOWLEDGEMENT, 1
        )
        is None
    )
    assert (
        milestone_repository.get_by_identities(
            session, a.id, {(b.order.id, MilestoneType.PO_ACKNOWLEDGEMENT, 1)}
        )
        == {}
    )


def test_imports_resolve_references_in_their_own_workspace_only(
    session: Session, a: Tenant, b: Tenant
) -> None:
    """B has a project DC-B-ONLY. A's file naming it gets "not found", like any unknown code."""
    factories.make_project(session, b.workspace, code="DC-B-ONLY")
    data = csv_bytes(
        ["Equipment Code", "Project Code", "Equipment Name", "Category", "Criticality"],
        [
            ["EQ-NEW-1", "DC-B-ONLY", "x", "UPS", "LOW"],
            ["EQ-NEW-2", "DC-NOWHERE", "y", "UPS", "LOW"],
            ["EQ-NEW-3", "DC-001", "z", "UPS", "LOW"],
        ],
    )

    result = ingestion_service.preview_import(
        session,
        a.id,
        UploadedFile("equipment.csv", "text/csv", data),
        IngestionEntityType.EQUIPMENT,
        limits=LIMITS,
    )

    assert [(e["row_number"], e["code"], e["message"]) for e in result.errors] == [
        (2, "REFERENCE_NOT_FOUND", result.errors[0]["message"]),
        (3, "REFERENCE_NOT_FOUND", result.errors[0]["message"]),
    ]
    assert result.batch.valid_rows == 1
    # The batch belongs to A and is invisible from B.
    assert ingestion_repository.get_by_id(session, b.id, result.batch.id) is None
    with pytest.raises(NotFoundError):
        ingestion_service.get_batch(session, b.id, result.batch.id, limit=50, offset=0)
    session.rollback()
    assert ingestion_service.list_batches(session, b.id, limit=50, offset=0).total == 0


def test_the_same_file_in_two_workspaces_is_two_batches(
    session: Session, a: Tenant, b: Tenant
) -> None:
    data = csv_bytes(["Supplier Code", "Supplier Name"], [["SUP-NEW", "New"]])
    upload = UploadedFile("suppliers.csv", "text/csv", data)

    in_a = ingestion_service.preview_import(
        session, a.id, upload, IngestionEntityType.SUPPLIER, limits=LIMITS
    )
    in_b = ingestion_service.preview_import(
        session, b.id, upload, IngestionEntityType.SUPPLIER, limits=LIMITS
    )

    assert in_a.batch.id != in_b.batch.id
    assert (in_a.duplicate_file, in_b.duplicate_file) == (False, False)
    assert in_a.batch.file_sha256 == in_b.batch.file_sha256


def test_a_missing_or_disabled_workspace_serves_nothing(session: Session, a: Tenant) -> None:
    with pytest.raises(WorkspaceNotAvailableError):
        project_service.list_projects(session, uuid4(), limit=50, offset=0)
    session.rollback()

    workspace = session.get(Workspace, a.id)
    assert workspace is not None
    workspace.status = WorkspaceStatus.DISABLED
    session.commit()

    for operation in (
        lambda: project_service.list_projects(session, a.id, limit=50, offset=0),
        lambda: project_service.get_project(session, a.id, a.project.id),
        lambda: project_service.create_project(session, a.id, ProjectCreate(code="X", name="X")),
        lambda: purchase_order_service.get_purchase_order(session, a.id, a.order.id),
        lambda: ingestion_service.list_batches(session, a.id, limit=50, offset=0),
    ):
        with pytest.raises(WorkspaceNotAvailableError):
            operation()
        session.rollback()
