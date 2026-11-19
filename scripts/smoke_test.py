"""Smoke test of a running Cortex Nexus API, over HTTP only.

Usage (from services/api, with the API running):
    uv run python ../../scripts/smoke_test.py --base-url http://127.0.0.1:8000
    uv run python ../../scripts/smoke_test.py --import-demo
    uv run python ../../scripts/smoke_test.py --import-demo --save-world-state before.json
    uv run python ../../scripts/smoke_test.py --compare-world-state before.json

Without options: health, the API contract and the workspace.
--import-demo        upload, preview and commit the demo dataset through the
                     public routes, replay it to prove idempotency, then check
                     the World State against the dataset.
--save-world-state   write the World State (without generated_at) to a file.
--compare-world-state  check that the World State equals a saved one; used
                     after a restart of the API and the database.
--evidence-dir       write the import results, the World State and the
                     commitment history as JSON files.

One line per check; exit code 1 if any check fails.
"""

import argparse
import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx2

import demo_checks
from app.core.config import get_settings

REQUEST_ID_HEADER = "X-Request-ID"
CSV_MEDIA_TYPE = "text/csv"
WHOLE_DATASET = {"equipment_limit": 200, "po_limit": 200, "include_history": "true"}
EXPECTED_ROUTES = (
    "/health/live",
    "/health/ready",
    "/api/v1/workspaces/{workspace_id}/ingestion/preview",
    "/api/v1/workspaces/{workspace_id}/ingestion/{batch_id}/commit",
    "/api/v1/workspaces/{workspace_id}/world-state",
    "/api/v1/workspaces/{workspace_id}/world-state/summary",
    "/api/v1/workspaces/{workspace_id}/world-state/projects/{project_id}",
)


@dataclass
class Report:
    """Collects check results; a failed check does not stop the later ones."""

    failures: list[str] = field(default_factory=list)
    passed: int = 0

    def check(self, name: str, condition: bool, detail: str = "") -> bool:
        if condition:
            self.passed += 1
        else:
            self.failures.append(name)
        suffix = f"  [{detail}]" if detail else ""
        print(f"{'PASS' if condition else 'FAIL'}  {name}{suffix}")
        return condition


class Api:
    """The API as a client sees it: a base URL and a workspace."""

    def __init__(self, client: httpx2.Client, workspace_id: str) -> None:
        self.client = client
        self.workspace = f"/api/v1/workspaces/{workspace_id}"

    def get(self, path: str, **params: Any) -> Any:
        response = self.client.get(self.workspace + path, params=params)
        response.raise_for_status()
        return response.json()

    def world_state(self) -> tuple[Any, Any, Any | None]:
        """Workspace summary, workspace World State and the first project's World State."""
        summary = self.get("/world-state/summary")
        workspace = self.get("/world-state")
        projects = workspace["projects"]["items"]
        project = (
            self.get(f"/world-state/projects/{projects[0]['id']}", **WHOLE_DATASET)
            if projects
            else None
        )
        return summary, workspace, project


def check_health(client: httpx2.Client, report: Report) -> None:
    live = client.get("/health/live")
    report.check("liveness answers 200", live.status_code == 200, f"HTTP {live.status_code}")
    report.check("every response carries a request id", bool(live.headers.get(REQUEST_ID_HEADER)))

    ready = client.get("/health/ready")
    checks = ready.json().get("checks", {}) if ready.status_code in (200, 503) else {}
    summary = ", ".join(f"{name}={check['status']}" for name, check in checks.items())
    report.check(
        "readiness: database reachable and schema at the migration head",
        ready.status_code == 200,
        f"HTTP {ready.status_code}; {summary}",
    )


