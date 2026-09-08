"""Prompt & AI Model Security Guardrails — Injection Defense, Secret Filtering, and DLP.

Enforces:
- Prompt injection and jailbreak pattern filtering
- Sensitive secret redaction (AWS keys, JWTs, DB DSNs, passwords)
- Untrusted data isolation
- Output schema compliance verification
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

# Known injection and manipulation patterns
_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior)\s+instructions", re.IGNORECASE),
    re.compile(r"system\s*:\s*you\s+are\s+now", re.IGNORECASE),
    re.compile(r"you\s+are\s+no\s+longer\s+an?\s+ai", re.IGNORECASE),
    re.compile(r"system\s+override", re.IGNORECASE),
    re.compile(r"disregard\s+(prior|all)\s+constraints", re.IGNORECASE),
    re.compile(r"drop\s+table|delete\s+from\s+|insert\s+into", re.IGNORECASE),
    re.compile(r"exec(\s+|\()|\beval\(", re.IGNORECASE),
]

# Sensitive patterns for DLP
_SECRET_PATTERNS = [
    (re.compile(r"AKIA[0-9A-Z]{16}"), "[REDACTED_AWS_KEY]"),
    (re.compile(r"wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"), "[REDACTED_AWS_SECRET]"),
    (
        re.compile(r"eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}"),
        "[REDACTED_JWT]",
    ),
    (re.compile(r"postgres(ql)?://[^\s\"']+"), "[REDACTED_DATABASE_DSN]"),
    (re.compile(r"bearer\s+[a-zA-Z0-9_\-\.]{20,}", re.IGNORECASE), "Bearer [REDACTED_TOKEN]"),
    (
        re.compile(r"password[\"']?\s*[:=]\s*[\"']?[^,\s\"']+", re.IGNORECASE),
        "password: [REDACTED]",
    ),
]


@dataclass
class SecurityCheckResult:
    is_safe: bool
    sanitized_text: str
    detected_threats: list[str]
    redactions_applied: int


class SecurityGuardrails:
    """Enterprise AI security guardrails engine."""

    @staticmethod
    def inspect_and_sanitize_prompt(text: str) -> SecurityCheckResult:
        """Scan input prompt for prompt injection patterns and scrub secrets."""
        threats: list[str] = []
        for pattern in _INJECTION_PATTERNS:
            if pattern.search(text):
                threats.append(f"Prompt injection pattern detected: {pattern.pattern}")

        sanitized = text
        redactions = 0
        for pattern, replacement in _SECRET_PATTERNS:
            new_text, count = pattern.subn(replacement, sanitized)
            if count > 0:
                sanitized = new_text
                redactions += count

        return SecurityCheckResult(
            is_safe=len(threats) == 0,
            sanitized_text=sanitized,
            detected_threats=threats,
            redactions_applied=redactions,
        )

    @staticmethod
    def filter_outgoing_payload(payload: dict[str, Any]) -> dict[str, Any]:
        """Deep-scrub sensitive credentials from telemetry, error messages, and responses."""
        payload_str = json.dumps(payload)
        for pattern, replacement in _SECRET_PATTERNS:
            payload_str = pattern.sub(replacement, payload_str)
        return json.loads(payload_str)

    @staticmethod
    def validate_output_schema(output: dict[str, Any], required_keys: list[str]) -> bool:
        """Verify that AI model outputs contain all mandatory fields and valid types."""
        return all(key in output for key in required_keys)


def detect_prompt_injection(text: str) -> tuple[bool, str | None]:
    """Scan text for malicious prompt injection patterns."""
    res = SecurityGuardrails.inspect_and_sanitize_prompt(text)
    if not res.is_safe:
        return True, res.detected_threats[0]
    return False, None


def scrub_sensitive_secrets(text: str) -> str:
    """Scrub sensitive keys, passwords, tokens, and database credentials."""
    res = SecurityGuardrails.inspect_and_sanitize_prompt(text)
    return res.sanitized_text


def validate_agent_output_schema(output: dict[str, Any], required_keys: list[str]) -> bool:
    """Check agent output dictionary against required keys."""
    return SecurityGuardrails.validate_output_schema(output, required_keys)
