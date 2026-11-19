"""Supplier and equipment routes."""

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.models import Workspace
from tests import factories
from tests.conftest import Api, detail_codes, error_of

pytestmark = pytest.mark.db

SUPPLIER = {
    "supplier_code": "SUP-001",
    "name": "Halcyon Grid Transformers",
    "country": "India",
    "city": "Vadodara",
}


# --- suppliers ------------------------------------------------------------------------


def test_supplier_create_get_list_update(api: Api) -> None:
    created = api.create("/suppliers", SUPPLIER)

    assert created["status"] == "ACTIVE"
    assert api.get(f"/suppliers/{created['id']}").json() == created
    assert api.get("/suppliers").json() == {
        "items": [created],
        "total": 1,
        "limit": 50,
        "offset": 0,
    }

    updated = api.patch(
        f"/suppliers/{created['id']}", json={"status": "INACTIVE", "city": "Surat"}
    ).json()
    assert (updated["status"], updated["city"], updated["supplier_code"]) == (
        "INACTIVE",
        "Surat",
        "SUP-001",
    )
    assert api.get("/suppliers", params={"status": "ACTIVE"}).json()["total"] == 0


def test_supplier_has_no_rating_or_score(api: Api) -> None:
    created = api.create("/suppliers", SUPPLIER)

    assert not {"rating", "score", "reliability", "risk_score"} & set(created)
    error = error_of(
        api.post("/suppliers", json={**SUPPLIER, "supplier_code": "S2", "reliability": 0.9}),
        422,
        "VALIDATION_ERROR",
    )
    assert detail_codes(error) == {("reliability", "UNKNOWN_FIELD")}


def test_supplier_code_is_unique_and_immutable(api: Api) -> None:
    created = api.create("/suppliers", SUPPLIER)

    error_of(api.post("/suppliers", json=SUPPLIER), 409, "DUPLICATE_NATURAL_KEY")
    error = error_of(
        api.patch(f"/suppliers/{created['id']}", json={"supplier_code": "X"}),
        422,
        "VALIDATION_ERROR",
    )
    assert detail_codes(error) == {("supplier_code", "UNKNOWN_FIELD")}
    error_of(api.get(f"/suppliers/{uuid4()}"), 404, "NOT_FOUND")


# --- equipment ------------------------------------------------------------------------


@pytest.fixture
def project_id(api: Api) -> str:
    return str(api.create("/projects", {"code": "DC-IN-001", "name": "North Ridge"})["id"])


def equipment_body(project_id: str, **changes: object) -> dict[str, object]:
    body: dict[str, object] = {
        "project_id": project_id,
        "equipment_code": "DG-003",
        "name": "Diesel generator set 3",
        "category": "GENERATOR",
        "criticality": "CRITICAL",
        "required_on_site_date": "2027-01-18",
        "specification": {
            "description": "2.5 MVA standby",
            "manufacturer": "Ostrava Genset Systems",
        },
    }
    body.update(changes)
    return body


def test_equipment_exists_without_a_purchase_order_or_supplier(api: Api, project_id: str) -> None:
    """A critical item nobody has ordered yet is a valid record: the procurement gap."""
    created = api.create("/equipment", equipment_body(project_id))

    assert created["criticality"] == "CRITICAL"
    assert created["procurement_status"] == "NOT_STARTED"
    assert created["specification"] == {
        "description": "2.5 MVA standby",
        "manufacturer": "Ostrava Genset Systems",
        "model": None,
        "notes": None,
    }
    assert not {"supplier_id", "purchase_order_id"} & set(created)
    assert api.get(f"/equipment/{created['id']}").json() == created


def test_equipment_without_a_required_date_is_accepted(api: Api, project_id: str) -> None:
    created = api.create(
        "/equipment", equipment_body(project_id, required_on_site_date=None, specification=None)
    )

    assert created["required_on_site_date"] is None
    assert created["specification"] is None


def test_invalid_equipment_project_returns_a_structured_error(api: Api, project_id: str) -> None:
    error = error_of(
        api.post("/equipment", json=equipment_body(str(uuid4()))), 422, "VALIDATION_ERROR"
    )

    assert detail_codes(error) == {("project_id", "REFERENCE_NOT_FOUND")}
    assert api.get("/equipment").json()["total"] == 0


