"""What PostgreSQL itself refuses, whatever the service layer does.

These tests write through the ORM directly, bypassing the services, to prove
that the database is the last line of defence for each invariant.
"""

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from psycopg.errors import CheckViolation, ForeignKeyViolation, NotNullViolation, UniqueViolation
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
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
    Workspace,
)
from app.models.enums import (
    BatchStatus,
    Criticality,
    EquipmentCategory,
    IngestionEntityType,
    MilestoneStatus,
    MilestoneType,
    ProjectStatus,
    PurchaseOrderStatus,
    RowStatus,
    SourceFormat,
)
from tests import factories

pytestmark = pytest.mark.db


def rejected(
    session: Session, violation: type[Exception], constraint: str, write: Callable[[], Any]
) -> None:
    """The write fails on exactly this constraint, and the session is usable afterwards."""

    def write_and_flush() -> None:
        write()
        session.flush()

    with pytest.raises(IntegrityError) as failure:
        write_and_flush()
    session.rollback()
    assert isinstance(failure.value.orig, violation), failure.value.orig
    assert failure.value.orig.diag.constraint_name == constraint


class World:
    """Two workspaces, each with a project, a supplier and equipment."""

    def __init__(self, session: Session) -> None:
        self.a = factories.make_workspace(session)
        self.b = factories.make_workspace(session, workspace_id=uuid4(), slug="other")
        self.project_a = factories.make_project(session, self.a, code="DC-A")
        self.project_a2 = factories.make_project(session, self.a, code="DC-A2")
        self.project_b = factories.make_project(session, self.b, code="DC-B")
        self.supplier_a = factories.make_supplier(session, self.a, supplier_code="SUP-A")
        self.supplier_b = factories.make_supplier(session, self.b, supplier_code="SUP-B")
        self.equipment_a = factories.make_equipment(session, self.project_a, equipment_code="EQ-A")
        self.equipment_a2 = factories.make_equipment(
            session, self.project_a2, equipment_code="EQ-A2"
        )
        self.equipment_b = factories.make_equipment(session, self.project_b, equipment_code="EQ-B")
        self.order_a = factories.make_purchase_order(
            session, self.project_a, self.supplier_a, po_number="PO-A"
        )


@pytest.fixture
def world(session: Session) -> World:
    return World(session)


def item(world: World, **changes: Any) -> PurchaseOrderItem:
    values: dict[str, Any] = {
        "workspace_id": world.a.id,
        "project_id": world.project_a.id,
        "purchase_order_id": world.order_a.id,
        "equipment_id": world.equipment_a.id,
        "quantity": Decimal("1"),
    }
    values.update(changes)
    return PurchaseOrderItem(**values)


# --- natural keys ---------------------------------------------------------------------


def test_workspace_slug_is_unique(session: Session, world: World) -> None:
    rejected(
        session,
        UniqueViolation,
        "uq_workspaces_slug",
        lambda: session.add(Workspace(name="Clone", slug="nexus-test")),
    )


def test_workspace_slug_format(session: Session) -> None:
    rejected(
        session,
        CheckViolation,
        "ck_workspaces_slug_format",
        lambda: session.add(Workspace(name="Bad", slug="Not A Slug")),
    )


def test_project_code_is_unique_within_a_workspace(session: Session, world: World) -> None:
    rejected(
        session,
        UniqueViolation,
        "uq_projects_workspace_id_code",
        lambda: session.add(Project(workspace_id=world.a.id, code="DC-A", name="Again")),
    )


def test_the_same_natural_keys_are_allowed_in_another_workspace(
    session: Session, world: World
) -> None:
    session.add_all(
        [
            Project(workspace_id=world.b.id, code="DC-A", name="Theirs"),
            Supplier(workspace_id=world.b.id, supplier_code="SUP-A", name="Theirs"),
            Equipment(
                workspace_id=world.b.id,
                project_id=world.project_b.id,
                equipment_code="EQ-A",
                name="Theirs",
                category=EquipmentCategory.UPS,
                criticality=Criticality.LOW,
            ),
            PurchaseOrder(
                workspace_id=world.b.id,
                project_id=world.project_b.id,
                supplier_id=world.supplier_b.id,
                po_number="PO-A",
                currency="INR",
            ),
        ]
    )
    session.commit()

    assert len(session.scalars(select(Project).where(Project.code == "DC-A")).all()) == 2


