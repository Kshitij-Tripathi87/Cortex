"""Workspace isolation over HTTP, for every route that takes a record id.

A second workspace with a full set of records exists in the database. The API
serves the configured workspace only, so the other one can be reached in a
single way: by putting one of its ids into a request for the served
workspace. Every such request must be answered exactly as for an id that does
not exist, must not show a value of the other workspace, and must write
nothing.

The table of cases is checked against the published OpenAPI document: a route
that takes an id and has no case here fails the suite.
"""

from datetime import date
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import Database
from app.models.enums import IngestionEntityType, MilestoneType
from tests import factories
from tests.conftest import Api, detail_codes, error_of
from tests.constants import OTHER_WORKSPACE_ID
from tests.importing import SUPPLIER_HEADERS, Importer

pytestmark = pytest.mark.db

SECRET = "Classified"
WORKSPACE_PREFIX = "/api/v1/workspaces/{workspace_id}"

# (method, path below the workspace, JSON body). The body is valid, so that
# nothing but the id can be the reason for a refusal.
CASES: list[tuple[str, str, dict[str, Any] | None]] = [
    ("GET", "/projects/{project_id}", None),
    ("PATCH", "/projects/{project_id}", {"name": "Taken over"}),
    ("GET", "/suppliers/{supplier_id}", None),
    ("PATCH", "/suppliers/{supplier_id}", {"name": "Taken over"}),
    ("GET", "/equipment/{equipment_id}", None),
    ("PATCH", "/equipment/{equipment_id}", {"name": "Taken over"}),
    ("GET", "/purchase-orders/{po_id}", None),
    ("PATCH", "/purchase-orders/{po_id}", {"status": "CANCELLED"}),
    ("GET", "/purchase-orders/{po_id}/milestones", None),
    (
        "POST",
        "/purchase-orders/{po_id}/milestones",
        {"milestone_type": "DISPATCH", "planned_date": "2027-01-05"},
    ),
    ("GET", "/purchase-orders/{po_id}/milestones/{milestone_id}", None),
    (
        "PATCH",
        "/purchase-orders/{po_id}/milestones/{milestone_id}",
        {"status": "COMPLETED", "actual_date": "2027-01-05"},
    ),
    (
        "POST",
        "/purchase-orders/{po_id}/milestones/{milestone_id}/plan-versions",
        {"planned_date": "2027-03-03"},
    ),
    ("GET", "/purchase-orders/{po_id}/commitments", None),
    (
        "POST",
        "/purchase-orders/{po_id}/commitments",
        {"committed_delivery_date": "2027-02-02"},
    ),
    ("GET", "/ingestion/{batch_id}", None),
    ("POST", "/ingestion/{batch_id}/commit", None),
    ("GET", "/world-state/projects/{project_id}", None),
]


class Records:
    """One of everything in a workspace, and the id of each by path parameter."""

    def __init__(self, session: Session, workspace: Any, label: str) -> None:
        self.project = factories.make_project(session, workspace, code="DC-001", name=label)
        self.supplier = factories.make_supplier(
            session, workspace, supplier_code="SUP-001", name=label
        )
        self.equipment = factories.make_equipment(
            session, self.project, equipment_code="EQ-001", name=label
        )
        self.order = factories.make_purchase_order(
            session, self.project, self.supplier, po_number="PO-001"
        )
        factories.make_item(session, self.order, self.equipment)
        self.milestone = factories.make_milestone(
            session, self.order, milestone_type=MilestoneType.DELIVERY
        )
        self.commitment = factories.make_commitment(
            session, self.order, committed_delivery_date=date(2026, 11, 28)
        )
        # A previewed batch with a valid row: it could be committed by its owner.
        self.batch = (
            Importer(session, workspace.id)
            .preview(
                IngestionEntityType.SUPPLIER,
                SUPPLIER_HEADERS,
                [["SUP-NEW", f"{label} newcomer", "", "", ""]],
                filename=f"{label}.csv",
            )
            .batch
        )
        self.ids = {
            "project_id": self.project.id,
            "supplier_id": self.supplier.id,
            "equipment_id": self.equipment.id,
            "po_id": self.order.id,
            "milestone_id": self.milestone.id,
            "batch_id": self.batch.id,
        }


@pytest.fixture
def mine(session: Session, workspace: Any) -> Records:
    return Records(session, workspace, "Mine")


@pytest.fixture
def theirs(session: Session) -> Records:
    other = factories.make_workspace(session, workspace_id=OTHER_WORKSPACE_ID, slug="other")
    return Records(session, other, SECRET)


def everything(db: Database) -> dict[str, list[tuple[Any, ...]]]:
    """Every row of every table, as PostgreSQL holds it right now."""
    with db.engine.connect() as connection:
        return {
            table.name: sorted(
                (tuple(row) for row in connection.execute(text(f'SELECT * FROM "{table.name}"'))),
                key=repr,
            )
            for table in Base.metadata.sorted_tables
        }


def parameters_of(path: str) -> list[str]:
    return [part[1:-1] for part in path.split("/") if part.startswith("{")]


def send(api: Api, method: str, path: str, body: dict[str, Any] | None) -> Any:
    return api.client.request(method, api.base + path, json=body)


