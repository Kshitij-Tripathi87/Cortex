"""Security hardening — RLS policies and secrets detection."""

from __future__ import annotations

import re
from pathlib import Path

# Pre-commit hook for secrets detection
SECRET_PATTERNS = [
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS Access Key"),
    (re.compile(r"sk-[a-zA-Z0-9]{48}"), "OpenAI API Key"),
    (re.compile(r"ghp_[a-zA-Z0-9]{36}"), "GitHub Personal Access Token"),
    (re.compile(r"gho_[a-zA-Z0-9]{36}"), "GitHub OAuth Token"),
    (re.compile(r"glpat-[a-zA-Z0-9]{20}"), "GitLab Personal Access Token"),
    (re.compile(r"xoxb-[a-zA-Z0-9-]{51}"), "Slack Bot Token"),
    (re.compile(r"xoxp-[a-zA-Z0-9-]{51}"), "Slack User Token"),
    (re.compile(r"postgres://[^:]+:[^@]+@"), "PostgreSQL DSN with credentials"),
    (re.compile(r"mysql://[^:]+:[^@]+@"), "MySQL DSN with credentials"),
    (re.compile(r"mongodb://[^:]+:[^@]+@"), "MongoDB URI with credentials"),
    (re.compile(r"-----BEGIN (RSA|EC|DSA) PRIVATE KEY-----"), "Private Key"),
    (re.compile(r"-----BEGIN CERTIFICATE-----"), "Certificate"),
]


def scan_for_secrets(file_path: Path) -> list[tuple[str, int, str]]:
    """Scan a file for potential secrets. Returns list of (pattern_name, line_number, match)."""
    findings = []
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception:
        return findings

    for i, line in enumerate(content.splitlines(), 1):
        for pattern, name in SECRET_PATTERNS:
            if pattern.search(line):
                findings.append((name, i, line.strip()[:100]))
    return findings


def scan_repo(root: Path = Path(".")) -> dict[str, list[tuple[int, str]]]:
    """Scan entire repo for secrets."""
    results: dict[str, list[tuple[int, str]]] = {}
    for path in root.rglob("*"):
        if path.is_file() and not _should_skip(path):
            findings = scan_for_secrets(path)
            if findings:
                results[str(path)] = findings
    return results


def _should_skip(path: Path) -> bool:
    """Skip binary files, generated files, and docs."""
    if path.suffix in {
        ".pyc",
        ".pyo",
        ".so",
        ".dll",
        ".exe",
        ".bin",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".ico",
        ".pdf",
        ".zip",
        ".tar",
        ".gz",
    }:
        return True
    if any(
        part
        in {
            ".git",
            "__pycache__",
            ".venv",
            "venv",
            "node_modules",
            ".next",
            "dist",
            "build",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
        }
        for part in path.parts
    ):
        return True
    return path.name in {"golden_dataset.py"}  # contains sample data, not real secrets


# RLS Policy SQL (run as migration)
RLS_POLICIES_SQL = """
-- Enable RLS on all tenant-scoped tables
ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE source_batches ENABLE ROW LEVEL SECURITY;
ALTER TABLE source_files ENABLE ROW LEVEL SECURITY;
ALTER TABLE source_column_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE evidence_claims ENABLE ROW LEVEL SECURITY;
ALTER TABLE evidence_conflicts ENABLE ROW LEVEL SECURITY;
ALTER TABLE conflict_resolutions ENABLE ROW LEVEL SECURITY;
ALTER TABLE readiness_assessments ENABLE ROW LEVEL SECURITY;
ALTER TABLE integration_outbox ENABLE ROW LEVEL SECURITY;

-- Tenant isolation policy
CREATE POLICY tenant_isolation ON audit_events
    USING (tenant_id = current_setting('app.tenant_id')::uuid);

CREATE POLICY tenant_isolation ON source_batches
    USING (tenant_id = current_setting('app.tenant_id')::uuid);

CREATE POLICY tenant_isolation ON source_files
    USING (tenant_id = current_setting('app.tenant_id')::uuid);

CREATE POLICY tenant_isolation ON source_column_profiles
    USING (tenant_id = current_setting('app.tenant_id')::uuid);

CREATE POLICY tenant_isolation ON evidence_claims
    USING (tenant_id = current_setting('app.tenant_id')::uuid);

CREATE POLICY tenant_isolation ON evidence_conflicts
    USING (tenant_id = current_setting('app.tenant_id')::uuid);

CREATE POLICY tenant_isolation ON conflict_resolutions
    USING (tenant_id = current_setting('app.tenant_id')::uuid);

CREATE POLICY tenant_isolation ON readiness_assessments
    USING (tenant_id = current_setting('app.tenant_id')::uuid);

CREATE POLICY tenant_isolation ON integration_outbox
    USING (tenant_id = current_setting('app.tenant_id')::uuid);

-- Workspace isolation policy (scoped within tenant)
CREATE POLICY workspace_isolation ON source_batches
    USING (workspace_id = current_setting('app.workspace_id')::uuid);

CREATE POLICY workspace_isolation ON source_files
    USING (workspace_id = current_setting('app.workspace_id')::uuid);

CREATE POLICY workspace_isolation ON source_column_profiles
    USING (workspace_id = current_setting('app.workspace_id')::uuid);

CREATE POLICY workspace_isolation ON evidence_claims
    USING (workspace_id = current_setting('app.workspace_id')::uuid);

CREATE POLICY workspace_isolation ON evidence_conflicts
    USING (workspace_id = current_setting('app.workspace_id')::uuid);

CREATE POLICY workspace_isolation ON conflict_resolutions
    USING (workspace_id = current_setting('app.workspace_id')::uuid);

CREATE POLICY workspace_isolation ON readiness_assessments
    USING (workspace_id = current_setting('app.workspace_id')::uuid);

CREATE POLICY workspace_isolation ON integration_outbox
    USING (workspace_id = current_setting('app.workspace_id')::uuid);

-- Audit events: tenant + workspace isolation
CREATE POLICY tenant_workspace_isolation ON audit_events
    USING (
        tenant_id = current_setting('app.tenant_id')::uuid
        AND (workspace_id IS NULL OR workspace_id = current_setting('app.workspace_id')::uuid)
    );

-- Admin role bypasses RLS
ALTER TABLE audit_events FORCE ROW LEVEL SECURITY;
ALTER TABLE source_batches FORCE ROW LEVEL SECURITY;
ALTER TABLE source_files FORCE ROW LEVEL SECURITY;
ALTER TABLE source_column_profiles FORCE ROW LEVEL SECURITY;
ALTER TABLE evidence_claims FORCE ROW LEVEL SECURITY;
ALTER TABLE evidence_conflicts FORCE ROW LEVEL SECURITY;
ALTER TABLE conflict_resolutions FORCE ROW LEVEL SECURITY;
ALTER TABLE readiness_assessments FORCE ROW LEVEL SECURITY;
ALTER TABLE integration_outbox FORCE ROW LEVEL SECURITY;
"""
