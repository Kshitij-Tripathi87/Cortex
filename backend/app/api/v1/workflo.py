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

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.modules.workflo_backend.agent import build_plan, diagnose, discover_surfaces
from app.modules.workflo_backend.execution_policy import (
    ExecutionPolicyBundle,
    PolicyResolutionError,
)
from app.modules.workflo_backend.infrastructure.security import (
    AuthContext,
    get_current_user,
    require_workspace_access,
)
from app.modules.workflo_backend.orchestrator import (
    ExecutionResult,
    SandboxError,
    SandboxNotFound,
    get_orchestrator,
)
from app.modules.workflo_backend.policy import PolicyViolation
from app.modules.workflo_backend.receipts import (
    ProductionReceipt,
    build_production_receipt,
    get_signing_key,
    sign_receipt,
    signing_required,
    verify_production_receipt,
)
from app.modules.workflo_backend.runs import (
    Run,
    RunNotFound,
    find_event,
    get_run_store,
    verify_event_chain,
)

router = APIRouter()


class SandboxCreateRequest(BaseModel):
    workspace_id: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=128)
    policy: dict[str, Any] | None = None
    # Optional validated policy bundle + authorised profile — resolves the
    # execution context exactly like the production run path, so the direct
    # executor path and production path share one policy resolution.
    policy_bundle: dict[str, Any] | None = None
    profile_id: str | None = None
    run_spec_id: str | None = None


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
    # Production receipt bindings: validated policy bundle + authorised
    # runner profile. When provided, the run resolves the profile
    # (fail-closed), emits a policy_enforced lifecycle event, and produces
    # a signed, independently verifiable production receipt.
    policy_bundle: dict[str, Any] | None = None
    profile_id: str | None = None


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


