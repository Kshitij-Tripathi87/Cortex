"""Workflo production receipt binding tests — P0 attack matrix.

Covers the P0 exit criterion: production receipts are bound to the resolved
execution context and independently verifiable — not just receipts generated
through the direct executor test path.

Matrix:
  1. Bundle cross-document validation (stable error codes)
  2. Policy resolution (authorised profiles only, fail-closed)
  3. Image identity: digest pinning, floating-tag rejection, runtime mismatch
  4. Executor enforcement under a resolved policy
  5. Production receipt: all bindings present → verification passes
  6. Receipt ↔ lifecycle event digest consistency (policy_enforced)
  7. Policy changes after submission → detected
  8. Profile substitution → detected
  9. Egress-policy bypass → blocked before execution
  10. Missing / incomplete bindings → rejected by the verifier
  11. Modified signed receipt → verification fails
  12. Policy-blocked run → NO receipt, denial auditable as a policy decision
  13. Full production path over HTTP: receipt + verify endpoint
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1.workflo import router as workflo_router
from app.modules.workflo_backend.execution_policy import (
    ExecutionPolicyBundle,
    PolicyResolutionError,
    RunnerProfile,
)
from app.modules.workflo_backend.orchestrator import (
    SandboxOrchestrator,
    reset_orchestrator,
)
from app.modules.workflo_backend.policy import PolicyViolation
from app.modules.workflo_backend.receipts import (
    ProductionReceipt,
    build_production_receipt,
    sign_receipt,
    verify_production_receipt,
)
from app.modules.workflo_backend.runs import RunStore, find_event

DIGEST = "sha256:" + "ab" * 32
DIGEST_B = "sha256:" + "cd" * 32
SIGNING_KEY = "test-signing-key-0123456789abcdef"


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures & helpers
# ─────────────────────────────────────────────────────────────────────────────


def make_profile(profile_id: str = "ci-runner", **overrides: Any) -> RunnerProfile:
    defaults: dict[str, Any] = {
        "profile_id": profile_id,
        "image_ref": f"ghcr.io/workflo/worker@{DIGEST}",
        "tool_version": "1.2.3",
        "cpu_limit": 2,
        "memory_limit_mb": 1024,
        "execution_timeout_s": 120,
        "process_limit": 64,
        "network_mode": "none",
        "allowed_hosts": (),
        "command_allowlist": ("python", "echo"),
    }
    defaults.update(overrides)
    return RunnerProfile(**defaults)


def make_bundle(
    profiles: tuple[RunnerProfile, ...] | None = None, **overrides: Any
) -> ExecutionPolicyBundle:
    defaults: dict[str, Any] = {
        "bundle_id": "bundle-ci",
        "policy_version": "v1",
        "cpu_limit": 4,
        "memory_limit_mb": 2048,
        "process_limit": 128,
        "execution_timeout_s": 300,
        "network_mode": "none",
        "command_allowlist": ("python", "echo", "pytest"),
        "authorised_profiles": (make_profile(),) if profiles is None else profiles,
    }
    defaults.update(overrides)
    return ExecutionPolicyBundle(**defaults)


@pytest.fixture()
def orchestrator(tmp_path: Path) -> SandboxOrchestrator:
    return SandboxOrchestrator(tmp_path / "wf-root")


def execute_resolved(
    orchestrator: SandboxOrchestrator,
    store: RunStore,
    *,
    bundle: ExecutionPolicyBundle | None = None,
    profile_id: str = "ci-runner",
    command: str = "echo receipt-ok",
) -> tuple[Any, Any, Any]:
    """Drive the production flow: run → resolve → policy_enforced → execute.

    Returns (run, resolved, execution_result).
    """
    bundle = bundle or make_bundle()
    run = store.create("ws_test", "receipt-run", "verify receipt binding")
    resolved = bundle.resolve(profile_id, run.id)
    store.append_event(
        run.id,
        "policy_enforced",
        f"policy enforced via profile '{resolved.profile_id}'",
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
        "ws_test", "receipt-run", None, bundle=bundle, profile_id=profile_id, run_spec_id=run.id
    )
    result = orchestrator._run_sync_execute(sandbox.id, command)
    return run, resolved, result


# The orchestrator's execute() is async; a tiny sync shim keeps the matrix
# readable without asyncio everywhere.
def _run_sync_execute(self: SandboxOrchestrator, sandbox_id: str, command: str) -> Any:
    import asyncio

    return asyncio.run(self.execute(sandbox_id, command))


SandboxOrchestrator._run_sync_execute = _run_sync_execute  # type: ignore[attr-defined]


# ─────────────────────────────────────────────────────────────────────────────
# 1. Bundle cross-document validation
# ─────────────────────────────────────────────────────────────────────────────


class TestBundleValidation:
    def test_valid_bundle_has_no_failures(self) -> None:
        assert make_bundle().validate() == []

    def test_require_valid_passes(self) -> None:
        make_bundle().require_valid()

    def test_empty_profiles_rejected(self) -> None:
        failures = make_bundle(authorised_profiles=()).validate()
        assert "BUNDLE_PROFILES_EMPTY" in failures

    def test_missing_bundle_id_rejected(self) -> None:
        failures = make_bundle(bundle_id="").validate()
        assert "BUNDLE_ID_MISSING" in failures

    def test_duplicate_profile_ids_rejected(self) -> None:
        bundle = make_bundle(profiles=(make_profile("dup"), make_profile("dup")))
        assert "PROFILE_ID_DUPLICATE: dup" in bundle.validate()

    def test_profile_exceeding_resource_ceiling_rejected(self) -> None:
        profile = make_profile(cpu_limit=8)  # bundle ceiling is 4
        failures = make_bundle(profiles=(profile,)).validate()
        assert "PROFILE_EXCEEDS_CEILING: ci-runner cpu_limit" in failures

    def test_profile_exceeding_memory_ceiling_rejected(self) -> None:
        profile = make_profile(memory_limit_mb=4096)  # bundle ceiling 2048
        assert any(
            "PROFILE_EXCEEDS_CEILING: ci-runner memory_limit_mb" in f
            for f in make_bundle(profiles=(profile,)).validate()
        )

    def test_profile_command_outside_bundle_rejected(self) -> None:
        profile = make_profile(command_allowlist=("python", "kubectl"))
        failures = make_bundle(profiles=(profile,)).validate()
        assert "PROFILE_COMMANDS_OUTSIDE_BUNDLE: ci-runner ['kubectl']" in failures

    def test_invalid_bundle_cannot_resolve(self) -> None:
        bundle = make_bundle(profiles=())
        with pytest.raises(PolicyResolutionError) as excinfo:
            bundle.resolve("ci-runner", "run_1")
        assert excinfo.value.code == "BUNDLE_INVALID"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Policy resolution
# ─────────────────────────────────────────────────────────────────────────────


class TestResolution:
    def test_resolution_carries_all_digests(self) -> None:
        resolved = make_bundle().resolve("ci-runner", "run_res_1")
        failures = resolved.binding_failures()
        assert failures == []
        assert len(resolved.policy_digest) == 64
        assert len(resolved.bundle_digest) == 64
        assert len(resolved.profile_digest) == 64
        assert resolved.tool_version == "1.2.3"
        assert resolved.image_digest == DIGEST
        assert resolved.run_spec_id == "run_res_1"

    def test_policy_digest_commits_to_effective_policy(self) -> None:
        from app.modules.workflo_backend.execution_policy import effective_policy_digest

        resolved = make_bundle().resolve("ci-runner", "run_d")
        assert resolved.policy_digest == effective_policy_digest(resolved.effective_policy)

    def test_unauthorised_profile_rejected(self) -> None:
        with pytest.raises(PolicyResolutionError) as excinfo:
            make_bundle().resolve("ghost-profile", "run_1")
        assert excinfo.value.code == "PROFILE_NOT_AUTHORISED"

    def test_digests_deterministic(self) -> None:
        bundle = make_bundle()
        r1 = bundle.resolve("ci-runner", "run_x")
        r2 = bundle.resolve("ci-runner", "run_x")
        assert (r1.policy_digest, r1.bundle_digest, r1.profile_digest) == (
            r2.policy_digest,
            r2.bundle_digest,
            r2.profile_digest,
        )

    def test_different_profile_produces_different_profile_digest(self) -> None:
        bundle = make_bundle(
            profiles=(
                make_profile("runner-a", image_ref=f"img@{DIGEST}"),
                make_profile("runner-b", image_ref=f"img@{DIGEST_B}"),
            )
        )
        ra = bundle.resolve("runner-a", "run_1")
        rb = bundle.resolve("runner-b", "run_1")
        assert ra.profile_digest != rb.profile_digest
        assert ra.image_digest != rb.image_digest

    def test_bundle_change_produces_different_bundle_digest(self) -> None:
        r1 = make_bundle(policy_version="v1").resolve("ci-runner", "run_1")
        r2 = make_bundle(policy_version="v2").resolve("ci-runner", "run_1")
        assert r1.bundle_digest != r2.bundle_digest


# ─────────────────────────────────────────────────────────────────────────────
# 3. Image identity
# ─────────────────────────────────────────────────────────────────────────────


class TestImageIdentity:
    def test_digest_pinned_ref_accepted(self) -> None:
        resolved = make_bundle().resolve("ci-runner", "run_1")
        assert resolved.image_digest == DIGEST

    @pytest.mark.parametrize("floating", ["workflo-worker:latest", "workflo-worker", "worker:1.2"])
    def test_floating_tag_rejected(self, floating: str) -> None:
        profile = make_profile(image_ref=floating)
        failures = make_bundle(profiles=(profile,)).validate()
        assert any(f.startswith("PROFILE_IMAGE_NOT_PINNED") for f in failures)
        with pytest.raises(PolicyResolutionError):
            make_bundle(profiles=(profile,)).require_valid()

    def test_malformed_digest_rejected(self) -> None:
        profile = make_profile(image_ref="worker@sha256:nothex")
        assert any(
            f.startswith("PROFILE_IMAGE_NOT_PINNED")
            for f in make_bundle(profiles=(profile,)).validate()
        )

    def test_process_identity_resolved_to_runtime_digest(self) -> None:
        profile = make_profile(image_ref="process://ci-runner")
        resolved = make_bundle(profiles=(profile,)).resolve("ci-runner", "run_1")
        assert resolved.image_digest.startswith("process-")
        assert len(resolved.image_digest) > 16

    def test_runtime_image_identity_mismatch_fail_closed(self) -> None:
        resolved = make_bundle().resolve("ci-runner", "run_1")
        failures = resolved.binding_failures(runtime_image_digest=DIGEST_B)
        assert any(f.startswith("IMAGE_IDENTITY_MISMATCH") for f in failures)

    def test_runtime_image_identity_match_passes(self) -> None:
        resolved = make_bundle().resolve("ci-runner", "run_1")
        assert resolved.binding_failures(runtime_image_digest=DIGEST) == []

    def test_runtime_digest_env_mismatch_fail_closed(self, monkeypatch) -> None:
        """When the deployment injects the actually-running image digest and
        it disagrees with the profile's declared digest, resolution fails."""
        monkeypatch.setenv("CORTEX_RUNNER_IMAGE_DIGEST", DIGEST_B)
        with pytest.raises(PolicyResolutionError) as excinfo:
            make_bundle().resolve("ci-runner", "run_env")
        assert excinfo.value.code == "IMAGE_IDENTITY_MISMATCH"

    def test_runtime_digest_env_match_resolves(self, monkeypatch) -> None:
        monkeypatch.setenv("CORTEX_RUNNER_IMAGE_DIGEST", DIGEST)
        resolved = make_bundle().resolve("ci-runner", "run_env_ok")
        assert resolved.image_digest == DIGEST

    def test_runtime_digest_env_ignored_for_process_identity(self, monkeypatch) -> None:
        """The deployment override only applies to container image refs."""
        monkeypatch.setenv("CORTEX_RUNNER_IMAGE_DIGEST", DIGEST_B)
        profile = make_profile(image_ref="process://ci-runner")
        resolved = make_bundle(profiles=(profile,)).resolve("ci-runner", "run_env_proc")
        assert resolved.image_digest.startswith("process-")


