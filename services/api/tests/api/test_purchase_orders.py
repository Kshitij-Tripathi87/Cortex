"""Purchase orders, line items, milestones and supplier commitments over HTTP."""

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Milestone, MilestonePlanVersion, PurchaseOrder, PurchaseOrderItem
from tests.conftest import Api, detail_codes, error_of

pytestmark = pytest.mark.db


class Scene:
    """A project with two pieces of equipment, a second project, and a supplier."""

    def __init__(self, api: Api) -> None:
        self.api = api
        self.project = api.create("/projects", {"code": "DC-IN-001", "name": "North Ridge"})["id"]
        self.other_project = api.create("/projects", {"code": "DC-IN-002", "name": "Other"})["id"]
        self.supplier = api.create("/suppliers", {"supplier_code": "SUP-001", "name": "Halcyon"})[
            "id"
        ]
        self.ups_1 = self._equipment(self.project, "UPS-001")
        self.ups_2 = self._equipment(self.project, "UPS-002")
        self.elsewhere = self._equipment(self.other_project, "CH-009")

    def _equipment(self, project: str, code: str) -> str:
        body = {
            "project_id": project,
            "equipment_code": code,
            "name": code,
            "category": "UPS",
            "criticality": "HIGH",
        }
        return str(self.api.create("/equipment", body)["id"])

    def order(self, **changes: Any) -> dict[str, Any]:
        body: dict[str, Any] = {
            "project_id": self.project,
            "supplier_id": self.supplier,
            "po_number": "PO-1007",
            "currency": "eur",
            "status": "ISSUED",
            "issue_date": "2026-06-22",
            "total_value": "412000.00",
            "items": [
                {"equipment_id": self.ups_1, "quantity": "1", "unit_price": "206000.00"},
                {"equipment_id": self.ups_2, "quantity": "1", "unit_price": "206000.00"},
            ],
        }
        body.update(changes)
        return body


@pytest.fixture
def scene(api: Api) -> Scene:
    return Scene(api)


def count(session: Session, model: type) -> int:
    session.rollback()
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


# --- purchase orders ------------------------------------------------------------------


def test_create_purchase_order_with_line_items(api: Api, scene: Scene) -> None:
    created = api.create("/purchase-orders", scene.order())

    assert created["po_number"] == "PO-1007"
    assert created["currency"] == "EUR"  # normalised to upper case
    assert created["total_value"] == "412000.00"
    assert created["supplier"] == {
        "id": scene.supplier,
        "supplier_code": "SUP-001",
        "name": "Halcyon",
        "status": "ACTIVE",
    }
    assert [
        (item["equipment_code"], item["quantity"], item["unit_price"]) for item in created["items"]
    ] == [
        ("UPS-001", "1.000", "206000.00"),
        ("UPS-002", "1.000", "206000.00"),
    ]
    assert created["current_commitment"] is None

    fetched = api.get(f"/purchase-orders/{created['id']}").json()
    assert fetched == created
    listed = api.get("/purchase-orders").json()
    assert listed["total"] == 1
    assert "items" not in listed["items"][0]  # the list is headers only


def test_a_purchase_order_header_without_line_items_is_allowed(api: Api, scene: Scene) -> None:
    created = api.create("/purchase-orders", scene.order(items=[]))

    assert created["items"] == []


def test_decimal_values_are_exact_end_to_end(api: Api, scene: Scene, session: Session) -> None:
    order = scene.order(
        total_value="1234567890123456.78",
        items=[{"equipment_id": scene.ups_1, "quantity": "2.125", "unit_price": "1234.56"}],
    )

    created = api.create("/purchase-orders", order)

    assert created["total_value"] == "1234567890123456.78"
    assert (created["items"][0]["quantity"], created["items"][0]["unit_price"]) == (
        "2.125",
        "1234.56",
    )
    stored = session.scalar(select(PurchaseOrderItem))
    assert stored is not None
    assert (str(stored.quantity), str(stored.unit_price)) == ("2.125", "1234.56")


