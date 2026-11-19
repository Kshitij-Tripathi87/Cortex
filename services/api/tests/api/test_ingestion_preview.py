"""Import preview over HTTP: upload checks, the report, and what preview never does."""

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.main import create_app
from app.models import (
    Equipment,
    IngestionBatch,
    IngestionRow,
    Milestone,
    Project,
    PurchaseOrder,
    PurchaseOrderItem,
    Supplier,
    SupplierCommitmentVersion,
    Workspace,
)
from tests.conftest import Api, error_of, make_settings
from tests.factories import csv_bytes, xlsx_bytes

pytestmark = pytest.mark.db

CSV = "text/csv"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CANONICAL = (
    Project,
    Supplier,
    Equipment,
    PurchaseOrder,
    PurchaseOrderItem,
    Milestone,
    SupplierCommitmentVersion,
)

PROJECTS = csv_bytes(
    ["Project Code", "Project Name", "Location", "Status", "Target Completion Date"],
    [["DC-IN-001", "North Ridge Data Centre Phase 1", "Pune, Maharashtra", "ACTIVE", "2027-09-30"]],
)
EQUIPMENT_HEADERS = [
    "Equipment Code",
    "Project Code",
    "Equipment Name",
    "Category",
    "Required On-Site Date",
    "Criticality",
    "Vendor Notes",
]
EQUIPMENT = csv_bytes(
    EQUIPMENT_HEADERS,
    [
        [
            "TR-001",
            "DC-IN-001",
            "Main transformer 1",
            "Transformer",
            "2027-02-01",
            "CRITICAL",
            "call first",
        ],
        ["TR-002", "DC-IN-001", "Main transformer 2", "Transformer", "03/04/26", "HIGH", ""],
        ["TR-003", "DC-XX-999", "Main transformer 3", "Transformer", "2027-02-01", "HIGH", ""],
    ],
)


def upload(
    api: Api,
    data: bytes,
    entity_type: str,
    *,
    filename: str = "upload.csv",
    content_type: str = CSV,
    **form: str,
) -> Response:
    return api.post(
        "/ingestion/preview",
        files={"file": (filename, data, content_type)},
        data={"entity_type": entity_type, **form},
    )


def counts(session: Session, *models: type) -> dict[str, int]:
    session.rollback()
    return {
        model.__name__: int(session.scalar(select(func.count()).select_from(model)) or 0)
        for model in models
    }


@pytest.fixture
def project(api: Api) -> dict[str, Any]:
    return api.create("/projects", {"code": "DC-IN-001", "name": "North Ridge"})


# --- upload checks --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [
        ("projects.xls", "application/vnd.ms-excel"),
        ("projects.xlsm", XLSX),
        ("projects.pdf", "application/pdf"),
        ("projects.json", "application/json"),
        ("projects", CSV),
        ("projects.csv", "image/png"),
    ],
)
def test_unsupported_file_returns_415(
    api: Api, session: Session, filename: str, content_type: str
) -> None:
    response = upload(api, PROJECTS, "project", filename=filename, content_type=content_type)

    error_of(response, 415, "UNSUPPORTED_FILE")
    assert counts(session, IngestionBatch, Project) == {"IngestionBatch": 0, "Project": 0}


def test_content_that_contradicts_the_extension_returns_415(api: Api) -> None:
    workbook = xlsx_bytes({"S": [["Project Code", "Project Name"], ["P1", "One"]]})

    error_of(upload(api, workbook, "project", filename="projects.csv"), 415, "UNSUPPORTED_FILE")
    error_of(
        upload(api, PROJECTS, "project", filename="projects.xlsx", content_type=XLSX),
        415,
        "UNSUPPORTED_FILE",
    )


