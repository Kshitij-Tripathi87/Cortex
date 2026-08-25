"""Workflo Control Plane API — sandboxes, execution, runs, events, artifacts.

Every documented curl against /api/v1/workflo/* is a contract test target.
Policy violations surface as HTTP 403 with a machine-readable violation reason;
unknown resources as 404. Execution is always mediated by SandboxOrchestrator.
"""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.modules.workflo.agent import build_plan, diagnose, discover_surfaces
from app.modules.workflo.orchestrator import (
    ExecutionResult,
    SandboxError,
    SandboxNotFound,
    get_orchestrator,
)
from app.modules.workflo.policy import PolicyViolation
from app.modules.workflo.runs import Run, RunNotFound, get_run_store

router = APIRouter()


class SandboxCreateRequest(BaseModel):
    workspace_id: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=128)
    policy: dict[str, Any] | None = None


class FileWriteRequest(BaseModel):
    path: str = Field(min_length=1)
    content_base64: str


class ExecuteRequest(BaseModel):
    command: str = Field(min_length=1)
    timeout_s: int | None = None


class RunCreateRequest(BaseModel):
    workspace_id: str = Field(min_length=1)
    name: str = Field(default="run", max_length=128)
    intent: str = ""
    files: list[FileWriteRequest] = Field(default_factory=list)
    command: str | None = None


class AgentPlanRequest(BaseModel):
    intent: str = Field(min_length=1)
    file_index: list[str] = Field(default_factory=list)


class AgentContinueRequest(BaseModel):
    run_id: str | None = None
    result: dict[str, Any]


def policy_error(reason: str) -> HTTPException:
    return HTTPException(
        status_code=403,
        detail={"code": "policy_violation", "message": reason},
    )


def not_found_error(message: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"code": "not_found", "message": message},
    )


def conflict_error(message: str) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"code": "conflict", "message": message},
    )


@router.get("/workflo/health")
async def health() -> dict[str, Any]:
    orch = get_orchestrator()
    return {
        "status": "ok",
        "service": "workflo-control-plane",
        "storage_root": str(orch.storage_root),
    }


# -- sandboxes ---------------------------------------------------------------


@router.post("/workflo/sandboxes", status_code=201)
async def create_sandbox(req: SandboxCreateRequest) -> dict[str, Any]:
    try:
        sandbox = get_orchestrator().create_sandbox(req.workspace_id, req.name, req.policy)
    except PolicyViolation as exc:
        raise policy_error(exc.reason) from exc
    d = sandbox.to_dict()
    d["layout"] = ["workspace/", "artifacts/", "tmp/"]
    return d


@router.get("/workflo/sandboxes/{sandbox_id}")
async def inspect_sandbox(sandbox_id: str) -> dict[str, Any]:
    try:
        return get_orchestrator().inspect(sandbox_id)
    except PolicyViolation as exc:
        raise policy_error(exc.reason) from exc
    except (SandboxNotFound, SandboxError) as exc:
        raise not_found_error(str(exc)) from exc


@router.delete("/workflo/sandboxes/{sandbox_id}")
async def destroy_sandbox(sandbox_id: str) -> dict[str, Any]:
    try:
        return get_orchestrator().destroy(sandbox_id)
    except PolicyViolation as exc:
        raise policy_error(exc.reason) from exc
    except (SandboxNotFound, SandboxError) as exc:
        raise not_found_error(str(exc)) from exc


@router.post("/workflo/sandboxes/{sandbox_id}/files", status_code=201)
async def write_file(sandbox_id: str, req: FileWriteRequest) -> dict[str, Any]:
    try:
        content = base64.b64decode(req.content_base64, validate=True)
        return get_orchestrator().write_file(sandbox_id, req.path, content)
    except PolicyViolation as exc:
        raise policy_error(exc.reason) from exc
    except (SandboxNotFound, SandboxError) as exc:
        raise not_found_error(str(exc)) from exc
    except ValueError as exc:
        raise conflict_error(f"invalid base64 content: {exc}") from exc


@router.get("/workflo/sandboxes/{sandbox_id}/files")
async def list_files(sandbox_id: str, path: str = "") -> dict[str, Any]:
    try:
        files: list[dict[str, Any]] = get_orchestrator().list_files(sandbox_id, path)
        return {"files": files}
    except PolicyViolation as exc:
        raise policy_error(exc.reason) from exc
    except (SandboxNotFound, SandboxError) as exc:
        raise not_found_error(str(exc)) from exc


@router.get("/workflo/sandboxes/{sandbox_id}/files/content")
async def read_file(sandbox_id: str, path: str) -> dict[str, Any]:
    try:
        content = get_orchestrator().read_file(sandbox_id, path)
        return {
            "path": path,
            "content_base64": base64.b64encode(content).decode(),
            "size_bytes": len(content),
        }
    except PolicyViolation as exc:
        raise policy_error(exc.reason) from exc
    except (SandboxNotFound, SandboxError) as exc:
        raise not_found_error(str(exc)) from exc


@router.post("/workflo/sandboxes/{sandbox_id}/execute")
async def execute(sandbox_id: str, req: ExecuteRequest) -> dict[str, Any]:
    try:
        result = await get_orchestrator().execute(sandbox_id, req.command, req.timeout_s)
    except PolicyViolation as exc:
        raise policy_error(exc.reason) from exc
    except SandboxNotFound as exc:
        raise not_found_error(str(exc)) from exc
    except SandboxError as exc:
        raise conflict_error(str(exc)) from exc
    d = result.to_dict()
    d["diagnosis"] = diagnose(d)
    return d


# -- agent -------------------------------------------------------------------