def test_every_route_that_takes_an_id_has_an_isolation_case(app: FastAPI) -> None:
    """Read from the published contract, so a new route cannot be forgotten."""
    routes = {
        (method.upper(), path.removeprefix(WORKSPACE_PREFIX))
        for path, operations in app.openapi()["paths"].items()
        if path.startswith(WORKSPACE_PREFIX + "/") and parameters_of(path) != ["workspace_id"]
        for method in operations
    }

    assert routes == {(method, path) for method, path, _ in CASES}


@pytest.mark.parametrize(("method", "path", "body"), CASES)
def test_an_id_of_another_workspace_is_an_id_that_does_not_exist(
    api: Api,
    db: Database,
    mine: Records,
    theirs: Records,
    method: str,
    path: str,
    body: dict[str, Any] | None,
) -> None:
    names = parameters_of(path)
    unknown = {name: uuid4() for name in names}
    before = everything(db)

    # Their id in every position, and in each single position beside my own
    # records: my purchase order with their milestone, and the reverse.
    combinations = [dict(theirs.ids)]
    if len(names) > 1:
        combinations += [{**mine.ids, name: theirs.ids[name]} for name in names]

    for ids in combinations:
        response = send(api, method, path.format(**ids), body)
        missing = send(api, method, path.format(**{**ids, **unknown}), body)

        error = error_of(response, 404, "NOT_FOUND")
        assert SECRET not in response.text
        # Not one word differs from the answer for an id nobody has.
        assert {**error, "request_id": None} == {
            **error_of(missing, 404, "NOT_FOUND"),
            "request_id": None,
        }

    assert everything(db) == before


def test_the_cases_are_real_requests_that_succeed_on_my_own_records(
    api: Api, mine: Records, theirs: Records
) -> None:
    """Guards the table above: a case that fails for any id would prove nothing."""
    for method, path, body in CASES:
        response = send(api, method, path.format(**mine.ids), body)

        assert response.status_code in (200, 201), (method, path, response.text)


def test_lists_filters_and_the_world_state_show_nothing_of_another_workspace(
    api: Api, mine: Records, theirs: Records
) -> None:
    foreign_ids = {str(value) for value in theirs.ids.values()}
    requests: list[tuple[str, dict[str, Any]]] = [
        ("/projects", {}),
        ("/suppliers", {}),
        ("/equipment", {}),
        ("/equipment", {"project_id": theirs.project.id}),
        ("/purchase-orders", {}),
        ("/purchase-orders", {"project_id": theirs.project.id}),
        ("/purchase-orders", {"supplier_id": theirs.supplier.id}),
        ("/ingestion/batches", {}),
        ("/world-state", {}),
        ("/world-state/summary", {}),
        (f"/world-state/projects/{mine.project.id}", {"include_history": "true"}),
    ]

    for path, params in requests:
        response = api.get(path, params=params)

        assert response.status_code == 200, (path, response.text)
        assert SECRET not in response.text, path
        assert not [value for value in foreign_ids if value in response.text], path

    # A filter on their project or supplier matches nothing of mine.
    assert api.get("/equipment", params={"project_id": theirs.project.id}).json()["total"] == 0
    assert (
        api.get("/purchase-orders", params={"supplier_id": theirs.supplier.id}).json()["total"] == 0
    )
    # Counted for my workspace alone: one of each, although the database holds two.
    counts = api.get("/world-state/summary").json()["summary"]
    assert (counts["projects"], counts["suppliers"], counts["purchase_orders"]) == (1, 1, 1)


def test_the_source_rows_of_a_record_of_another_workspace_are_not_listed(
    api: Api, session: Session, theirs: Records
) -> None:
    """Their batch is committed, so their new supplier has a source row. Not for me."""
    committed = Importer(session, OTHER_WORKSPACE_ID).commit(theirs.batch.id)
    assert committed.batch.committed_rows == 1
    row = Importer(session, OTHER_WORKSPACE_ID).rows(theirs.batch.id)[0]
    assert row.canonical_entity_id is not None

    listed = api.get(
        "/ingestion/sources",
        params={"entity_type": "supplier", "entity_id": row.canonical_entity_id},
    )

    assert listed.status_code == 200
    assert listed.json()["items"] == []
    assert listed.json()["total"] == 0


def test_a_request_cannot_link_my_records_to_those_of_another_workspace(
    api: Api, db: Database, mine: Records, theirs: Records
) -> None:
    before = everything(db)
    equipment = {"equipment_code": "EQ-X", "name": "x", "category": "UPS", "criticality": "HIGH"}
    order = {"po_number": "PO-X", "currency": "INR"}
    attempts: list[tuple[str, dict[str, Any], str]] = [
        ("/equipment", {**equipment, "project_id": str(theirs.project.id)}, "project_id"),
        (
            "/purchase-orders",
            {**order, "project_id": str(mine.project.id), "supplier_id": str(theirs.supplier.id)},
            "supplier_id",
        ),
        (
            "/purchase-orders",
            {**order, "project_id": str(theirs.project.id), "supplier_id": str(mine.supplier.id)},
            "project_id",
        ),
        (
            "/purchase-orders",
            {
                **order,
                "project_id": str(mine.project.id),
                "supplier_id": str(mine.supplier.id),
                "items": [{"equipment_id": str(theirs.equipment.id), "quantity": "1"}],
            },
            "items.0.equipment_id",
        ),
    ]

    for path, body, field in attempts:
        response = api.post(path, json=body)

        error = error_of(response, 422, "VALIDATION_ERROR")
        assert detail_codes(error) == {(field, "REFERENCE_NOT_FOUND")}
        assert SECRET not in response.text

    assert everything(db) == before
