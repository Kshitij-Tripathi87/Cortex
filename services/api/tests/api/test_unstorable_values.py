"""Values the database cannot hold are refused as input, never met as a failure.

PostgreSQL text cannot contain the NUL character and an INTEGER column ends
at 2,147,483,647. A request or a file that carries such a value is answered
with a validation error that names the field or the row. None of these may
reach the database and come back as an internal error, and a row that passes
preview must always be storable at commit.
"""

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import IngestionBatch, Milestone, Project
from app.models.limits import INTEGER_MAX
from tests.conftest import Api, detail_codes, error_of
from tests.factories import csv_bytes
from tests.importing import MILESTONE_HEADERS, SUPPLIER_HEADERS

pytestmark = pytest.mark.db

NUL = "\x00"


@pytest.fixture
def order(api: Api) -> str:
    """A purchase order to hang milestones and commitments on."""
    project = api.create("/projects", {"code": "DC-1", "name": "Project"})["id"]
    supplier = api.create("/suppliers", {"supplier_code": "SUP-1", "name": "Supplier"})["id"]
    body = {"project_id": project, "supplier_id": supplier, "po_number": "PO-1", "currency": "INR"}
    return str(api.create("/purchase-orders", body)["id"])


def upload(api: Api, entity_type: str, data: bytes, filename: str = "file.csv") -> Any:
    return api.post(
        "/ingestion/preview",
        files={"file": (filename, data, "text/csv")},
        data={"entity_type": entity_type},
    )


# --- text --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "body", "field"),
    [
        ("/projects", {"code": "DC-9", "name": f"North{NUL}Ridge"}, "name"),
        ("/projects", {"code": f"DC{NUL}9", "name": "North Ridge"}, "code"),
        ("/projects", {"code": "DC-9", "name": "n", "location": f"x{NUL}"}, "location"),
        ("/suppliers", {"supplier_code": "S-9", "name": "n", "city": f"{NUL}Pune"}, "city"),
    ],
)
def test_text_with_a_nul_character_is_a_validation_error(
    api: Api, session: Session, path: str, body: dict[str, Any], field: str
) -> None:
    error = error_of(api.post(path, json=body), 422, "VALIDATION_ERROR")

    assert detail_codes(error) == {(field, "INVALID_VALUE")}
    # The message names the rule and does not repeat the value.
    assert NUL not in str(error)
    assert session.scalar(select(Project).where(Project.code == "DC-9")) is None


def test_a_nul_character_is_refused_in_updates_notes_and_actor_names(api: Api, order: str) -> None:
    project = api.get("/projects").json()["items"][0]["id"]
    patched = api.patch(f"/projects/{project}", json={"location": f"Pune{NUL}"})
    assert detail_codes(error_of(patched, 422, "VALIDATION_ERROR")) == {
        ("location", "INVALID_VALUE")
    }

    equipment = {
        "project_id": project,
        "equipment_code": "EQ-1",
        "name": "UPS",
        "category": "UPS",
        "criticality": "HIGH",
        "specification": {"notes": f"see{NUL}drawing"},
    }
    assert detail_codes(
        error_of(api.post("/equipment", json=equipment), 422, "VALIDATION_ERROR")
    ) == {("specification.notes", "INVALID_VALUE")}

    commitment = {"committed_delivery_date": "2027-01-10", "recorded_by": f"a{NUL}b"}
    response = api.post(f"/purchase-orders/{order}/commitments", json=commitment)
    assert detail_codes(error_of(response, 422, "VALIDATION_ERROR")) == {
        ("recorded_by", "INVALID_VALUE")
    }
    assert api.get(f"/purchase-orders/{order}/commitments").json()["total"] == 0


def test_a_text_file_with_a_nul_character_is_not_a_text_file(api: Api, session: Session) -> None:
    data = csv_bytes(SUPPLIER_HEADERS, [["SUP-1", f"Bad{NUL}Name", "", "", ""]])

    error_of(upload(api, "supplier", data), 415, "UNSUPPORTED_FILE")

    assert session.scalar(select(IngestionBatch)) is None


def test_control_characters_never_reach_the_stored_file_name(api: Api) -> None:
    """The file name comes from the client and is display text only."""
    data = csv_bytes(SUPPLIER_HEADERS, [["SUP-1", "Supplier", "", "", ""]])
    boundary = "nexus-boundary"
    sent_name = f"..\\\\secret/sup{NUL}pli\x07ers.csv"  # a path, a NUL and a bell
    # Written by hand: a well-behaved client would escape the name.
    body = (
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="entity_type"\r\n\r\n'
            "supplier\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{sent_name}"\r\n'
            "Content-Type: text/csv\r\n\r\n"
        ).encode()
        + data
        + f"\r\n--{boundary}--\r\n".encode()
    )

    response = api.post(
        "/ingestion/preview",
        content=body,
        headers={"content-type": f"multipart/form-data; boundary={boundary}"},
    )

    assert response.status_code == 201, response.text
    assert response.json()["original_filename"] == "suppliers.csv"


# --- whole numbers -----------------------------------------------------------------------