def test_oversized_file_returns_413(session: Session, workspace: Workspace) -> None:
    app = create_app(make_settings(max_upload_size_mb=1))
    too_large = b"Project Code,Project Name\n" + b"P,x\n" * 400_000  # about 1.6 MB

    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/workspaces/{workspace.id}/ingestion/preview",
            files={"file": ("projects.csv", too_large, CSV)},
            data={"entity_type": "project"},
        )

    error = error_of(response, 413, "FILE_TOO_LARGE")
    assert "1 MB" in error["message"]
    assert counts(session, IngestionBatch, IngestionRow, Project) == {
        "IngestionBatch": 0,
        "IngestionRow": 0,
        "Project": 0,
    }


def test_a_file_just_above_the_limit_is_refused_by_the_service_check(
    session: Session, workspace: Workspace
) -> None:
    """Below the request-body guard (limit + multipart allowance) but above the file limit."""
    app = create_app(make_settings(max_upload_size_mb=1))
    header = b"Project Code,Project Name\n"
    slightly_over = header + b"x" * (1024 * 1024 + 10 - len(header))

    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/workspaces/{workspace.id}/ingestion/preview",
            files={"file": ("projects.csv", slightly_over, CSV)},
            data={"entity_type": "project"},
        )

    error_of(response, 413, "FILE_TOO_LARGE")
    assert counts(session, IngestionBatch) == {"IngestionBatch": 0}


def test_row_and_column_limits_are_enforced(session: Session, workspace: Workspace) -> None:
    app = create_app(make_settings(max_import_rows=3, max_import_columns=4))
    base = f"/api/v1/workspaces/{workspace.id}/ingestion/preview"
    too_many_rows = csv_bytes(["Project Code", "Project Name"], [[f"P{i}", "x"] for i in range(4)])
    too_many_columns = csv_bytes(
        ["Project Code", "Project Name", "A", "B", "C"], [["P1", "x", "", "", ""]]
    )

    with TestClient(app) as client:
        rows = client.post(
            base, files={"file": ("p.csv", too_many_rows, CSV)}, data={"entity_type": "project"}
        )
        columns = client.post(
            base, files={"file": ("p.csv", too_many_columns, CSV)}, data={"entity_type": "project"}
        )

    error_of(rows, 422, "ROW_LIMIT_EXCEEDED")
    error_of(columns, 422, "COLUMN_LIMIT_EXCEEDED")
    assert counts(session, IngestionBatch) == {"IngestionBatch": 0}


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"", "EMPTY_FILE"),
        (b"\n\n", "EMPTY_FILE"),
        (b"Project Code,Project Name\n", "EMPTY_FILE"),
        (b"Project Code,Project Code\nP1,P2\n", "DUPLICATE_HEADER"),
        ("Projekt,Näme\nP1,x\n".encode("latin-1"), "INVALID_ENCODING"),
        (b'Project Code,Project Name\n"P1,x\n', "MALFORMED_FILE"),
    ],
)
def test_a_file_that_is_not_a_table_is_refused_and_leaves_no_batch(
    api: Api, session: Session, data: bytes, code: str
) -> None:
    error_of(upload(api, data, "project"), 422, code)

    assert counts(session, IngestionBatch, IngestionRow) == {"IngestionBatch": 0, "IngestionRow": 0}


def test_unknown_entity_type_and_missing_parts(api: Api) -> None:
    error = error_of(upload(api, PROJECTS, "risk_score"), 422, "VALIDATION_ERROR")
    assert (error["details"][0]["field"], error["details"][0]["code"]) == (
        "entity_type",
        "INVALID_ENUM",
    )

    missing_file = api.post("/ingestion/preview", data={"entity_type": "project"})
    error = error_of(missing_file, 422, "VALIDATION_ERROR")
    assert (error["details"][0]["field"], error["details"][0]["code"]) == (
        "file",
        "REQUIRED_FIELD_MISSING",
    )


# --- the preview report ---------------------------------------------------------------