@pytest.mark.parametrize(
    ("constraint", "build"),
    [
        (
            "uq_suppliers_workspace_id_supplier_code",
            lambda w: Supplier(workspace_id=w.a.id, supplier_code="SUP-A", name="Again"),
        ),
        (
            "uq_equipment_workspace_id_equipment_code",
            lambda w: Equipment(
                workspace_id=w.a.id,
                project_id=w.project_a.id,
                equipment_code="EQ-A",
                name="Again",
                category=EquipmentCategory.UPS,
                criticality=Criticality.LOW,
            ),
        ),
        (
            "uq_purchase_orders_workspace_id_po_number",
            lambda w: PurchaseOrder(
                workspace_id=w.a.id,
                project_id=w.project_a.id,
                supplier_id=w.supplier_a.id,
                po_number="PO-A",
                currency="INR",
            ),
        ),
    ],
)
def test_other_natural_keys_are_unique_within_a_workspace(
    session: Session, world: World, constraint: str, build: Callable[[World], Any]
) -> None:
    rejected(session, UniqueViolation, constraint, lambda: session.add(build(world)))


# --- equipment and purchase orders ----------------------------------------------------


def test_equipment_exists_without_any_purchase_order(session: Session, world: World) -> None:
    critical = Equipment(
        workspace_id=world.a.id,
        project_id=world.project_a.id,
        equipment_code="DG-003",
        name="Diesel generator set 3",
        category=EquipmentCategory.GENERATOR,
        criticality=Criticality.CRITICAL,
    )
    session.add(critical)
    session.commit()

    assert (
        session.scalar(
            select(PurchaseOrderItem).where(PurchaseOrderItem.equipment_id == critical.id)
        )
        is None
    )
    assert not hasattr(Equipment, "supplier_id")
    assert not hasattr(Equipment, "purchase_order_id")


def test_equipment_cannot_point_at_a_project_of_another_workspace(
    session: Session, world: World
) -> None:
    rejected(
        session,
        ForeignKeyViolation,
        "fk_equipment_workspace_project",
        lambda: session.add(
            Equipment(
                workspace_id=world.a.id,
                project_id=world.project_b.id,
                equipment_code="EQ-X",
                name="Cross",
                category=EquipmentCategory.UPS,
                criticality=Criticality.LOW,
            )
        ),
    )


def test_purchase_order_cannot_name_a_supplier_of_another_workspace(
    session: Session, world: World
) -> None:
    rejected(
        session,
        ForeignKeyViolation,
        "fk_purchase_orders_workspace_supplier",
        lambda: session.add(
            PurchaseOrder(
                workspace_id=world.a.id,
                project_id=world.project_a.id,
                supplier_id=world.supplier_b.id,
                po_number="PO-X",
                currency="INR",
            )
        ),
    )


def test_purchase_order_cannot_name_a_project_of_another_workspace(
    session: Session, world: World
) -> None:
    rejected(
        session,
        ForeignKeyViolation,
        "fk_purchase_orders_workspace_project",
        lambda: session.add(
            PurchaseOrder(
                workspace_id=world.a.id,
                project_id=world.project_b.id,
                supplier_id=world.supplier_a.id,
                po_number="PO-X",
                currency="INR",
            )
        ),
    )


@pytest.mark.parametrize("currency", ["inr", "RS", "A1B", "1NR"])
def test_currency_format(session: Session, world: World, currency: str) -> None:
    rejected(
        session,
        CheckViolation,
        "ck_purchase_orders_currency_format",
        lambda: session.add(
            PurchaseOrder(
                workspace_id=world.a.id,
                project_id=world.project_a.id,
                supplier_id=world.supplier_a.id,
                po_number="PO-X",
                currency=currency,
            )
        ),
    )