def test_a_whole_number_may_be_sent_as_a_json_number(api: Api, scene: Scene) -> None:
    """An integer is exact, unlike a JSON float; it is stored with the scale of its field."""
    order = scene.order(
        total_value=1500,
        items=[{"equipment_id": scene.ups_1, "quantity": 3, "unit_price": 500}],
    )

    created = api.create("/purchase-orders", order)

    assert created["total_value"] == "1500.00"
    assert (created["items"][0]["quantity"], created["items"][0]["unit_price"]) == (
        "3.000",
        "500.00",
    )
    # The bounds of the field hold for a JSON number as for a string.
    for too_large in (10**16, 10**40, 10**400):
        error = error_of(
            api.patch(f"/purchase-orders/{created['id']}", json={"total_value": too_large}),
            422,
            "VALIDATION_ERROR",
        )
        assert [detail["field"] for detail in error["details"]] == ["total_value"]
    error = error_of(
        api.patch(f"/purchase-orders/{created['id']}", json={"total_value": -1}),
        422,
        "VALIDATION_ERROR",
    )
    assert detail_codes(error) == {("total_value", "MUST_BE_NON_NEGATIVE")}
    assert api.get(f"/purchase-orders/{created['id']}").json()["total_value"] == "1500.00"


@pytest.mark.parametrize(
    ("item", "expected"),
    [
        ({"quantity": "0"}, ("items.0.quantity", "MUST_BE_POSITIVE")),
        ({"quantity": "-1"}, ("items.0.quantity", "MUST_BE_POSITIVE")),
        ({"quantity": 1.5}, ("items.0.quantity", "INVALID_DECIMAL")),  # a JSON float is not exact
        ({"quantity": "1.0005"}, ("items.0.quantity", "INVALID_DECIMAL")),
        ({"quantity": "1e2"}, ("items.0.quantity", "INVALID_DECIMAL")),
        ({"quantity": "1", "unit_price": "-0.01"}, ("items.0.unit_price", "MUST_BE_NON_NEGATIVE")),
        ({"quantity": "1", "unit_price": "10.999"}, ("items.0.unit_price", "INVALID_DECIMAL")),
    ],
)
def test_invalid_quantities_and_prices(
    api: Api, scene: Scene, session: Session, item: dict[str, Any], expected: tuple[str, str]
) -> None:
    order = scene.order(items=[{"equipment_id": scene.ups_1, **item}])

    error = error_of(api.post("/purchase-orders", json=order), 422, "VALIDATION_ERROR")

    assert expected in detail_codes(error)
    assert count(session, PurchaseOrder) == 0


def test_creation_rolls_back_when_one_line_item_is_invalid(
    api: Api, scene: Scene, session: Session
) -> None:
    """One bad line among good ones: no header, no line, nothing."""
    order = scene.order(
        items=[
            {"equipment_id": scene.ups_1, "quantity": "1"},
            {"equipment_id": str(uuid4()), "quantity": "1"},
            {"equipment_id": scene.elsewhere, "quantity": "1"},
        ]
    )

    error = error_of(api.post("/purchase-orders", json=order), 422, "VALIDATION_ERROR")

    assert detail_codes(error) == {
        ("items.1.equipment_id", "REFERENCE_NOT_FOUND"),
        ("items.2.equipment_id", "CROSS_PROJECT_REFERENCE"),
    }
    assert count(session, PurchaseOrder) == 0
    assert count(session, PurchaseOrderItem) == 0
    assert api.get("/purchase-orders").json()["total"] == 0


def test_the_same_equipment_twice_in_one_order_is_rejected(
    api: Api, scene: Scene, session: Session
) -> None:
    order = scene.order(
        items=[
            {"equipment_id": scene.ups_1, "quantity": "1"},
            {"equipment_id": scene.ups_1, "quantity": "2"},
        ]
    )

    error = error_of(api.post("/purchase-orders", json=order), 422, "VALIDATION_ERROR")

    assert detail_codes(error) == {("items.1.equipment_id", "DUPLICATE_NATURAL_KEY")}
    assert count(session, PurchaseOrder) == 0


def test_references_must_exist_in_the_workspace(api: Api, scene: Scene) -> None:
    order = scene.order(project_id=str(uuid4()), supplier_id=str(uuid4()), items=[])

    error = error_of(api.post("/purchase-orders", json=order), 422, "VALIDATION_ERROR")

    assert detail_codes(error) == {
        ("project_id", "REFERENCE_NOT_FOUND"),
        ("supplier_id", "REFERENCE_NOT_FOUND"),
    }


def test_a_new_order_cannot_name_an_inactive_supplier_but_old_orders_remain(
    api: Api, scene: Scene
) -> None:
    existing = api.create("/purchase-orders", scene.order())
    api.patch(f"/suppliers/{scene.supplier}", json={"status": "INACTIVE"})

    error = error_of(
        api.post("/purchase-orders", json=scene.order(po_number="PO-2", items=[])),
        422,
        "VALIDATION_ERROR",
    )

    assert detail_codes(error) == {("supplier_id", "REFERENCE_INACTIVE")}
    kept = api.get(f"/purchase-orders/{existing['id']}").json()
    assert kept["supplier"]["status"] == "INACTIVE"
    assert len(kept["items"]) == 2


