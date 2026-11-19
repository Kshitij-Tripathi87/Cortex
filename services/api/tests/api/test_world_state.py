"""World State over HTTP: scoped, bounded, deterministic, and nothing but stored facts."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import clock
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
    IngestionEntityType,
    MilestoneType,
    ProcurementStatus,
    PurchaseOrderStatus,
)
from tests import factories
from tests.conftest import Api, error_of
from tests.importing import Importer, import_small_dataset

pytestmark = pytest.mark.db

FORBIDDEN = {
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
    "slippage_days",
}


def keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in keys(item)}
    if isinstance(value, list):
        return {key for item in value for key in keys(item)}
    return set()


def without_generated_at(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: without_generated_at(v) for k, v in value.items() if k != "generated_at"}
    if isinstance(value, list):
        return [without_generated_at(item) for item in value]
    return value


@pytest.fixture
def dataset(session: Session, workspace: Workspace) -> Importer:
    importer = Importer(session, workspace.id)
    import_small_dataset(importer)
    return importer


def project_state(api: Api, **params: Any) -> dict[str, Any]:
    project_id = api.get("/projects").json()["items"][0]["id"]
    response = api.get(f"/world-state/projects/{project_id}", params=params)
    assert response.status_code == 200, response.text
    state: dict[str, Any] = response.json()
    return state


# --- workspace level --------------------------------------------------------------------


def test_summary_counts_match_the_database(api: Api, dataset: Importer, session: Session) -> None:
    summary = api.get("/world-state/summary").json()

    def count(model: type) -> int:
        statement = select(func.count()).select_from(model)
        if hasattr(model, "workspace_id"):
            statement = statement.where(model.workspace_id == api.workspace_id)
        return int(session.scalar(statement) or 0)

    session.rollback()
    assert summary["workspace_id"] == str(api.workspace_id)
    assert summary["summary"] == {
        "projects": count(Project),
        "suppliers": count(Supplier),
        "equipment": count(Equipment),
        "purchase_orders": count(PurchaseOrder),
        "purchase_order_items": count(PurchaseOrderItem),
        "milestones": count(Milestone),
        "milestone_plan_versions": count(MilestonePlanVersion),
        "supplier_commitment_versions": count(SupplierCommitmentVersion),
    }
    assert summary["summary"] == {
        "projects": 1,
        "suppliers": 2,
        "equipment": 3,
        "purchase_orders": 2,
        "purchase_order_items": 2,
        "milestones": 3,
        "milestone_plan_versions": 3,
        "supplier_commitment_versions": 2,
    }


def test_counts_follow_the_database_not_a_fixture(
    api: Api, dataset: Importer, session: Session
) -> None:
    before = api.get("/world-state/summary").json()["summary"]

    factories.make_supplier(
        session, session.get(Workspace, api.workspace_id), supplier_code="SUP-NEW"
    )  # type: ignore[arg-type]
    after = api.get("/world-state/summary").json()["summary"]

    assert after["suppliers"] == before["suppliers"] + 1
    assert {k: v for k, v in after.items() if k != "suppliers"} == {
        k: v for k, v in before.items() if k != "suppliers"
    }


def test_counts_exclude_other_workspaces(api: Api, dataset: Importer, session: Session) -> None:
    other = factories.make_workspace(session, workspace_id=uuid4(), slug="other")
    project = factories.make_project(session, other, code="DC-1")
    supplier = factories.make_supplier(session, other, supplier_code="SUP-1")
    factories.make_equipment(session, project, equipment_code="EQ-1")
    order = factories.make_purchase_order(session, project, supplier, po_number="PO-1")
    factories.make_milestone(session, order)
    factories.make_commitment(session, order, committed_delivery_date=date(2026, 12, 1))

    state = api.get("/world-state").json()

    assert state["summary"]["projects"] == 1
    assert state["summary"]["suppliers"] == 2
    assert state["summary"]["supplier_commitment_versions"] == 2
    assert [p["code"] for p in state["projects"]["items"]] == ["DC-1"]
    assert state["projects"]["items"][0]["id"] != str(project.id)


def test_workspace_world_state_lists_projects_with_their_counts(
    api: Api, dataset: Importer
) -> None:
    state = api.get("/world-state").json()

    assert state["workspace"] == {
        "id": str(api.workspace_id),
        "name": "Nexus Test Workspace",
        "slug": "nexus-test",
        "status": "ACTIVE",
    }
    assert state["projects"]["total"] == 1
    (project,) = state["projects"]["items"]
    assert (project["code"], project["name"], project["status"]) == (
        "DC-1",
        "Project one",
        "ACTIVE",
    )
    assert project["counts"] == {
        "equipment": 3,
        "purchase_orders": 2,
        "purchase_order_items": 2,
        "milestones": 3,
    }
    assert set(state) == {
        "workspace_id",
        "generated_at",
        "workspace",
        "summary",
        "data_quality",
        "projects",
    }


def test_the_project_list_is_paged_and_the_total_stays_complete(
    api: Api, session: Session, workspace: Workspace
) -> None:
    for code in ("DC-C", "DC-A", "DC-B"):
        factories.make_project(session, workspace, code=code)

    page = api.get("/world-state", params={"limit": 2, "offset": 1}).json()

    assert [p["code"] for p in page["projects"]["items"]] == ["DC-B", "DC-C"]
    assert (page["projects"]["total"], page["projects"]["limit"], page["projects"]["offset"]) == (
        3,
        2,
        1,
    )
    assert page["summary"]["projects"] == 3  # the count is of the database, not of the page
    error_of(api.get("/world-state", params={"limit": 201}), 422, "VALIDATION_ERROR")
    error_of(api.get("/world-state", params={"limit": 0}), 422, "VALIDATION_ERROR")


def test_an_empty_workspace_has_zero_counts_and_empty_lists(api: Api) -> None:
    state = api.get("/world-state").json()

    assert set(state["summary"].values()) == {0}
    assert state["projects"] == {"items": [], "total": 0, "limit": 50, "offset": 0}
    assert state["data_quality"]["warnings"] == []
    assert state["data_quality"]["warning_counts"] == {}
    assert (state["data_quality"]["valid_records"], state["data_quality"]["invalid_records"]) == (
        0,
        0,
    )
    assert set(state["data_quality"]["ingestion"]["rows"].values()) == {0}
    assert set(state["data_quality"]["ingestion"]["batches"]) == {
        "UPLOADED",
        "PREVIEWED",
        "COMMITTING",
        "COMMITTED",
        "FAILED",
    }


def test_ledger_quality_counts_source_rows_by_outcome(api: Api, dataset: Importer) -> None:
    dataset.preview(
        IngestionEntityType.SUPPLIER,
        ["Supplier Code", "Supplier Name"],
        [["SUP-9", "Nine"], ["", "No code"]],
    )

    quality = api.get("/world-state/summary").json()["data_quality"]

    assert quality["ingestion"]["batches"]["COMMITTED"] == 7
    assert quality["ingestion"]["batches"]["PREVIEWED"] == 1
    assert quality["ingestion"]["rows"] == {
        "VALID": 1,
        "INVALID": 1,
        "COMMITTED": 15,
        "SKIPPED": 0,
        "FAILED": 0,
    }
    assert (quality["valid_records"], quality["invalid_records"]) == (16, 1)


# --- project level ----------------------------------------------------------------------


def test_project_world_state_shows_equipment_orders_suppliers_and_milestones(
    api: Api, dataset: Importer
) -> None:
    state = project_state(api)

    assert state["project"]["code"] == "DC-1"
    assert state["summary"] == {
        "equipment": 3,
        "purchase_orders": 2,
        "purchase_order_items": 2,
        "milestones": 3,
        "suppliers": 2,
    }

    equipment = {item["equipment_code"]: item for item in state["equipment"]["items"]}
    assert list(equipment) == ["EQ-1", "EQ-2", "EQ-3"]
    assert equipment["EQ-1"]["criticality"] == "CRITICAL"
    assert equipment["EQ-1"]["required_on_site_date"] == "2027-02-01"
    (link,) = equipment["EQ-1"]["purchase_orders"]
    assert (link["po_number"], link["quantity"], link["supplier"]["supplier_code"]) == (
        "PO-1",
        "1.000",
        "SUP-1",
    )

    orders = {order["po_number"]: order for order in state["purchase_orders"]["items"]}
    assert list(orders) == ["PO-1", "PO-2"]
    first = orders["PO-1"]
    assert first["supplier"]["name"] == "Supplier one"
    assert (first["currency"], first["status"]) == ("INR", "ISSUED")
    assert [(i["equipment_code"], i["quantity"], i["unit_price"]) for i in first["line_items"]] == [
        ("EQ-1", "1.000", "1000.50")
    ]
    assert (
        first["line_item_count"],
        first["milestone_count"],
        first["commitment_version_count"],
    ) == (1, 2, 1)
    assert [(m["milestone_type"], m["status"], m["actual_date"]) for m in first["milestones"]] == [
        ("PO_ACKNOWLEDGEMENT", "COMPLETED", "2026-06-08"),
        ("DELIVERY", "PENDING", None),
    ]
    assert first["milestones"][1]["current_plan"]["planned_date"] == "2026-12-15"
    assert first["current_commitment"]["committed_delivery_date"] == "2026-12-15"
    assert first["current_commitment"]["source_reference"] == "REF-1"
    assert first["current_commitment"]["source_ingestion_row_id"] is not None


def test_procurement_gap_equipment_without_an_order_and_no_invented_supplier(
    api: Api, dataset: Importer
) -> None:
    state = project_state(api)

    gap = next(item for item in state["equipment"]["items"] if item["equipment_code"] == "EQ-3")
    assert gap["criticality"] == "CRITICAL"
    assert (gap["purchase_order_count"], gap["purchase_orders"]) == (0, [])
    assert "supplier" not in gap
    warnings = [
        (w["code"], w["reference"], w["entity_type"]) for w in state["data_quality"]["warnings"]
    ]
    assert ("EQUIPMENT_WITHOUT_PO_LINE_ITEM", "EQ-3", "equipment") in warnings


def test_missing_confirmation_stays_visible_as_missing(api: Api, dataset: Importer) -> None:
    state = project_state(api)

    unconfirmed = next(
        order for order in state["purchase_orders"]["items"] if order["po_number"] == "PO-2"
    )
    assert "PO_ACKNOWLEDGEMENT" not in [
        m["milestone_type"] for m in unconfirmed["milestones"]
    ]  # none was made up
    warning = next(
        w
        for w in state["data_quality"]["warnings"]
        if w["code"] == "PO_ACKNOWLEDGEMENT_NOT_RECORDED"
    )
    assert (warning["reference"], warning["dimension"]) == ("PO-2", "COMPLETENESS")
    # "Not recorded" is said about the data. Nothing blames the supplier.
    assert warning["message"] == "No acknowledgement milestone is recorded for this purchase order."
    assert state["data_quality"]["warning_counts"] == {
        "EQUIPMENT_WITHOUT_PO_LINE_ITEM": 1,
        "PO_ACKNOWLEDGEMENT_NOT_RECORDED": 1,
    }


def test_planned_and_actual_dates_are_side_by_side_and_uncompared(
    api: Api, dataset: Importer
) -> None:
    state = project_state(api)

    order = next(o for o in state["purchase_orders"]["items"] if o["po_number"] == "PO-2")
    (test,) = order["milestones"]
    # Planned 10 November, actual 14 November. Both facts, no verdict.
    assert (test["current_plan"]["planned_date"], test["actual_date"], test["status"]) == (
        "2026-11-10",
        "2026-11-14",
        "COMPLETED",
    )
    assert set(test) == {
        "id",
        "milestone_type",
        "sequence_no",
        "status",
        "actual_date",
        "plan_version_count",
        "current_plan",
        "plan_history",
    }


def test_commitment_history_both_versions_latest_explicit(api: Api, dataset: Importer) -> None:
    order_id = next(
        o["id"] for o in api.get("/purchase-orders").json()["items"] if o["po_number"] == "PO-2"
    )
    api.post(
        f"/purchase-orders/{order_id}/commitments", json={"committed_delivery_date": "2026-12-06"}
    )

    default = next(
        o for o in project_state(api)["purchase_orders"]["items"] if o["po_number"] == "PO-2"
    )
    with_history = next(
        o
        for o in project_state(api, include_history="true")["purchase_orders"]["items"]
        if o["po_number"] == "PO-2"
    )

    assert default["commitment_history"] is None  # histories are not loaded unless asked for
    assert default["milestones"][0]["plan_history"] is None
    assert default["commitment_version_count"] == 2
    assert (
        default["current_commitment"]["version_no"],
        default["current_commitment"]["committed_delivery_date"],
    ) == (2, "2026-12-06")
    assert [
        (v["version_no"], v["committed_delivery_date"]) for v in with_history["commitment_history"]
    ] == [
        (1, "2026-11-28"),
        (2, "2026-12-06"),
    ]
    assert with_history["current_commitment"] == with_history["commitment_history"][-1]
    assert [v["version_no"] for v in with_history["milestones"][0]["plan_history"]] == [1]


def test_project_collections_are_paged(api: Api, dataset: Importer) -> None:
    page = project_state(api, equipment_limit=2, equipment_offset=1, po_limit=1)

    assert [e["equipment_code"] for e in page["equipment"]["items"]] == ["EQ-2", "EQ-3"]
    assert (
        page["equipment"]["total"],
        page["equipment"]["limit"],
        page["equipment"]["offset"],
    ) == (3, 2, 1)
    assert [o["po_number"] for o in page["purchase_orders"]["items"]] == ["PO-1"]
    assert page["purchase_orders"]["total"] == 2
    assert page["summary"]["equipment"] == 3  # totals are not those of the page
    project_id = page["project"]["id"]
    error_of(
        api.get(f"/world-state/projects/{project_id}", params={"po_limit": 500}),
        422,
        "VALIDATION_ERROR",
    )


def test_nested_lists_are_capped_and_the_count_stays_complete(
    api: Api, session: Session, workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import world_state_service

    project = factories.make_project(session, workspace, code="DC-1")
    supplier = factories.make_supplier(session, workspace, supplier_code="SUP-1")
    order = factories.make_purchase_order(session, project, supplier, po_number="PO-1")
    for index in range(5):
        equipment = factories.make_equipment(session, project, equipment_code=f"EQ-{index}")
        factories.make_item(session, order, equipment, quantity=Decimal("1"))
        factories.make_milestone(
            session, order, milestone_type=MilestoneType.DISPATCH, sequence_no=index + 1
        )
    monkeypatch.setattr(world_state_service, "LINE_ITEM_LIMIT", 3)
    monkeypatch.setattr(world_state_service, "MILESTONE_LIMIT", 2)

    (state,) = project_state(api)["purchase_orders"]["items"]

    assert [i["equipment_code"] for i in state["line_items"]] == ["EQ-0", "EQ-1", "EQ-2"]
    assert state["line_item_count"] == 5
    assert [m["sequence_no"] for m in state["milestones"]] == [1, 2]
    assert state["milestone_count"] == 5


def test_cancelled_records_raise_no_completeness_warning(
    api: Api, session: Session, workspace: Workspace
) -> None:
    project = factories.make_project(session, workspace, code="DC-1")
    supplier = factories.make_supplier(session, workspace, supplier_code="SUP-1")
    factories.make_equipment(
        session,
        project,
        equipment_code="EQ-LIVE",
        required_on_site_date=None,
        criticality=Criticality.LOW,
    )
    factories.make_equipment(
        session,
        project,
        equipment_code="EQ-CANCELLED",
        procurement_status=ProcurementStatus.CANCELLED,
    )
    factories.make_purchase_order(session, project, supplier, po_number="PO-LIVE")
    factories.make_purchase_order(
        session, project, supplier, po_number="PO-CANCELLED", status=PurchaseOrderStatus.CANCELLED
    )

    quality = project_state(api)["data_quality"]

    assert quality["warning_counts"] == {
        "EQUIPMENT_REQUIRED_DATE_NOT_RECORDED": 1,
        "EQUIPMENT_WITHOUT_PO_LINE_ITEM": 1,
        "PO_ACKNOWLEDGEMENT_NOT_RECORDED": 1,
        "PO_WITHOUT_LINE_ITEMS": 1,
        "PO_WITHOUT_SUPPLIER_COMMITMENT": 1,
    }
    assert {w["reference"] for w in quality["warnings"]} == {"EQ-LIVE", "PO-LIVE"}
    # Ordered by code, then by reference.
    assert [w["code"] for w in quality["warnings"]] == sorted(
        w["code"] for w in quality["warnings"]
    )


def test_warnings_are_bounded_and_counts_are_complete(
    api: Api, session: Session, workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import data_quality_service

    project = factories.make_project(session, workspace, code="DC-1")
    for index in range(6):
        factories.make_equipment(session, project, equipment_code=f"EQ-{index}")
    monkeypatch.setattr(data_quality_service, "WARNING_LIST_LIMIT", 4)

    quality = api.get("/world-state/summary").json()["data_quality"]

    assert quality["warning_counts"] == {"EQUIPMENT_WITHOUT_PO_LINE_ITEM": 6}
    assert [w["reference"] for w in quality["warnings"]] == ["EQ-0", "EQ-1", "EQ-2", "EQ-3"]
    assert quality["warnings_truncated"] is True


# --- properties -------------------------------------------------------------------------


def test_no_risk_score_lateness_or_recommendation_anywhere(api: Api, dataset: Importer) -> None:
    responses = [
        api.get("/world-state").json(),
        api.get("/world-state/summary").json(),
        project_state(api, include_history="true"),
    ]

    for response in responses:
        assert not keys(response) & FORBIDDEN


def test_the_same_database_state_gives_the_same_response(api: Api, dataset: Importer) -> None:
    first = [api.get("/world-state").json(), project_state(api, include_history="true")]
    second = [api.get("/world-state").json(), project_state(api, include_history="true")]

    assert without_generated_at(first) == without_generated_at(second)


def test_generated_at_comes_from_the_service_clock(api: Api, dataset: Importer) -> None:
    moment = datetime(2026, 11, 19, 7, 30, tzinfo=UTC)

    with clock.frozen_at(moment):
        summary = api.get("/world-state/summary").json()
        state = project_state(api)

    assert summary["generated_at"] == "2026-11-19T07:30:00Z"
    assert state["generated_at"] == "2026-11-19T07:30:00Z"


def test_the_response_does_not_depend_on_the_date(api: Api, dataset: Importer) -> None:
    """Nothing is derived from "today": a year later the facts read the same."""
    with clock.frozen_at(datetime(2026, 11, 19, tzinfo=UTC)):
        now = project_state(api, include_history="true")
    with clock.frozen_at(datetime(2027, 11, 19, tzinfo=UTC)):
        later = project_state(api, include_history="true")

    assert without_generated_at(now) == without_generated_at(later)


def test_world_state_of_another_workspace_or_project_is_not_disclosed(
    api: Api, client: TestClient, dataset: Importer, session: Session
) -> None:
    other = factories.make_workspace(session, workspace_id=uuid4(), slug="other")
    foreign_project = factories.make_project(session, other, code="DC-SECRET")

    error_of(
        client.get(f"/api/v1/workspaces/{other.id}/world-state"), 404, "WORKSPACE_NOT_AVAILABLE"
    )
    error_of(
        client.get(f"/api/v1/workspaces/{other.id}/world-state/summary"),
        404,
        "WORKSPACE_NOT_AVAILABLE",
    )
    error_of(api.get(f"/world-state/projects/{foreign_project.id}"), 404, "NOT_FOUND")
    error_of(api.get(f"/world-state/projects/{uuid4()}"), 404, "NOT_FOUND")
    assert "DC-SECRET" not in api.get("/world-state").text