def test_enumerated_columns_reject_other_values(session: Session, world: World) -> None:
    """Raw SQL, so that the value reaches PostgreSQL instead of being stopped by the ORM."""
    project_id = world.project_a.id

    rejected(
        session,
        CheckViolation,
        "ck_projects_status",
        lambda: session.execute(
            text("UPDATE projects SET status = 'PAUSED' WHERE id = :id"), {"id": project_id}
        ),
    )
    rejected(
        session,
        CheckViolation,
        "ck_milestones_milestone_type",
        lambda: session.execute(
            text(
                "INSERT INTO milestones "
                "(workspace_id, purchase_order_id, milestone_type, sequence_no, status) "
                "VALUES (:workspace, :po, 'SHIPPED', 1, 'PENDING')"
            ),
            {"workspace": world.a.id, "po": world.order_a.id},
        ),
    )


# --- line items -----------------------------------------------------------------------


def test_line_item_with_equipment_of_another_project_is_rejected_by_the_database(
    session: Session, world: World
) -> None:
    """Equipment belongs to project A2, the purchase order to project A."""
    rejected(
        session,
        ForeignKeyViolation,
        "fk_purchase_order_items_equipment",
        lambda: session.add(item(world, equipment_id=world.equipment_a2.id)),
    )


def test_line_item_cannot_claim_the_other_project_either(session: Session, world: World) -> None:
    rejected(
        session,
        ForeignKeyViolation,
        "fk_purchase_order_items_purchase_order",
        lambda: session.add(
            item(world, project_id=world.project_a2.id, equipment_id=world.equipment_a2.id)
        ),
    )


def test_line_item_cannot_cross_workspaces(session: Session, world: World) -> None:
    rejected(
        session,
        ForeignKeyViolation,
        "fk_purchase_order_items_equipment",
        lambda: session.add(item(world, equipment_id=world.equipment_b.id)),
    )


@pytest.mark.parametrize("quantity", [Decimal("0"), Decimal("-1")])
def test_quantity_must_be_positive(session: Session, world: World, quantity: Decimal) -> None:
    rejected(
        session,
        CheckViolation,
        "ck_purchase_order_items_quantity_positive",
        lambda: session.add(item(world, quantity=quantity)),
    )


def test_unit_price_must_not_be_negative(session: Session, world: World) -> None:
    rejected(
        session,
        CheckViolation,
        "ck_purchase_order_items_unit_price_not_negative",
        lambda: session.add(item(world, unit_price=Decimal("-0.01"))),
    )


def test_the_same_equipment_once_per_purchase_order(session: Session, world: World) -> None:
    session.add(item(world))
    session.commit()

    rejected(
        session,
        UniqueViolation,
        "uq_purchase_order_items_purchase_order_id_equipment_id",
        lambda: session.add(item(world, quantity=Decimal("2"))),
    )


def test_decimal_values_are_stored_exactly(session: Session, world: World) -> None:
    line = item(world, quantity=Decimal("2.125"), unit_price=Decimal("1234.56"))
    world.order_a.total_value = Decimal("1234567890123456.78")
    session.add(line)
    session.commit()
    session.expire_all()

    reloaded = session.get(PurchaseOrderItem, line.id)
    order = session.get(PurchaseOrder, world.order_a.id)
    assert reloaded is not None
    assert order is not None
    assert isinstance(reloaded.unit_price, Decimal)
    assert reloaded.unit_price == Decimal("1234.56")
    assert str(reloaded.unit_price) == "1234.56"
    assert str(reloaded.quantity) == "2.125"
    assert str(order.total_value) == "1234567890123456.78"


# --- milestones and versions ----------------------------------------------------------