def test_po_number_is_unique_and_identity_fields_are_fixed(api: Api, scene: Scene) -> None:
    created = api.create("/purchase-orders", scene.order())
    path = f"/purchase-orders/{created['id']}"

    error = error_of(
        api.post("/purchase-orders", json=scene.order(items=[])), 409, "DUPLICATE_NATURAL_KEY"
    )
    assert detail_codes(error) == {("po_number", "DUPLICATE_NATURAL_KEY")}

    for forbidden in (
        {"po_number": "X"},
        {"project_id": scene.other_project},
        {"supplier_id": str(uuid4())},
    ):
        error_of(api.patch(path, json=forbidden), 422, "VALIDATION_ERROR")

    updated = api.patch(
        path, json={"status": "IN_PRODUCTION", "total_value": None, "currency": "inr"}
    ).json()
    assert (updated["status"], updated["total_value"], updated["currency"]) == (
        "IN_PRODUCTION",
        None,
        "INR",
    )
    assert len(updated["items"]) == 2


def test_invalid_currency(api: Api, scene: Scene) -> None:
    for currency in ("RS", "EURO", "12A", ""):
        error = error_of(
            api.post("/purchase-orders", json=scene.order(currency=currency, items=[])),
            422,
            "VALIDATION_ERROR",
        )
        assert detail_codes(error) == {("currency", "INVALID_CURRENCY")}


def test_list_filters_and_unknown_order(api: Api, scene: Scene) -> None:
    api.create("/purchase-orders", scene.order(po_number="PO-B", status="DRAFT", items=[]))
    api.create("/purchase-orders", scene.order(po_number="PO-A", items=[]))
    api.create(
        "/purchase-orders", scene.order(po_number="PO-C", project_id=scene.other_project, items=[])
    )

    def numbers(**params: str) -> list[str]:
        return [
            item["po_number"] for item in api.get("/purchase-orders", params=params).json()["items"]
        ]

    assert numbers() == ["PO-A", "PO-B", "PO-C"]
    assert numbers(status="DRAFT") == ["PO-B"]
    assert numbers(project_id=scene.other_project) == ["PO-C"]
    assert numbers(supplier_id=scene.supplier) == ["PO-A", "PO-B", "PO-C"]
    assert numbers(supplier_id=str(uuid4())) == []
    error_of(api.get(f"/purchase-orders/{uuid4()}"), 404, "NOT_FOUND")


# --- milestones -----------------------------------------------------------------------


@pytest.fixture
def order_id(api: Api, scene: Scene) -> str:
    return str(api.create("/purchase-orders", scene.order())["id"])


def test_create_milestone_with_its_first_plan_version(api: Api, order_id: str) -> None:
    created = api.create(
        f"/purchase-orders/{order_id}/milestones",
        {
            "milestone_type": "FACTORY_ACCEPTANCE_TEST",
            "planned_date": "2026-11-10",
            "recorded_by": "expeditor",
        },
    )

    assert (created["sequence_no"], created["status"], created["actual_date"]) == (
        1,
        "PENDING",
        None,
    )
    assert created["plan_version_count"] == 1
    assert created["current_plan"]["version_no"] == 1
    assert created["current_plan"]["planned_date"] == "2026-11-10"
    assert created["current_plan"]["recorded_by"] == "expeditor"
    assert created["current_plan"]["source_ingestion_row_id"] is None
    assert created["plan_versions"] == [created["current_plan"]]
    assert api.get(f"/purchase-orders/{order_id}/milestones/{created['id']}").json() == created


