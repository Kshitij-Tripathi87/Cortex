"""The vertical slice, end to end, with the demo dataset and the public routes only.

    workspace -> preview + commit of each file, in dependency order
              -> World State, compared with PostgreSQL
              -> revised commitment: old and new version
              -> the whole import again: nothing changes

No record is inserted by the test. Everything the World State shows came in
through POST .../ingestion/preview and POST .../ingestion/{batch}/commit.
"""

from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

import demo_checks
from app.models import (
    Equipment,
    IngestionBatch,
    IngestionRow,
    Milestone,
    MilestonePlanVersion,
    Project,
    PurchaseOrder,
    PurchaseOrderItem,
    Supplier,
    SupplierCommitmentVersion,
)
from tests.conftest import Api
from tests.constants import DEMO_AS_OF

pytestmark = pytest.mark.db

MANIFEST = demo_checks.load_manifest()
COUNTED = {
    "projects": Project,
    "suppliers": Supplier,
    "equipment": Equipment,
    "purchase_orders": PurchaseOrder,
    "purchase_order_items": PurchaseOrderItem,
    "milestones": Milestone,
    "milestone_plan_versions": MilestonePlanVersion,
    "supplier_commitment_versions": SupplierCommitmentVersion,
}


def upload(api: Api, entry: dict[str, Any]) -> Any:
    path = demo_checks.DATASET_DIR / entry["file"]
    return api.post(
        "/ingestion/preview",
        files={"file": (path.name, path.read_bytes(), "text/csv")},
        data={"entity_type": entry["entity_type"]},
    )


def import_file(api: Api, entry: dict[str, Any]) -> dict[str, Any]:
    preview = upload(api, entry)
    assert preview.status_code == 201, preview.text
    body = preview.json()
    assert (body["total_rows"], body["valid_rows"], body["invalid_rows"]) == (
        entry["rows"],
        entry["rows"],
        0,
    )
    assert body["errors"] == []
    commit = api.post(f"/ingestion/{body['batch_id']}/commit")
    assert commit.status_code == 200, commit.text
    result: dict[str, Any] = commit.json()
    assert (result["status"], result["replayed"], result["committed_rows"]) == (
        "COMMITTED",
        False,
        entry["rows"],
    )
    return result


def database_counts(session: Session) -> dict[str, int]:
    session.rollback()
    return {
        name: int(session.scalar(select(func.count()).select_from(model)) or 0)
        for name, model in COUNTED.items()
    }


def world_state(api: Api) -> tuple[dict[str, Any], dict[str, Any]]:
    summary = api.get("/world-state/summary").json()
    project_id = api.get("/world-state").json()["projects"]["items"][0]["id"]
    project = api.get(
        f"/world-state/projects/{project_id}",
        params={"equipment_limit": 200, "po_limit": 200, "include_history": "true"},
    ).json()
    return summary, project


@pytest.fixture
def imported(api: Api) -> Api:
    """The demo dataset without the later commitment revision."""
    for entry in MANIFEST["files"]:
        import_file(api, entry)
    return api


def test_the_dataset_manifest_matches_the_reference_date() -> None:
    assert MANIFEST["as_of"] == DEMO_AS_OF.isoformat()


def test_full_import_reaches_the_target_counts_and_world_state_matches_postgresql(
    imported: Api, session: Session
) -> None:
    summary, project = world_state(imported)

    # Before the revision there is one commitment version per committed order.
    expected = {**MANIFEST["counts"], "supplier_commitment_versions": 11}
    assert summary["summary"] == expected
    # The API totals are the totals of the database, counted independently here.
    assert summary["summary"] == database_counts(session)
    assert project["summary"]["suppliers"] == 8
    assert len(project["equipment"]["items"]) == 20
    assert len(project["purchase_orders"]["items"]) == 12
    assert sum(order["line_item_count"] for order in project["purchase_orders"]["items"]) == 19
    assert sum(order["milestone_count"] for order in project["purchase_orders"]["items"]) == 40
    quality = summary["data_quality"]
    assert (quality["valid_records"], quality["invalid_records"]) == (111, 0)
    assert quality["ingestion"]["batches"]["COMMITTED"] == 7