def test_preview_response_contains_row_counts_errors_and_warnings(
    api: Api, project: dict[str, Any]
) -> None:
    response = upload(api, EQUIPMENT, "equipment", filename="equipment.csv")

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "PREVIEWED"
    assert (body["entity_type"], body["source_format"], body["original_filename"]) == (
        "equipment",
        "CSV",
        "equipment.csv",
    )
    assert body["duplicate_file"] is False
    assert (body["total_rows"], body["valid_rows"], body["invalid_rows"]) == (3, 1, 2)
    assert body["planned_actions"] == {"CREATE": 1, "UPDATE": 0, "NO_CHANGE": 0}
    assert body["errors"] == [
        {
            "row_number": 3,
            "column": "required_on_site_date",
            "code": "INVALID_DATE",
            "message": "Use an unambiguous date in YYYY-MM-DD format.",
        },
        {
            "row_number": 4,
            "column": "project_code",
            "code": "REFERENCE_NOT_FOUND",
            "message": (
                "The project does not exist in this workspace. "
                "Import it first or correct the reference."
            ),
        },
    ]
    assert body["warnings"] == [
        {
            "row_number": 2,
            "column": "Vendor Notes",
            "code": "UNKNOWN_SOURCE_COLUMN",
            "message": "Column retained in raw source data but not mapped to a canonical field.",
        }
    ]
    assert (body["errors_count"], body["warnings_count"], body["truncated"]) == (2, 1, False)
    assert body["quality"] == {
        "COMPLETENESS": 0,
        "VALIDITY": 1,
        "CONSISTENCY": 0,
        "UNIQUENESS": 0,
        "REFERENTIAL_INTEGRITY": 1,
    }
    assert len(body["file_sha256"]) == 64


def test_error_messages_do_not_repeat_source_values(api: Api, project: dict[str, Any]) -> None:
    secret = "CONFIDENTIAL-91"
    data = csv_bytes(EQUIPMENT_HEADERS, [[secret, secret, secret, secret, secret, secret, secret]])

    body = upload(api, data, "equipment").json()

    assert body["invalid_rows"] == 1
    assert secret not in str(body["errors"])
    assert secret not in str(body["warnings"])


def test_preview_creates_ledger_entries_and_no_canonical_record(
    api: Api, session: Session, project: dict[str, Any]
) -> None:
    before = counts(session, *CANONICAL)

    body = upload(api, EQUIPMENT, "equipment").json()

    assert counts(session, *CANONICAL) == before  # one project, nothing else, nothing new
    assert before["Equipment"] == 0
    assert counts(session, IngestionBatch, IngestionRow) == {"IngestionBatch": 1, "IngestionRow": 3}
    assert api.get("/equipment").json()["total"] == 0

    detail = api.get(f"/ingestion/{body['batch_id']}").json()
    assert (detail["status"], detail["committed_at"], detail["committed_rows"]) == (
        "PREVIEWED",
        None,
        0,
    )
    rows = detail["rows"]["items"]
    assert [(row["row_number"], row["status"], row["planned_action"]) for row in rows] == [
        (2, "VALID", "CREATE"),
        (3, "INVALID", None),
        (4, "INVALID", None),
    ]
    # The invalid rows are kept, with their source values and the reason.
    assert rows[1]["raw_data"]["Required On-Site Date"] == "03/04/26"
    assert rows[1]["validation_errors"] == [
        {
            "code": "INVALID_DATE",
            "message": "Use an unambiguous date in YYYY-MM-DD format.",
            "column": "required_on_site_date",
        }
    ]
    assert rows[0]["raw_data"]["Vendor Notes"] == "call first"  # the unknown column is retained
    assert rows[0]["normalized_data"] == {
        "equipment_code": "TR-001",
        "project_code": "DC-IN-001",
        "name": "Main transformer 1",
        "category": "TRANSFORMER",
        "required_on_site_date": "2027-02-01",
        "criticality": "CRITICAL",
    }
    assert all(row["canonical_entity_id"] is None and row["outcome"] is None for row in rows)