def test_updating_the_planned_date_appends_a_version(
    api: Api, order_id: str, session: Session
) -> None:
    base = f"/purchase-orders/{order_id}/milestones"
    milestone = api.create(base, {"milestone_type": "DISPATCH", "planned_date": "2026-12-01"})
    versions = f"{base}/{milestone['id']}/plan-versions"

    replanned = api.post(versions, json={"planned_date": "2026-12-15"})

    assert replanned.status_code == 201
    body = replanned.json()
    assert body["plan_version_count"] == 2
    assert body["current_plan"]["planned_date"] == "2026-12-15"
    # The first plan is still there, unchanged.
    assert [(v["version_no"], v["planned_date"]) for v in body["plan_versions"]] == [
        (1, "2026-12-01"),
        (2, "2026-12-15"),
    ]
    assert body["plan_versions"][0] == milestone["plan_versions"][0]

    same_again = api.post(versions, json={"planned_date": "2026-12-15"})
    assert same_again.status_code == 200
    assert same_again.json()["plan_version_count"] == 2
    assert count(session, MilestonePlanVersion) == 2

    back_to_the_first = api.post(versions, json={"planned_date": "2026-12-01"})
    assert back_to_the_first.status_code == 201  # differs from the current plan: a new version
    assert [v["planned_date"] for v in back_to_the_first.json()["plan_versions"]] == [
        "2026-12-01",
        "2026-12-15",
        "2026-12-01",
    ]


def test_planned_and_actual_are_separate_facts(api: Api, order_id: str) -> None:
    base = f"/purchase-orders/{order_id}/milestones"
    milestone = api.create(
        base, {"milestone_type": "FACTORY_ACCEPTANCE_TEST", "planned_date": "2026-11-10"}
    )
    path = f"{base}/{milestone['id']}"

    recorded = api.patch(path, json={"actual_date": "2026-11-14"}).json()

    # An actual date after the plan is recorded as given; the plan is untouched
    # and nothing compares the two.
    assert (recorded["status"], recorded["actual_date"]) == ("COMPLETED", "2026-11-14")
    assert recorded["current_plan"]["planned_date"] == "2026-11-10"
    assert recorded["plan_version_count"] == 1
    assert not {"days_late", "slippage", "delay"} & set(recorded)


def test_milestone_state_rules(api: Api, order_id: str) -> None:
    base = f"/purchase-orders/{order_id}/milestones"

    error = error_of(
        api.post(
            base,
            json={
                "milestone_type": "DISPATCH",
                "planned_date": "2026-12-01",
                "actual_date": "2026-12-02",
                "status": "PENDING",
            },
        ),
        422,
        "VALIDATION_ERROR",
    )
    assert next(iter(detail_codes(error)))[1] == "INCONSISTENT_MILESTONE_STATE"

    done = api.create(
        base,
        {"milestone_type": "DISPATCH", "planned_date": "2026-12-01", "actual_date": "2026-12-02"},
    )
    assert done["status"] == "COMPLETED"
    path = f"{base}/{done['id']}"

    error = error_of(api.patch(path, json={"status": "PENDING"}), 422, "VALIDATION_ERROR")
    assert detail_codes(error) == {("actual_date", "INCONSISTENT_MILESTONE_STATE")}

    reopened = api.patch(path, json={"status": "PENDING", "actual_date": None}).json()
    assert (reopened["status"], reopened["actual_date"]) == ("PENDING", None)

    # A status alone never produces a date.
    completed_without_date = api.patch(path, json={"status": "COMPLETED"}).json()
    assert (completed_without_date["status"], completed_without_date["actual_date"]) == (
        "COMPLETED",
        None,
    )

    error = error_of(api.patch(path, json={"planned_date": "2027-01-01"}), 422, "VALIDATION_ERROR")
    assert detail_codes(error) == {("planned_date", "UNKNOWN_FIELD")}


def test_milestone_identity_and_lifecycle_order(api: Api, order_id: str, session: Session) -> None:
    base = f"/purchase-orders/{order_id}/milestones"
    for body in (
        {"milestone_type": "DELIVERY", "planned_date": "2026-12-20"},
        {"milestone_type": "PO_ACKNOWLEDGEMENT", "planned_date": "2026-06-29"},
        {"milestone_type": "DISPATCH", "sequence_no": 2, "planned_date": "2026-12-10"},
        {"milestone_type": "DISPATCH", "sequence_no": 1, "planned_date": "2026-12-05"},
    ):
        api.create(base, body)

    error = error_of(
        api.post(base, json={"milestone_type": "DELIVERY", "planned_date": "2027-01-01"}),
        409,
        "DUPLICATE_NATURAL_KEY",
    )
    assert error["details"][0]["code"] == "DUPLICATE_NATURAL_KEY"
    assert count(session, Milestone) == 4

    listed = api.get(base).json()
    assert listed["total"] == 4
    assert [(m["milestone_type"], m["sequence_no"]) for m in listed["items"]] == [
        ("PO_ACKNOWLEDGEMENT", 1),
        ("DISPATCH", 1),
        ("DISPATCH", 2),
        ("DELIVERY", 1),
    ]
    assert [
        m["milestone_type"] for m in api.get(base, params={"limit": 2, "offset": 1}).json()["items"]
    ] == ["DISPATCH", "DISPATCH"]


