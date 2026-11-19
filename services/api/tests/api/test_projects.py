"""Project routes: create, list, get, update, and the rules around the natural key."""

from uuid import uuid4

import pytest

from tests.conftest import Api, detail_codes, error_of

PROJECT = {
    "code": "DC-IN-001",
    "name": "North Ridge Data Centre Phase 1",
    "location": "Pune, Maharashtra",
    "status": "ACTIVE",
    "target_completion_date": "2027-09-30",
}

pytestmark = pytest.mark.db


def test_create_get_list_update(api: Api) -> None:
    created = api.create("/projects", PROJECT)

    assert {key: created[key] for key in PROJECT} == PROJECT
    assert created["workspace_id"] == str(api.workspace_id)
    assert created["created_at"].endswith("Z")

    fetched = api.get(f"/projects/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json() == created

    listed = api.get("/projects").json()
    assert listed == {"items": [created], "total": 1, "limit": 50, "offset": 0}

    updated = api.patch(f"/projects/{created['id']}", json={"status": "ON_HOLD", "location": None})
    assert updated.status_code == 200
    body = updated.json()
    assert (body["status"], body["location"], body["name"]) == ("ON_HOLD", None, PROJECT["name"])
    assert body["code"] == "DC-IN-001"
    assert body["updated_at"] >= created["updated_at"]


def test_defaults_and_trimmed_text(api: Api) -> None:
    created = api.create("/projects", {"code": "  DC-2  ", "name": "  Second  "})

    assert (created["code"], created["name"]) == ("DC-2", "Second")
    assert created["status"] == "PLANNING"
    assert created["location"] is None
    assert created["target_completion_date"] is None


def test_duplicate_code_is_a_conflict(api: Api) -> None:
    api.create("/projects", PROJECT)

    error = error_of(api.post("/projects", json=PROJECT), 409, "DUPLICATE_NATURAL_KEY")

    assert detail_codes(error) == {("code", "DUPLICATE_NATURAL_KEY")}
    assert api.get("/projects").json()["total"] == 1


def test_the_code_cannot_be_changed(api: Api) -> None:
    created = api.create("/projects", PROJECT)

    error = error_of(
        api.patch(f"/projects/{created['id']}", json={"code": "DC-IN-002"}), 422, "VALIDATION_ERROR"
    )

    assert detail_codes(error) == {("code", "UNKNOWN_FIELD")}
    assert api.get(f"/projects/{created['id']}").json()["code"] == "DC-IN-001"


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"status": "PAUSED"}, ("status", "INVALID_ENUM")),
        ({"target_completion_date": "30/09/2027"}, ("target_completion_date", "INVALID_DATE")),
        (
            {"target_completion_date": "2027-09-30T00:00:00"},
            ("target_completion_date", "INVALID_DATE"),
        ),
        ({"name": ""}, ("name", "VALUE_TOO_SHORT")),
        ({"name": "x" * 201}, ("name", "VALUE_TOO_LONG")),
        ({"code": "x" * 65}, ("code", "VALUE_TOO_LONG")),
        ({"risk_score": 0.9}, ("risk_score", "UNKNOWN_FIELD")),
    ],
)
def test_invalid_content_is_rejected_with_field_and_code(
    api: Api, change: dict[str, object], expected: tuple[str, str]
) -> None:
    error = error_of(api.post("/projects", json={**PROJECT, **change}), 422, "VALIDATION_ERROR")

    assert expected in detail_codes(error)
    assert api.get("/projects").json()["total"] == 0


def test_missing_required_fields(api: Api) -> None:
    error = error_of(api.post("/projects", json={}), 422, "VALIDATION_ERROR")

    assert detail_codes(error) == {
        ("code", "REQUIRED_FIELD_MISSING"),
        ("name", "REQUIRED_FIELD_MISSING"),
    }


def test_null_is_refused_for_a_required_field_on_update(api: Api) -> None:
    created = api.create("/projects", PROJECT)

    error = error_of(
        api.patch(f"/projects/{created['id']}", json={"name": None}), 422, "VALIDATION_ERROR"
    )

    assert detail_codes(error) == {("name", "REQUIRED_FIELD_MISSING")}


def test_an_empty_update_changes_nothing(api: Api) -> None:
    created = api.create("/projects", PROJECT)

    response = api.patch(f"/projects/{created['id']}", json={})

    assert response.status_code == 200
    assert response.json() == created


def test_unknown_project_is_not_found(api: Api) -> None:
    error_of(api.get(f"/projects/{uuid4()}"), 404, "NOT_FOUND")
    error_of(api.patch(f"/projects/{uuid4()}", json={"name": "x"}), 404, "NOT_FOUND")
    error = error_of(api.get("/projects/not-a-uuid"), 422, "VALIDATION_ERROR")
    assert detail_codes(error) == {("project_id", "INVALID_UUID")}


def test_list_is_ordered_filtered_and_bounded(api: Api) -> None:
    for code, status in [("C", "ACTIVE"), ("A", "PLANNING"), ("B", "ACTIVE")]:
        api.create("/projects", {"code": code, "name": code, "status": status})

    everything = api.get("/projects").json()
    assert [item["code"] for item in everything["items"]] == ["A", "B", "C"]

    page = api.get("/projects", params={"limit": 1, "offset": 1}).json()
    assert [item["code"] for item in page["items"]] == ["B"]
    assert (page["total"], page["limit"], page["offset"]) == (3, 1, 1)

    active = api.get("/projects", params={"status": "ACTIVE"}).json()
    assert [item["code"] for item in active["items"]] == ["B", "C"]
    assert active["total"] == 2


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"offset": -1}, {"limit": "x"}])
def test_paging_parameters_are_bounded(api: Api, params: dict[str, object]) -> None:
    error_of(api.get("/projects", params=params), 422, "VALIDATION_ERROR")
