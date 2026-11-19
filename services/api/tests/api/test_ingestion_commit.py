"""Import commit over HTTP: row outcomes, replay, failure, and the batch afterwards."""

from typing import Any
from uuid import uuid4

import pytest
from httpx2 import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Equipment, IngestionBatch, Project, Supplier
from tests.conftest import Api, error_of
from tests.factories import csv_bytes

pytestmark = pytest.mark.db

SUPPLIER_HEADERS = ["Supplier Code", "Supplier Name", "Country", "City", "Status"]
EQUIPMENT_HEADERS = [
    "Equipment Code",
    "Project Code",
    "Equipment Name",
    "Category",
    "Required On-Site Date",
    "Criticality",
]


def preview(
    api: Api,
    entity_type: str,
    headers: list[str],
    rows: list[list[Any]],
    filename: str = "upload.csv",
) -> dict[str, Any]:
    response = api.post(
        "/ingestion/preview",
        files={"file": (filename, csv_bytes(headers, rows), "text/csv")},
        data={"entity_type": entity_type},
    )
    assert response.status_code in (200, 201), response.text
    body: dict[str, Any] = response.json()
    return body


def commit(api: Api, batch_id: str) -> Response:
    return api.post(f"/ingestion/{batch_id}/commit")


def count(session: Session, model: type) -> int:
    session.rollback()
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def test_commit_returns_counters_and_row_outcomes(api: Api, session: Session) -> None:
    batch = preview(
        api,
        "supplier",
        SUPPLIER_HEADERS,
        [
            ["SUP-1", "One", "India", "Pune", "ACTIVE"],
            ["SUP-2", "", "", "", ""],
            ["SUP-3", "Three", "", "", ""],
        ],
        filename="suppliers.csv",
    )
    assert (batch["valid_rows"], batch["invalid_rows"]) == (2, 1)

    response = commit(api, batch["batch_id"])

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "batch_id",
        "status",
        "entity_type",
        "replayed",
        "total_rows",
        "valid_rows",
        "invalid_rows",
        "committed_rows",
        "skipped_rows",
        "failed_rows",
        "entities",
        "committed_at",
    }
    assert (body["status"], body["entity_type"], body["replayed"]) == (
        "COMMITTED",
        "supplier",
        False,
    )
    # Valid, invalid, committed and skipped are four separate numbers.
    assert (body["total_rows"], body["valid_rows"], body["invalid_rows"]) == (3, 2, 1)
    assert (body["committed_rows"], body["skipped_rows"], body["failed_rows"]) == (2, 0, 0)
    assert body["entities"] == {"supplier": {"created": 2, "updated": 0, "unchanged": 0}}
    assert body["committed_at"].endswith("Z")

    suppliers = {s["supplier_code"]: s["id"] for s in api.get("/suppliers").json()["items"]}
    assert set(suppliers) == {"SUP-1", "SUP-3"}
    detail = api.get(f"/ingestion/{batch['batch_id']}").json()
    assert (detail["status"], detail["committed_rows"], detail["failure_code"]) == (
        "COMMITTED",
        2,
        None,
    )
    assert detail["committed_at"] == body["committed_at"]
    assert [
        (
            row["row_number"],
            row["status"],
            row["outcome"],
            row["canonical_entity_type"],
            row["canonical_entity_id"],
        )
        for row in detail["rows"]["items"]
    ] == [
        (2, "COMMITTED", "CREATED", "supplier", suppliers["SUP-1"]),
        (3, "INVALID", None, None, None),
        (4, "COMMITTED", "CREATED", "supplier", suppliers["SUP-3"]),
    ]
    only_invalid = api.get(f"/ingestion/{batch['batch_id']}", params={"status": "INVALID"}).json()
    assert [row["validation_errors"][0]["code"] for row in only_invalid["rows"]["items"]] == [
        "REQUIRED_FIELD_MISSING"
    ]


def test_repeated_commit_does_not_duplicate_records(api: Api, session: Session) -> None:
    batch = preview(
        api,
        "supplier",
        SUPPLIER_HEADERS,
        [["SUP-1", "One", "", "", ""], ["SUP-2", "Two", "", "", ""]],
    )
    first = commit(api, batch["batch_id"]).json()

    replays = [commit(api, batch["batch_id"]) for _ in range(3)]

    assert [r.status_code for r in replays] == [200, 200, 200]
    for replay in replays:
        body = replay.json()
        assert body["replayed"] is True
        # The recorded result of the first commit, unchanged.
        assert {k: v for k, v in body.items() if k != "replayed"} == {
            k: v for k, v in first.items() if k != "replayed"
        }
    assert count(session, Supplier) == 2
    assert count(session, IngestionBatch) == 1


def test_uploading_a_committed_file_again_reports_the_committed_batch(
    api: Api, session: Session
) -> None:
    rows = [["SUP-1", "One", "", "", ""]]
    batch = preview(api, "supplier", SUPPLIER_HEADERS, rows)
    commit(api, batch["batch_id"])

    again = api.post(
        "/ingestion/preview",
        files={"file": ("other-name.csv", csv_bytes(SUPPLIER_HEADERS, rows), "text/csv")},
        data={"entity_type": "supplier"},
    )

    assert again.status_code == 200
    body = again.json()
    assert (body["batch_id"], body["status"], body["duplicate_file"]) == (
        batch["batch_id"],
        "COMMITTED",
        True,
    )
    assert count(session, Supplier) == 1
    assert count(session, IngestionBatch) == 1


