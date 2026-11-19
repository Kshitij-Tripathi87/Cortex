"""The World State lives in PostgreSQL, not in a process.

A second application instance, and then a second operating-system process,
read the same World State as the instance that imported the data. Restarting
the database container with its volume is exercised by the end-to-end run
(`make e2e`) and by CI, where a container exists to restart.
"""

import json
import subprocess
import sys
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import demo_checks
from app.core.config import Settings
from app.db.health import SERVICE_ROOT
from app.db.session import Database
from app.main import create_app
from app.models import Workspace
from tests.constants import DEV_WORKSPACE_ID
from tests.importing import Importer, import_small_dataset

pytestmark = pytest.mark.db

BASE = f"/api/v1/workspaces/{DEV_WORKSPACE_ID}"

# What a freshly started process does: build the application, ask, print.
FRESH_PROCESS = """
import json, sys
from fastapi.testclient import TestClient
from app.main import create_app
from tests.conftest import make_settings

app = create_app(make_settings(log_level="CRITICAL"))
with TestClient(app) as client:
    print(json.dumps({path: client.get(path).json() for path in sys.argv[1:]}))
"""


def world_state_paths(client: TestClient) -> list[str]:
    project_id = client.get(f"{BASE}/world-state").json()["projects"]["items"][0]["id"]
    return [
        f"{BASE}/world-state",
        f"{BASE}/world-state/summary",
        f"{BASE}/world-state/projects/{project_id}?include_history=true",
    ]


def read(client: TestClient, paths: list[str]) -> Any:
    return demo_checks.comparable({path: client.get(path).json() for path in paths})


@pytest.fixture
def dataset(session: Session, workspace: Workspace) -> None:
    import_small_dataset(Importer(session, workspace.id))
    session.rollback()


def test_a_second_application_instance_reads_the_same_world_state(
    dataset: None, settings: Settings
) -> None:
    first_app = create_app(settings)
    with TestClient(first_app) as first:
        paths = world_state_paths(first)
        before = read(first, paths)
    # Leaving the block shut the first application down and closed its connections.
    first_database: Database = first_app.state.database
    assert first_database.engine.pool.checkedout() == 0  # type: ignore[attr-defined]

    second_app = create_app(settings)
    assert second_app.state.database is not first_database
    with TestClient(second_app) as second:
        after = read(second, paths)

    assert after == before
    assert before[paths[1]]["summary"]["purchase_orders"] == 2


def test_a_new_process_reads_the_same_world_state(dataset: None, client: TestClient) -> None:
    """Nothing is carried in memory: another process sees exactly the same facts."""
    paths = world_state_paths(client)
    before = read(client, paths)

    completed = subprocess.run(
        [sys.executable, "-c", FRESH_PROCESS, *paths],
        cwd=SERVICE_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr[-2000:]
    after = demo_checks.comparable(json.loads(completed.stdout))
    assert after == before
    project = after[paths[2]]
    assert [order["po_number"] for order in project["purchase_orders"]["items"]] == ["PO-1", "PO-2"]
    assert (
        project["purchase_orders"]["items"][0]["current_commitment"]["committed_delivery_date"]
        == "2026-12-15"
    )


def test_history_survives_with_the_records(
    dataset: None, client: TestClient, settings: Settings
) -> None:
    order_id = next(
        o["id"]
        for o in client.get(f"{BASE}/purchase-orders").json()["items"]
        if o["po_number"] == "PO-2"
    )
    client.post(
        f"{BASE}/purchase-orders/{order_id}/commitments",
        json={"committed_delivery_date": "2026-12-06"},
    )

    with TestClient(create_app(settings)) as restarted:
        history = restarted.get(f"{BASE}/purchase-orders/{order_id}/commitments").json()

    assert [(v["version_no"], v["committed_delivery_date"]) for v in history["items"]] == [
        (1, "2026-11-28"),
        (2, "2026-12-06"),
    ]


def test_only_generated_at_differs_between_two_reads(dataset: None, client: TestClient) -> None:
    path = f"{BASE}/world-state"

    first = client.get(path).json()
    second = client.get(path).json()

    assert first["generated_at"] <= second["generated_at"]
    assert demo_checks.comparable(first) == demo_checks.comparable(second)
    assert "generated_at" not in demo_checks.comparable(first)
