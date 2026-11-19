"""World State projection logic, without a database.

The assembly functions turn records into the response shapes. They are fed
plain objects here, so what they keep, order and leave out can be checked on
its own.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel

from app.models.enums import (
    Criticality,
    EquipmentCategory,
    MilestoneStatus,
    MilestoneType,
    ProcurementStatus,
    PurchaseOrderStatus,
    QualityDimension,
    SupplierStatus,
)
from app.repositories.world_state_repository import LineItem, OrderLink
from app.schemas import world_state as schemas
from app.services import world_state_service as service
from app.services.data_quality_service import RecordQualityReport, RecordWarning

RECORDED_AT = datetime(2026, 11, 19, 7, 30, tzinfo=UTC)

FORBIDDEN_FIELDS = {
    "risk_score",
    "delay_probability",
    "root_cause",
    "recovery_options",
    "recommended_action",
    "days_late",
    "is_late",
    "is_overdue",
    "severity",
    "risk_level",
    "recommendation",
}


def supplier(code: str = "SUP-1") -> Any:
    return SimpleNamespace(
        id=uuid4(), supplier_code=code, name=f"Supplier {code}", status=SupplierStatus.ACTIVE
    )


def equipment(code: str = "EQ-1", **changes: Any) -> Any:
    values: dict[str, Any] = {
        "id": uuid4(),
        "equipment_code": code,
        "name": f"Equipment {code}",
        "category": EquipmentCategory.GENERATOR,
        "criticality": Criticality.CRITICAL,
        "procurement_status": ProcurementStatus.RFQ,
        "required_on_site_date": date(2027, 1, 18),
        "specification": None,
    }
    values.update(changes)
    return SimpleNamespace(**values)


def order(number: str = "PO-1", **changes: Any) -> Any:
    values: dict[str, Any] = {
        "id": uuid4(),
        "po_number": number,
        "status": PurchaseOrderStatus.IN_PRODUCTION,
        "issue_date": date(2026, 6, 22),
        "currency": "EUR",
        "total_value": Decimal("412000"),
    }
    values.update(changes)
    return SimpleNamespace(**values)


def item(quantity: str = "1", unit_price: str | None = "206000.00") -> Any:
    return SimpleNamespace(
        id=uuid4(),
        quantity=Decimal(quantity),
        unit_price=Decimal(unit_price) if unit_price else None,
    )


def plan(version_no: int, planned: date, source: UUID | None = None) -> Any:
    return SimpleNamespace(
        version_no=version_no,
        planned_date=planned,
        recorded_at=RECORDED_AT,
        recorded_by="import:milestones.csv",
        source_ingestion_row_id=source,
    )


def commitment(version_no: int, committed: date) -> Any:
    return SimpleNamespace(
        version_no=version_no,
        committed_delivery_date=committed,
        source_reference=None,
        recorded_at=RECORDED_AT,
        recorded_by="Expediting",
        source_ingestion_row_id=uuid4(),
    )


def milestone(milestone_type: MilestoneType, **changes: Any) -> Any:
    values: dict[str, Any] = {
        "id": uuid4(),
        "milestone_type": milestone_type,
        "sequence_no": 1,
        "status": MilestoneStatus.PENDING,
        "actual_date": None,
    }
    values.update(changes)
    return SimpleNamespace(**values)


# --- equipment --------------------------------------------------------------------------


def test_equipment_without_a_purchase_order_has_an_empty_list_and_no_supplier() -> None:
    state = service.equipment_state(equipment("DG-003"), [], 0)

    assert state.purchase_orders == []
    assert state.purchase_order_count == 0
    assert state.criticality is Criticality.CRITICAL
    assert "supplier" not in state.model_dump()


def test_equipment_links_keep_the_order_they_are_given_and_carry_the_supplier() -> None:
    first = OrderLink(item("2.5"), order("PO-1"), supplier("SUP-1"))
    second = OrderLink(item("1"), order("PO-2"), supplier("SUP-2"))

    state = service.equipment_state(equipment(), [first, second], 2)

    assert [link.po_number for link in state.purchase_orders] == ["PO-1", "PO-2"]
    assert [link.supplier.supplier_code for link in state.purchase_orders] == ["SUP-1", "SUP-2"]
    dumped = state.model_dump(mode="json")
    assert dumped["purchase_orders"][0]["quantity"] == "2.500"  # fixed scale, as text


def test_equipment_keeps_a_missing_date_and_specification_as_null() -> None:
    state = service.equipment_state(equipment(required_on_site_date=None), [], 0)
    with_spec = service.equipment_state(equipment(specification={"description": "2.5 MVA"}), [], 0)

    assert state.required_on_site_date is None
    assert state.specification is None
    assert with_spec.specification is not None
    assert with_spec.specification.description == "2.5 MVA"
    assert with_spec.specification.manufacturer is None


# --- milestones -------------------------------------------------------------------------


def test_a_milestone_keeps_planned_and_actual_separately() -> None:
    record = milestone(
        MilestoneType.FACTORY_ACCEPTANCE_TEST,
        status=MilestoneStatus.COMPLETED,
        actual_date=date(2026, 11, 14),
    )

    state = service.milestone_state(record, plan(1, date(2026, 11, 10)), 1, None)

    assert state.current_plan is not None
    assert (state.current_plan.planned_date, state.actual_date) == (
        date(2026, 11, 10),
        date(2026, 11, 14),
    )
    # The two dates are reported; no field says which is later or by how much.
    assert set(state.model_dump()) == {
        "id",
        "milestone_type",
        "sequence_no",
        "status",
        "actual_date",
        "plan_version_count",
        "current_plan",
        "plan_history",
    }


def test_a_pending_milestone_has_no_actual_date_and_no_history_unless_asked() -> None:
    pending = service.milestone_state(
        milestone(MilestoneType.DELIVERY), plan(2, date(2026, 12, 15)), 2, None
    )
    detailed = service.milestone_state(
        milestone(MilestoneType.DELIVERY),
        plan(2, date(2026, 12, 15)),
        2,
        [plan(1, date(2026, 12, 1)), plan(2, date(2026, 12, 15))],
    )

    assert (pending.actual_date, pending.plan_history, pending.plan_version_count) == (
        None,
        None,
        2,
    )
    assert detailed.plan_history is not None
    assert [version.version_no for version in detailed.plan_history] == [1, 2]
    assert detailed.current_plan == detailed.plan_history[-1]


def test_a_milestone_without_any_plan_version_has_a_null_plan() -> None:
    state = service.milestone_state(milestone(MilestoneType.DISPATCH), None, 0, [])

    assert (state.current_plan, state.plan_history, state.plan_version_count) == (None, [], 0)


# --- purchase orders --------------------------------------------------------------------


def build_order(**changes: Any) -> schemas.PurchaseOrderState:
    arguments: dict[str, Any] = {
        "line_items": [
            LineItem(item(), equipment("UPS-001")),
            LineItem(item(), equipment("UPS-002")),
        ],
        "line_item_count": 2,
        "milestones": [],
        "milestone_count": 0,
        "current_commitment": None,
        "commitment_version_count": 0,
        "commitment_history": None,
    }
    arguments.update(changes)
    return service.purchase_order_state(order("PO-1007"), supplier("SUP-004"), **arguments)


def test_a_purchase_order_without_a_commitment_reports_none() -> None:
    state = build_order()

    assert (state.current_commitment, state.commitment_history, state.commitment_version_count) == (
        None,
        None,
        0,
    )
    assert state.supplier.supplier_code == "SUP-004"
    assert [line.equipment_code for line in state.line_items] == ["UPS-001", "UPS-002"]


def test_the_current_commitment_is_the_one_it_is_given_and_history_is_separate() -> None:
    versions = [commitment(1, date(2026, 11, 28)), commitment(2, date(2026, 12, 6))]

    state = build_order(
        current_commitment=versions[-1], commitment_version_count=2, commitment_history=versions
    )

    assert state.current_commitment is not None
    assert (
        state.current_commitment.version_no,
        state.current_commitment.committed_delivery_date,
    ) == (
        2,
        date(2026, 12, 6),
    )
    assert state.commitment_history is not None
    assert [v.committed_delivery_date for v in state.commitment_history] == [
        date(2026, 11, 28),
        date(2026, 12, 6),
    ]


def test_counts_can_exceed_the_listed_items_so_truncation_is_visible() -> None:
    state = build_order(line_item_count=250, milestone_count=7)

    assert (len(state.line_items), state.line_item_count) == (2, 250)
    assert (len(state.milestones), state.milestone_count) == (0, 7)


def test_money_and_quantity_are_rendered_as_exact_text() -> None:
    dumped = build_order().model_dump(mode="json")

    assert dumped["total_value"] == "412000.00"
    assert dumped["line_items"][0]["quantity"] == "1.000"
    assert dumped["line_items"][0]["unit_price"] == "206000.00"
    without_price = service.purchase_order_state(
        order(total_value=None),
        supplier(),
        line_items=[LineItem(item(unit_price=None), equipment())],
        line_item_count=1,
        milestones=[],
        milestone_count=0,
        current_commitment=None,
        commitment_version_count=0,
        commitment_history=None,
    ).model_dump(mode="json")
    assert (without_price["total_value"], without_price["line_items"][0]["unit_price"]) == (
        None,
        None,
    )


# --- data quality -----------------------------------------------------------------------


def test_record_quality_is_passed_through_with_counts_and_truncation() -> None:
    project_id = uuid4()
    warning = RecordWarning(
        dimension=QualityDimension.COMPLETENESS,
        code="PO_ACKNOWLEDGEMENT_NOT_RECORDED",
        entity_type="purchase_order",
        entity_id=uuid4(),
        reference="PO-1005",
        project_id=project_id,
        message="No acknowledgement milestone is recorded for this purchase order.",
    )
    report = RecordQualityReport({"PO_ACKNOWLEDGEMENT_NOT_RECORDED": 3}, [warning], truncated=True)

    state = service.record_quality_state(report)

    assert state.warning_counts == {"PO_ACKNOWLEDGEMENT_NOT_RECORDED": 3}
    assert state.warnings_truncated is True
    assert [(w.code, w.reference, w.dimension) for w in state.warnings] == [
        ("PO_ACKNOWLEDGEMENT_NOT_RECORDED", "PO-1005", QualityDimension.COMPLETENESS)
    ]


# --- the contract itself ----------------------------------------------------------------


def _field_names(model: type[BaseModel], seen: set[type] | None = None) -> set[str]:
    """Every field name reachable from a response model."""
    seen = seen if seen is not None else set()
    if model in seen:
        return set()
    seen.add(model)
    names = set(model.model_fields)
    for info in model.model_fields.values():
        stack = [info.annotation]
        while stack:
            annotation = stack.pop()
            if isinstance(annotation, type) and issubclass(annotation, BaseModel):
                names |= _field_names(annotation, seen)
            stack.extend(getattr(annotation, "__args__", ()))
    return names


def test_no_world_state_schema_has_a_field_for_risk_lateness_or_advice() -> None:
    for model in (
        schemas.WorldStateSummary,
        schemas.WorkspaceWorldState,
        schemas.ProjectWorldState,
    ):
        names = _field_names(model)
        assert len(names) > 10
        assert not names & FORBIDDEN_FIELDS, model.__name__
        assert not {
            name for name in names if "score" in name or "probab" in name or "recommend" in name
        }


def test_summary_counts_name_every_kind_of_record() -> None:
    assert set(schemas.WorkspaceCounts.model_fields) == {
        "projects",
        "suppliers",
        "equipment",
        "purchase_orders",
        "purchase_order_items",
        "milestones",
        "milestone_plan_versions",
        "supplier_commitment_versions",
    }


def test_nested_collection_caps_are_bounded() -> None:
    assert 0 < service.EQUIPMENT_ORDER_LINK_LIMIT <= 50
    assert 0 < service.LINE_ITEM_LIMIT <= 500
    assert 0 < service.MILESTONE_LIMIT <= 500
    assert 0 < service.HISTORY_LIMIT <= 100