def test_milestone_identity_is_unique_per_order_type_and_sequence(
    session: Session, world: World
) -> None:
    factories.make_milestone(
        session, world.order_a, milestone_type=MilestoneType.DISPATCH, sequence_no=1
    )
    factories.make_milestone(
        session, world.order_a, milestone_type=MilestoneType.DISPATCH, sequence_no=2
    )

    rejected(
        session,
        UniqueViolation,
        "uq_milestones_purchase_order_id_type_sequence_no",
        lambda: session.add(
            Milestone(
                workspace_id=world.a.id,
                purchase_order_id=world.order_a.id,
                milestone_type=MilestoneType.DISPATCH,
                sequence_no=1,
            )
        ),
    )


def test_an_actual_date_needs_a_completed_milestone(session: Session, world: World) -> None:
    rejected(
        session,
        CheckViolation,
        "ck_milestones_actual_date_requires_completed",
        lambda: session.add(
            Milestone(
                workspace_id=world.a.id,
                purchase_order_id=world.order_a.id,
                milestone_type=MilestoneType.DELIVERY,
                status=MilestoneStatus.PENDING,
                actual_date=date(2026, 11, 14),
            )
        ),
    )


def test_milestone_cannot_belong_to_an_order_of_another_workspace(
    session: Session, world: World
) -> None:
    rejected(
        session,
        ForeignKeyViolation,
        "fk_milestones_workspace_purchase_order",
        lambda: session.add(
            Milestone(
                workspace_id=world.b.id,
                purchase_order_id=world.order_a.id,
                milestone_type=MilestoneType.DELIVERY,
            )
        ),
    )


def test_version_numbers_are_unique_per_parent_and_positive(session: Session, world: World) -> None:
    milestone = factories.make_milestone(session, world.order_a)
    factories.make_commitment(session, world.order_a, committed_delivery_date=date(2026, 11, 28))

    rejected(
        session,
        UniqueViolation,
        "uq_milestone_plan_versions_milestone_id_version_no",
        lambda: session.add(
            MilestonePlanVersion(
                milestone_id=milestone.id,
                version_no=1,
                planned_date=date(2026, 12, 1),
                recorded_by="t",
            )
        ),
    )
    rejected(
        session,
        UniqueViolation,
        "uq_supplier_commitment_versions_purchase_order_id_version_no",
        lambda: session.add(
            SupplierCommitmentVersion(
                workspace_id=world.a.id,
                purchase_order_id=world.order_a.id,
                version_no=1,
                committed_delivery_date=date(2026, 12, 6),
                recorded_by="t",
            )
        ),
    )
    rejected(
        session,
        CheckViolation,
        "ck_supplier_commitment_versions_version_no_positive",
        lambda: session.add(
            SupplierCommitmentVersion(
                workspace_id=world.a.id,
                purchase_order_id=world.order_a.id,
                version_no=0,
                committed_delivery_date=date(2026, 12, 6),
                recorded_by="t",
            )
        ),
    )


def test_a_commitment_cannot_cross_workspaces(session: Session, world: World) -> None:
    rejected(
        session,
        ForeignKeyViolation,
        "fk_supplier_commitment_versions_workspace_purchase_order",
        lambda: session.add(
            SupplierCommitmentVersion(
                workspace_id=world.b.id,
                purchase_order_id=world.order_a.id,
                version_no=1,
                committed_delivery_date=date(2026, 12, 6),
                recorded_by="t",
            )
        ),
    )


def test_a_version_must_have_a_date_and_an_author(session: Session, world: World) -> None:
    def write() -> None:
        session.execute(
            SupplierCommitmentVersion.__table__.insert().values(
                workspace_id=world.a.id,
                purchase_order_id=world.order_a.id,
                version_no=1,
                recorded_by="t",
            )
        )

    with pytest.raises(IntegrityError) as failure:
        write()
    session.rollback()
    assert isinstance(failure.value.orig, NotNullViolation)


# --- ingestion ledger -----------------------------------------------------------------


def batch(world: World, **changes: Any) -> IngestionBatch:
    values: dict[str, Any] = {
        "workspace_id": world.a.id,
        "entity_type": IngestionEntityType.PROJECT,
        "original_filename": "projects.csv",
        "file_sha256": "a" * 64,
        "source_format": SourceFormat.CSV,
        "file_size_bytes": 10,
        "file_warnings": [],
        "status": BatchStatus.PREVIEWED,
    }
    values.update(changes)
    return IngestionBatch(**values)