@pytest.mark.parametrize(
    ("entity_type", "headers", "row"),
    [
        ("project", ["Project Code", "Project Name"], ["P-NEW", "New"]),
        ("supplier", ["Supplier Code", "Supplier Name"], ["S-NEW", "New"]),
        (
            "equipment",
            EQUIPMENT_HEADERS[:6],
            ["E-NEW", "DC-IN-001", "New", "UPS", "2027-01-01", "HIGH"],
        ),
    ],
)
def test_preview_of_any_valid_file_changes_no_canonical_count(
    api: Api,
    session: Session,
    project: dict[str, Any],
    entity_type: str,
    headers: list[str],
    row: list[str],
) -> None:
    before = counts(session, *CANONICAL)

    response = upload(api, csv_bytes(headers, [row]), entity_type)

    assert response.status_code == 201
    assert response.json()["valid_rows"] == 1
    assert counts(session, *CANONICAL) == before


def test_duplicate_and_conflicting_rows_are_told_apart(api: Api) -> None:
    data = csv_bytes(
        ["Supplier Code", "Supplier Name"],
        [
            ["S1", "Acme"],
            ["S1", "Acme"],
            ["S2", "Beta"],
            ["S2", "Beta Industries"],
            ["S3", "Gamma"],
        ],
    )

    body = upload(api, data, "supplier").json()

    assert (body["total_rows"], body["valid_rows"], body["invalid_rows"]) == (5, 3, 2)
    assert body["planned_actions"] == {"CREATE": 2, "UPDATE": 0, "NO_CHANGE": 1}
    assert [(e["row_number"], e["code"]) for e in body["errors"]] == [
        (4, "DUPLICATE_NATURAL_KEY"),
        (5, "DUPLICATE_NATURAL_KEY"),
    ]
    assert [(w["row_number"], w["code"]) for w in body["warnings"]] == [(3, "DUPLICATE_ROW")]
    assert body["quality"]["UNIQUENESS"] == 2


def test_a_purchase_order_that_references_a_missing_supplier_is_blocked(
    api: Api, project: dict[str, Any]
) -> None:
    data = csv_bytes(
        ["PO Number", "Project Code", "Supplier Code", "Currency", "Status"],
        [["PO-1", "DC-IN-001", "SUP-MISSING", "INR", "ISSUED"]],
    )

    body = upload(api, data, "purchase_order").json()

    assert (body["valid_rows"], body["invalid_rows"]) == (0, 1)
    assert [(e["column"], e["code"]) for e in body["errors"]] == [
        ("supplier_code", "REFERENCE_NOT_FOUND")
    ]
    assert api.get("/suppliers").json()["total"] == 0  # the supplier was not made up


def test_issue_lists_are_bounded_and_the_counts_are_complete(api: Api) -> None:
    data = csv_bytes(
        ["Project Code", "Project Name", "Status"],
        [[f"P{i}", "x", "NOT-A-STATUS"] for i in range(150)],
    )

    body = upload(api, data, "project").json()

    assert (body["invalid_rows"], body["errors_count"]) == (150, 150)
    assert len(body["errors"]) == 100
    assert body["truncated"] is True
    detail = api.get(
        f"/ingestion/{body['batch_id']}", params={"limit": 200, "status": "INVALID"}
    ).json()
    assert detail["rows"]["total"] == 150  # every row is still available


# --- the same file again --------------------------------------------------------------


def test_the_same_bytes_resolve_to_the_same_batch(
    api: Api, session: Session, project: dict[str, Any]
) -> None:
    first = upload(api, EQUIPMENT, "equipment", filename="equipment.csv")
    again = upload(api, EQUIPMENT, "equipment", filename="renamed.csv")

    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json()["duplicate_file"] is True
    assert again.json()["batch_id"] == first.json()["batch_id"]
    assert again.json()["original_filename"] == "equipment.csv"
    assert counts(session, IngestionBatch, IngestionRow) == {"IngestionBatch": 1, "IngestionRow": 3}