def test_every_source_row_is_linked_to_the_record_it_produced(
    imported: Api, session: Session
) -> None:
    session.rollback()
    rows = session.execute(
        select(
            IngestionBatch.entity_type,
            IngestionRow.status,
            IngestionRow.canonical_entity_type,
            func.count(),
        )
        .join(IngestionBatch, IngestionBatch.id == IngestionRow.batch_id)
        .group_by(
            IngestionBatch.entity_type, IngestionRow.status, IngestionRow.canonical_entity_type
        )
    ).all()

    assert {(entity.value, status.value, kind): count for entity, status, kind, count in rows} == {
        ("project", "COMMITTED", "project"): 1,
        ("supplier", "COMMITTED", "supplier"): 8,
        ("equipment", "COMMITTED", "equipment"): 20,
        ("purchase_order", "COMMITTED", "purchase_order"): 12,
        ("purchase_order_item", "COMMITTED", "purchase_order_item"): 19,
        ("milestone", "COMMITTED", "milestone"): 40,
        ("supplier_commitment", "COMMITTED", "supplier_commitment_version"): 11,
    }
    orphans = session.scalar(
        text(
            "SELECT count(*) FROM ingestion_rows r "
            "WHERE r.canonical_entity_type = 'purchase_order' AND NOT EXISTS "
            "(SELECT 1 FROM purchase_orders p WHERE p.id = r.canonical_entity_id)"
        )
    )
    assert orphans == 0
    # Every plan and commitment version names the source row that introduced it.
    for table in ("milestone_plan_versions", "supplier_commitment_versions"):
        without_source = session.scalar(
            text(f"SELECT count(*) FROM {table} WHERE source_ingestion_row_id IS NULL")
        )
        assert without_source == 0, table


def test_the_revised_commitment_is_appended_and_the_old_one_remains(
    imported: Api, session: Session
) -> None:
    changed = MANIFEST["conditions"]["changed_commitment"]
    _, before = world_state(imported)
    order_before = next(
        o for o in before["purchase_orders"]["items"] if o["po_number"] == changed["po_number"]
    )
    assert [
        (v["version_no"], v["committed_delivery_date"]) for v in order_before["commitment_history"]
    ] == [(1, changed["first"])]

    for entry in MANIFEST["updates"]:
        result = import_file(imported, entry)
        assert result["entities"] == {
            "supplier_commitment_version": {"created": 1, "updated": 0, "unchanged": 0}
        }

    _, after = world_state(imported)
    order_after = next(
        o for o in after["purchase_orders"]["items"] if o["po_number"] == changed["po_number"]
    )
    assert [
        (v["version_no"], v["committed_delivery_date"]) for v in order_after["commitment_history"]
    ] == [
        (1, changed["first"]),
        (2, changed["revised"]),
    ]
    # The first version is byte for byte what it was before the revision.
    assert order_after["commitment_history"][0] == order_before["commitment_history"][0]
    assert order_after["current_commitment"]["version_no"] == 2
    assert database_counts(session)["supplier_commitment_versions"] == 12


def test_all_five_conditions_are_represented_and_queryable(imported: Api) -> None:
    for entry in MANIFEST["updates"]:
        import_file(imported, entry)

    summary, project = world_state(imported)
    checks = demo_checks.check_demo_world_state(MANIFEST, summary, project)

    assert len(checks) >= 25
    assert [check.line() for check in checks if not check.passed] == []


def test_repeating_the_whole_import_changes_no_count_and_appends_no_version(
    imported: Api, session: Session
) -> None:
    for entry in MANIFEST["updates"]:
        import_file(imported, entry)
    counts = database_counts(session)
    ledger = (
        session.scalar(select(func.count()).select_from(IngestionBatch)),
        session.scalar(select(func.count()).select_from(IngestionRow)),
    )
    state = demo_checks.comparable(world_state(imported))

    for entry in [*MANIFEST["files"], *MANIFEST["updates"]]:
        again = upload(imported, entry)
        assert again.status_code == 200
        body = again.json()
        assert (body["duplicate_file"], body["status"]) == (True, "COMMITTED")
        replay = imported.post(f"/ingestion/{body['batch_id']}/commit").json()
        assert replay["replayed"] is True

    assert database_counts(session) == counts
    session.rollback()
    assert (
        session.scalar(select(func.count()).select_from(IngestionBatch)),
        session.scalar(select(func.count()).select_from(IngestionRow)),
    ) == ledger
    assert demo_checks.comparable(world_state(imported)) == state


def test_files_out_of_order_are_refused_row_by_row_and_nothing_is_made_up(
    api: Api, session: Session
) -> None:
    """Commitments before purchase orders: every row is unresolved, no record appears."""
    commitments = next(e for e in MANIFEST["files"] if e["entity_type"] == "supplier_commitment")

    preview = upload(api, commitments).json()

    assert (preview["valid_rows"], preview["invalid_rows"]) == (0, commitments["rows"])
    assert {error["code"] for error in preview["errors"]} == {"REFERENCE_NOT_FOUND"}
    assert set(database_counts(session).values()) == {0}
    assert api.post(f"/ingestion/{preview['batch_id']}/commit").status_code == 409