# ─────────────────────────────────────────────────────────────────────────────
# 4. Executor enforcement under a resolved policy
# ─────────────────────────────────────────────────────────────────────────────


class TestExecutorEnforcement:
    def test_sandbox_enforces_effective_policy(self, orchestrator: SandboxOrchestrator) -> None:
        bundle = make_bundle()
        resolved = bundle.resolve("ci-runner", "run_e1")
        sandbox = orchestrator.create_sandbox(
            "ws_test", "enforced", None, bundle=bundle, profile_id="ci-runner", run_spec_id="run_e1"
        )
        assert sandbox.resolved is not None
        assert sandbox.resolved.policy_digest == resolved.policy_digest
        assert sandbox.policy.command_allowlist == ("python", "echo")
        assert sandbox.policy.network_mode == "none"

    def test_disallowed_command_blocked_before_execution(
        self, orchestrator: SandboxOrchestrator
    ) -> None:
        bundle = make_bundle()
        sandbox = orchestrator.create_sandbox(
            "ws_test", "blocked", None, bundle=bundle, profile_id="ci-runner", run_spec_id="run_e2"
        )
        with pytest.raises(PolicyViolation):
            orchestrator._run_sync_execute(sandbox.id, "whoami")
        # Nothing was executed: no artifacts, no result side effects.
        assert orchestrator.collect_artifacts(sandbox) == []

    def test_network_command_blocked_under_none_egress(
        self, orchestrator: SandboxOrchestrator
    ) -> None:
        bundle = make_bundle()
        sandbox = orchestrator.create_sandbox(
            "ws_test", "nonet", None, bundle=bundle, profile_id="ci-runner", run_spec_id="run_e3"
        )
        with pytest.raises(PolicyViolation):
            orchestrator._run_sync_execute(sandbox.id, "curl http://evil.example.com")

    def test_execution_result_carries_bindings(self, orchestrator: SandboxOrchestrator) -> None:
        bundle = make_bundle()
        resolved = bundle.resolve("ci-runner", "run_e4")
        sandbox = orchestrator.create_sandbox(
            "ws_test", "bind", None, bundle=bundle, profile_id="ci-runner", run_spec_id="run_e4"
        )
        result = orchestrator._run_sync_execute(sandbox.id, "echo hi")
        assert result.resolved is not None
        assert result.resolved.policy_digest == resolved.policy_digest
        d = result.to_dict()
        assert d["resolved"]["bundle_digest"] == resolved.bundle_digest

    def test_legacy_path_unresolved_still_works(self, orchestrator: SandboxOrchestrator) -> None:
        sandbox = orchestrator.create_sandbox("ws_test", "legacy", None)
        assert sandbox.resolved is None
        result = orchestrator._run_sync_execute(sandbox.id, "echo legacy")
        assert result.resolved is None
        assert result.exit_code == 0

    def test_resolution_requires_run_spec(self, orchestrator: SandboxOrchestrator) -> None:
        with pytest.raises(PolicyResolutionError) as excinfo:
            orchestrator.create_sandbox(
                "ws_test", "nospec", None, bundle=make_bundle(), profile_id="ci-runner"
            )
        assert excinfo.value.code == "RUN_SPEC_MISSING"


