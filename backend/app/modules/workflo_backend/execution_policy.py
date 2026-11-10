"""Workflo execution policy bundles — validated policy + authorised runner profiles.

Closes the gap between policy enforcement and production evidence:

    ExecutionPolicyBundle (validated, cross-document)
        │
        ▼  bundle.resolve(profile_id, run_spec_id)
    ResolvedExecution (immutable — policy/bundle/profile/image digests)
        │
        ▼  consumed by BOTH the direct executor path (SandboxOrchestrator)
        │  and the production supervisor path (run pipeline)
        ▼
    ProductionReceipt (signed, independently verifiable)

Fail-closed guarantees:
  * A bundle that fails cross-document validation cannot resolve anything.
  * Only profiles explicitly authorised by the bundle can be resolved.
  * Profiles must stay within every bundle ceiling (cpu, memory, processes,
    timeout, artifacts, output) — a profile can only narrow, never widen.
  * Egress can only be narrowed: a profile may not enable network access
    the bundle denies, and its allowed_hosts must be a subset of the
    bundle's allowlist.
  * The command allowlist is always a subset of the bundle's.
  * Image identity must be pinned: container refs require an explicit
    registry digest (``repo@sha256:<64 hex>``); floating tags are rejected.
    In-process runners declare a ``process://`` identity that is resolved
    to a digest computed from actual runtime facts.

Every digest is SHA-256 over canonical JSON (sorted keys, compact
separators) — deterministic, order-insensitive, tamper-evident.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import sys
from dataclasses import dataclass, field
from typing import Any

from app.modules.workflo_backend.policy import SandboxPolicy

_IMAGE_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")

# Network modes ordered from most to least restrictive.
_NETWORK_MODES = ("none", "allowlisted")


class PolicyResolutionError(Exception):
    """Raised when a policy bundle or profile cannot be resolved. Fail-closed."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def canonical_json(payload: Any) -> str:
    """Deterministic canonical JSON (sorted keys, compact separators)."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def compute_digest(payload: Any) -> str:
    """SHA-256 hex digest over canonical JSON of ``payload``."""
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RunnerProfile:
    """An authorised runner configuration declared inside a policy bundle.

    ``image_ref`` is the declared runner identity:
      * containerised runners: ``<name>@sha256:<64 hex>`` (registry digest —
        floating tags like ``name:latest`` are rejected at resolution time)
      * in-process runners: ``process://<name>`` — resolved to a digest
        computed from the actual runtime (platform + interpreter facts)
    """

    profile_id: str
    image_ref: str
    tool_version: str
    cpu_limit: int
    memory_limit_mb: int
    execution_timeout_s: int
    process_limit: int
    network_mode: str = "none"
    allowed_hosts: tuple[str, ...] = ()
    command_allowlist: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "image_ref": self.image_ref,
            "tool_version": self.tool_version,
            "cpu_limit": self.cpu_limit,
            "memory_limit_mb": self.memory_limit_mb,
            "execution_timeout_s": self.execution_timeout_s,
            "process_limit": self.process_limit,
            "network_mode": self.network_mode,
            "allowed_hosts": list(self.allowed_hosts),
            "command_allowlist": list(self.command_allowlist),
        }

    def digest(self) -> str:
        return compute_digest(self.to_dict())


@dataclass(frozen=True)
class ExecutionPolicyBundle:
    """Validated policy bundle: ceilings + egress policy + authorised profiles.

    The bundle is the single authority for what a sandbox run may do.
    Runner profiles are authorised subsets of the bundle. Cross-document
    validation (``validate``) must pass before anything can be resolved.
    """

    bundle_id: str
    policy_version: str
    # Resource ceilings
    cpu_limit: int = 2
    memory_limit_mb: int = 1024
    process_limit: int = 64
    execution_timeout_s: int = 120
    artifact_limit: int = 50
    artifact_max_bytes: int = 10 * 1024 * 1024
    output_max_bytes: int = 512 * 1024
    # Egress ceiling
    network_mode: str = "none"
    allowed_hosts: tuple[str, ...] = ()
    # Filesystem + commands
    filesystem_scope: str = "sandbox"
    command_allowlist: tuple[str, ...] = ()
    # Authorised runner profiles
    authorised_profiles: tuple[RunnerProfile, ...] = ()

    # ── Cross-document validation ────────────────────────────────────────

    def validate(self) -> list[str]:
        """Return stable-code failures for every cross-document violation."""
        failures: list[str] = []

        if not self.bundle_id:
            failures.append("BUNDLE_ID_MISSING")
        if not self.policy_version:
            failures.append("BUNDLE_POLICY_VERSION_MISSING")

        # Bundle bounds reuse the sandbox policy bounds (same ceilings).
        try:
            self._as_policy().validate_bounds()
        except Exception as exc:  # PolicyViolation from bounds check
            failures.append(f"BUNDLE_BOUNDS_INVALID: {exc}")

        if self.network_mode not in _NETWORK_MODES:
            failures.append(f"BUNDLE_NETWORK_MODE_INVALID: {self.network_mode}")
        if self.network_mode == "allowlisted" and not self.allowed_hosts:
            failures.append("BUNDLE_EGRESS_HOSTS_MISSING")

        if not self.authorised_profiles:
            failures.append("BUNDLE_PROFILES_EMPTY")

        seen_ids: set[str] = set()
        for profile in self.authorised_profiles:
            pid = profile.profile_id
            if not pid:
                failures.append("PROFILE_ID_MISSING")
                continue
            if pid in seen_ids:
                failures.append(f"PROFILE_ID_DUPLICATE: {pid}")
                continue
            seen_ids.add(pid)
            failures.extend(self._profile_violations(profile))

        return failures

    def _profile_violations(self, profile: RunnerProfile) -> list[str]:
        """All ways ``profile`` escapes the bundle's ceilings/policy."""
        pid = profile.profile_id
        failures: list[str] = []

        if not profile.image_ref:
            failures.append(f"PROFILE_IMAGE_MISSING: {pid}")
        elif profile.image_ref.startswith("process://"):
            pass  # in-process identity — resolved to a runtime digest
        elif "@" in profile.image_ref:
            _, _, digest = profile.image_ref.rpartition("@")
            if not _IMAGE_DIGEST_RE.match(digest):
                failures.append(f"PROFILE_IMAGE_NOT_PINNED: {pid} ({profile.image_ref})")
        else:
            # A bare name or name:tag is a floating reference.
            failures.append(f"PROFILE_IMAGE_NOT_PINNED: {pid} ({profile.image_ref})")

        if not profile.tool_version:
            failures.append(f"PROFILE_TOOL_VERSION_MISSING: {pid}")

        if profile.cpu_limit > self.cpu_limit:
            failures.append(f"PROFILE_EXCEEDS_CEILING: {pid} cpu_limit")
        if profile.memory_limit_mb > self.memory_limit_mb:
            failures.append(f"PROFILE_EXCEEDS_CEILING: {pid} memory_limit_mb")
        if profile.process_limit > self.process_limit:
            failures.append(f"PROFILE_EXCEEDS_CEILING: {pid} process_limit")
        if profile.execution_timeout_s > self.execution_timeout_s:
            failures.append(f"PROFILE_EXCEEDS_CEILING: {pid} execution_timeout_s")

        if profile.network_mode not in _NETWORK_MODES:
            failures.append(f"PROFILE_NETWORK_MODE_INVALID: {pid} ({profile.network_mode})")
        elif profile.network_mode == "allowlisted":
            if self.network_mode != "allowlisted":
                # Egress bypass attempt: bundle says none, profile wants network.
                failures.append(
                    f"PROFILE_EGRESS_BYPASS: {pid} requests "
                    f"'{profile.network_mode}' but bundle allows '{self.network_mode}'"
                )
            else:
                bundle_hosts = set(self.allowed_hosts)
                outside = [h for h in profile.allowed_hosts if h not in bundle_hosts]
                if outside:
                    failures.append(f"PROFILE_EGRESS_HOSTS_OUTSIDE_BUNDLE: {pid} {sorted(outside)}")
                if not profile.allowed_hosts:
                    failures.append(f"PROFILE_EGRESS_HOSTS_MISSING: {pid}")

        bundle_allow = set(self.command_allowlist)
        outside = [c for c in profile.command_allowlist if c not in bundle_allow]
        if outside:
            failures.append(f"PROFILE_COMMANDS_OUTSIDE_BUNDLE: {pid} {sorted(outside)}")

        return failures

    def require_valid(self) -> ExecutionPolicyBundle:
        """Raise PolicyResolutionError when the bundle fails validation."""
        failures = self.validate()
        if failures:
            raise PolicyResolutionError(
                "BUNDLE_INVALID",
                "; ".join(failures),
            )
        return self

    def _as_policy(self) -> SandboxPolicy:
        """Bundle ceilings expressed as a SandboxPolicy for bounds validation."""
        return SandboxPolicy(
            cpu_limit=self.cpu_limit,
            memory_limit_mb=self.memory_limit_mb,
            process_limit=self.process_limit,
            execution_timeout_s=self.execution_timeout_s,
            filesystem_scope=self.filesystem_scope,
            network_mode=self.network_mode,
            allowed_hosts=self.allowed_hosts,
            artifact_limit=self.artifact_limit,
            artifact_max_bytes=self.artifact_max_bytes,
            output_max_bytes=self.output_max_bytes,
            command_allowlist=self.command_allowlist,
        )

    # ── Digests ───────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "policy_version": self.policy_version,
            "cpu_limit": self.cpu_limit,
            "memory_limit_mb": self.memory_limit_mb,
            "process_limit": self.process_limit,
            "execution_timeout_s": self.execution_timeout_s,
            "artifact_limit": self.artifact_limit,
            "artifact_max_bytes": self.artifact_max_bytes,
            "output_max_bytes": self.output_max_bytes,
            "network_mode": self.network_mode,
            "allowed_hosts": list(self.allowed_hosts),
            "filesystem_scope": self.filesystem_scope,
            "command_allowlist": list(self.command_allowlist),
            "authorised_profiles": [p.to_dict() for p in self.authorised_profiles],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ExecutionPolicyBundle:
        """Reconstruct a bundle from serialized form (API/CLI payloads).

        Unknown fields are ignored — the validated, canonical digests are
        computed from the reconstructed bundle only.
        """
        if not data:
            raise PolicyResolutionError("BUNDLE_MISSING", "policy bundle is required")
        profiles = tuple(
            RunnerProfile(
                profile_id=str(p.get("profile_id", "")),
                image_ref=str(p.get("image_ref", "")),
                tool_version=str(p.get("tool_version", "")),
                cpu_limit=int(p.get("cpu_limit", 0)),
                memory_limit_mb=int(p.get("memory_limit_mb", 0)),
                execution_timeout_s=int(p.get("execution_timeout_s", 0)),
                process_limit=int(p.get("process_limit", 0)),
                network_mode=str(p.get("network_mode", "none")),
                allowed_hosts=tuple(p.get("allowed_hosts", ()) or ()),
                command_allowlist=tuple(p.get("command_allowlist", ()) or ()),
            )
            for p in data.get("authorised_profiles", ()) or ()
        )
        return cls(
            bundle_id=str(data.get("bundle_id", "")),
            policy_version=str(data.get("policy_version", "")),
            cpu_limit=int(data.get("cpu_limit", 2)),
            memory_limit_mb=int(data.get("memory_limit_mb", 1024)),
            process_limit=int(data.get("process_limit", 64)),
            execution_timeout_s=int(data.get("execution_timeout_s", 120)),
            artifact_limit=int(data.get("artifact_limit", 50)),
            artifact_max_bytes=int(data.get("artifact_max_bytes", 10 * 1024 * 1024)),
            output_max_bytes=int(data.get("output_max_bytes", 512 * 1024)),
            network_mode=str(data.get("network_mode", "none")),
            allowed_hosts=tuple(data.get("allowed_hosts", ()) or ()),
            filesystem_scope=str(data.get("filesystem_scope", "sandbox")),
            command_allowlist=tuple(data.get("command_allowlist", ()) or ()),
            authorised_profiles=profiles,
        )

    def digest(self) -> str:
        return compute_digest(self.to_dict())

    # ── Resolution ────────────────────────────────────────────────────────

    def resolve(self, profile_id: str, run_spec_id: str) -> ResolvedExecution:
        """Resolve an authorised profile into an immutable execution context.

        Fail-closed: any validation failure, unknown profile, ceiling breach,
        egress bypass, or unpinned image raises PolicyResolutionError.
        """
        self.require_valid()

        profile = next(
            (p for p in self.authorised_profiles if p.profile_id == profile_id),
            None,
        )
        if profile is None:
            raise PolicyResolutionError(
                "PROFILE_NOT_AUTHORISED",
                f"profile '{profile_id}' is not authorised by bundle '{self.bundle_id}'",
            )

        # Runtime image identity. For in-process runners the identity is the
        # actual runtime (platform + interpreter) — an honest statement of
        # what executed, not a container guarantee. Container refs must have
        # been digest-pinned (validated above).
        if profile.image_ref.startswith("process://"):
            image_digest = process_identity_digest()
        else:
            image_digest = profile.image_ref.rpartition("@")[2]
            # Fail-closed runtime identity check: when the deployment tells
            # us which image digest is actually running (e.g. injected by
            # CI/CD as CORTEX_RUNNER_IMAGE_DIGEST), it MUST match the
            # profile's declared digest.
            runtime_digest = os.environ.get("CORTEX_RUNNER_IMAGE_DIGEST", "")
            if runtime_digest and runtime_digest != image_digest:
                raise PolicyResolutionError(
                    "IMAGE_IDENTITY_MISMATCH",
                    f"runtime image digest {runtime_digest} does not match "
                    f"declared {image_digest} for profile '{profile.profile_id}'",
                )

        effective_policy = self.effective_policy(profile)

        return ResolvedExecution(
            run_spec_id=run_spec_id,
            profile_id=profile.profile_id,
            bundle_id=self.bundle_id,
            policy_version=self.policy_version,
            policy_digest=effective_policy_digest(effective_policy),
            bundle_digest=self.digest(),
            profile_digest=profile.digest(),
            tool_version=profile.tool_version,
            image_ref=profile.image_ref,
            image_digest=image_digest,
            effective_policy=effective_policy,
        )

    def effective_policy(self, profile: RunnerProfile) -> SandboxPolicy:
        """The SandboxPolicy the runner will actually enforce for a profile.

        The profile narrows the bundle; the result is what the orchestrator
        enforces and what ``policy_digest`` commits to.
        """
        return SandboxPolicy(
            cpu_limit=profile.cpu_limit,
            memory_limit_mb=profile.memory_limit_mb,
            process_limit=profile.process_limit,
            execution_timeout_s=profile.execution_timeout_s,
            filesystem_scope=self.filesystem_scope,
            network_mode=profile.network_mode,
            allowed_hosts=profile.allowed_hosts,
            artifact_limit=self.artifact_limit,
            artifact_max_bytes=self.artifact_max_bytes,
            output_max_bytes=self.output_max_bytes,
            command_allowlist=(profile.command_allowlist or self.command_allowlist),
        )


