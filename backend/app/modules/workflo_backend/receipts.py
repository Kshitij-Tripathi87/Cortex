"""Workflo production receipts — signed, bound, independently verifiable.

A production receipt is the evidence that a sandbox execution ran under a
specific resolved policy context. It is built from the SAME
``ResolvedExecution`` the orchestrator consumed — never recomputed — so the
receipt, the lifecycle ``policy_enforced`` event, and the enforced
``SandboxPolicy`` cannot drift apart silently.

Receipt bindings (all independently verifiable):

    run_spec_id        — the run this execution belongs to
    sandbox_id         — the sandbox that executed the command
    command            — the exact command line executed
    policy_digest      — SHA-256 of the effective SandboxPolicy enforced
    bundle_digest      — SHA-256 of the validated ExecutionPolicyBundle
    profile_digest     — SHA-256 of the authorised RunnerProfile
    tool_version       — declared runner tool version
    image_digest       — pinned runner image digest (or process identity)
    exit_code / timed_out / duration_ms / artifact_count
    policy_enforced_event_hash — hash-chained lifecycle event carrying the
                         same digests (receipt ↔ event-stream binding)
    executed_at        — when execution happened

Integrity:
    receipt_hash = SHA-256(canonical JSON over all binding fields)
    signature    = HMAC-SHA256(receipt_hash, signing_key)

    The signing key comes from CORTEX_RECEIPT_SIGNING_KEY. Verification is
    fail-closed: missing bindings, a hash mismatch, a signature mismatch, a
    mismatch against the expected ResolvedExecution, or a mismatch against
    the lifecycle event stream all report concrete failure codes.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.modules.workflo_backend.execution_policy import ResolvedExecution
    from app.modules.workflo_backend.orchestrator import ExecutionResult
    from app.modules.workflo_backend.runs import Run

RECEIPT_VERSION = "wp1"
SIGNING_KEY_ENV = "CORTEX_RECEIPT_SIGNING_KEY"

_BINDING_FIELDS = (
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
)


def get_signing_key() -> str:
    """The receipt signing key (server-side secret; never exposed via API)."""
    return os.environ.get(SIGNING_KEY_ENV, "")


def signing_required() -> bool:
    """Whether production execution MUST produce signed receipts.

    Fail-closed policy:
      * Explicit flag wins: CORTEX_REQUIRE_SIGNED_RECEIPTS=1 forces signing.
      * Otherwise, enforced automatically for CORTEX_ENV values where
        evidence integrity is load-bearing: ``staging``, ``pilot``, ``prod``.
      * ``dev``/``test`` default to permissive so local development and
        unit tests do not need a secret.

    When signing is required and no key is configured, the control plane
    must refuse governed execution entirely — staging and production must
    never silently operate without a signing key.
    """
    flag = os.environ.get("CORTEX_REQUIRE_SIGNED_RECEIPTS", "").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        return True
    if flag in {"0", "false", "no", "off"}:
        return False
    from app.config import get_settings

    try:
        env = get_settings().env.strip().lower()
    except Exception:
        return False
    return env in {"staging", "pilot", "prod"}


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def dataclasses_fields(cls: type) -> list[str]:
    from dataclasses import fields

    return [f.name for f in fields(cls)]


def compute_receipt_hash(*, receipt_version: str, bindings: dict[str, Any]) -> str:
    """SHA-256 over the receipt version + every binding field."""
    canonical = {
        "receipt_version": receipt_version,
        **{k: bindings.get(k) for k in _BINDING_FIELDS},
    }
    return hashlib.sha256(_canonical(canonical).encode("utf-8")).hexdigest()


def compute_signature(receipt_hash: str, key: str) -> str:
    """HMAC-SHA256 over the receipt hash."""
    return hmac.new(key.encode("utf-8"), receipt_hash.encode("utf-8"), hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class ProductionReceipt:
    """A production-grade sandbox execution receipt."""

    receipt_version: str = RECEIPT_VERSION
    run_spec_id: str = ""
    sandbox_id: str = ""
    command: str = ""
    policy_digest: str = ""
    bundle_digest: str = ""
    profile_digest: str = ""
    tool_version: str = ""
    image_digest: str = ""
    exit_code: int | None = None
    timed_out: bool = False
    duration_ms: int = 0
    artifact_count: int = 0
    policy_enforced_event_hash: str = ""
    executed_at: str = field(default_factory=lambda: _utc_now_iso())
    receipt_hash: str = ""
    signature: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "receipt_version": self.receipt_version,
            "run_spec_id": self.run_spec_id,
            "sandbox_id": self.sandbox_id,
            "command": self.command,
            "policy_digest": self.policy_digest,
            "bundle_digest": self.bundle_digest,
            "profile_digest": self.profile_digest,
            "tool_version": self.tool_version,
            "image_digest": self.image_digest,
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "duration_ms": self.duration_ms,
            "artifact_count": self.artifact_count,
            "policy_enforced_event_hash": self.policy_enforced_event_hash,
            "executed_at": self.executed_at,
            "receipt_hash": self.receipt_hash,
            "signature": self.signature,
        }

    def bindings(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in _BINDING_FIELDS}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProductionReceipt:
        """Reconstruct a receipt from its serialized form (persistence/API)."""
        known = {f for f in dataclasses_fields(cls)}
        kwargs = {k: v for k, v in data.items() if k in known}
        return cls(**kwargs)

    def binding_failures(self) -> list[str]:
        """Missing or incomplete bindings (fail-closed)."""
        failures: list[str] = []
        for name in _BINDING_FIELDS:
            value = getattr(self, name)
            if value is None and name == "exit_code":
                continue  # exit_code may legitimately be None (timeout kill)
            if value == "" or value is None:
                failures.append(f"RECEIPT_MISSING_{name.upper()}")
        if self.receipt_version != RECEIPT_VERSION:
            failures.append(f"RECEIPT_VERSION_UNSUPPORTED: {self.receipt_version}")
        if self.receipt_hash and len(self.receipt_hash) != 64:
            failures.append("RECEIPT_HASH_MALFORMED")
        return failures

    def expected_hash(self) -> str:
        """Recompute the binding root from the receipt's own fields."""
        return compute_receipt_hash(receipt_version=self.receipt_version, bindings=self.bindings())