def test_a_different_file_with_the_same_keys_updates_instead_of_duplicating(
    api: Api, session: Session
) -> None:
    commit(
        api,
        preview(api, "supplier", SUPPLIER_HEADERS, [["SUP-1", "One", "India", "Pune", "ACTIVE"]])[
            "batch_id"
        ],
    )
    supplier_id = api.get("/suppliers").json()["items"][0]["id"]

    second = preview(
        api,
        "supplier",
        SUPPLIER_HEADERS,
        [["SUP-1", "One Ltd", "", "", ""], ["SUP-2", "Two", "", "", ""]],
    )
    assert second["planned_actions"] == {"CREATE": 1, "UPDATE": 1, "NO_CHANGE": 0}
    body = commit(api, second["batch_id"]).json()

    assert body["entities"] == {"supplier": {"created": 1, "updated": 1, "unchanged": 0}}
    assert count(session, Supplier) == 2
    stored = api.get(f"/suppliers/{supplier_id}").json()
    assert (stored["name"], stored["country"], stored["city"]) == (
        "One Ltd",
        "India",
        "Pune",
    )  # blanks kept the stored values


def test_commit_status_codes(api: Api, session: Session) -> None:
    error_of(commit(api, str(uuid4())), 404, "NOT_FOUND")
    error_of(commit(api, "not-a-uuid"), 422, "VALIDATION_ERROR")

    nothing_valid = preview(api, "supplier", SUPPLIER_HEADERS, [["", "No code", "", "", ""]])
    error = error_of(commit(api, nothing_valid["batch_id"]), 409, "BATCH_NOT_COMMITTABLE")
    assert "no valid row" in error["message"]
    assert api.get(f"/ingestion/{nothing_valid['batch_id']}").json()["status"] == "PREVIEWED"


def test_a_commit_that_no_longer_holds_fails_as_a_whole(api: Api, session: Session) -> None:
    project = api.create("/projects", {"code": "DC-1", "name": "One"})
    supplier = api.create("/suppliers", {"supplier_code": "SUP-1", "name": "One"})
    rows = [["PO-1", "DC-1", "SUP-1", "INR", "ISSUED"], ["PO-2", "DC-1", "SUP-1", "INR", "ISSUED"]]
    headers = ["PO Number", "Project Code", "Supplier Code", "Currency", "Status"]
    batch = preview(api, "purchase_order", headers, rows)
    assert batch["valid_rows"] == 2

    api.patch(f"/suppliers/{supplier['id']}", json={"status": "INACTIVE"})
    response = commit(api, batch["batch_id"])

    error = error_of(response, 409, "COMMIT_CONFLICT")
    assert [(d["row_number"], d["column"], d["code"]) for d in error["details"]] == [
        (2, "supplier_code", "REFERENCE_INACTIVE"),
        (3, "supplier_code", "REFERENCE_INACTIVE"),
    ]
    assert api.get("/purchase-orders").json()["total"] == 0
    detail = api.get(f"/ingestion/{batch['batch_id']}").json()
    assert (
        detail["status"],
        detail["failure_code"],
        detail["failed_rows"],
        detail["committed_at"],
    ) == (
        "FAILED",
        "COMMIT_CONFLICT",
        2,
        None,
    )
    assert [(row["status"], row["outcome"]) for row in detail["rows"]["items"]] == [
        ("FAILED", "REJECTED")
    ] * 2
    error_of(commit(api, batch["batch_id"]), 409, "BATCH_NOT_COMMITTABLE")
    assert api.get("/ingestion/batches", params={"status": "FAILED"}).json()["total"] == 1
    assert project["code"] == "DC-1"


def test_preview_then_commit_is_the_only_way_a_file_becomes_records(
    api: Api, session: Session
) -> None:
    api.create("/projects", {"code": "DC-1", "name": "One"})
    batch = preview(
        api,
        "equipment",
        EQUIPMENT_HEADERS,
        [["DG-003", "DC-1", "Diesel generator set 3", "Generator", "2027-01-18", "CRITICAL"]],
    )
    assert count(session, Equipment) == 0  # previewed: still nothing

    body = commit(api, batch["batch_id"]).json()

    assert body["entities"] == {"equipment": {"created": 1, "updated": 0, "unchanged": 0}}
    (equipment,) = api.get("/equipment").json()["items"]
    assert (equipment["equipment_code"], equipment["criticality"], equipment["category"]) == (
        "DG-003",
        "CRITICAL",
        "GENERATOR",
    )
    sources = api.get(
        "/ingestion/sources", params={"entity_type": "equipment", "entity_id": equipment["id"]}
    ).json()
    assert [
        (s["original_filename"], s["row_number"], s["row_status"], s["outcome"])
        for s in sources["items"]
    ] == [("upload.csv", 2, "COMMITTED", "CREATED")]
    assert count(session, Project) == 1


def test_sources_of_an_unknown_record_and_invalid_parameters(api: Api) -> None:
    empty = api.get(
        "/ingestion/sources", params={"entity_type": "project", "entity_id": str(uuid4())}
    ).json()
    assert empty == {"items": [], "total": 0, "limit": 50, "offset": 0}
    error_of(
        api.get(
            "/ingestion/sources", params={"entity_type": "risk_finding", "entity_id": str(uuid4())}
        ),
        422,
        "VALIDATION_ERROR",
    )
    error_of(
        api.get("/ingestion/sources", params={"entity_type": "project"}), 422, "VALIDATION_ERROR"
    )