# ─────────────────────────────────────────────────────────────────────────────
# 5-11. Production receipt binding + verification
# ─────────────────────────────────────────────────────────────────────────────


class TestProductionReceipt:
    def test_full_flow_receipt_verifies(self, orchestrator, tmp_path) -> None:
        run, resolved, result = execute_resolved(orchestrator, RunStore())
        receipt = build_production_receipt(
            resolved=resolved,
            result=result,
            policy_enforced_event_hash=find_event(run, "policy_enforced").hash,
        )
        passed, result_obj = receipt.binding_failures() == [], verify_production_receipt(receipt)
        assert passed, result_obj.failures
        assert result_obj.verification_passed
        assert result_obj.bindings_complete
        assert result_obj.receipt_hash_ok

    def test_receipt_binds_run_spec_and_command(self, orchestrator) -> None:
        run, resolved, result = execute_resolved(orchestrator, RunStore(), command="echo bind-me")
        receipt = build_production_receipt(
            resolved=resolved,
            result=result,
            policy_enforced_event_hash=find_event(run, "policy_enforced").hash,
        )
        assert receipt.run_spec_id == run.id
        assert receipt.command == "echo bind-me"
        assert receipt.sandbox_id == result.sandbox_id

    def test_receipt_hash_deterministic(self, orchestrator) -> None:
        run, resolved, result = execute_resolved(orchestrator, RunStore())
        event_hash = find_event(run, "policy_enforced").hash
        # Same bindings (including an identical executed_at) → identical hash
        r1 = build_production_receipt(
            resolved=resolved,
            result=result,
            policy_enforced_event_hash=event_hash,
            executed_at="2026-11-09T00:00:00+00:00",
        )
        r2 = build_production_receipt(
            resolved=resolved,
            result=result,
            policy_enforced_event_hash=event_hash,
            executed_at="2026-11-09T00:00:00+00:00",
        )
        assert r1.receipt_hash == r2.receipt_hash
        # A different timestamp is a different binding → different hash
        r3 = build_production_receipt(
            resolved=resolved,
            result=result,
            policy_enforced_event_hash=event_hash,
            executed_at="2026-11-09T00:00:01+00:00",
        )
        assert r3.receipt_hash != r1.receipt_hash

    def test_expected_resolved_consistency_passes(self, orchestrator) -> None:
        run, resolved, result = execute_resolved(orchestrator, RunStore())
        receipt = build_production_receipt(
            resolved=resolved,
            result=result,
            policy_enforced_event_hash=find_event(run, "policy_enforced").hash,
        )
        verification = verify_production_receipt(receipt, expected_resolved=resolved)
        assert verification.verification_passed
        assert verification.resolved_consistency is True

    def test_policy_change_after_submission_detected(self, orchestrator) -> None:
        """The receipt was issued under bundle v1; the operator swapped the
        policy to v2 before execution was audited — the verifier must flag it."""
        run, resolved, result = execute_resolved(orchestrator, RunStore())
        receipt = build_production_receipt(
            resolved=resolved,
            result=result,
            policy_enforced_event_hash=find_event(run, "policy_enforced").hash,
        )
        new_bundle = make_bundle(policy_version="v2", artifact_limit=10)
        new_resolved = new_bundle.resolve("ci-runner", run.id)
        verification = verify_production_receipt(receipt, expected_resolved=new_resolved)
        assert not verification.verification_passed
        assert verification.resolved_consistency is False
        assert any("BINDING_MISMATCH_BUNDLE_DIGEST" in f for f in verification.failures)
        assert any("BINDING_MISMATCH_POLICY_DIGEST" in f for f in verification.failures)

    def test_profile_substitution_detected(self, orchestrator) -> None:
        """A different (authorised) profile is presented as the one that ran."""
        bundle = make_bundle(
            profiles=(
                make_profile("runner-a", image_ref=f"img@{DIGEST}"),
                make_profile("runner-b", image_ref=f"img@{DIGEST_B}"),
            )
        )
        run, resolved, result = execute_resolved(
            orchestrator, RunStore(), bundle=bundle, profile_id="runner-a"
        )
        receipt = build_production_receipt(
            resolved=resolved,
            result=result,
            policy_enforced_event_hash=find_event(run, "policy_enforced").hash,
        )
        substituted = bundle.resolve("runner-b", run.id)
        verification = verify_production_receipt(receipt, expected_resolved=substituted)
        assert not verification.verification_passed
        assert any("BINDING_MISMATCH_PROFILE_DIGEST" in f for f in verification.failures)
        assert any("BINDING_MISMATCH_IMAGE_DIGEST" in f for f in verification.failures)

    def test_event_chain_digest_consistency(self, orchestrator) -> None:
        run, resolved, result = execute_resolved(orchestrator, RunStore())
        receipt = build_production_receipt(
            resolved=resolved,
            result=result,
            policy_enforced_event_hash=find_event(run, "policy_enforced").hash,
        )
        verification = verify_production_receipt(receipt, run=run)
        assert verification.verification_passed
        assert verification.event_chain_consistency is True

    def test_event_digest_drift_detected(self, orchestrator) -> None:
        """Simulate the lifecycle event stream recording a DIFFERENT policy
        than the receipt claims (policy swap after queue submission)."""
        run, resolved, result = execute_resolved(orchestrator, RunStore())
        receipt = build_production_receipt(
            resolved=resolved,
            result=result,
            policy_enforced_event_hash=find_event(run, "policy_enforced").hash,
        )
        tampered_event = find_event(run, "policy_enforced")
        tampered_event.data["policy_digest"] = "f" * 64
        verification = verify_production_receipt(receipt, run=run)
        assert not verification.verification_passed
        assert verification.event_chain_consistency is False
        assert any("EVENT_DIGEST_MISMATCH_POLICY_DIGEST" in f for f in verification.failures)

    def test_event_hash_rebinding_detected(self, orchestrator) -> None:
        run, resolved, result = execute_resolved(orchestrator, RunStore())
        receipt = build_production_receipt(
            resolved=resolved,
            result=result,
            policy_enforced_event_hash=find_event(run, "policy_enforced").hash,
        )
        receipt = ProductionReceipt.from_dict(
            {**receipt.to_dict(), "policy_enforced_event_hash": "0" * 64}
        )
        verification = verify_production_receipt(receipt, run=run)
        assert not verification.verification_passed
        assert any("EVENT_HASH_MISMATCH" in f for f in verification.failures)

    @pytest.mark.parametrize(
        "field",
        [
            "run_spec_id",
            "sandbox_id",
            "command",
            "policy_digest",
            "bundle_digest",
            "profile_digest",
            "tool_version",
            "image_digest",
            "policy_enforced_event_hash",
        ],
    )
    def test_missing_binding_rejected_by_verifier(self, orchestrator, field: str) -> None:
        run, resolved, result = execute_resolved(orchestrator, RunStore())
        receipt = build_production_receipt(
            resolved=resolved,
            result=result,
            policy_enforced_event_hash=find_event(run, "policy_enforced").hash,
        )
        stripped = ProductionReceipt.from_dict({**receipt.to_dict(), field: ""})
        verification = verify_production_receipt(stripped)
        assert not verification.verification_passed
        assert f"RECEIPT_MISSING_{field.upper()}" in verification.failures

    def test_modified_binding_breaks_hash(self, orchestrator) -> None:
        run, resolved, result = execute_resolved(orchestrator, RunStore())
        receipt = build_production_receipt(
            resolved=resolved,
            result=result,
            policy_enforced_event_hash=find_event(run, "policy_enforced").hash,
        )
        modified = ProductionReceipt.from_dict({**receipt.to_dict(), "exit_code": 1})
        verification = verify_production_receipt(modified)
        assert not verification.verification_passed
        assert any("RECEIPT_HASH_MISMATCH" in f for f in verification.failures)

    def test_signed_receipt_verifies(self, orchestrator) -> None:
        run, resolved, result = execute_resolved(orchestrator, RunStore())
        receipt = build_production_receipt(
            resolved=resolved,
            result=result,
            policy_enforced_event_hash=find_event(run, "policy_enforced").hash,
        )
        signed = sign_receipt(receipt, SIGNING_KEY)
        assert signed.signature
        verification = verify_production_receipt(signed, signing_key=SIGNING_KEY)
        assert verification.verification_passed
        assert verification.signature_ok is True

    def test_modified_signed_receipt_fails(self, orchestrator) -> None:
        run, resolved, result = execute_resolved(orchestrator, RunStore())
        receipt = sign_receipt(
            build_production_receipt(
                resolved=resolved,
                result=result,
                policy_enforced_event_hash=find_event(run, "policy_enforced").hash,
            ),
            SIGNING_KEY,
        )
        tampered = ProductionReceipt.from_dict(
            {**receipt.to_dict(), "duration_ms": receipt.duration_ms + 999}
        )
        verification = verify_production_receipt(tampered, signing_key=SIGNING_KEY)
        assert not verification.verification_passed
        assert any("RECEIPT_HASH_MISMATCH" in f for f in verification.failures)
        assert verification.signature_ok is False
        assert any("RECEIPT_SIGNATURE_MISMATCH" in f for f in verification.failures)

    def test_wrong_signing_key_fails(self, orchestrator) -> None:
        run, resolved, result = execute_resolved(orchestrator, RunStore())
        receipt = sign_receipt(
            build_production_receipt(
                resolved=resolved,
                result=result,
                policy_enforced_event_hash=find_event(run, "policy_enforced").hash,
            ),
            SIGNING_KEY,
        )
        verification = verify_production_receipt(receipt, signing_key="attacker-key")
        assert not verification.verification_passed
        assert verification.signature_ok is False

    def test_unsigned_receipt_signature_flagged_when_key_present(self, orchestrator) -> None:
        run, resolved, result = execute_resolved(orchestrator, RunStore())
        receipt = build_production_receipt(
            resolved=resolved,
            result=result,
            policy_enforced_event_hash=find_event(run, "policy_enforced").hash,
        )
        verification = verify_production_receipt(receipt, signing_key=SIGNING_KEY)
        assert not verification.verification_passed
        assert "RECEIPT_SIGNATURE_MISSING" in verification.failures

    def test_builder_refuses_incomplete_resolution(self, orchestrator) -> None:
        from dataclasses import replace as dc_replace

        run, resolved, result = execute_resolved(orchestrator, RunStore())
        broken = dc_replace(resolved, policy_digest="")
        with pytest.raises(ValueError, match="RECEIPT_BUILD_BLOCKED"):
            build_production_receipt(
                resolved=broken,
                result=result,
                policy_enforced_event_hash=find_event(run, "policy_enforced").hash,
            )


