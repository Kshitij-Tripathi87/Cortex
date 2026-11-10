"""Workflo deployed-boundary security qualification — API-level integration.

Distinction this suite draws (per the RC0 security matrix):
  * NOT "a security rule exists somewhere in a unit test" —
  * Each test drives the REAL FastAPI application boundary and proves the
    application enforces the control on the deployed request path.

Coverage map (staging security matrix):
  Tenant isolation  — cross-workspace sandbox/run/receipt/artifact access 403
  Authorization     — strict-env Bearer enforcement (401), token scope (403)
  Queue/replay      — destroyed-sandbox reuse denied; event-chain tamper caught
  Secrets           — host secret never surfaces in events/receipt/report
  Policy integrity  — runtime image identity mismatch denied at the API
  Evidence          — stored-receipt tampering detected by the verify endpoint
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1 import workflo as workflo_module
from app.api.v1.workflo import router as workflo_router
from app.modules.workflo_backend.execution_policy import RunnerProfile
from app.modules.workflo_backend.orchestrator import reset_orchestrator
from app.modules.workflo_backend.runs import get_run_store

DIGEST = "sha256:" + "ab" * 32
SIGNING_KEY = "security-qualification-key"
SECRET_TOKEN = "super-secret-host-credential-9f2b7c"

WORKSPACE_A = "ws-tenant-a"
WORKSPACE_B = "ws-tenant-b"


def _restricted_headers(workspace: str) -> dict[str, str]:
    """Simulate a scoped principal at the dev identity boundary."""
    return {"X-User-Id": f"user-{workspace}", "X-User-Workspaces": workspace}


@pytest.fixture()
async def api(tmp_path, monkeypatch):
    reset_orchestrator()
    monkeypatch.setenv("CORTEX_WORKFLO_ROOT", str(tmp_path / "wf-root"))
    monkeypatch.setenv("CORTEX_TEST_SECRET_TOKEN", SECRET_TOKEN)
    test_app = FastAPI()
    test_app.include_router(workflo_router, prefix="/api/v1")
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        yield client


def _bundle_payload(profile_id: str = "qual-runner") -> dict[str, Any]:
    profile = RunnerProfile(
        profile_id=profile_id,
        image_ref=f"ghcr.io/workflo/worker@{DIGEST}",
        tool_version="1.2.3",
        cpu_limit=2,
        memory_limit_mb=1024,
        execution_timeout_s=120,
        process_limit=64,
        network_mode="none",
        allowed_hosts=(),
        command_allowlist=("python", "echo"),
    )
    from app.modules.workflo_backend.execution_policy import ExecutionPolicyBundle

    return ExecutionPolicyBundle(
        bundle_id="security-qual",
        policy_version="v1",
        cpu_limit=4,
        memory_limit_mb=2048,
        process_limit=128,
        execution_timeout_s=300,
        network_mode="none",
        command_allowlist=("python", "echo"),
        authorised_profiles=(profile,),
    ).to_dict()


async def _create_qualified_run(api: AsyncClient, workspace: str) -> dict[str, Any]:
    resp = await api.post(
        "/api/v1/workflo/runs",
        headers=_restricted_headers(workspace),
        json={
            "workspace_id": workspace,
            "name": "security-qual-run",
            "intent": "deployed boundary qualification",
            "command": "echo qualification",
            "policy_bundle": _bundle_payload(),
            "profile_id": "qual-runner",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ─────────────────────────────────────────────────────────────────────────────
# Tenant isolation
# ─────────────────────────────────────────────────────────────────────────────


class TestTenantIsolation:
    async def test_cross_workspace_sandbox_access_denied(self, api) -> None:
        created = await api.post(
            "/api/v1/workflo/sandboxes",
            headers=_restricted_headers(WORKSPACE_A),
            json={"workspace_id": WORKSPACE_A, "name": "a-sandbox"},
        )
        assert created.status_code == 201
        sandbox_id = created.json()["id"]

        resp = await api.get(
            f"/api/v1/workflo/sandboxes/{sandbox_id}",
            headers=_restricted_headers(WORKSPACE_B),
        )
        assert resp.status_code == 403
        assert resp.json()["detail"]["error"] == "forbidden"

        destroyed = await api.delete(
            f"/api/v1/workflo/sandboxes/{sandbox_id}",
            headers=_restricted_headers(WORKSPACE_B),
        )
        assert destroyed.status_code == 403

    async def test_cross_workspace_run_and_evidence_denied(self, api) -> None:
        run = await _create_qualified_run(api, WORKSPACE_A)
        run_id = run["id"]

        for path in (
            f"/api/v1/workflo/runs/{run_id}",
            f"/api/v1/workflo/runs/{run_id}/receipt",
            f"/api/v1/workflo/runs/{run_id}/receipt/verify",
            f"/api/v1/workflo/runs/{run_id}/events/verify",
        ):
            resp = await api.get(path, headers=_restricted_headers(WORKSPACE_B))
            assert resp.status_code == 403, f"{path} → {resp.status_code}"

    async def test_cross_workspace_file_and_artifact_access_denied(self, api) -> None:
        created = await api.post(
            "/api/v1/workflo/sandboxes",
            headers=_restricted_headers(WORKSPACE_A),
            json={"workspace_id": WORKSPACE_A, "name": "files"},
        )
        sandbox_id = created.json()["id"]
        import base64

        await api.post(
            f"/api/v1/workflo/sandboxes/{sandbox_id}/files",
            headers=_restricted_headers(WORKSPACE_A),
            json={"path": "secret.txt", "content_base64": base64.b64encode(b"x").decode()},
        )
        resp = await api.get(
            f"/api/v1/workflo/sandboxes/{sandbox_id}/files/content",
            headers=_restricted_headers(WORKSPACE_B),
            params={"path": "secret.txt"},
        )
        assert resp.status_code == 403


# ─────────────────────────────────────────────────────────────────────────────
# Authorization — strict environment (prod/pilot identity)
# ─────────────────────────────────────────────────────────────────────────────


class TestStrictAuthorization:
    async def test_strict_env_requires_bearer(self, api, monkeypatch) -> None:
        monkeypatch.setattr(workflo_module, "_is_strict_env", lambda: True, raising=False)
        # get_current_user is imported into workflo.py's deps module; patch
        # the security module's strict check used by the real dependency.
        from app.modules.workflo_backend.infrastructure import security as security_module

        monkeypatch.setattr(security_module, "_is_strict_env", lambda: True)

        resp = await api.post(
            "/api/v1/workflo/sandboxes",
            json={"workspace_id": WORKSPACE_A, "name": "strict"},
        )
        assert resp.status_code == 401
        assert "Bearer" in resp.json()["detail"]

    async def test_strict_env_workspace_scoped_token_cannot_cross_tenant(
        self, api, monkeypatch
    ) -> None:
        from uuid import uuid4

        from app.config import Settings
        from app.modules.identity.jwt_auth import issue_token
        from app.modules.workflo_backend.infrastructure import security as security_module

        settings = Settings(jwt_secret="strict-test-secret-0123456789abcdef", jwt_audience="cortex")
        token, _ = issue_token(
            user_id=uuid4(),
            workspace_id=uuid4(),  # a DIFFERENT workspace than WORKSPACE_A
            role="operator",
            email="op@test",
            settings=settings,
        )
        monkeypatch.setattr(security_module, "_is_strict_env", lambda: True)
        # verify_token resolves settings through jwt_auth's own module —
        # patch that reference so the same secret is used for verification.
        import app.modules.identity.jwt_auth as jwt_auth_module

        monkeypatch.setattr(jwt_auth_module, "get_settings", lambda: settings)

        resp = await api.post(
            "/api/v1/workflo/sandboxes",
            headers={"Authorization": f"Bearer {token}"},
            json={"workspace_id": WORKSPACE_A, "name": "crossed"},
        )
        assert resp.status_code == 403


# ─────────────────────────────────────────────────────────────────────────────
# Queue / replay security
# ─────────────────────────────────────────────────────────────────────────────


class TestQueueSecurity:
    async def test_destroyed_sandbox_reuse_denied_at_api(self, api) -> None:
        created = await api.post(
            "/api/v1/workflo/sandboxes",
            headers=_restricted_headers(WORKSPACE_A),
            json={"workspace_id": WORKSPACE_A, "name": "doomed"},
        )
        sandbox_id = created.json()["id"]
        destroyed = await api.delete(
            f"/api/v1/workflo/sandboxes/{sandbox_id}",
            headers=_restricted_headers(WORKSPACE_A),
        )
        assert destroyed.status_code == 200

        replay = await api.post(
            f"/api/v1/workflo/sandboxes/{sandbox_id}/execute",
            headers=_restricted_headers(WORKSPACE_A),
            json={"command": "echo replay-attack"},
        )
        assert replay.status_code == 403
        assert "destroyed" in replay.json()["detail"]["message"]

    async def test_event_chain_tamper_detected_at_api(self, api) -> None:
        run = await _create_qualified_run(api, WORKSPACE_A)
        run_id = run["id"]

        clean = await api.get(
            f"/api/v1/workflo/runs/{run_id}/events/verify",
            headers=_restricted_headers(WORKSPACE_A),
        )
        assert clean.json()["chain_ok"] is True

        # Tamper with a recorded lifecycle payload (policy_enforced digests).
        store = get_run_store()
        stored_run = store.get(run_id)
        for ev in stored_run.events:
            if ev.type == "policy_enforced":
                ev.data["policy_digest"] = "f" * 64
                break

        tampered = await api.get(
            f"/api/v1/workflo/runs/{run_id}/events/verify",
            headers=_restricted_headers(WORKSPACE_A),
        )
        body = tampered.json()
        assert body["chain_ok"] is False
        assert any("EVENT_HASH_MISMATCH" in f for f in body["failures"])

        # And the receipt verify endpoint cross-checks the SAME event stream.
        receipt_verdict = await api.get(
            f"/api/v1/workflo/runs/{run_id}/receipt/verify",
            headers=_restricted_headers(WORKSPACE_A),
        )
        assert receipt_verdict.json()["verification_passed"] is False
        assert any(
            "EVENT_DIGEST_MISMATCH_POLICY_DIGEST" in f for f in receipt_verdict.json()["failures"]
        )


# ─────────────────────────────────────────────────────────────────────────────
# Secrets
# ─────────────────────────────────────────────────────────────────────────────


class TestSecretsNonLeakage:
    async def test_host_secret_absent_from_evidence(self, api) -> None:
        run = await _create_qualified_run(api, WORKSPACE_A)
        blob = _response_evidence_blob(run)
        assert SECRET_TOKEN not in blob
        # The signing key must not leak either.
        assert SIGNING_KEY not in blob

    async def test_receipt_contains_no_environment_or_host_data(self, api, monkeypatch) -> None:
        monkeypatch.setenv("CORTEX_RECEIPT_SIGNING_KEY", SIGNING_KEY)
        run = await _create_qualified_run(api, WORKSPACE_A)
        receipt = run["receipt"]
        allowed_keys = set(receipt.keys())
        # The receipt carries ONLY binding fields — no environment dump,
        # no host paths, no credentials.
        assert allowed_keys == {
            "receipt_version",
            "run_spec_id",
            "sandbox_id",
            "command",
            "policy_digest",
            "bundle_digest",
            "profile_digest",
            "tool_version",
            "image_digest",
            "exit_code",
            "timed_out",
            "duration_ms",
            "artifact_count",
            "policy_enforced_event_hash",
            "executed_at",
            "receipt_hash",
            "signature",
        }


def _response_evidence_blob(run_response: dict[str, Any]) -> str:
    """Every byte of evidence the API returns for a run, as one string."""
    import json

    parts = [json.dumps(run_response)]
    for event in run_response.get("events", []):
        parts.append(json.dumps(event.get("data", {})))
    for finding in run_response.get("findings", []):
        parts.append(json.dumps(finding))
    receipt = run_response.get("receipt")
    if receipt:
        parts.append(json.dumps(receipt))
    return "\n".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Policy integrity + evidence tampering at the API
# ─────────────────────────────────────────────────────────────────────────────


class TestPolicyAndEvidenceIntegrity:
    async def test_runtime_image_digest_mismatch_denied_at_api(self, api, monkeypatch) -> None:
        monkeypatch.setenv("CORTEX_RUNNER_IMAGE_DIGEST", "sha256:" + "cd" * 32)
        resp = await api.post(
            "/api/v1/workflo/runs",
            headers=_restricted_headers(WORKSPACE_A),
            json={
                "workspace_id": WORKSPACE_A,
                "name": "image-mismatch",
                "command": "echo nope",
                "policy_bundle": _bundle_payload(),
                "profile_id": "qual-runner",
            },
        )
        assert resp.status_code == 403
        assert "IMAGE_IDENTITY_MISMATCH" in resp.json()["detail"]["message"]

    async def test_stored_receipt_tampering_detected(self, api, monkeypatch) -> None:
        monkeypatch.setenv("CORTEX_REQUIRE_SIGNED_RECEIPTS", "1")
        monkeypatch.setenv("CORTEX_RECEIPT_SIGNING_KEY", SIGNING_KEY)
        run = await _create_qualified_run(api, WORKSPACE_A)
        run_id = run["id"]

        clean = await api.get(
            f"/api/v1/workflo/runs/{run_id}/receipt/verify",
            headers=_restricted_headers(WORKSPACE_A),
        )
        assert clean.json()["verification_passed"] is True

        # Tamper with the STORED receipt (insider/DB-level modification).
        stored = get_run_store().get(run_id)
        stored.receipt["exit_code"] = 0 if stored.receipt["exit_code"] else 1

        verdict = await api.get(
            f"/api/v1/workflo/runs/{run_id}/receipt/verify",
            headers=_restricted_headers(WORKSPACE_A),
        )
        body = verdict.json()
        assert body["verification_passed"] is False
        assert any("RECEIPT_HASH_MISMATCH" in f for f in body["failures"])

    async def test_wrong_signing_key_rejected_at_api(self, api, monkeypatch) -> None:
        monkeypatch.setenv("CORTEX_REQUIRE_SIGNED_RECEIPTS", "1")
        monkeypatch.setenv("CORTEX_RECEIPT_SIGNING_KEY", SIGNING_KEY)
        run = await _create_qualified_run(api, WORKSPACE_A)
        run_id = run["id"]

        # Verification rotated to a different key: signed receipts from the
        # old key must not pass.
        monkeypatch.setenv("CORTEX_RECEIPT_SIGNING_KEY", "rotated-key-different")
        verdict = await api.get(
            f"/api/v1/workflo/runs/{run_id}/receipt/verify",
            headers=_restricted_headers(WORKSPACE_A),
        )
        body = verdict.json()
        assert body["verification_passed"] is False
        assert body["signature_ok"] is False
        assert any("RECEIPT_SIGNATURE_MISMATCH" in f for f in body["failures"])