def build_production_receipt(
    *,
    resolved: ResolvedExecution,
    result: ExecutionResult,
    policy_enforced_event_hash: str,
    executed_at: str | None = None,
) -> ProductionReceipt:
    """Bind an execution result to its resolved execution context.

    ``resolved`` MUST be the same immutable context the orchestrator used —
    the builder consumes it verbatim and never recomputes digests, so the
    receipt cannot drift from the enforced policy.
    """
    failures = resolved.binding_failures()
    if failures:
        raise ValueError(
            "RECEIPT_BUILD_BLOCKED: resolved execution context incomplete: " + "; ".join(failures)
        )

    receipt = ProductionReceipt(
        run_spec_id=resolved.run_spec_id,
        sandbox_id=result.sandbox_id,
        command=result.command,
        policy_digest=resolved.policy_digest,
        bundle_digest=resolved.bundle_digest,
        profile_digest=resolved.profile_digest,
        tool_version=resolved.tool_version,
        image_digest=resolved.image_digest,
        exit_code=result.exit_code,
        timed_out=result.timed_out,
        duration_ms=result.duration_ms,
        artifact_count=len(result.artifacts),
        policy_enforced_event_hash=policy_enforced_event_hash,
        executed_at=executed_at or _utc_now_iso(),
    )
    return replace(receipt, receipt_hash=receipt.expected_hash())


def sign_receipt(receipt: ProductionReceipt, key: str) -> ProductionReceipt:
    """HMAC-sign the receipt's binding hash."""
    if not key:
        raise ValueError("RECEIPT_SIGN_BLOCKED: signing key is empty")
    return replace(receipt, signature=compute_signature(receipt.receipt_hash, key))


@dataclass(frozen=True)
class ReceiptVerificationResult:
    """Independent verification outcome for a production receipt."""

    receipt: ProductionReceipt
    verification_passed: bool
    failures: list[str]
    bindings_complete: bool
    receipt_hash_ok: bool
    signature_ok: bool | None  # None = no key supplied (unsigned check skipped)
    resolved_consistency: bool | None  # None = no expected context supplied
    event_chain_consistency: bool | None  # None = no event stream supplied

    def to_dict(self) -> dict[str, Any]:
        return {
            "verification_passed": self.verification_passed,
            "failures": list(self.failures),
            "bindings_complete": self.bindings_complete,
            "receipt_hash_ok": self.receipt_hash_ok,
            "signature_ok": self.signature_ok,
            "resolved_consistency": self.resolved_consistency,
            "event_chain_consistency": self.event_chain_consistency,
            "receipt": self.receipt.to_dict(),
        }