# ─────────────────────────────────────────────────────────────────────────────
# 12. Egress-policy bypass attempts
# ─────────────────────────────────────────────────────────────────────────────


class TestEgressBypass:
    def test_profile_cannot_enable_network_bundle_denies(self) -> None:
        profile = make_profile(network_mode="allowlisted", allowed_hosts=("pypi.org",))
        failures = make_bundle(network_mode="none", profiles=(profile,)).validate()
        assert any(f.startswith("PROFILE_EGRESS_BYPASS") for f in failures)
        with pytest.raises(PolicyResolutionError) as excinfo:
            make_bundle(network_mode="none", profiles=(profile,)).resolve("ci-runner", "run_1")
        assert excinfo.value.code == "BUNDLE_INVALID"

    def test_profile_host_outside_bundle_allowlist_rejected(self) -> None:
        profile = make_profile(network_mode="allowlisted", allowed_hosts=("evil.example.com",))
        bundle = make_bundle(
            network_mode="allowlisted",
            allowed_hosts=("pypi.org", "npmjs.org"),
            profiles=(profile,),
        )
        failures = bundle.validate()
        assert any(f.startswith("PROFILE_EGRESS_HOSTS_OUTSIDE_BUNDLE") for f in failures)

    def test_profile_within_bundle_egress_allowed(self) -> None:
        profile = make_profile(network_mode="allowlisted", allowed_hosts=("pypi.org",))
        bundle = make_bundle(
            network_mode="allowlisted",
            allowed_hosts=("pypi.org", "npmjs.org"),
            profiles=(profile,),
        )
        resolved = bundle.resolve("ci-runner", "run_eg")
        assert resolved.effective_policy.network_mode == "allowlisted"
        assert resolved.effective_policy.allowed_hosts == ("pypi.org",)