def test_the_largest_sequence_number_the_database_holds_is_accepted(api: Api, order: str) -> None:
    body = {"milestone_type": "DELIVERY", "sequence_no": INTEGER_MAX, "planned_date": "2026-12-01"}

    created = api.create(f"/purchase-orders/{order}/milestones", body)

    assert created["sequence_no"] == INTEGER_MAX


@pytest.mark.parametrize("sequence_no", [INTEGER_MAX + 1, 99_999_999_999, 10**40])
def test_a_sequence_number_beyond_it_is_a_validation_error(
    api: Api, order: str, session: Session, sequence_no: int
) -> None:
    body = {"milestone_type": "DELIVERY", "sequence_no": sequence_no, "planned_date": "2026-12-01"}

    error = error_of(
        api.post(f"/purchase-orders/{order}/milestones", json=body), 422, "VALIDATION_ERROR"
    )

    assert {field for field, _ in detail_codes(error)} == {"sequence_no"}
    assert session.scalar(select(Milestone)) is None


@pytest.mark.parametrize("sequence_no", ["1", 1.0, 1.5, True, None, [1]])
def test_a_sequence_number_is_a_json_whole_number_and_nothing_else(
    api: Api, order: str, sequence_no: object
) -> None:
    body = {"milestone_type": "DELIVERY", "sequence_no": sequence_no, "planned_date": "2026-12-01"}

    error = error_of(
        api.post(f"/purchase-orders/{order}/milestones", json=body), 422, "VALIDATION_ERROR"
    )

    assert detail_codes(error) == {("sequence_no", "INVALID_INTEGER")}


def test_a_row_with_a_sequence_number_beyond_it_is_invalid_at_preview(
    api: Api, order: str, session: Session
) -> None:
    """Refused where the operator can see it: at preview, on the row, by column."""
    data = csv_bytes(
        MILESTONE_HEADERS,
        [
            ["PO-1", "DELIVERY", str(INTEGER_MAX), "2026-12-01", "", ""],
            ["PO-1", "DISPATCH", str(INTEGER_MAX + 1), "2026-12-01", "", ""],
            ["PO-1", "INSTALLATION", "9" * 60, "2026-12-01", "", ""],
        ],
    )

    preview = upload(api, "milestone", data)

    assert preview.status_code == 201, preview.text
    body = preview.json()
    assert (body["valid_rows"], body["invalid_rows"]) == (1, 2)
    assert [(issue["row_number"], issue["column"], issue["code"]) for issue in body["errors"]] == [
        (3, "sequence_no", "INVALID_INTEGER"),
        (4, "sequence_no", "INVALID_INTEGER"),
    ]

    # What preview called valid can be stored.
    committed = api.post(f"/ingestion/{body['batch_id']}/commit")
    assert committed.status_code == 200, committed.text
    assert committed.json()["committed_rows"] == 1
    session.rollback()
    assert [milestone.sequence_no for milestone in session.scalars(select(Milestone))] == [
        INTEGER_MAX
    ]


# --- paging ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/projects",
        "/suppliers",
        "/equipment",
        "/purchase-orders",
        "/ingestion/batches",
        "/world-state",
    ],
)
def test_an_absurd_offset_is_a_validation_error(api: Api, path: str) -> None:
    for offset in (INTEGER_MAX + 1, 99_999_999_999_999_999_999_999):
        error = error_of(api.get(path, params={"offset": offset}), 422, "VALIDATION_ERROR")
        assert detail_codes(error) == {("offset", "OUT_OF_RANGE")}

    assert api.get(path, params={"offset": INTEGER_MAX}).status_code == 200


def test_absurd_offsets_of_the_project_world_state_are_validation_errors(api: Api) -> None:
    project = api.create("/projects", {"code": "DC-1", "name": "Project"})["id"]
    path = f"/world-state/projects/{project}"

    for name in ("equipment_offset", "po_offset"):
        error = error_of(api.get(path, params={name: 10**30}), 422, "VALIDATION_ERROR")
        assert detail_codes(error) == {(name, "OUT_OF_RANGE")}

    assert api.get(path, params={"equipment_offset": INTEGER_MAX}).status_code == 200


# --- the net under all of it -------------------------------------------------------------


def test_a_value_the_database_refuses_is_answered_as_invalid_input(
    app: FastAPI, session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    """Should validation ever miss a value, the answer is still not an internal error."""

    def store_unvalidated_text() -> None:
        session.add(Project(workspace_id=None, code="DC-1", name=f"secret{NUL}value"))
        session.flush()

    app.add_api_route("/_probe/unvalidated", store_unvalidated_text, methods=["GET"])

    with TestClient(app) as client:
        response = client.get("/_probe/unvalidated")

    error = error_of(response, 422, "VALIDATION_ERROR")
    assert error["details"] == []
    assert "secret" not in response.text
    # Logged as an error so the gap is noticed; the value is not in the log.
    records = [record for record in caplog.records if record.name == "app.error"]
    assert [record.levelname for record in records] == ["ERROR"]
    assert "secret" not in caplog.text