def test_milestones_of_an_unknown_order_or_milestone(api: Api, order_id: str) -> None:
    error_of(api.get(f"/purchase-orders/{uuid4()}/milestones"), 404, "NOT_FOUND")
    error_of(
        api.post(
            f"/purchase-orders/{uuid4()}/milestones",
            json={"milestone_type": "DISPATCH", "planned_date": "2026-12-01"},
        ),
        404,
        "NOT_FOUND",
    )
    error_of(api.get(f"/purchase-orders/{order_id}/milestones/{uuid4()}"), 404, "NOT_FOUND")
    error_of(
        api.post(
            f"/purchase-orders/{order_id}/milestones/{uuid4()}/plan-versions",
            json={"planned_date": "2026-12-01"},
        ),
        404,
        "NOT_FOUND",
    )


def test_a_milestone_is_reachable_only_under_its_own_order(
    api: Api, scene: Scene, order_id: str
) -> None:
    other_order = api.create("/purchase-orders", scene.order(po_number="PO-OTHER", items=[]))["id"]
    milestone = api.create(
        f"/purchase-orders/{order_id}/milestones",
        {"milestone_type": "DISPATCH", "planned_date": "2026-12-01"},
    )

    error_of(
        api.get(f"/purchase-orders/{other_order}/milestones/{milestone['id']}"), 404, "NOT_FOUND"
    )
    error_of(
        api.patch(
            f"/purchase-orders/{other_order}/milestones/{milestone['id']}",
            json={"status": "CANCELLED"},
        ),
        404,
        "NOT_FOUND",
    )


# --- supplier commitments -------------------------------------------------------------


def test_commitment_history_is_append_only(api: Api, order_id: str) -> None:
    path = f"/purchase-orders/{order_id}/commitments"

    first = api.post(
        path, json={"committed_delivery_date": "2026-11-28", "source_reference": "LTR-0412"}
    )
    assert first.status_code == 201
    assert (first.json()["version_no"], first.json()["recorded_by"]) == (1, "api")

    revised = api.post(
        path, json={"committed_delivery_date": "2026-12-06", "recorded_by": "expeditor"}
    )
    assert revised.status_code == 201
    assert revised.json()["version_no"] == 2

    replay = api.post(path, json={"committed_delivery_date": "2026-12-06"})
    assert replay.status_code == 200  # the date is already current: nothing is created
    assert replay.json() == revised.json()

    history = api.get(path).json()
    assert history["total"] == 2
    assert [(v["version_no"], v["committed_delivery_date"]) for v in history["items"]] == [
        (1, "2026-11-28"),
        (2, "2026-12-06"),
    ]
    assert history["items"][0] == first.json()  # the earlier commitment is unchanged

    current = api.get(f"/purchase-orders/{order_id}").json()["current_commitment"]
    assert current == revised.json()


def test_commitment_validation_and_unknown_order(api: Api, order_id: str) -> None:
    path = f"/purchase-orders/{order_id}/commitments"

    error = error_of(
        api.post(path, json={"committed_delivery_date": "06/12/2026"}), 422, "VALIDATION_ERROR"
    )
    assert detail_codes(error) == {("committed_delivery_date", "INVALID_DATE")}
    # One spelling only: no timestamp, no date-time, no basic format, and no
    # digits of another script (such a date may be of another calendar). The
    # right spelling of a day that does not exist is not a date either.
    for not_a_date in (
        1796515200,
        "2026-12-06T00:00:00",
        "20261206",
        "२०२६-१२-०६",
        "2027-02-30",
        "2026-13-01",
        "2026-00-10",
    ):
        error = error_of(
            api.post(path, json={"committed_delivery_date": not_a_date}), 422, "VALIDATION_ERROR"
        )
        assert detail_codes(error) == {("committed_delivery_date", "INVALID_DATE")}
    assert api.get(path).json()["total"] == 0
    error_of(api.post(path, json={}), 422, "VALIDATION_ERROR")
    error_of(
        api.post(
            f"/purchase-orders/{uuid4()}/commitments",
            json={"committed_delivery_date": "2026-12-06"},
        ),
        404,
        "NOT_FOUND",
    )
    error_of(api.get(f"/purchase-orders/{uuid4()}/commitments"), 404, "NOT_FOUND")
    assert api.get(path).json() == {"items": [], "total": 0, "limit": 50, "offset": 0}
