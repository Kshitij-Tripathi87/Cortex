"""Workflo agent Ã¢â‚¬â€ deterministic planner and diagnostician.

The planner converts a natural-language intent into an auditable, ordered plan
of tool invocations. The diagnostician reasons over execution observations to
produce findings. Both are pure functions over their inputs: no hidden state,
no silent command execution, every step auditable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PlanStep:
    index: int
    action: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"index": self.index, "action": self.action, "detail": self.detail}


@dataclass
class AgentPlan:
    intent: str
    steps: list[PlanStep] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "steps": [s.to_dict() for s in self.steps],
            "step_count": len(self.steps),
        }


@dataclass
class Finding:
    severity: str
    title: str
    evidence: str
    suggestion: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "title": self.title,
            "evidence": self.evidence,
            "suggestion": self.suggestion,
        }


_TEST_FRAMEWORKS = (
    ("package.json", "node"),
    ("pytest.ini", "pytest"),
    ("pyproject.toml", "pytest"),
    ("go.mod", "go"),
    ("Cargo.toml", "cargo"),
)


def build_plan(intent: str, discovered: dict[str, Any] | None = None) -> AgentPlan:
    """Map an intent to an ordered, auditable execution plan."""
    text = (intent or "").lower()
    steps: list[PlanStep] = []

    def add(action: str, detail: str) -> None:
        steps.append(PlanStep(index=len(steps), action=action, detail=detail))

    add("inspect_project", "read manifests and source layout inside the sandbox")
    frameworks = (discovered or {}).get("frameworks", [])
    if frameworks:
        add(
            "discover_tests",
            "test surfaces found: " + ", ".join(frameworks),
        )
    else:
        add("discover_tests", "scan for test suites, flows, and API contracts")

    if any(k in text for k in ("regression", "all", "full", "suite")):
        add("run_suite", "execute the full regression suite in the sandbox")
    if "checkout" in text:
        add("run_target", "run checkout-related tests only")
    if any(k in text for k in ("why", "failing", "failure", "broken", "diagnose", "find")):
        add("inspect_failure", "capture stdout/stderr and exit codes of failing targets")
        add("reproduce", "re-run the failing target once to confirm determinism")
    if any(k in text for k in ("api", "contract", "schema")):
        add("check_contracts", "validate API response schemas against expectations")
    add("collect_artifacts", "persist logs, reports, and dumps as artifacts")
    add("report", "emit structured run report with findings")

    return AgentPlan(intent=intent or "", steps=steps)


def discover_surfaces(file_index: list[str]) -> dict[str, Any]:
    """Inspect a file listing to identify project type and test surfaces.

    `file_index` is a flat list of relative paths from the sandbox workspace.
    """
    names = set(file_index)
    frameworks: list[str] = []
    for marker, framework in _TEST_FRAMEWORKS:
        if marker in names and framework not in frameworks:
            frameworks.append(framework)

    test_files = [
        f
        for f in file_index
        if re.search(r"(^|/)(test_|.*\.test\.|.*\.spec\.)|(_test\.go$)|tests/", f)
    ]
    suites = len(set(_suite_name(f) for f in test_files))
    return {
        "frameworks": frameworks,
        "test_files": test_files[:200],
        "suite_count": suites,
        "case_estimate": max(suites * 3, len(test_files)),
    }


def _suite_name(path: str) -> str:
    parts = path.replace("\\", "/").split("/")
    for part in parts:
        if part.startswith("test_") or part.endswith(
            (".test.ts", ".test.js", ".spec.ts", ".spec.js")
        ):
            return part.rsplit(".", 1)[0]
    return parts[-1]


def diagnose(result: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Produce findings from an ExecutionResult dict. Deterministic rules."""
    findings: list[Finding] = []
    exit_code = result.get("exit_code")
    stderr = result.get("stderr") or ""
    stdout = result.get("stdout") or ""
    combined = stdout + "\n" + stderr
    timed_out = result.get("timed_out")

    if timed_out:
        findings.append(
            Finding(
                severity="high",
                title="execution timed out",
                evidence=f"command '{result.get('command')}' exceeded the policy timeout",
                suggestion="raise execution_timeout_s in the sandbox policy or fix the hang",
            )
        )
    elif exit_code not in (0, None):
        findings.append(
            Finding(
                severity="high",
                title=f"command failed with exit code {exit_code}",
                evidence=_first_failure_lines(combined),
                suggestion=_suggest_from_output(combined),
            )
        )
    if "ECONNREFUSED" in combined or "connection refused" in combined.lower():
        findings.append(
            Finding(
                severity="medium",
                title="network dependency unreachable",
                evidence=_grep_line(combined, ("ECONNREFUSED", "connection refused")),
                suggestion="sandbox network_mode is 'none'; stub external services",
            )
        )
    if re.search(r"\b\d+ (failed|failing)\b", combined, re.IGNORECASE):
        m = re.search(r"(\d+) (?:tests? )?failed", combined, re.IGNORECASE)
        count = m.group(1) if m else "?"
        findings.append(
            Finding(
                severity="critical",
                title=f"{count} test case(s) failed",
                evidence=_first_failure_lines(combined),
                suggestion="see failing target output; reproduce individually before fixing",
            )
        )
    if not findings and exit_code == 0:
        findings.append(
            Finding(
                severity="info",
                title="execution succeeded",
                evidence=f"'{result.get('command')}' exited 0 in {result.get('duration_ms')}ms",
                suggestion="no action required",
            )
        )
    return {
        "status": "healthy" if exit_code == 0 and not timed_out else "degraded",
        "findings": [f.to_dict() for f in findings],
    }


_FAIL_HINTS = {
    "assertionerror": "assertion mismatch Ã¢â‚¬â€ compare expected vs actual payload",
    "expect(": "expectation failed Ã¢â‚¬â€ inspect the diff above it",
    "modulenotfounderror": "missing dependency Ã¢â‚¬â€ install inside the sandbox image",
    "cannot find module": "missing dependency Ã¢â‚¬â€ install inside the sandbox image",
    "syntaxerror": "syntax error Ã¢â‚¬â€ check the reported file and line",
    "typeerror": "type error Ã¢â‚¬â€ inspect null/undefined access at reported location",
}


def _suggest_from_output(output: str) -> str:
    lowered = output.lower()
    for hint, suggestion in _FAIL_HINTS.items():
        if hint in lowered:
            return suggestion
    return "inspect stderr and failing test output"


def _first_failure_lines(output: str, max_lines: int = 8) -> str:
    lines = [ln for ln in output.splitlines() if ln.strip()]
    interesting = [
        ln
        for ln in lines
        if any(k in ln.lower() for k in ("fail", "error", "assert", "expect", "Ã¢Å“â€”"))
    ]
    picked = (interesting or lines)[-max_lines:]
    return "\n".join(picked)


def _grep_line(output: str, needles: tuple[str, ...]) -> str:
    for line in output.splitlines():
        low = line.lower()
        if any(n.lower() in low for n in needles):
            return line
    return ""
