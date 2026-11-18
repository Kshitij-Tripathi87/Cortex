"""Security hardening — secrets detection.

This module used to carry a block of row-level security SQL as well. It was
never run from here (migrations 002 and 003 created the policies) and no
longer matched them; the policies themselves were removed by migration 026.
"""

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
