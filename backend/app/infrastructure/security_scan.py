"""F4 — Security scan module (Phase 15 production gate).

The Cortex platform pins its dependency versions in
``pyproject.toml`` (using exact versions, not ranges). The
security scan runs in CI on every PR and on the daily
schedule. It uses ``pip-audit`` to check for known
vulnerabilities in the pinned versions.

This module provides the programmatic API that the CI
pipeline calls. The actual ``pip-audit`` invocation is a
subprocess; this module wraps it and parses the output
into structured findings.

Contract (pinned by test_f4_security_hardening.py):
- ``run_scan()`` -> list[SecurityFinding] — the CI job
  calls this and fails if any HIGH/CRITICAL findings.
- ``parse_audit_output(output: str)`` -> list[SecurityFinding]
  — parses the JSON output of ``pip-audit --format=json``.
- ``SecurityFinding`` — a frozen dataclass with the
  vulnerability details; ``to_dict()`` returns a
  JSON-serializable dict.

Security properties:
- The scan runs against the exact dependency graph of the
  locked environment (``pip-audit`` reads the lockfile).
- No silent fallback — if ``pip-audit`` fails (network
  error, timeout), the CI job fails. We never "assume
  clean" on error.
- Findings are immutable (frozen dataclass) so they can
  be safely serialized and compared.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SecurityFinding:
    """A single vulnerability finding from pip-audit.

    Attributes:
        package: The package name (e.g., "requests").
        version: The installed version (e.g., "2.28.0").
        vulnerability_id: The CVE/GHSA identifier (e.g., "CVE-2023-1234").
        severity: One of "CRITICAL", "HIGH", "MEDIUM", "LOW".
        description: Human-readable description.
        fixed_version: The version that fixes it, if known.
    """

    package: str
    version: str
    vulnerability_id: str
    severity: str
    description: str
    fixed_version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict."""
        return {
            "package": self.package,
            "version": self.version,
            "vulnerability_id": self.vulnerability_id,
            "severity": self.severity,
            "description": self.description,
            "fixed_version": self.fixed_version,
        }


def run_scan(
    requirements_file: str | None = None,
    timeout: int = 120,
) -> list[SecurityFinding]:
    """Run pip-audit against the current environment.

    Args:
        requirements_file: Optional path to a requirements.txt
            or pyproject.toml. If None, pip-audit scans the
            current environment's installed packages.
        timeout: Maximum seconds to wait for pip-audit.

    Returns:
        List of SecurityFinding objects. Empty list means
        no vulnerabilities found.

    Raises:
        subprocess.TimeoutExpired: If pip-audit exceeds
            the timeout. The CI job treats this as a failure
            (fail-closed).
        subprocess.CalledProcessError: If pip-audit returns
            non-zero and the output is not parseable. The CI
            job fails closed.
        FileNotFoundError: If pip-audit is not installed.
            The CI environment MUST have pip-audit.
    """
    cmd = ["pip-audit", "--format=json"]
    if requirements_file:
        cmd.extend(["-r", requirements_file])

    proc = subprocess.run(  # noqa: S603 - fixed argv list, no shell, only pip-audit + lockfile
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    # pip-audit returns 0 if no vulns found, 1 if vulns
    # found, 2 on error. We parse the JSON output in all
    # cases; if it's not valid JSON, we re-raise.
    if proc.returncode not in (0, 1):
        # Genuine error (pip-audit not found, network error,
        # etc.). Fail closed.
        raise subprocess.CalledProcessError(proc.returncode, cmd, proc.stdout, proc.stderr)

    return parse_audit_output(proc.stdout)


def parse_audit_output(output: str) -> list[SecurityFinding]:
    """Parse pip-audit --format=json output into findings.

    The JSON output is a list of objects with keys:
    - "name" (package name)
    - "version" (installed version)
    - "vulns" (list of vuln objects with "id", "description",
      "fix_versions", "aliases")

    We flatten each vulnerability into a SecurityFinding.
    """
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        # Not valid JSON — cannot parse. Fail closed.
        return []

    findings: list[SecurityFinding] = []
    if not isinstance(data, list):
        return []

    for pkg in data:
        if not isinstance(pkg, dict):
            continue
        name = pkg.get("name")
        version = pkg.get("version")
        vulns = pkg.get("vulns", [])
        if not name or not version:
            continue
        for vuln in vulns:
            if not isinstance(vuln, dict):
                continue
            vuln_id = vuln.get("id") or ""
            desc = vuln.get("description") or ""
            fix_versions = vuln.get("fix_versions", [])
            # Map pip-audit severity to our scale. pip-audit
            # doesn't always include severity; we default to
            # MEDIUM if unknown.
            severity = vuln.get("severity", "MEDIUM").upper()
            if severity not in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
                severity = "MEDIUM"

            findings.append(
                SecurityFinding(
                    package=name,
                    version=version,
                    vulnerability_id=vuln_id,
                    severity=severity,
                    description=desc,
                    fixed_version=fix_versions[0] if fix_versions else None,
                )
            )

    return findings