def check_contract(client: httpx2.Client, report: Report) -> None:
    document = client.get("/openapi.json")
    paths = document.json().get("paths", {}) if document.status_code == 200 else {}
    missing = [route for route in EXPECTED_ROUTES if route not in paths]
    report.check(
        "OpenAPI document lists the import and World State routes",
        document.status_code == 200 and not missing,
        f"{len(paths)} paths" + (f"; missing {missing}" if missing else ""),
    )

    unknown = client.get(
        "/api/v1/this-route-does-not-exist", headers={REQUEST_ID_HEADER: "smoke-test-0001"}
    )
    body = unknown.json() if unknown.headers.get("content-type") == "application/json" else {}
    error = body.get("error", {})
    report.check(
        "errors use the standard envelope and echo the request id",
        unknown.status_code == 404
        and set(error) == {"code", "message", "details", "request_id"}
        and error.get("request_id") == "smoke-test-0001",
        f"HTTP {unknown.status_code}; code={error.get('code')}",
    )


def check_workspace(client: httpx2.Client, api: Api, report: Report) -> None:
    own = client.get(api.workspace)
    report.check(
        "the configured workspace is served and active",
        own.status_code == 200 and own.json().get("status") == "ACTIVE",
        f"HTTP {own.status_code}",
    )
    other = client.get("/api/v1/workspaces/00000000-0000-4000-8000-00000000ffff/projects")
    code = other.json().get("error", {}).get("code") if other.status_code == 404 else None
    report.check(
        "any other workspace id is not available",
        other.status_code == 404 and code == "WORKSPACE_NOT_AVAILABLE",
        f"HTTP {other.status_code}; code={code}",
    )


def _upload(api: Api, entry: Mapping[str, Any]) -> httpx2.Response:
    path = demo_checks.DATASET_DIR / entry["file"]
    return api.client.post(
        api.workspace + "/ingestion/preview",
        files={"file": (path.name, path.read_bytes(), CSV_MEDIA_TYPE)},
        data={"entity_type": entry["entity_type"]},
    )


def import_demo(api: Api, manifest: Mapping[str, Any], report: Report) -> list[dict[str, Any]]:
    """Preview and commit every dataset file through the public routes."""
    results: list[dict[str, Any]] = []
    for entry in [*manifest["files"], *manifest["updates"]]:
        preview = _upload(api, entry)
        body = preview.json() if preview.status_code in (200, 201) else {}
        commit = (
            api.client.post(f"{api.workspace}/ingestion/{body['batch_id']}/commit")
            if body
            else None
        )
        committed = commit.json() if commit is not None and commit.status_code == 200 else {}
        results.append({"file": entry["file"], "preview": body, "commit": committed})
        report.check(
            f"import {entry['file']}",
            preview.status_code in (200, 201)
            and body.get("total_rows") == entry["rows"]
            and body.get("invalid_rows") == 0
            and committed.get("status") == "COMMITTED",
            f"preview HTTP {preview.status_code}, rows={body.get('total_rows')}, "
            f"invalid={body.get('invalid_rows')}, commit={committed.get('status')}, "
            f"committed={committed.get('committed_rows')}, "
            f"skipped={committed.get('skipped_rows')}, replayed={committed.get('replayed')}",
        )
    return results


def check_idempotency(
    api: Api, manifest: Mapping[str, Any], first: list[dict[str, Any]], report: Report
) -> None:
    """Send the whole dataset again: same batches, nothing written."""
    before = api.get("/world-state/summary")["summary"]
    batches_before = api.get("/ingestion/batches", limit=1)["total"]
    same_batches = True
    replayed = True
    for entry, earlier in zip([*manifest["files"], *manifest["updates"]], first, strict=True):
        preview = _upload(api, entry)
        body = preview.json()
        same_batches &= (
            preview.status_code == 200
            and body.get("duplicate_file") is True
            and body.get("batch_id") == earlier["preview"].get("batch_id")
        )
        commit = api.client.post(f"{api.workspace}/ingestion/{body['batch_id']}/commit")
        replayed &= commit.status_code == 200 and commit.json().get("replayed") is True
    after = api.get("/world-state/summary")["summary"]
    report.check("repeat import: every file resolves to its existing batch", same_batches)
    report.check("repeat import: every commit is a replay", replayed)
    report.check("repeat import: record counts unchanged", before == after, json.dumps(after))
    report.check(
        "repeat import: no new batch",
        api.get("/ingestion/batches", limit=1)["total"] == batches_before,
        f"{batches_before} batches",
    )


