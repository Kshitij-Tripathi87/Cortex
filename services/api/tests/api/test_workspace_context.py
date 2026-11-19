"""The development workspace context: one workspace is served, nothing else is disclosed."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Workspace
from app.models.enums import WorkspaceStatus
from tests import factories
from tests.conftest import error_of

pytestmark = pytest.mark.db

ROUTES = [
    ("GET", ""),
    ("GET", "/projects"),
    ("POST", "/projects"),
    ("GET", "/suppliers"),
    ("GET", "/equipment"),
    ("GET", "/purchase-orders"),
    ("GET", "/ingestion/batches"),
]


def call(client: TestClient, method: str, workspace_id: object, path: str):  # type: ignore[no-untyped-def]
    url = f"/api/v1/workspaces/{workspace_id}{path}"
    if method == "POST":
        return client.post(url, json={"code": "X", "name": "X"})
    return client.get(url)


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_another_workspace_is_not_available_whether_or_not_it_exists(
    client: TestClient, session: Session, workspace: Workspace, method: str, path: str
) -> None:
    existing_other = factories.make_workspace(session, workspace_id=uuid4(), slug="other")
    factories.make_project(session, existing_other, code="SECRET-PROJECT")

    for_existing = call(client, method, existing_other.id, path)
    for_unknown = call(client, method, uuid4(), path)

    error_of(for_existing, 404, "WORKSPACE_NOT_AVAILABLE")
    error_of(for_unknown, 404, "WORKSPACE_NOT_AVAILABLE")
    # Same status, code and message: the answer does not say which of the two exists.
    assert for_existing.json()["error"]["message"] == for_unknown.json()["error"]["message"]
    assert "SECRET-PROJECT" not in for_existing.text


def test_a_workspace_id_in_a_header_or_body_grants_nothing(
    client: TestClient, session: Session, workspace: Workspace
) -> None:
    other = factories.make_workspace(session, workspace_id=uuid4(), slug="other")
    factories.make_project(session, other, code="SECRET-PROJECT")

    listed = client.get(
        f"/api/v1/workspaces/{workspace.id}/projects",
        headers={"X-Workspace-ID": str(other.id)},
    )
    created = client.post(
        f"/api/v1/workspaces/{workspace.id}/projects",
        json={"code": "P1", "name": "One", "workspace_id": str(other.id)},
    )

    assert listed.json()["total"] == 0  # the header is ignored
    error_of(created, 422, "VALIDATION_ERROR")  # the body field is refused, not obeyed


def test_the_configured_workspace_must_exist(client: TestClient) -> None:
    """The id is configured but nobody created the workspace yet."""
    from tests.constants import DEV_WORKSPACE_ID

    error_of(client.get(f"/api/v1/workspaces/{DEV_WORKSPACE_ID}"), 404, "WORKSPACE_NOT_AVAILABLE")
    error_of(
        client.get(f"/api/v1/workspaces/{DEV_WORKSPACE_ID}/projects"),
        404,
        "WORKSPACE_NOT_AVAILABLE",
    )


def test_a_disabled_workspace_can_be_inspected_and_nothing_else(
    client: TestClient, session: Session
) -> None:
    workspace = factories.make_workspace(session, status=WorkspaceStatus.DISABLED)
    base = f"/api/v1/workspaces/{workspace.id}"

    inspected = client.get(base)

    assert inspected.status_code == 200
    assert inspected.json()["status"] == "DISABLED"
    error_of(client.get(f"{base}/projects"), 404, "WORKSPACE_NOT_AVAILABLE")
    error_of(
        client.post(f"{base}/projects", json={"code": "P", "name": "P"}),
        404,
        "WORKSPACE_NOT_AVAILABLE",
    )


def test_a_malformed_workspace_id_is_a_validation_error(client: TestClient) -> None:
    error = error_of(client.get("/api/v1/workspaces/not-a-uuid/projects"), 422, "VALIDATION_ERROR")

    assert error["details"][0]["code"] == "INVALID_UUID"


def test_records_of_another_workspace_are_not_found_by_id(
    client: TestClient, session: Session, workspace: Workspace
) -> None:
    """Workspace A cannot read or change Workspace B's records, even knowing their ids."""
    other = factories.make_workspace(session, workspace_id=uuid4(), slug="other")
    project = factories.make_project(session, other, code="DC-B")
    supplier = factories.make_supplier(session, other, supplier_code="SUP-B")
    equipment = factories.make_equipment(session, project, equipment_code="EQ-B")
    order = factories.make_purchase_order(session, project, supplier, po_number="PO-B")
    milestone = factories.make_milestone(session, order)
    base = f"/api/v1/workspaces/{workspace.id}"

    for path in (
        f"/projects/{project.id}",
        f"/suppliers/{supplier.id}",
        f"/equipment/{equipment.id}",
        f"/purchase-orders/{order.id}",
        f"/purchase-orders/{order.id}/milestones",
        f"/purchase-orders/{order.id}/milestones/{milestone.id}",
        f"/purchase-orders/{order.id}/commitments",
    ):
        error_of(client.get(base + path), 404, "NOT_FOUND")

    error_of(
        client.patch(f"{base}/projects/{project.id}", json={"name": "taken over"}), 404, "NOT_FOUND"
    )
    error_of(
        client.patch(f"{base}/suppliers/{supplier.id}", json={"status": "INACTIVE"}),
        404,
        "NOT_FOUND",
    )
    error_of(client.patch(f"{base}/equipment/{equipment.id}", json={"name": "x"}), 404, "NOT_FOUND")
    error_of(
        client.patch(f"{base}/purchase-orders/{order.id}", json={"status": "CANCELLED"}),
        404,
        "NOT_FOUND",
    )
    error_of(
        client.post(
            f"{base}/purchase-orders/{order.id}/commitments",
            json={"committed_delivery_date": "2026-12-01"},
        ),
        404,
        "NOT_FOUND",
    )

    session.refresh(project)
    session.refresh(supplier)
    assert (project.name, supplier.status.value) == ("Project DC-B", "ACTIVE")
    for path in ("/projects", "/suppliers", "/equipment", "/purchase-orders"):
        assert client.get(base + path).json()["total"] == 0


def test_the_same_natural_key_may_exist_in_two_workspaces(
    client: TestClient, session: Session, workspace: Workspace
) -> None:
    other = factories.make_workspace(session, workspace_id=uuid4(), slug="other")
    factories.make_project(session, other, code="DC-IN-001")

    created = client.post(
        f"/api/v1/workspaces/{workspace.id}/projects", json={"code": "DC-IN-001", "name": "Ours"}
    )

    assert created.status_code == 201