def service_unavailable_error(message: str) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={"code": "service_unavailable", "message": message},
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
async def create_sandbox(
    req: SandboxCreateRequest,
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    require_workspace_access(req.workspace_id, auth)
    try:
        bundle: ExecutionPolicyBundle | None = None
        if req.policy_bundle is not None:
            bundle = ExecutionPolicyBundle.from_dict(req.policy_bundle)
            bundle.require_valid()
        sandbox = get_orchestrator().create_sandbox(
            req.workspace_id,
            req.name,
            req.policy,
            bundle=bundle,
            profile_id=req.profile_id or "",
            run_spec_id=req.run_spec_id or "",
        )
    except PolicyResolutionError as exc:
        raise policy_error(f"{exc.code}: {exc.message}") from exc
    except PolicyViolation as exc:
        raise policy_error(exc.reason) from exc
    d = sandbox.to_dict()
    d["layout"] = ["workspace/", "artifacts/", "tmp/"]
    return d


@router.get("/workflo/sandboxes/{sandbox_id}")
async def inspect_sandbox(
    sandbox_id: str,
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        sb = get_orchestrator().get(sandbox_id)
        require_workspace_access(sb.workspace_id, auth)
        return get_orchestrator().inspect(sandbox_id)
    except PolicyViolation as exc:
        raise policy_error(exc.reason) from exc
    except (SandboxNotFound, SandboxError) as exc:
        raise not_found_error(str(exc)) from exc


@router.delete("/workflo/sandboxes/{sandbox_id}")
async def destroy_sandbox(
    sandbox_id: str,
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        sb = get_orchestrator().get(sandbox_id)
        require_workspace_access(sb.workspace_id, auth)
        return get_orchestrator().destroy(sandbox_id)
    except PolicyViolation as exc:
        raise policy_error(exc.reason) from exc
    except (SandboxNotFound, SandboxError) as exc:
        raise not_found_error(str(exc)) from exc


@router.post("/workflo/sandboxes/{sandbox_id}/files", status_code=201)
async def write_file(
    sandbox_id: str,
    req: FileWriteRequest,
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        sb = get_orchestrator().get(sandbox_id)
        require_workspace_access(sb.workspace_id, auth)
        content = base64.b64decode(req.content_base64, validate=True)
        return get_orchestrator().write_file(sandbox_id, req.path, content)
    except PolicyViolation as exc:
        raise policy_error(exc.reason) from exc
    except (SandboxNotFound, SandboxError) as exc:
        raise not_found_error(str(exc)) from exc
    except ValueError as exc:
        raise conflict_error(f"invalid base64 content: {exc}") from exc


@router.get("/workflo/sandboxes/{sandbox_id}/files")
async def list_files(
    sandbox_id: str,
    path: str = "",
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        sb = get_orchestrator().get(sandbox_id)
        require_workspace_access(sb.workspace_id, auth)
        files: list[dict[str, Any]] = get_orchestrator().list_files(sandbox_id, path)
        return {"files": files}
    except PolicyViolation as exc:
        raise policy_error(exc.reason) from exc
    except (SandboxNotFound, SandboxError) as exc:
        raise not_found_error(str(exc)) from exc


@router.get("/workflo/sandboxes/{sandbox_id}/files/content")
async def read_file(
    sandbox_id: str,
    path: str,
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        sb = get_orchestrator().get(sandbox_id)
        require_workspace_access(sb.workspace_id, auth)
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
async def execute(
    sandbox_id: str,
    req: ExecuteRequest,
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        sb = get_orchestrator().get(sandbox_id)
        require_workspace_access(sb.workspace_id, auth)
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
async def agent_plan(
    req: AgentPlanRequest,
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    discovered = discover_surfaces(req.file_index)
    plan = build_plan(req.intent, discovered)
    out = plan.to_dict()
    out["discovered"] = discovered
    return out


@router.post("/workflo/agent/continue")
async def agent_continue(
    req: AgentContinueRequest,
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    diagnosis = diagnose(req.result)
    if req.run_id:
        store = get_run_store()
        try:
            run = store.get(req.run_id)
            require_workspace_access(run.workspace_id, auth)
            for finding in diagnosis["findings"]:
                store.append_event(req.run_id, "finding", finding["title"], {"finding": finding})
        except RunNotFound as exc:
            raise not_found_error(str(exc)) from exc
    return diagnosis


# -- runs ----------------------------------------------------------------


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


def _resolved_bundle_or_denial(
    req: RunCreateRequest,
    store: Any,
    run: Run,
) -> ExecutionPolicyBundle:
    """Reconstruct + validate the bundle; record a policy_denied event on failure.

    A policy-blocked run produces NO execution receipt, but the denial
    remains auditable as a policy decision in the run's event stream.
    Raises PolicyViolation (already recorded) on any failure.
    """
    try:
        bundle = ExecutionPolicyBundle.from_dict(req.policy_bundle)
        bundle.require_valid()
        # Fail-closed resolution BEFORE any sandbox exists: an unauthorised
        # profile, floating image tag, or egress bypass never reaches
        # container creation.
        bundle.resolve(req.profile_id or "", run.id)
    except PolicyResolutionError as exc:
        store.append_event(
            run.id,
            "policy_denied",
            f"policy decision: {exc.code}",
            {"code": exc.code, "reason": exc.message, "profile_id": req.profile_id or ""},
        )
        # The denial is auditable via the run's event stream; no execution
        # receipt is produced for a policy-blocked request.
        raise PolicyViolation(f"{exc.code}: {exc.message} (run_id={run.id})") from exc
    return bundle


@router.post("/workflo/runs", status_code=201)
async def create_run(
    req: RunCreateRequest,
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    require_workspace_access(req.workspace_id, auth)

    # Fail-closed evidence guarantee: in staging/pilot/prod (or when the
    # explicit flag is set), governed execution is refused entirely unless
    # a receipt signing key is configured — with or without a policy bundle.
    # Staging must never silently operate without signed production receipts.
    if signing_required() and not get_signing_key():
        raise service_unavailable_error(
            "RECEIPT_SIGNING_UNAVAILABLE: CORTEX_RECEIPT_SIGNING_KEY is not "
            "configured; signed production receipts cannot be issued, so "
            "governed execution is refused in this environment. Configure the "
            "signing key from the secret store to enable execution."
        )

    orchestrator = get_orchestrator()
    store = get_run_store()
    try:
        run = store.create(req.workspace_id, req.name, req.intent)
        store.append_event(run.id, "created", f"run {run.name} created")

        # ── Policy resolution (fail-closed, before any sandbox exists) ──
        bundle: ExecutionPolicyBundle | None = None
        resolved = None
        if req.policy_bundle is not None:
            bundle = _resolved_bundle_or_denial(req, store, run)
            resolved = bundle.resolve(req.profile_id or "", run.id)
            store.append_event(
                run.id,
                "policy_enforced",
                f"policy {resolved.policy_version} enforced via profile "
                f"'{resolved.profile_id}' (bundle '{resolved.bundle_id}')",
                {
                    "run_spec_id": resolved.run_spec_id,
                    "profile_id": resolved.profile_id,
                    "bundle_id": resolved.bundle_id,
                    "policy_version": resolved.policy_version,
                    "policy_digest": resolved.policy_digest,
                    "bundle_digest": resolved.bundle_digest,
                    "profile_digest": resolved.profile_digest,
                    "tool_version": resolved.tool_version,
                    "image_ref": resolved.image_ref,
                    "image_digest": resolved.image_digest,
                },
            )

        sandbox = orchestrator.create_sandbox(
            req.workspace_id,
            req.name,
            None,
            bundle=bundle,
            profile_id=req.profile_id or "",
            run_spec_id=run.id if bundle else "",
        )
        run.sandbox_id = sandbox.id

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

        # ── Production receipt (bound to the SAME resolved context) ─────
        if resolved is not None:
            policy_event = find_event(run, "policy_enforced")
            receipt = build_production_receipt(
                resolved=resolved,
                result=result,
                policy_enforced_event_hash=policy_event.hash if policy_event else "",
            )
            signing_key = get_signing_key()
            if signing_key:
                receipt = sign_receipt(receipt, signing_key)
            verification = verify_production_receipt(
                receipt,
                run=run,
                signing_key=signing_key or None,
            )
            store.append_event(
                run.id,
                "receipt_created",
                f"production receipt bound ({receipt.receipt_hash[:16]}…)",
                {
                    "receipt_hash": receipt.receipt_hash,
                    "policy_digest": receipt.policy_digest,
                    "bundle_digest": receipt.bundle_digest,
                    "profile_digest": receipt.profile_digest,
                    "image_digest": receipt.image_digest,
                },
            )
            out["receipt"] = receipt.to_dict()
            out["receipt_verification"] = verification.to_dict()
            run.receipt = receipt.to_dict()

        return out
    except PolicyViolation as exc:
        raise policy_error(exc.reason) from exc
    except SandboxError as exc:
        raise conflict_error(str(exc)) from exc


@router.get("/workflo/runs/{run_id}")
async def get_run(
    run_id: str,
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        run = get_run_store().get(run_id)
        require_workspace_access(run.workspace_id, auth)
        return run.to_dict(include_events=True)
    except RunNotFound as exc:
        raise not_found_error(str(exc)) from exc


@router.get("/workflo/runs/{run_id}/receipt")
async def get_run_receipt(
    run_id: str,
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Return the run's production receipt, if one was issued.

    Policy-blocked and unresolved (legacy) runs have no receipt — the
    response states so explicitly rather than fabricating evidence.
    """
    try:
        run = get_run_store().get(run_id)
        require_workspace_access(run.workspace_id, auth)
    except RunNotFound as exc:
        raise not_found_error(str(exc)) from exc
    if run.receipt is None:
        denied = find_event(run, "policy_denied") is not None
        return {
            "run_id": run_id,
            "receipt": None,
            "reason": ("policy_denied_no_receipt" if denied else "unresolved_execution_no_receipt"),
        }
    return {"run_id": run_id, "receipt": run.receipt}


@router.get("/workflo/runs/{run_id}/receipt/verify")
async def verify_run_receipt(
    run_id: str,
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Independently verify a run's production receipt.

    Recomputes the binding hash, checks the HMAC signature (when a signing
    key is configured), and cross-checks every digest against the run's
    hash-chained ``policy_enforced`` lifecycle event. This endpoint trusts
    nothing on the receipt: every binding is re-derived from the event
    stream.
    """
    try:
        run = get_run_store().get(run_id)
        require_workspace_access(run.workspace_id, auth)
    except RunNotFound as exc:
        raise not_found_error(str(exc)) from exc
    if run.receipt is None:
        return {
            "run_id": run_id,
            "verification_passed": False,
            "failures": ["RECEIPT_ABSENT"],
            "receipt": None,
        }
    receipt = ProductionReceipt.from_dict(run.receipt)
    verification = verify_production_receipt(
        receipt,
        run=run,
        require_signature=signing_required(),
    )
    return {
        "run_id": run_id,
        **verification.to_dict(),
    }


@router.get("/workflo/runs/{run_id}/events/verify")
async def verify_run_events(
    run_id: str,
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Verify the integrity of a run's hash-chained lifecycle event stream.

    Recomputes every event hash and the chain linkage, so any tampering
    with recorded messages, payloads, or timestamps is detected. This is
    the audit surface for lifecycle evidence (created → policy_enforced →
    executed → receipt_created → completed).
    """
    try:
        run = get_run_store().get(run_id)
        require_workspace_access(run.workspace_id, auth)
    except RunNotFound as exc:
        raise not_found_error(str(exc)) from exc
    ok, failures = verify_event_chain(run)
    return {
        "run_id": run_id,
        "event_count": len(run.events),
        "chain_ok": ok,
        "failures": failures,
    }


@router.get("/workflo/runs/{run_id}/artifacts")
async def list_run_artifacts(
    run_id: str,
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        run = get_run_store().get(run_id)
        require_workspace_access(run.workspace_id, auth)
        return {"artifacts": run.artifacts}
    except RunNotFound as exc:
        raise not_found_error(str(exc)) from exc


@router.get("/workflo/runs/{run_id}/events")
async def stream_events(
    run_id: str,
    request: Request,
    auth: AuthContext = Depends(get_current_user),
) -> StreamingResponse:
    try:
        run = get_run_store().get(run_id)
        require_workspace_access(run.workspace_id, auth)
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