def check_list_totals(api: Api, summary: Mapping[str, Any], report: Report) -> None:
    for kind, path in (
        ("projects", "/projects"),
        ("suppliers", "/suppliers"),
        ("equipment", "/equipment"),
        ("purchase_orders", "/purchase-orders"),
    ):
        total = api.get(path, limit=1)["total"]
        report.check(
            f"World State count equals the list total: {kind}",
            total == summary["summary"][kind],
            f"{total}",
        )


def check_provenance(
    api: Api, manifest: Mapping[str, Any], project: Mapping[str, Any], report: Report
) -> Any:
    """Which file supplied the order, and which source row its current commitment."""
    changed = manifest["conditions"]["changed_commitment"]["po_number"]
    order = next(o for o in project["purchase_orders"]["items"] if o["po_number"] == changed)
    sources = api.get("/ingestion/sources", entity_type="purchase_order", entity_id=order["id"])
    report.check(
        f"provenance: the file that supplied {changed}",
        [source["original_filename"] for source in sources["items"]] == ["purchase_orders.csv"],
        ", ".join(f"{s['original_filename']} row {s['row_number']}" for s in sources["items"]),
    )
    history = api.get(f"/purchase-orders/{order['id']}/commitments")
    current = history["items"][-1]
    origin = api.get(
        "/ingestion/sources", entity_type="supplier_commitment_version", entity_id=current["id"]
    )
    rows = [(s["original_filename"], s["row_id"]) for s in origin["items"]]
    report.check(
        f"provenance: the source row of the current commitment of {changed}",
        rows == [("supplier_commitments_revision_01.csv", current["source_ingestion_row_id"])],
        f"version {current['version_no']} from {rows[0][0] if rows else 'nothing'}",
    )
    return history


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--workspace-id", help="default: NEXUS_DEV_WORKSPACE_ID from the settings")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--import-demo", action="store_true")
    parser.add_argument("--save-world-state", type=Path)
    parser.add_argument("--compare-world-state", type=Path)
    parser.add_argument("--evidence-dir", type=Path)
    arguments = parser.parse_args()

    workspace_id = arguments.workspace_id or str(get_settings().nexus_dev_workspace_id)
    manifest = demo_checks.load_manifest()
    report = Report()
    try:
        with httpx2.Client(base_url=arguments.base_url, timeout=arguments.timeout) as client:
            api = Api(client, workspace_id)
            check_health(client, report)
            check_contract(client, report)
            check_workspace(client, api, report)

            if arguments.import_demo:
                results = import_demo(api, manifest, report)
                check_idempotency(api, manifest, results, report)
                if arguments.evidence_dir:
                    write_json(arguments.evidence_dir / "day3-import-results.json", results)

            summary, workspace, project = api.world_state()
            if arguments.import_demo or arguments.compare_world_state:
                assert project is not None, "the demo project is not there"
                for check in demo_checks.check_demo_world_state(manifest, summary, project):
                    report.check(check.name, check.passed, f"{check.actual}")
                check_list_totals(api, summary, report)
                history = check_provenance(api, manifest, project, report)
                if arguments.evidence_dir:
                    write_json(
                        arguments.evidence_dir / "day3-world-state.json",
                        {"workspace": workspace, "project": project},
                    )
                    write_json(arguments.evidence_dir / "day3-commitment-history.json", history)

            state = demo_checks.comparable({"workspace": workspace, "project": project})
            if arguments.save_world_state:
                write_json(arguments.save_world_state, state)
                print(f"SAVED World State to {arguments.save_world_state}")
            if arguments.compare_world_state:
                saved = json.loads(arguments.compare_world_state.read_text(encoding="utf-8"))
                report.check(
                    "World State is identical to the saved one (apart from generated_at)",
                    json.loads(json.dumps(state, sort_keys=True)) == saved,
                    f"compared with {arguments.compare_world_state.name}",
                )
    except httpx2.HTTPError as exc:
        print(f"FAIL  the API at {arguments.base_url} did not answer as expected ({exc!r})")
        return 1

    total = report.passed + len(report.failures)
    print(f"\n{report.passed} of {total} checks passed.")
    return 1 if report.failures else 0


if __name__ == "__main__":
    sys.exit(main())