def test_a_project_of_another_workspace_looks_exactly_like_a_missing_one(
    api: Api, session: Session, project_id: str
) -> None:
    other = factories.make_workspace(session, workspace_id=uuid4(), slug="other")
    foreign_project = factories.make_project(session, other, code="DC-IN-001")

    foreign = api.post("/equipment", json=equipment_body(str(foreign_project.id)))
    missing = api.post("/equipment", json=equipment_body(str(uuid4())))

    assert foreign.status_code == missing.status_code == 422
    assert foreign.json()["error"]["details"] == missing.json()["error"]["details"]


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"category": "REACTOR"}, ("category", "INVALID_ENUM")),
        ({"criticality": "URGENT"}, ("criticality", "INVALID_ENUM")),
        ({"procurement_status": "AT_RISK"}, ("procurement_status", "INVALID_ENUM")),
        ({"required_on_site_date": "18/01/2027"}, ("required_on_site_date", "INVALID_DATE")),
        ({"specification": {"voltage": "33kV"}}, ("specification.voltage", "UNKNOWN_FIELD")),
        ({"supplier_id": str(uuid4())}, ("supplier_id", "UNKNOWN_FIELD")),
        ({"risk_level": "HIGH"}, ("risk_level", "UNKNOWN_FIELD")),
    ],
)
def test_equipment_validation(
    api: Api, project_id: str, change: dict[str, object], expected: tuple[str, str]
) -> None:
    error = error_of(
        api.post("/equipment", json=equipment_body(project_id, **change)), 422, "VALIDATION_ERROR"
    )

    assert expected in detail_codes(error)


def test_equipment_code_is_unique_within_the_workspace(api: Api, project_id: str) -> None:
    api.create("/equipment", equipment_body(project_id))
    second_project = api.create("/projects", {"code": "DC-IN-002", "name": "Second"})["id"]

    error = error_of(
        api.post("/equipment", json=equipment_body(second_project)), 409, "DUPLICATE_NATURAL_KEY"
    )

    assert detail_codes(error) == {("equipment_code", "DUPLICATE_NATURAL_KEY")}


def test_equipment_update_changes_only_the_permitted_fields(api: Api, project_id: str) -> None:
    created = api.create("/equipment", equipment_body(project_id))
    path = f"/equipment/{created['id']}"

    updated = api.patch(
        path,
        json={
            "procurement_status": "RFQ",
            "criticality": "HIGH",
            "specification": {"notes": "re-rated"},
        },
    ).json()

    assert (updated["procurement_status"], updated["criticality"]) == ("RFQ", "HIGH")
    assert updated["specification"] == {
        "description": None,
        "manufacturer": None,
        "model": None,
        "notes": "re-rated",
    }
    assert updated["equipment_code"] == "DG-003"

    for forbidden in ({"equipment_code": "X"}, {"project_id": str(uuid4())}):
        error = error_of(api.patch(path, json=forbidden), 422, "VALIDATION_ERROR")
        assert next(iter(detail_codes(error)))[1] == "UNKNOWN_FIELD"
    error_of(api.patch(path, json={"criticality": None}), 422, "VALIDATION_ERROR")

    cleared = api.patch(path, json={"required_on_site_date": None, "specification": None}).json()
    assert (cleared["required_on_site_date"], cleared["specification"]) == (None, None)


def test_equipment_list_filters(api: Api, project_id: str) -> None:
    second_project = api.create("/projects", {"code": "DC-IN-002", "name": "Second"})["id"]
    api.create(
        "/equipment", equipment_body(project_id, equipment_code="TR-001", category="TRANSFORMER")
    )
    api.create(
        "/equipment", equipment_body(project_id, equipment_code="DG-001", criticality="HIGH")
    )
    api.create(
        "/equipment",
        equipment_body(
            second_project,
            equipment_code="CH-001",
            category="COOLING",
            procurement_status="ORDERED",
        ),
    )

    def codes(**params: str) -> list[str]:
        return [
            item["equipment_code"] for item in api.get("/equipment", params=params).json()["items"]
        ]

    assert codes() == ["CH-001", "DG-001", "TR-001"]
    assert codes(project_id=project_id) == ["DG-001", "TR-001"]
    assert codes(category="GENERATOR") == ["DG-001"]
    assert codes(criticality="CRITICAL") == ["CH-001", "TR-001"]
    assert codes(procurement_status="ORDERED") == ["CH-001"]
    assert codes(project_id=second_project, category="TRANSFORMER") == []
    error_of(api.get("/equipment", params={"category": "REACTOR"}), 422, "VALIDATION_ERROR")


def test_workspace_fixture_is_the_configured_one(api: Api, workspace: Workspace) -> None:
    body = api.get().json()

    assert (body["id"], body["slug"], body["status"]) == (str(workspace.id), "nexus-test", "ACTIVE")