def test_the_same_bytes_for_another_entity_type_are_a_different_batch(
    api: Api, session: Session
) -> None:
    data = csv_bytes(
        ["Project Code", "Project Name", "Supplier Code", "Supplier Name"],
        [["P1", "One", "S1", "Acme"]],
    )

    as_project = upload(api, data, "project")
    as_supplier = upload(api, data, "supplier")

    assert (as_project.status_code, as_supplier.status_code) == (201, 201)
    assert as_project.json()["batch_id"] != as_supplier.json()["batch_id"]
    assert counts(session, IngestionBatch) == {"IngestionBatch": 2}


def test_a_previewed_file_is_revalidated_when_it_is_uploaded_again(
    api: Api, session: Session
) -> None:
    """Previewed before its dependency existed; valid once the dependency is there."""
    data = csv_bytes(
        EQUIPMENT_HEADERS[:6],
        [["TR-001", "DC-IN-001", "Transformer", "Transformer", "2027-02-01", "CRITICAL"]],
    )

    early = upload(api, data, "equipment").json()
    assert (early["valid_rows"], early["invalid_rows"]) == (0, 1)
    assert early["errors"][0]["code"] == "REFERENCE_NOT_FOUND"

    api.create("/projects", {"code": "DC-IN-001", "name": "North Ridge"})
    refreshed = upload(api, data, "equipment")

    assert refreshed.status_code == 200
    body = refreshed.json()
    assert body["batch_id"] == early["batch_id"]  # the same batch, not a second one
    assert body["duplicate_file"] is True
    assert (body["valid_rows"], body["invalid_rows"], body["errors"]) == (1, 0, [])
    assert body["planned_actions"]["CREATE"] == 1
    assert counts(session, IngestionBatch, IngestionRow, Equipment) == {
        "IngestionBatch": 1,
        "IngestionRow": 1,
        "Equipment": 0,
    }
    row = api.get(f"/ingestion/{body['batch_id']}").json()["rows"]["items"][0]
    assert (row["status"], row["validation_errors"]) == ("VALID", [])


def test_existing_records_are_previewed_as_updates_not_duplicates(
    api: Api, project: dict[str, Any]
) -> None:
    data = csv_bytes(
        ["Project Code", "Project Name", "Status"],
        [["DC-IN-001", "North Ridge", ""], ["DC-IN-001-B", "Second", ""]],
    )
    changed = csv_bytes(
        ["Project Code", "Project Name", "Status"],
        [["DC-IN-001", "North Ridge Phase 1", "ON_HOLD"]],
    )

    assert upload(api, data, "project").json()["planned_actions"] == {
        "CREATE": 1,
        "UPDATE": 0,
        "NO_CHANGE": 1,
    }
    assert upload(api, changed, "project").json()["planned_actions"] == {
        "CREATE": 0,
        "UPDATE": 1,
        "NO_CHANGE": 0,
    }
    # Still only a preview: the stored project is untouched.
    stored = api.get(f"/projects/{project['id']}").json()
    assert (stored["name"], stored["status"]) == ("North Ridge", "PLANNING")


# --- XLSX -----------------------------------------------------------------------------


def test_xlsx_preview_with_typed_cells(api: Api, project: dict[str, Any]) -> None:
    from datetime import date

    workbook = xlsx_bytes(
        {
            "Equipment": [
                EQUIPMENT_HEADERS[:6],
                ["UPS-001", "DC-IN-001", "UPS module 1", "UPS", date(2026, 12, 15), "HIGH"],
            ]
        }
    )

    response = upload(api, workbook, "equipment", filename="equipment.xlsx", content_type=XLSX)

    assert response.status_code == 201
    body = response.json()
    assert (body["source_format"], body["sheet_name"], body["valid_rows"]) == (
        "XLSX",
        "Equipment",
        1,
    )
    row = api.get(f"/ingestion/{body['batch_id']}").json()["rows"]["items"][0]
    assert row["normalized_data"]["required_on_site_date"] == "2026-12-15"