@router.post("/workflo/agent/plan")
async def agent_plan(req: AgentPlanRequest) -> dict[str, Any]:
    discovered = discover_surfaces(req.file_index)
    plan = build_plan(req.intent, discovered)
    out = plan.to_dict()
    out["discovered"] = discovered
    return out


@router.post("/workflo/agent/continue")
async def agent_continue(req: AgentContinueRequest) -> dict[str, Any]:
    diagnosis = diagnose(req.result)
    if req.run_id:
        store = get_run_store()
        try:
            for finding in diagnosis["findings"]:
                store.append_event(req.run_id, "finding", finding["title"], {"finding": finding})
        except RunNotFound as exc:
            raise not_found_error(str(exc)) from exc
    return diagnosis


# -- runs --------------------------------------------------------------------


def _default_command(discovered: dict[str, Any]) -> str:
    frameworks = discovered.get("frameworks", [])
    if "node" in frameworks:
        return "npm test --silent"
    if "pytest" in frameworks:
        return "python -m pytest -q"
    if "go" in frameworks:
        return "go test ./..."
    if "cargo" in frameworks:
        return "cargo test"
    return "cmd /c echo no test framework detected"


def render_report(run: Run, result: ExecutionResult, diagnosis: dict[str, Any]) -> str:
    lines = [
        f"# Workflo Report — {run.id}",
        "",
        f"- intent: {run.intent or '(none)'}",
        f"- status: **{run.status}**",
        f"- sandbox: `{run.sandbox_id}`",
        f"- duration: {result.duration_ms}ms",
        "",
        "## Findings",
        "",
    ]
    findings = diagnosis.get("findings", [])
    if not findings:
        lines.append("No findings.")
    for finding in findings:
        lines += [
            f"### [{finding['severity']}] {finding['title']}",
            "",
            "```",
            finding.get("evidence", ""),
            "```",
            "",
            f"Suggested fix: {finding.get('suggestion', '')}",
            "",
        ]
    return "\n".join(lines)


@router.post("/workflo/runs", status_code=201)
async def create_run(req: RunCreateRequest) -> dict[str, Any]:
    orchestrator = get_orchestrator()
    store = get_run_store()
    try:
        sandbox = orchestrator.create_sandbox(req.workspace_id, req.name, None)
        run = store.create(req.workspace_id, req.name, req.intent)
        run.sandbox_id = sandbox.id
        store.append_event(run.id, "created", f"run {run.name} created")

        file_index: list[str] = []
        for spec in req.files:
            content = base64.b64decode(spec.content_base64, validate=True)
            orchestrator.write_file(sandbox.id, spec.path, content)
            file_index.append(spec.path)
        if file_index:
            store.append_event(
                run.id,
                "mounted",
                f"{len(file_index)} file(s) mounted",
                {"count": len(file_index)},
            )

        discovered = discover_surfaces(file_index)
        plan = build_plan(req.intent or req.name, discovered)
        run.plan = plan.to_dict()
        store.append_event(
            run.id,
            "planned",
            f"plan built with {len(plan.steps)} steps",
            {"steps": [step.detail for step in plan.steps]},
        )

        command = req.command or _default_command(discovered)
        store.append_event(run.id, "executing", f"$ {command}", {"command": command})
        result = await orchestrator.execute(sandbox.id, command)
        run.status = "passed" if (result.exit_code == 0 and not result.timed_out) else "failed"
        store.append_event(
            run.id,
            "executed" if result.exit_code == 0 else "failed",
            f"exit={result.exit_code} in {result.duration_ms}ms",
            {"exit_code": result.exit_code, "duration_ms": result.duration_ms},
        )
        artifacts: list[dict[str, Any]] = [
            {"name": artifact.name, "path": artifact.path, "size_bytes": artifact.size_bytes}
            for artifact in result.artifacts
        ]

        diagnosis = diagnose(result.to_dict())
        run.findings = diagnosis["findings"]
        for finding in run.findings:
            store.append_event(run.id, "finding", finding["title"], {"finding": finding})
        report_md = render_report(run, result, diagnosis)
        report_name = f"report-{run.id}.md"
        orchestrator.save_artifact(sandbox.id, report_name, report_md.encode())
        artifacts.append(
            {
                "name": report_name,
                "path": f"artifacts/{report_name}",
                "size_bytes": len(report_md.encode()),
            }
        )
        store.set_artifacts(run.id, artifacts)

        store.append_event(run.id, "reported", "report generated")
        store.append_event(run.id, "completed", f"run {run.status}")

        out = run.to_dict(include_events=True)
        out["execution"] = result.to_dict()
        out["diagnosis"] = diagnosis
        out["artifacts"] = artifacts
        return out
    except PolicyViolation as exc:
        raise policy_error(exc.reason) from exc
    except SandboxError as exc:
        raise conflict_error(str(exc)) from exc


@router.get("/workflo/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    try:
        return get_run_store().get(run_id).to_dict(include_events=True)
    except RunNotFound as exc:
        raise not_found_error(str(exc)) from exc


@router.get("/workflo/runs/{run_id}/artifacts")
async def list_run_artifacts(run_id: str) -> dict[str, Any]:
    try:
        run = get_run_store().get(run_id)
        return {"artifacts": run.artifacts}
    except RunNotFound as exc:
        raise not_found_error(str(exc)) from exc


@router.get("/workflo/runs/{run_id}/events")
async def stream_events(run_id: str, request: Request) -> StreamingResponse:
    try:
        queue = await get_run_store().subscribe(run_id)
    except RunNotFound as exc:
        raise not_found_error(str(exc)) from exc

    async def event_stream() -> AsyncIterator[str]:
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield (f"id: {ev.seq}\nevent: {ev.type}\ndata: {json.dumps(ev.to_dict())}\n\n")
                    if ev.type == "completed":
                        break
                except TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            get_run_store().unsubscribe(run_id, queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