def test_the_same_file_for_the_same_entity_type_is_one_batch(
    session: Session, world: World
) -> None:
    session.add(batch(world))
    session.commit()

    rejected(
        session,
        UniqueViolation,
        "uq_ingestion_batches_active_checksum",
        lambda: session.add(batch(world)),
    )


def test_a_failed_batch_does_not_block_the_same_file(session: Session, world: World) -> None:
    session.add(batch(world, status=BatchStatus.FAILED, failure_code="COMMIT_CONFLICT"))
    session.commit()

    session.add(batch(world))
    session.add(batch(world, entity_type=IngestionEntityType.SUPPLIER))
    session.add(batch(world, workspace_id=world.b.id))
    session.commit()

    assert len(session.scalars(select(IngestionBatch)).all()) == 4


@pytest.mark.parametrize(
    ("changes", "constraint"),
    [
        ({"file_sha256": "not-a-checksum"}, "ck_ingestion_batches_file_sha256_format"),
        ({"file_size_bytes": 0}, "ck_ingestion_batches_file_size_positive"),
        (
            {"total_rows": 3, "valid_rows": 1, "invalid_rows": 1},
            "ck_ingestion_batches_preview_counters_add_up",
        ),
        ({"status": BatchStatus.COMMITTED}, "ck_ingestion_batches_committed_at_iff_committed"),
        ({"status": BatchStatus.FAILED}, "ck_ingestion_batches_failure_code_iff_failed"),
        ({"failure_code": "X"}, "ck_ingestion_batches_failure_code_iff_failed"),
    ],
)
def test_batch_consistency(
    session: Session, world: World, changes: dict[str, Any], constraint: str
) -> None:
    rejected(session, CheckViolation, constraint, lambda: session.add(batch(world, **changes)))


def test_source_rows_are_unique_per_batch_and_consistently_linked(
    session: Session, world: World
) -> None:
    parent = batch(world)
    session.add(parent)
    session.commit()

    def row(**changes: Any) -> IngestionRow:
        values: dict[str, Any] = {
            "batch_id": parent.id,
            "row_number": 2,
            "raw_data": {"Project Code": "P1"},
            "normalized_data": {"code": "P1"},
            "validation_errors": [],
            "warnings": [],
            "status": RowStatus.VALID,
        }
        values.update(changes)
        return IngestionRow(**values)

    session.add(row())
    session.commit()

    rejected(
        session,
        UniqueViolation,
        "uq_ingestion_rows_batch_id_row_number",
        lambda: session.add(row()),
    )
    rejected(
        session,
        CheckViolation,
        "ck_ingestion_rows_canonical_link_complete",
        lambda: session.add(row(row_number=3, canonical_entity_type="project")),
    )
    rejected(
        session,
        CheckViolation,
        "ck_ingestion_rows_canonical_entity_type_allowed",
        lambda: session.add(
            row(row_number=3, canonical_entity_type="risk_finding", canonical_entity_id=uuid4())
        ),
    )
    rejected(
        session,
        CheckViolation,
        "ck_ingestion_rows_committed_row_has_canonical_link",
        lambda: session.add(row(row_number=3, status=RowStatus.COMMITTED)),
    )
    rejected(
        session,
        CheckViolation,
        "ck_ingestion_rows_row_number_positive",
        lambda: session.add(row(row_number=0)),
    )


def test_project_status_default_and_timestamps(session: Session, world: World) -> None:
    project = Project(workspace_id=world.a.id, code="DC-NEW", name="New")
    session.add(project)
    session.commit()
    session.expire_all()

    reloaded = session.get(Project, project.id)
    assert reloaded is not None
    assert reloaded.status is ProjectStatus.PLANNING
    assert reloaded.created_at.tzinfo is not None
    assert reloaded.created_at.utcoffset().total_seconds() == 0  # type: ignore[union-attr]
    assert PurchaseOrderStatus.DRAFT is PurchaseOrderStatus("DRAFT")