def verify_production_receipt(
    receipt: ProductionReceipt,
    *,
    expected_run_spec_id: str | None = None,
    expected_resolved: ResolvedExecution | None = None,
    run: Run | None = None,
    signing_key: str | None = None,
    require_signature: bool = False,
) -> ReceiptVerificationResult:
    """Independently verify a production receipt. Fail-closed.

    Checks, in order:
      1. Bindings complete (every binding field present).
      2. Receipt hash: recomputed binding root must equal the stored hash —
         detects ANY modification of a binding field.
      3. Signature (when a key is available/required): HMAC over the hash.
      4. Resolved-context consistency (when ``expected_resolved`` given):
         policy/bundle/profile digests, tool version and image identity must
         match the resolution the caller believes governed the run — detects
         policy changes after submission and profile substitution.
      5. Event-chain consistency (when ``run`` given): the hash-chained
         ``policy_enforced`` lifecycle event must exist and carry the same
         digests as the receipt.
    """
    from app.modules.workflo_backend.runs import find_event

    failures: list[str] = []

    # 1. Bindings
    binding_failures = receipt.binding_failures()
    bindings_complete = not binding_failures
    failures.extend(binding_failures)

    # 2. Hash integrity
    receipt_hash_ok = False
    if bindings_complete:
        receipt_hash_ok = receipt.expected_hash() == receipt.receipt_hash
        if not receipt_hash_ok:
            failures.append("RECEIPT_HASH_MISMATCH: receipt was modified after signing")
    elif not receipt.receipt_hash:
        failures.append("RECEIPT_HASH_MISSING")

    # 3. Signature — HMAC over the RECOMPUTED binding hash, so any binding
    #    tamper breaks both the hash and the signature.
    key = signing_key if signing_key is not None else get_signing_key()
    signature_ok: bool | None = None
    if key:
        if not receipt.signature:
            signature_ok = False
            failures.append("RECEIPT_SIGNATURE_MISSING")
        else:
            signature_ok = hmac.compare_digest(
                receipt.signature,
                compute_signature(receipt.expected_hash(), key),
            )
            if not signature_ok:
                failures.append("RECEIPT_SIGNATURE_MISMATCH")
    elif require_signature:
        failures.append("RECEIPT_SIGNING_KEY_UNAVAILABLE")

    # 4. Resolved-context consistency
    resolved_consistency: bool | None = None
    if expected_resolved is not None:
        resolved_failures: list[str] = []
        if receipt.run_spec_id != expected_resolved.run_spec_id:
            resolved_failures.append(
                f"RUN_SPEC_MISMATCH: receipt={receipt.run_spec_id} "
                f"expected={expected_resolved.run_spec_id}"
            )
        if expected_run_spec_id and receipt.run_spec_id != expected_run_spec_id:
            resolved_failures.append(
                f"RUN_SPEC_MISMATCH: receipt={receipt.run_spec_id} expected={expected_run_spec_id}"
            )
        for name in (
            "policy_digest",
            "bundle_digest",
            "profile_digest",
            "tool_version",
            "image_digest",
        ):
            expected_value = getattr(expected_resolved, name)
            receipt_value = getattr(receipt, name)
            if receipt_value != expected_value:
                resolved_failures.append(
                    f"BINDING_MISMATCH_{name.upper()}: receipt={receipt_value} "
                    f"expected={expected_value}"
                )
        resolved_consistency = not resolved_failures
        failures.extend(resolved_failures)
    elif expected_run_spec_id and receipt.run_spec_id != expected_run_spec_id:
        failures.append(
            f"RUN_SPEC_MISMATCH: receipt={receipt.run_spec_id} expected={expected_run_spec_id}"
        )

    # 5. Event-chain consistency
    event_chain_consistency: bool | None = None
    if run is not None:
        event = find_event(run, "policy_enforced")
        if event is None:
            event_chain_consistency = False
            failures.append("EVENT_POLICY_ENFORCED_MISSING")
        else:
            chain_failures: list[str] = []
            if receipt.policy_enforced_event_hash != event.hash:
                chain_failures.append(
                    "EVENT_HASH_MISMATCH: receipt does not bind the recorded policy_enforced event"
                )
            data = event.data or {}
            for name in (
                "policy_digest",
                "bundle_digest",
                "profile_digest",
                "tool_version",
                "image_digest",
            ):
                receipt_value = getattr(receipt, name)
                if receipt_value and data.get(name) != receipt_value:
                    chain_failures.append(
                        f"EVENT_DIGEST_MISMATCH_{name.upper()}: "
                        f"receipt={receipt_value} event={data.get(name)}"
                    )
            event_chain_consistency = not chain_failures
            failures.extend(chain_failures)

    passed = len(failures) == 0
    return ReceiptVerificationResult(
        receipt=receipt,
        verification_passed=passed,
        failures=failures,
        bindings_complete=bindings_complete,
        receipt_hash_ok=receipt_hash_ok,
        signature_ok=signature_ok,
        resolved_consistency=resolved_consistency,
        event_chain_consistency=event_chain_consistency,
    )


def _utc_now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()