def effective_policy_digest(policy: SandboxPolicy) -> str:
    """SHA-256 over the canonical effective SandboxPolicy."""
    return compute_digest(policy.to_dict())


def process_identity_digest() -> str:
    """Digest of the actual in-process runtime identity.

    This is NOT a container image guarantee — it binds receipts to the real
    interpreter/platform that executed the command. Docker-pinned runners
    use ``name@sha256:...`` image refs instead.
    """
    identity = {
        "scheme": "process",
        "platform": platform.platform(),
        "python": sys.implementation.name,
        "python_version": sys.version.split()[0],
        "executable_name": sys.executable.replace("\\", "/").split("/")[-1],
    }
    return "process-" + compute_digest(identity)


@dataclass(frozen=True)
class ResolvedExecution:
    """Immutable resolved execution context — the single provenance source.

    Produced ONCE by ``ExecutionPolicyBundle.resolve`` and consumed by BOTH
    the direct executor path (SandboxOrchestrator) and the production
    supervisor path (run pipeline → receipt). Every digest below is bound
    into the production receipt; the lifecycle ``policy_enforced`` event
    carries the same digests so an auditor can cross-check them.
    """

    run_spec_id: str
    profile_id: str
    bundle_id: str
    policy_version: str
    policy_digest: str
    bundle_digest: str
    profile_digest: str
    tool_version: str
    image_ref: str
    image_digest: str
    effective_policy: SandboxPolicy
    resolved_at: str = field(default_factory=lambda: _utc_now_iso())

    def to_dict(self, *, include_policy: bool = False) -> dict[str, Any]:
        d: dict[str, Any] = {
            "run_spec_id": self.run_spec_id,
            "profile_id": self.profile_id,
            "bundle_id": self.bundle_id,
            "policy_version": self.policy_version,
            "policy_digest": self.policy_digest,
            "bundle_digest": self.bundle_digest,
            "profile_digest": self.profile_digest,
            "tool_version": self.tool_version,
            "image_ref": self.image_ref,
            "image_digest": self.image_digest,
            "resolved_at": self.resolved_at,
        }
        if include_policy:
            d["effective_policy"] = self.effective_policy.to_dict()
        return d

    def binding_failures(self, *, runtime_image_digest: str | None = None) -> list[str]:
        """Fail-closed binding checks on the resolved context itself."""
        failures: list[str] = []
        if not self.run_spec_id:
            failures.append("RESOLUTION_RUN_SPEC_MISSING")
        for name in (
            "policy_digest",
            "bundle_digest",
            "profile_digest",
            "tool_version",
            "image_digest",
        ):
            if not getattr(self, name):
                failures.append(f"RESOLUTION_{name.upper()}_MISSING")
        if not _HEX64_RE.match(self.policy_digest):
            failures.append("RESOLUTION_POLICY_DIGEST_MALFORMED")
        if not _HEX64_RE.match(self.bundle_digest):
            failures.append("RESOLUTION_BUNDLE_DIGEST_MALFORMED")
        if not _HEX64_RE.match(self.profile_digest):
            failures.append("RESOLUTION_PROFILE_DIGEST_MALFORMED")
        if runtime_image_digest is not None and runtime_image_digest != self.image_digest:
            failures.append(
                f"IMAGE_IDENTITY_MISMATCH: runtime={runtime_image_digest} "
                f"declared={self.image_digest}"
            )
        return failures


def _utc_now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()