# ─────────────────────────────────────────────────────────────────────────────
# 13. Full production path over HTTP
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture()
async def api(tmp_path):
    reset_orchestrator()
    import os

    os.environ["CORTEX_WORKFLO_ROOT"] = str(tmp_path / "wf-root")
    test_app = FastAPI()
    test_app.include_router(workflo_router, prefix="/api/v1")
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _bundle_payload() -> dict[str, Any]:
    return make_bundle().to_dict()


class TestAPIProductionPath:
    @pytest.mark.asyncio
    async def test_run_with_bundle_produces_bound_receipt(self, api, monkeypatch) -> None:
        monkeypatch.setenv("CORTEX_RECEIPT_SIGNING_KEY", SIGNING_KEY)
        resp = await api.post(
            "/api/v1/workflo/runs",
            json={
                "workspace_id": "ws_rcpt",
                "name": "bound-run",
                "intent": "verify production receipt",
                "command": "echo bound-ok",
                "policy_bundle": _bundle_payload(),
                "profile_id": "ci-runner",
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        receipt = body["receipt"]
        assert receipt["run_spec_id"] == body["id"]
        assert len(receipt["policy_digest"]) == 64
        assert len(receipt["bundle_digest"]) == 64
        assert len(receipt["profile_digest"]) == 64
        assert receipt["image_digest"] == DIGEST
        assert receipt["signature"]
        # lifecycle event with matching digests exists
        events = {e["type"]: e for e in body["events"]}
        assert "policy_enforced" in events
        ev = events["policy_enforced"]
        assert ev["data"]["policy_digest"] == receipt["policy_digest"]
        assert ev["data"]["image_digest"] == receipt["image_digest"]
        # server-side verification passed at creation
        assert body["receipt_verification"]["verification_passed"] is True

        # Independent verification endpoint
        ver = await api.get(f"/api/v1/workflo/runs/{body['id']}/receipt/verify")
        assert ver.status_code == 200
        vbody = ver.json()
        assert vbody["verification_passed"] is True
        assert vbody["event_chain_consistency"] is True
        assert vbody["signature_ok"] is True

    @pytest.mark.asyncio
    async def test_run_policy_blocked_no_receipt_denial_auditable(self, api) -> None:
        resp = await api.post(
            "/api/v1/workflo/runs",
            json={
                "workspace_id": "ws_rcpt",
                "name": "blocked-run",
                "command": "echo nope",
                "policy_bundle": _bundle_payload(),
                "profile_id": "ghost-profile",
            },
        )
        assert resp.status_code == 403
        detail = resp.json()["detail"]
        assert detail["code"] == "policy_violation"
        match = re.search(r"run_id=(run_[a-f0-9-]+)", detail["message"])
        assert match, detail
        run_id = match.group(1)

        # The denial is auditable; NO receipt exists.
        run_resp = await api.get(f"/api/v1/workflo/runs/{run_id}")
        run_body = run_resp.json()
        types = [e["type"] for e in run_body["events"]]
        assert "policy_denied" in types
        assert "policy_enforced" not in types
        assert run_body["receipt"] is None

        receipt_resp = await api.get(f"/api/v1/workflo/runs/{run_id}/receipt")
        assert receipt_resp.status_code == 200
        assert receipt_resp.json()["receipt"] is None
        assert receipt_resp.json()["reason"] == "policy_denied_no_receipt"

        verify_resp = await api.get(f"/api/v1/workflo/runs/{run_id}/receipt/verify")
        assert verify_resp.json()["verification_passed"] is False
        assert "RECEIPT_ABSENT" in verify_resp.json()["failures"]

    @pytest.mark.asyncio
    async def test_run_invalid_bundle_rejected_with_stable_code(self, api) -> None:
        payload = _bundle_payload()
        payload["authorised_profiles"][0]["image_ref"] = "workflo-worker:latest"
        resp = await api.post(
            "/api/v1/workflo/runs",
            json={
                "workspace_id": "ws_rcpt",
                "name": "floating",
                "command": "echo nope",
                "policy_bundle": payload,
                "profile_id": "ci-runner",
            },
        )
        assert resp.status_code == 403
        assert "PROFILE_IMAGE_NOT_PINNED" in resp.json()["detail"]["message"]

    @pytest.mark.asyncio
    async def test_sandbox_direct_path_resolution(self, api) -> None:
        resp = await api.post(
            "/api/v1/workflo/sandboxes",
            json={
                "workspace_id": "ws_rcpt",
                "name": "direct",
                "policy_bundle": _bundle_payload(),
                "profile_id": "ci-runner",
                "run_spec_id": "run_direct_1",
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["resolved"]["run_spec_id"] == "run_direct_1"
        assert body["resolved"]["image_digest"] == DIGEST

    @pytest.mark.asyncio
    async def test_sandbox_direct_path_unauthorised_profile_403(self, api) -> None:
        resp = await api.post(
            "/api/v1/workflo/sandboxes",
            json={
                "workspace_id": "ws_rcpt",
                "name": "direct-bad",
                "policy_bundle": _bundle_payload(),
                "profile_id": "not-authorised",
                "run_spec_id": "run_direct_2",
            },
        )
        assert resp.status_code == 403
        assert "PROFILE_NOT_AUTHORISED" in resp.json()["detail"]["message"]

    @pytest.mark.asyncio
    async def test_run_without_bundle_has_no_receipt(self, api) -> None:
        """Legacy unresolved runs state explicitly that no receipt exists."""
        resp = await api.post(
            "/api/v1/workflo/runs",
            json={"workspace_id": "ws_rcpt", "name": "legacy", "command": "echo legacy"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert "receipt" not in body or body.get("receipt") is None
        ver = await api.get(f"/api/v1/workflo/runs/{body['id']}/receipt/verify")
        assert ver.json()["verification_passed"] is False
        assert "RECEIPT_ABSENT" in ver.json()["failures"]


class TestSigningEnforcement:
    """Fail-closed signing: staging/pilot/prod must never execute without
    a configured receipt signing key — with or without a policy bundle."""

    @pytest.mark.asyncio
    async def test_signing_required_without_key_refuses_all_execution(
        self, api, monkeypatch
    ) -> None:
        monkeypatch.setenv("CORTEX_REQUIRE_SIGNED_RECEIPTS", "1")
        monkeypatch.delenv("CORTEX_RECEIPT_SIGNING_KEY", raising=False)
        # With a bundle
        resp = await api.post(
            "/api/v1/workflo/runs",
            json={
                "workspace_id": "ws_rcpt",
                "name": "unsigned-bundle",
                "command": "echo nope",
                "policy_bundle": _bundle_payload(),
                "profile_id": "ci-runner",
            },
        )
        assert resp.status_code == 503
        detail = resp.json()["detail"]
        assert detail["code"] == "service_unavailable"
        assert "RECEIPT_SIGNING_UNAVAILABLE" in detail["message"]
        # Without a bundle — the bypass attempt
        resp2 = await api.post(
            "/api/v1/workflo/runs",
            json={"workspace_id": "ws_rcpt", "name": "unsigned-legacy", "command": "echo x"},
        )
        assert resp2.status_code == 503
        assert "RECEIPT_SIGNING_UNAVAILABLE" in resp2.json()["detail"]["message"]

    @pytest.mark.asyncio
    async def test_signing_required_with_key_produces_signed_receipt(
        self, api, monkeypatch
    ) -> None:
        monkeypatch.setenv("CORTEX_REQUIRE_SIGNED_RECEIPTS", "1")
        monkeypatch.setenv("CORTEX_RECEIPT_SIGNING_KEY", SIGNING_KEY)
        resp = await api.post(
            "/api/v1/workflo/runs",
            json={
                "workspace_id": "ws_rcpt",
                "name": "signed-staging",
                "command": "echo signed-ok",
                "policy_bundle": _bundle_payload(),
                "profile_id": "ci-runner",
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["receipt"]["signature"]
        ver = await api.get(f"/api/v1/workflo/runs/{body['id']}/receipt/verify")
        assert ver.json()["verification_passed"] is True
        assert ver.json()["signature_ok"] is True

    @pytest.mark.asyncio
    async def test_verification_fails_when_key_lost_after_execution(self, api, monkeypatch) -> None:
        """A receipt created while the key was present must NOT pass
        verification if the environment lost its signing key but still
        requires signed receipts."""
        monkeypatch.setenv("CORTEX_REQUIRE_SIGNED_RECEIPTS", "1")
        monkeypatch.setenv("CORTEX_RECEIPT_SIGNING_KEY", SIGNING_KEY)
        created = await api.post(
            "/api/v1/workflo/runs",
            json={
                "workspace_id": "ws_rcpt",
                "name": "lost-key",
                "command": "echo signed",
                "policy_bundle": _bundle_payload(),
                "profile_id": "ci-runner",
            },
        )
        assert created.status_code == 201
        run_id = created.json()["id"]

        # The key is lost (rotation accident / secret store outage)…
        monkeypatch.delenv("CORTEX_RECEIPT_SIGNING_KEY", raising=False)
        # …but the environment still requires signed receipts.
        ver = await api.get(f"/api/v1/workflo/runs/{run_id}/receipt/verify")
        body = ver.json()
        assert body["verification_passed"] is False
        assert "RECEIPT_SIGNING_KEY_UNAVAILABLE" in body["failures"]

    @pytest.mark.asyncio
    async def test_dev_environment_still_permits_unsigned_runs(self, api, monkeypatch) -> None:
        """Explicit opt-out keeps dev permissive — no secret required locally."""
        monkeypatch.setenv("CORTEX_REQUIRE_SIGNED_RECEIPTS", "0")
        resp = await api.post(
            "/api/v1/workflo/runs",
            json={"workspace_id": "ws_rcpt", "name": "dev-ok", "command": "echo dev"},
        )
        assert resp.status_code == 201
