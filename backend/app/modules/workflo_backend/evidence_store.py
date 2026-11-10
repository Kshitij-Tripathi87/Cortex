"""Workflo evidence store — S3-backed, tenant-scoped evidence persistence.

Persists production receipts and run artifacts to S3-compatible object
storage (MinIO in CI/staging) under tenant-scoped keys:

    workflo/{workspace_id}/runs/{run_id}/receipt.json
    workflo/{workspace_id}/runs/{run_id}/artifacts/{name}

Security contract (qualified by tests/test_evidence_store.py):
  * Tenant isolation — every key is namespaced by workspace; all reads
    re-verify the key belongs to the caller's workspace, so guessed or
    leaked object identifiers from another tenant are rejected.
  * Integrity — every stored object returns its SHA-256 digest; loaders
    can re-verify content against the recorded digest so tampering is
    detectable.
  * Path safety — artifact names are normalized and cannot traverse out
    of the run's prefix.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from app.modules.workflo_backend.infrastructure.storage_client import ObjectStorageClient

_KEY_NAMESPACE = "workflo"
_UNSAFE_KEY_CHARS = re.compile(r"[^A-Za-z0-9._\-/]")


class EvidenceStoreError(Exception):
    """Raised for evidence store contract violations (tenant, path, integrity)."""


def _sanitize_segment(segment: str) -> str:
    cleaned = _UNSAFE_KEY_CHARS.sub("_", segment)
    if cleaned != segment or ".." in segment or segment.startswith("/"):
        # The caller-specified identifier itself contained unsafe characters.
        raise EvidenceStoreError(f"UNSAFE_EVIDENCE_IDENTIFIER: {segment!r}")
    return segment


def tenant_key(workspace_id: str, run_id: str, leaf: str) -> str:
    """Build a tenant-scoped object key and fail on unsafe identifiers."""
    ws = _sanitize_segment(workspace_id)
    run = _sanitize_segment(run_id)
    parts = [p for p in leaf.split("/") if p not in ("", ".")]
    for part in parts:
        if part == ".." or part != _sanitize_segment(part):
            raise EvidenceStoreError(f"UNSAFE_EVIDENCE_IDENTIFIER: {leaf!r}")
    return f"{_KEY_NAMESPACE}/{ws}/runs/{run}/{'/'.join(parts)}"


def assert_tenant_key(workspace_id: str, key: str) -> str:
    """Verify ``key`` belongs to ``workspace_id``; return the validated key.

    This is the guessed-object-ID guard: possession of a foreign key string
    is not enough — the key must be inside the caller's tenant namespace.
    """
    expected_prefix = f"{_KEY_NAMESPACE}/{workspace_id}/"
    if not key.startswith(expected_prefix):
        raise EvidenceStoreError(
            f"CROSS_TENANT_EVIDENCE_DENIED: key '{key}' is outside workspace '{workspace_id}'"
        )
    return key


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class EvidenceStore:
    """Tenant-scoped receipt/artifact persistence over object storage."""

    def __init__(self, storage: ObjectStorageClient) -> None:
        self._storage = storage

    # ── Receipts ──────────────────────────────────────────────────────────

    def store_receipt(
        self, workspace_id: str, run_id: str, receipt: dict[str, Any]
    ) -> tuple[str, str]:
        """Persist a production receipt. Returns (key, sha256)."""
        import json

        payload = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("utf-8")
        key = tenant_key(workspace_id, run_id, "receipt.json")
        self._storage.put_object(key, payload, content_type="application/json")
        return key, digest_bytes(payload)

    def load_receipt(self, workspace_id: str, run_id: str) -> dict[str, Any] | None:
        """Load a receipt, refusing keys outside the caller's tenant."""
        import json

        key = assert_tenant_key(workspace_id, tenant_key(workspace_id, run_id, "receipt.json"))
        if not self._storage.object_exists(key):
            return None
        return json.loads(self._storage.get_object(key).decode("utf-8"))

    # ── Artifacts ─────────────────────────────────────────────────────────

    def store_artifact(
        self, workspace_id: str, run_id: str, name: str, content: bytes
    ) -> tuple[str, str]:
        """Persist a run artifact. Returns (key, sha256)."""
        key = tenant_key(workspace_id, run_id, f"artifacts/{name}")
        self._storage.put_object(key, content)
        return key, digest_bytes(content)

    def load_artifact(self, workspace_id: str, run_id: str, name: str) -> tuple[bytes, str]:
        """Load a run artifact. Returns (content, sha256-of-content)."""
        key = assert_tenant_key(workspace_id, tenant_key(workspace_id, run_id, f"artifacts/{name}"))
        content = self._storage.get_object(key)
        return content, digest_bytes(content)

    def verify_integrity(self, workspace_id: str, run_id: str, leaf: str, expected: str) -> bool:
        """Re-download an object and compare its digest to the recorded one."""
        key = assert_tenant_key(workspace_id, tenant_key(workspace_id, run_id, leaf))
        return digest_bytes(self._storage.get_object(key)) == expected


_evidence_store: EvidenceStore | None = None


def get_evidence_store() -> EvidenceStore:
    """Process-wide evidence store over the shared object storage client."""
    global _evidence_store
    if _evidence_store is None:
        from app.modules.workflo_backend.infrastructure.storage_client import get_storage

        _evidence_store = EvidenceStore(get_storage())
    return _evidence_store


def reset_evidence_store() -> None:
    global _evidence_store
    _evidence_store = None
