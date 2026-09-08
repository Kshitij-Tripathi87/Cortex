"""Workflo Control Plane API contract tests.

Every documented curl against /api/v1/workflo/* is exercised here: HTTP status,
response schema, side effects on the sandbox filesystem, and security blocks
surfaced as 403 with a machine-readable reason.
"""

from __future__ import annotations

import base64
import os
import sys

# Add product folder to path for moved workflo modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "product"))

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from product.workflo_api import router as workflo_router
from product.workflo_backend.orchestrator import reset_orchestrator


@pytest.fixture()
def client(tmp_path):
    reset_orchestrator()
    import os

    os.environ["CORTEX_WORKFLO_ROOT"] = str(tmp_path / "wf-root")
    test_app = FastAPI()
    test_app.include_router(workflo_router, prefix="/api/v1")
    return ASGITransport(app=test_app)


@pytest.fixture()
async def api(client):
    async with AsyncClient(transport=client, base_url="http://test") as c:
        yield c


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


class TestSandboxContract:
    async def test_create_sandbox_201_schema(self, api) -> None:
        resp = await api.post(
            "/api/v1/workflo/sandboxes",
            json={"workspace_id": "ws_demo", "name": "smoke"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["id"].startswith("sbx_")
        assert body["workspace_id"] == "ws_demo"
        assert body["status"] == "running"
        assert set(body["layout"]) == {"workspace/", "artifacts/", "tmp/"}
        policy = body["policy"]
        assert policy["filesystem_scope"] == "sandbox"
        assert policy["network_mode"] == "none"

    async def test_invalid_policy_rejected(self, api) -> None:
        resp = await api.post(
            "/api/v1/workflo/sandboxes",
            json={
                "workspace_id": "ws",
                "name": "bad",
                "policy": {"filesystem_scope": "host"},
            },
        )
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "policy_violation"

    async def test_inspect_unknown_404(self, api) -> None:
        resp = await api.get("/api/v1/workflo/sandboxes/sbx_nope")
        assert resp.status_code == 404

    async def test_destroy_side_effect(self, api) -> None:
        create = await api.post(
            "/api/v1/workflo/sandboxes", json={"workspace_id": "ws", "name": "d"}
        )
        sid = create.json()["id"]
        destroyed = await api.delete(f"/api/v1/workflo/sandboxes/{sid}")
        assert destroyed.status_code == 200
        assert destroyed.json()["status"] == "destroyed"


class TestFileContract:
    async def _sandbox(self, api) -> str:
        r = await api.post("/api/v1/workflo/sandboxes", json={"workspace_id": "ws", "name": "f"})
        return r.json()["id"]

    async def test_write_and_list(self, api) -> None:
        sid = await self._sandbox(api)
        put = await api.post(
            f"/api/v1/workflo/sandboxes/{sid}/files",
            json={"path": "src/app.py", "content_base64": _b64("print(1)\n")},
        )
        assert put.status_code == 201
        assert put.json()["size_bytes"] == len(b"print(1)\n")

        listing = await api.get(f"/api/v1/workflo/sandboxes/{sid}/files")
        assert listing.status_code == 200
        paths = [f["path"] for f in listing.json()["files"]]
        assert "src/app.py" in paths

        content = await api.get(
            f"/api/v1/workflo/sandboxes/{sid}/files/content",
            params={"path": "src/app.py"},
        )
        assert content.status_code == 200
        assert base64.b64decode(content.json()["content_base64"]) == b"print(1)\n"

    async def test_traversal_write_blocked_403(self, api) -> None:
        sid = await self._sandbox(api)
        resp = await api.post(
            f"/api/v1/workflo/sandboxes/{sid}/files",
            json={"path": "../escape.txt", "content_base64": _b64("x")},
        )
        assert resp.status_code == 403


class TestExecutionContract:
    async def test_execute_success_with_diagnosis(self, api) -> None:
        create = await api.post(
            "/api/v1/workflo/sandboxes", json={"workspace_id": "ws", "name": "x"}
        )
        sid = create.json()["id"]
        resp = await api.post(
            f"/api/v1/workflo/sandboxes/{sid}/execute",
            json={"command": "echo contract-ok"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["exit_code"] == 0
        assert "contract-ok" in body["stdout"]
        assert body["diagnosis"]["status"] == "healthy"
        assert isinstance(body["artifacts"], list)

    async def test_execute_policy_block_is_403(self, api) -> None:
        create = await api.post(
            "/api/v1/workflo/sandboxes", json={"workspace_id": "ws", "name": "x"}
        )
        sid = create.json()["id"]
        resp = await api.post(
            f"/api/v1/workflo/sandboxes/{sid}/execute",
            json={"command": "curl http://attacker.example.com"},
        )
        assert resp.status_code == 403
        assert "network command" in resp.json()["detail"]["message"]

    async def test_execute_after_destroy_blocked(self, api) -> None:
        create = await api.post(
            "/api/v1/workflo/sandboxes", json={"workspace_id": "ws", "name": "x"}
        )
        sid = create.json()["id"]
        await api.delete(f"/api/v1/workflo/sandboxes/{sid}")
        resp = await api.post(
            f"/api/v1/workflo/sandboxes/{sid}/execute",
            json={"command": "echo hi"},
        )
        assert resp.status_code == 403


class TestAgentContract:
    async def test_plan_endpoint(self, api) -> None:
        resp = await api.post(
            "/api/v1/workflo/agent/plan",
            json={
                "intent": "run regression and diagnose checkout failure",
                "file_index": ["package.json", "tests/a.test.ts"],
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["step_count"] >= 5
        assert body["discovered"]["frameworks"] == ["node"]

    async def test_continue_endpoint_records_finding_on_run(self, api) -> None:
        run = await api.post(
            "/api/v1/workflo/runs",
            json={
                "workspace_id": "ws",
                "name": "diag",
                "intent": "run tests",
                "files": [
                    {
                        "path": "package.json",
                        "content_base64": _b64('{"scripts":{"test":"node t.js"}}'),
                    },
                    {"path": "t.js", "content_base64": _b64("process.exit(1)")},
                ],
                "command": "npm test --silent",
            },
        )
        assert run.status_code == 201
        run_id = run.json()["id"]
        cont = await api.post(
            "/api/v1/workflo/agent/continue",
            json={
                "run_id": run_id,
                "result": {
                    "command": "npm test",
                    "exit_code": 2,
                    "stdout": "",
                    "stderr": "AssertionError: boom",
                    "timed_out": False,
                    "duration_ms": 5,
                },
            },
        )
        assert cont.status_code == 200
        assert cont.json()["status"] == "degraded"
        fetched = await api.get(f"/api/v1/workflo/runs/{run_id}")
        finding_types = [e["type"] for e in fetched.json()["events"]]
        assert "finding" in finding_types


class TestRunContract:
    async def test_full_pipeline_run(self, api) -> None:
        files = [
            {
                "path": "package.json",
                "content_base64": _b64('{"name":"demo","scripts":{"test":"node run.js"}}'),
            },
            {"path": "run.js", "content_base64": _b64("console.log('tests: 3 passed')")},
        ]
        resp = await api.post(
            "/api/v1/workflo/runs",
            json={
                "workspace_id": "ws_demo",
                "name": "smoke-run",
                "intent": "run regression suite",
                "files": files,
                "command": "npm test --silent",
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["id"].startswith("run_")
        assert body["sandbox_id"].startswith("sbx_")
        assert body["plan"]["step_count"] >= 4
        types = [e["type"] for e in body["events"]]
        for expected in ("created", "mounted", "planned", "executing", "reported", "completed"):
            assert expected in types, f"missing event {expected} in {types}"
        assert body["status"] == "passed"
        artifact_names = [a["name"] for a in body["artifacts"]]
        assert any(n.startswith("report-") and n.endswith(".md") for n in artifact_names)

    async def test_run_events_sse_stream(self, api) -> None:
        run = await api.post(
            "/api/v1/workflo/runs",
            json={"workspace_id": "ws", "name": "sse", "intent": "", "files": []},
        )
        run_id = run.json()["id"]
        async with api.stream("GET", f"/api/v1/workflo/runs/{run_id}/events") as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            chunks = []
            async for chunk in resp.aiter_text():
                chunks.append(chunk)
                if "completed" in "".join(chunks):
                    break
        stream = "".join(chunks)
        assert "event: created" in stream

    async def test_run_artifacts_listing(self, api) -> None:
        run = await api.post(
            "/api/v1/workflo/runs",
            json={
                "workspace_id": "ws",
                "name": "art",
                "files": [],
                "command": "echo hi > ../artifacts/out.txt",
            },
        )
        run_id = run.json()["id"]
        arts = await api.get(f"/api/v1/workflo/runs/{run_id}/artifacts")
        assert arts.status_code == 200
        names = [a["name"] for a in arts.json()["artifacts"]]
        assert "out.txt" in names

    async def test_health_endpoint(self, api) -> None:
        resp = await api.get("/api/v1/workflo/health")
        assert resp.status_code == 200
        assert resp.json()["service"] == "workflo-control-plane"