def test_xlsx_with_several_sheets_needs_sheet_name(api: Api, session: Session) -> None:
    workbook = xlsx_bytes(
        {
            "Projects": [["Project Code", "Project Name"], ["P1", "One"]],
            "Suppliers": [["Supplier Code", "Supplier Name"], ["S1", "Acme"], ["S2", "Beta"]],
        }
    )

    ambiguous = upload(api, workbook, "supplier", filename="book.xlsx", content_type=XLSX)
    error = error_of(ambiguous, 422, "AMBIGUOUS_WORKSHEET")
    assert "Projects" in error["message"]
    assert "Suppliers" in error["message"]
    assert counts(session, IngestionBatch) == {"IngestionBatch": 0}

    chosen = upload(
        api, workbook, "supplier", filename="book.xlsx", content_type=XLSX, sheet_name="Suppliers"
    )
    assert chosen.status_code == 201
    assert (chosen.json()["sheet_name"], chosen.json()["valid_rows"]) == ("Suppliers", 2)

    error_of(
        upload(
            api, workbook, "supplier", filename="book.xlsx", content_type=XLSX, sheet_name="Nope"
        ),
        422,
        "WORKSHEET_NOT_FOUND",
    )
    # The same workbook and entity type with another worksheet cannot share the batch.
    error_of(
        upload(
            api,
            workbook,
            "supplier",
            filename="book.xlsx",
            content_type=XLSX,
            sheet_name="Projects",
        ),
        409,
        "DUPLICATE_FILE",
    )


# --- batches --------------------------------------------------------------------------


def test_batches_are_listed_newest_first_and_filtered(api: Api, project: dict[str, Any]) -> None:
    first = upload(api, PROJECTS, "project", filename="projects.csv").json()["batch_id"]
    second = upload(api, EQUIPMENT, "equipment", filename="equipment.csv").json()["batch_id"]

    listed = api.get("/ingestion/batches").json()
    assert [batch["id"] for batch in listed["items"]] == [second, first]
    assert listed["total"] == 2
    assert listed["items"][0]["file_warnings"] == []

    only_projects = api.get("/ingestion/batches", params={"entity_type": "project"}).json()
    assert [batch["id"] for batch in only_projects["items"]] == [first]
    assert api.get("/ingestion/batches", params={"status": "COMMITTED"}).json()["total"] == 0


def test_unknown_batch_is_not_found(api: Api) -> None:
    error_of(api.get(f"/ingestion/{uuid4()}"), 404, "NOT_FOUND")
    error_of(api.get("/ingestion/not-a-uuid"), 422, "VALIDATION_ERROR")


def test_file_level_warnings_are_kept_with_the_batch(api: Api) -> None:
    data = b"Project Code,Project Name\nP1,One\n\nP2,Two\n"

    body = upload(api, data, "project").json()

    assert body["warnings"][0]["code"] == "BLANK_ROWS_SKIPPED"
    assert body["warnings"][0]["row_number"] is None
    detail = api.get(f"/ingestion/{body['batch_id']}").json()
    assert [warning["code"] for warning in detail["file_warnings"]] == ["BLANK_ROWS_SKIPPED"]
    assert [row["row_number"] for row in detail["rows"]["items"]] == [2, 4]


def test_the_file_name_is_display_metadata_only(api: Api, session: Session) -> None:
    body = upload(api, PROJECTS, "project", filename="../../etc/cron.d/projects.csv").json()

    assert body["original_filename"] == "projects.csv"
    session.rollback()
    stored = session.scalar(select(IngestionBatch))
    assert stored is not None
    assert stored.original_filename == "projects.csv"
